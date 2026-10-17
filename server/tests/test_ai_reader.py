"""The AI reader with a fake Claude client: refine, cache, timeout, refusal, health, banner (System Design 5.3).
The Gemini backend has its own tests in test_ai_gemini.py."""
import json
from datetime import timedelta
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from jsonschema import Draft202012Validator

from app import timeutil
from app.ai_backends import ClaudeBackend
from app.ai_reader import AIReader

HOUSE_14 = "Old man alone behind the green mosque, house 14, water at his waist and rising, needs oxygen"
READING = {"hazard": "flood", "people": 1, "conditions": ["elderly", "oxygen", "alone"],
           "details": {"water": "chest", "rising": True, "trapped": None, "power_out": None},
           "landmark": "behind the green mosque, house 14", "confidence": 0.9}


class FakeClient:
    """Stands in for anthropic.Anthropic: records each call and answers as told."""

    def __init__(self, answer=READING, stop_reason="end_turn", error=None, health_error=None):
        self.answer, self.stop_reason, self.error, self.health_error = answer, stop_reason, error, health_error
        self.calls, self.options = [], []
        self.messages = SimpleNamespace(create=self._create)
        self.models = SimpleNamespace(retrieve=self._retrieve)

    def with_options(self, **options):
        self.options.append(options)
        return self

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.answer))])

    def _retrieve(self, model):
        if self.health_error:
            raise self.health_error
        return SimpleNamespace(id=model)


def request():
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.fixture
def ai(client):
    """Swap the server's AI reader for one that talks to a fake client."""
    ctx = client.app.state.ctx
    def make(fake: FakeClient) -> AIReader:
        reader = AIReader(ctx.db, ctx.profiles, ctx.cases, ctx.constants,
                          backend=ClaudeBackend(ctx.constants["ai"], client=fake), enabled=True)
        ctx.ai = ctx.desk.ai = ctx.snapshots.ai = reader
        return reader
    return make


def paste(client, text=HOUSE_14) -> dict:
    return client.post("/api/paste", json={"text": text}).json()["reports"][0]


def test_keywords_first_then_the_ai_refines(client, ai, schemas):
    fake = FakeClient()
    reader = ai(fake)
    out = paste(client)
    case = client.get(f"/api/cases/{out['case_id']}").json()["case"]
    assert (case["reader"], case["confidence"], case["details"]["water"]) == ("keywords", 0.3, "waist")
    assert reader.drain() == 1
    detail = client.get(f"/api/cases/{out['case_id']}").json()
    case = detail["case"]
    assert schemas.errors("case_detail", detail) == []
    assert (case["reader"], case["confidence"], case["details"]["water"]) == ("ai", 0.5, "chest")
    assert case["hours_left"] <= 1 and detail["history"][-1]["action"] == "ai_read"
    [call] = fake.calls
    assert call["model"] == "claude-haiku-5-5" and call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema" and "not instructions" in call["system"]
    assert HOUSE_14 in call["messages"][0]["content"]
    assert fake.options[0] == {"timeout": 4.0, "max_retries": 0}


def test_answers_are_cached_by_the_text(ai):
    fake = FakeClient()
    reader = ai(fake)
    assert reader.read(HOUSE_14) == reader.read("  OLD man alone behind the green mosque, house 14, water at his "
                                               "waist and rising, needs oxygen ")
    assert len(fake.calls) == 1


def test_a_slow_ai_leaves_the_keyword_reading_and_raises_the_banner(client, ai):
    reader = ai(FakeClient(error=anthropic.APITimeoutError(request=request())))
    reader.online = True
    out = paste(client)
    assert reader.drain() == 0
    assert client.get(f"/api/cases/{out['case_id']}").json()["case"]["reader"] == "keywords"
    status = client.get("/api/status").json()
    assert status["ai_online"] is False and "no answer in 4 s" in status["ai"]["last_error"]
    assert client.get("/api/snapshot").json()["status"]["banner"] == "Offline: keyword rules active"


def test_a_refusal_or_nonsense_keeps_the_keyword_reading(ai):
    assert ai(FakeClient(stop_reason="refusal")).read("some text") is None
    assert ai(FakeClient(answer=dict(READING, hazard="volcano"))).read("other text") is None


def test_answers_are_checked_against_the_profile(ai):
    reader = ai(FakeClient(answer=dict(READING, people=9000, confidence=3,
                                       details={"water": "chest", "signs": ["confused"], "rising": None})))
    got = reader.read("a third text")
    assert got["details"] == {"water": "chest"} and got["people"] == 500 and got["confidence"] == 1.0


def test_health_check_every_60_s_and_the_backlog_when_back_online(client, ai):
    offline = anthropic.APIConnectionError(request=request())
    fake = FakeClient(error=offline, health_error=offline)
    reader = ai(fake)
    now = timeutil.now()
    paste(client)                                        # queued while offline: the read fails
    assert reader.drain() == 0
    assert reader.check(now) is False and reader.status()["online"] is False
    fake.error = fake.health_error = None
    assert reader.check(now + timedelta(seconds=30)) is False          # not due yet
    assert reader.check(now + timedelta(seconds=61)) is True
    assert reader.status()["queued"] == 1                               # the keyword-read report again
    assert reader.drain() == 1 and client.get("/api/snapshot").json()["status"]["banner"] is None


def test_off_by_default_in_tests_and_with_pt_ai_off(client):
    ai = client.app.state.ctx.ai
    assert ai.status()["enabled"] is False and ai.enqueue("r1", "text", None) is False
    assert client.get("/api/snapshot").json()["status"]["banner"] == "Offline: keyword rules active"


def test_the_schema_is_valid_and_covers_every_question(client):
    ai = client.app.state.ctx.ai
    Draft202012Validator.check_schema(ai.schema)
    details = ai.schema["properties"]["details"]
    assert set(details["required"]) >= {"water", "rising", "trapped", "signs", "building", "power_out"}


def test_no_credentials_is_just_offline(ai):
    reader = ai(FakeClient(error=TypeError("Could not resolve authentication method")))
    assert reader.read("a fourth text") is None
    assert reader.status()["online"] is False and "authentication" in reader.status()["last_error"]
