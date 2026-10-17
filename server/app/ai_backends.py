"""Who the AI reader asks: Gemini (Google) or Claude (Anthropic), chosen by constants ai.provider
or PT_AI_PROVIDER. Both get the same instruction and JSON schema, one try within ai.timeout_s.

A backend has two calls:
  answer(system, prompt, schema)  the reply's JSON text, or None when the model declined or the
                                  reply was cut off; raises Offline when it could not be reached
  health()                        raises Offline when the API does not answer (no tokens spent)

Keys come from the environment (server/.env): GEMINI_API_KEY (or GOOGLE_API_KEY) for Gemini,
ANTHROPIC_API_KEY for Claude.
"""
from __future__ import annotations

import copy
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

log = logging.getLogger("pulsetriage.ai")


class Offline(Exception):
    """The AI could not be reached in time; the message says why."""


def _why(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:200]


class GeminiBackend:
    """The Gemini API refuses a request deadline under 10 s, so the request gets
    ai.gemini_min_deadline_s and the reader waits only ai.timeout_s for it in a thread; a late
    answer is dropped and the keyword reading stays."""
    name = "gemini"

    def __init__(self, rules: dict, client=None):
        self.rules = rules
        self.model = rules["gemini_model"]
        self._client = client
        self._pool = ThreadPoolExecutor(max_workers=2 * rules["workers"], thread_name_prefix="gemini")

    @property
    def client(self):
        if self._client is None:
            from google import genai
            try:
                self._client = genai.Client()          # reads GEMINI_API_KEY or GOOGLE_API_KEY
            except Exception as exc:                   # no key: the SDK raises ValueError
                raise Offline(_why(exc)) from exc
        return self._client

    def _http(self) -> dict:
        deadline = max(self.rules["timeout_s"], self.rules["gemini_min_deadline_s"])
        return {"timeout": int(deadline * 1000)}                  # milliseconds; no retries by default

    @staticmethod
    def schema(schema: dict) -> dict:
        """Gemini takes nullable fields as anyOf [type, null] rather than a list of types."""
        def walk(node):
            if isinstance(node, dict):
                node = {k: walk(v) for k, v in node.items()}
                if isinstance(node.get("type"), list):
                    kinds = node.pop("type")
                    node = {"anyOf": [dict(node, type=k) if k != "null" else {"type": "null"} for k in kinds]}
                return node
            if isinstance(node, list):
                return [walk(v) for v in node]
            return node
        return walk(copy.deepcopy(schema))

    def answer(self, system: str, prompt: str, schema: dict) -> str | None:
        from google.genai import errors
        config = {"system_instruction": system, "response_mime_type": "application/json",
                  "response_json_schema": self.schema(schema), "max_output_tokens": self.rules["max_tokens"],
                  "http_options": self._http()}
        if self.rules.get("gemini_thinking_budget") is not None:
            config["thinking_config"] = {"thinking_budget": self.rules["gemini_thinking_budget"]}
        try:
            client = self.client
            future = self._pool.submit(client.models.generate_content, model=self.model, contents=prompt, config=config)
            response = future.result(timeout=self.rules["timeout_s"])
        except FutureTimeout as exc:
            raise Offline(f"no answer in {self.rules['timeout_s']} s") from exc
        except errors.ClientError as exc:
            if exc.code in (401, 403):
                raise Offline("the API key was refused") from exc
            if exc.code == 429:
                raise Offline("rate limited") from exc
            log.warning("AI reader (Gemini): request refused %s: %s", exc.code, exc.message)
            return None
        except errors.ServerError as exc:
            raise Offline(f"API error {exc.code}") from exc
        except Offline:
            raise
        except Exception as exc:                       # timeouts and connection errors (httpx)
            raise Offline(_why(exc)) from exc
        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason:
            log.info("AI reader (Gemini): blocked (%s)", feedback.block_reason)
            return None
        candidates = response.candidates or []
        finish = getattr(candidates[0].finish_reason, "name", str(candidates[0].finish_reason)) if candidates else None
        if finish != "STOP":
            log.info("AI reader (Gemini): no reading (finish_reason %s)", finish)
            return None
        return response.text

    def health(self) -> None:
        try:
            self.client.models.get(model=self.model, config={"http_options": self._http()})
        except Offline:
            raise
        except Exception as exc:
            raise Offline(_why(exc)) from exc


class ClaudeBackend:
    name = "claude"

    def __init__(self, rules: dict, client=None):
        self.rules = rules
        self.model = rules["claude_model"]
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()        # ANTHROPIC_API_KEY or an `ant auth login` profile
        return self._client

    def _fast(self):
        """One try, ai.timeout_s seconds: a slow answer is worth less than the keyword reading."""
        try:
            return self.client.with_options(timeout=float(self.rules["timeout_s"]), max_retries=0)
        except Exception as exc:
            raise Offline(_why(exc)) from exc

    def answer(self, system: str, prompt: str, schema: dict) -> str | None:
        import anthropic
        fast = self._fast()
        try:
            response = fast.messages.create(
                model=self.model, max_tokens=self.rules["max_tokens"], system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.rules["effort"], "format": {"type": "json_schema", "schema": schema}},
            )
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise Offline(f"{type(exc).__name__}: no answer in {self.rules['timeout_s']} s") from exc
        except anthropic.AuthenticationError as exc:
            raise Offline("the API key was refused") from exc
        except anthropic.RateLimitError as exc:
            raise Offline("rate limited") from exc
        except anthropic.APIStatusError as exc:
            log.warning("AI reader (Claude): API error %s: %s", exc.status_code, exc.message)
            if exc.status_code >= 500:
                raise Offline(f"API error {exc.status_code}") from exc
            return None
        except Exception as exc:                       # no credentials: the SDK raises TypeError here
            raise Offline(_why(exc)) from exc
        if response.stop_reason != "end_turn":        # refusal or cut off
            log.info("AI reader (Claude): no reading (stop_reason %s)", response.stop_reason)
            return None
        return next((b.text for b in response.content if b.type == "text"), None)

    def health(self) -> None:
        try:
            self._fast().models.retrieve(self.model)
        except Offline:
            raise
        except Exception as exc:
            raise Offline(_why(exc)) from exc


def make_backend(rules: dict, provider: str | None = None, client=None):
    provider = provider or rules["provider"]
    if provider == "gemini":
        return GeminiBackend(rules, client)
    if provider == "claude":
        return ClaudeBackend(rules, client)
    raise ValueError(f"ai provider must be gemini or claude, not {provider!r}")
