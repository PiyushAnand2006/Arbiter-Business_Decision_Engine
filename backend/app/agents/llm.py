"""LLMClient interface + providers (Claude, Gemini, Mock) + session budget.

Every provider returns the raw text of a JSON reply; validation happens in
`validate.py` so all providers are held to the same contract.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional

from ..db import Store
from . import mock_reasoner


class LLMError(RuntimeError):
    """Provider failure (network, rate limit, refusal, truncation...)."""


class LLMClient:
    provider = "base"

    def __init__(self, model: str):
        self.model = model

    def generate(self, role: str, system: str, prompt: str, schema: dict, context: dict) -> str:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Claude (Anthropic SDK)
# --------------------------------------------------------------------------- #
class ClaudeClient(LLMClient):
    provider = "claude"

    def __init__(self, model: str, effort: str = "low", timeout: float = 45.0):
        super().__init__(model)
        import anthropic  # imported lazily so mock mode needs no SDK

        self._anthropic = anthropic
        # Credentials resolve from ANTHROPIC_API_KEY / an `ant auth login` profile.
        # SDK retries 429/5xx/connection errors itself; one retry = "retry once with backoff".
        self.client = anthropic.Anthropic(timeout=timeout, max_retries=1)
        self.effort = effort

    def generate(self, role: str, system: str, prompt: str, schema: dict, context: dict) -> str:
        a = self._anthropic
        try:
            # Structured outputs constrain the reply to the per-packet schema (evidence
            # IDs and resolved values are enums). Current Claude models take no
            # temperature; `effort` controls depth instead. Server-side fallbacks
            # re-run a policy-declined request on a fallback model in the same call.
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.AuthenticationError as e:
            raise LLMError(f"Claude authentication failed - set ANTHROPIC_API_KEY ({e.message})") from e
        except a.RateLimitError as e:
            raise LLMError("Claude rate limit reached") from e
        except a.APITimeoutError as e:
            raise LLMError("Claude request timed out") from e
        except a.BadRequestError as e:
            raise LLMError(f"Claude rejected the request: {e.message}") from e
        except a.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError("Could not reach the Claude API") from e

        if resp.stop_reason == "refusal":
            raise LLMError("Claude declined to answer (refusal)")
        if resp.stop_reason == "max_tokens":
            raise LLMError("Claude reply was truncated (max_tokens)")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text:
            raise LLMError("Claude returned no text block")
        return text


# --------------------------------------------------------------------------- #
# Gemini (free tier) via REST
# --------------------------------------------------------------------------- #
class GeminiClient(LLMClient):
    provider = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, model: str, temperature: float = 0.2, timeout: float = 45.0):
        super().__init__(model)
        import httpx

        self.httpx = httpx
        self.key = os.getenv("GEMINI_API_KEY", "")
        self.temperature = temperature
        self.timeout = timeout

    def generate(self, role: str, system: str, prompt: str, schema: dict, context: dict) -> str:
        if not self.key:
            raise LLMError("GEMINI_API_KEY is not set")
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature if role == "judge" else min(0.7, self.temperature + 0.3),
                "responseMimeType": "application/json",
            },
        }
        last: Optional[Exception] = None
        for attempt in range(2):  # retry once with backoff
            try:
                r = self.httpx.post(self.URL.format(model=self.model), json=body, timeout=self.timeout,
                                    headers={"x-goog-api-key": self.key})
                if r.status_code == 429 or r.status_code >= 500:
                    raise LLMError(f"Gemini HTTP {r.status_code}")
                r.raise_for_status()
                data = r.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (LLMError, self.httpx.HTTPError, KeyError, IndexError) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"Gemini request failed: {last}")


# --------------------------------------------------------------------------- #
# Mock (deterministic, zero quota)
# --------------------------------------------------------------------------- #
class MockClient(LLMClient):
    provider = "mock"

    def __init__(self, model: str = "mock-reasoner-v1", latency_ms: int = 0,
                 fail_plan: Optional[dict[str, list[str]]] = None):
        super().__init__(model)
        self.latency_ms = latency_ms
        # e.g. {"judge": ["bad_citation"]} -> the judge's first reply cites a fake ID
        self.fail_plan = {k: list(v) for k, v in (fail_plan or {}).items()}
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def _next_failure(self, role: str) -> Optional[str]:
        with self._lock:
            self.calls.append(role)
            plan = self.fail_plan.get(role)
            return plan.pop(0) if plan else None

    def generate(self, role: str, system: str, prompt: str, schema: dict, context: dict) -> str:
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000.0)
        failure = self._next_failure(role)
        if failure == "error":
            raise LLMError("mock provider error")
        if failure == "invalid_json":
            return '{"winner": "A", "reasoning": '
        packet = context["packet"]
        out: dict[str, Any] = (mock_reasoner.verdict(packet) if role == "judge"
                               else mock_reasoner.argument(role, packet))
        if failure == "bad_citation":
            if role == "judge":
                out["evidence_ids"] = [*out["evidence_ids"], "A9999-HALLUCINATED"]
            else:
                out["claims"][0]["evidence_ids"] = ["CRM-D0000-made_up"]
        if failure == "wrong_value" and role == "judge":
            out["winner"], out["resolved_value"] = "A", "not-a-candidate"
        if failure == "flip" and role == "judge" and out["winner"] in ("A", "B"):
            other = "B" if out["winner"] == "A" else "A"  # a valid but opposite verdict (position-bias probe)
            out["winner"], out["resolved_value"] = other, packet["sides"][other]["value"]
        return json.dumps(out)


def make_client(cfg) -> LLMClient:
    if cfg.LLM_PROVIDER == "claude":
        return ClaudeClient(cfg.model, effort=cfg.LLM_EFFORT, timeout=cfg.LLM_TIMEOUT_S)
    if cfg.LLM_PROVIDER == "gemini":
        return GeminiClient(cfg.model, temperature=cfg.LLM_TEMPERATURE_JUDGE, timeout=cfg.LLM_TIMEOUT_S)
    return MockClient(cfg.model, latency_ms=cfg.MOCK_LATENCY_MS)


# --------------------------------------------------------------------------- #
# Budget: global per-session cap on debates + call accounting
# --------------------------------------------------------------------------- #
class Budget:
    def __init__(self, store: Store, max_debates: int):
        self.store = store
        self.max_debates = max_debates
        self._lock = threading.Lock()

    def try_reserve(self) -> bool:
        with self._lock:
            used = int(self.store.get_meta("debates_run", 0))
            if used >= self.max_debates:
                return False
            self.store.set_meta("debates_run", used + 1)
            return True

    def record_calls(self, n: int):
        if n:
            self.store.incr_meta("llm_calls", n)

    def record_cache_hit(self):
        self.store.incr_meta("cache_hits", 1)

    def record_fallback(self):
        self.store.incr_meta("fallbacks", 1)

    def snapshot(self) -> dict:
        return {
            "debates_run": int(self.store.get_meta("debates_run", 0)),
            "debates_cap": self.max_debates,
            "llm_calls": int(self.store.get_meta("llm_calls", 0)),
            "cache_hits": int(self.store.get_meta("cache_hits", 0)),
            "fallbacks": int(self.store.get_meta("fallbacks", 0)),
        }
