"""The Gemini backend of the AI reader, with a fake google-genai client (no network)."""
import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.ai_backends import GeminiBackend, Offline, make_backend
from app.ai_reader import AIReader

READING = {"hazard": "flood", "people": 1, "conditions": ["elderly", "oxygen", "alone"],
           "details": {"water": "chest", "rising": True}, "landmark": "behind the green mosque, house 14",
           "confidence": 0.85}


class FakeGemini:
    """Stands in for google.genai.Client: models.generate_content and models.get."""

    def __init__(self, answer=READING, finish="STOP", blocked=None, error=None, health_error=None):
        self.answer, self.finish, self.blocked, self.error, self.health_error = answer, finish, blocked, error, health_error
        self.calls, self.health_calls = [], []
        self.models = SimpleNamespace(generate_content=self._generate, get=self._get)

    def _generate(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return SimpleNamespace(
            prompt_feedback=SimpleNamespace(block_reason=self.blocked) if self.blocked else None,
            candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=self.finish))],
            text=json.dumps(self.answer))

    def _get(self, *, model, config):
        self.health_calls.append({"model": model, "config": config})
        if self.health_error:
            raise self.health_error


@pytest.fixture
def gemini(client):
    ctx = client.app.state.ctx

    def make(fake: FakeGemini) -> AIReader:
        reader = AIReader(ctx.db, ctx.profiles, ctx.cases, ctx.constants,
                          backend=GeminiBackend(ctx.constants["ai"], client=fake), enabled=True)
        ctx.ai = ctx.desk.ai = ctx.snapshots.ai = reader
        return reader
    return make


def test_gemini_is_the_default_provider(constants):
    assert make_backend(constants["ai"]).name == "gemini"
    assert make_backend(constants["ai"], "claude").name == "claude"
    with pytest.raises(ValueError):
        make_backend(constants["ai"], "llama")


def test_gemini_refines_a_pasted_message(client, gemini):
    fake = FakeGemini()
    reader = gemini(fake)
    out = client.post("/api/paste", json={"text": "old man behind the green mosque, house 14, water at waist"}).json()
    assert reader.drain() == 1
    case = client.get(f"/api/cases/{out['reports'][0]['case_id']}").json()["case"]
    assert (case["reader"], case["details"]["water"], case["confidence"]) == ("ai", "chest", 0.5)
    [call] = fake.calls
    config = call["config"]
    assert call["model"] == "gemini-2.5-flash" and config["response_mime_type"] == "application/json"
    assert config["http_options"] == {"timeout": 10000} and config["thinking_config"] == {"thinking_budget": 0}
    assert "not instructions" in config["system_instruction"] and "house 14" in call["contents"]
    water = config["response_json_schema"]["properties"]["details"]["properties"]["rising"]
    assert water == {"anyOf": [{"type": "boolean"}, {"type": "null"}]}       # no list-of-types for Gemini
    assert reader.status()["provider"] == "gemini" and reader.status()["model"] == "gemini-2.5-flash"


@pytest.mark.parametrize("error, why", [
    (errors.ClientError(403, {"error": {"code": 403, "message": "API key not valid", "status": "PERMISSION_DENIED"}}),
     "the API key was refused"),
    (errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
     "rate limited"),
    (errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}),
     "API error 503"),
    (httpx.ReadTimeout("timed out"), "ReadTimeout"),
])
def test_gemini_failures_mean_offline(gemini, error, why):
    reader = gemini(FakeGemini(error=error))
    assert reader.read(f"message for {why}") is None
    assert reader.status()["online"] is False and why in reader.status()["last_error"]


def test_a_bad_request_or_a_block_keeps_the_keyword_reading_but_stays_online(gemini):
    reader = gemini(FakeGemini(error=errors.ClientError(400, {"error": {"code": 400, "message": "bad schema",
                                                                        "status": "INVALID_ARGUMENT"}})))
    reader.online = True
    assert reader.read("one") is None and reader.status()["online"] is True
    assert gemini(FakeGemini(blocked="SAFETY")).read("two") is None
    assert gemini(FakeGemini(finish="MAX_TOKENS")).read("three") is None


def test_gemini_health_check(gemini):
    fake = FakeGemini(health_error=errors.ClientError(403, {"error": {"code": 403, "message": "bad key",
                                                                      "status": "PERMISSION_DENIED"}}))
    reader = gemini(fake)
    assert reader.check() is False and "ClientError" in reader.status()["last_error"]
    assert fake.health_calls[0] == {"model": "gemini-2.5-flash", "config": {"http_options": {"timeout": 10000}}}


def test_no_gemini_key_is_just_offline(constants, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    backend = GeminiBackend(constants["ai"])
    with pytest.raises(Offline):
        backend.health()


def test_the_reader_waits_only_4_s_even_though_gemini_gets_10(constants):
    import threading
    release = threading.Event()

    class Slow(FakeGemini):
        def _generate(self, **kw):
            release.wait(5)
            return super()._generate(**kw)

    backend = GeminiBackend(dict(constants["ai"], timeout_s=0.2), client=Slow())
    with pytest.raises(Offline, match="no answer in 0.2 s"):
        backend.answer("system", "prompt", {"type": "object"})
    release.set()
