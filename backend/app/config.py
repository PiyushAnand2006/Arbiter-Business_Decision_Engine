"""Single source of truth for every tunable in Arbiter.

Thresholds, weights, half-lives and budgets live here (overridable via env /
.env) so the scoring formula shown on the dashboard is exactly the one used.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _env(name: str, default):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, (dict, list)):
        return json.loads(raw)
    return raw


DEFAULT_MODELS = {
    "claude": "claude-opus-5-5",
    "gemini": "gemini-2.5-flash",
    "mock": "mock-reasoner-v1",
}


@dataclass
class Settings:
    # --- data -----------------------------------------------------------------
    SEED: int = field(default_factory=lambda: _env("SEED", 42))
    N_DEALS: int = field(default_factory=lambda: _env("N_DEALS", 50))
    DB_PATH: Path = field(default_factory=lambda: Path(_env("DB_PATH", str(ROOT_DIR / "data" / "arbiter.db"))))
    GROUND_TRUTH_PATH: Path = field(
        default_factory=lambda: Path(_env("GROUND_TRUTH_PATH", str(ROOT_DIR / "data" / "ground_truth.json")))
    )

    # --- confidence engine (no LLM) ------------------------------------------
    # Days until a fact's freshness halves. Volatile fields decay faster.
    HALF_LIFE_DAYS: dict = field(default_factory=lambda: _env("HALF_LIFE_DAYS", {
        "company": 365,
        "stage": 14,
        "value": 30,
        "close_date": 30,
        "last_contacted": 7,
        "invoice_status": 21,
        "forecast_category": 21,
        "owner": 90,
    }))
    # C = wF*F + wR*R + wA*A.  (The PRD draft used 0.4/0.2/0.4; with those
    # weights a fully-agreeing fact can never fall below 0.60 however stale it
    # is, so freshness gets the largest weight here. See docs/decisions.md.)
    WEIGHTS: dict = field(default_factory=lambda: _env("WEIGHTS", {"F": 0.5, "R": 0.15, "A": 0.35}))
    THRESH_LOW: float = field(default_factory=lambda: _env("THRESH_LOW", 0.60))
    NUMERIC_TOLERANCE: float = field(default_factory=lambda: _env("NUMERIC_TOLERANCE", 0.005))
    RELIABILITY_WINDOW_DAYS: int = field(default_factory=lambda: _env("RELIABILITY_WINDOW_DAYS", 90))
    RELIABILITY_FLOOR: float = 0.5
    # Facts compared across systems and routed through the gate.
    GATED_FIELDS: list = field(default_factory=lambda: _env("GATED_FIELDS", ["company", "stage", "value", "close_date"]))

    # --- debate / LLM ---------------------------------------------------------
    LLM_PROVIDER: str = field(default_factory=lambda: _env("LLM_PROVIDER", "mock").lower())
    LLM_MODEL: str = field(default_factory=lambda: _env("LLM_MODEL", ""))
    LLM_EFFORT: str = field(default_factory=lambda: _env("LLM_EFFORT", "low"))
    LLM_TEMPERATURE_JUDGE: float = field(default_factory=lambda: _env("LLM_TEMPERATURE_JUDGE", 0.2))
    LLM_TIMEOUT_S: float = field(default_factory=lambda: _env("LLM_TIMEOUT_S", 45.0))
    MAX_DEBATES_PER_SESSION: int = field(default_factory=lambda: _env("MAX_DEBATES_PER_SESSION", 25))
    # 3 calls on the happy path (proponent, challenger, judge) + at most one
    # repair retry per conflict when an output fails validation.
    MAX_CALLS_PER_CONFLICT: int = field(default_factory=lambda: _env("MAX_CALLS_PER_CONFLICT", 4))
    MOCK_LATENCY_MS: int = field(default_factory=lambda: _env("MOCK_LATENCY_MS", 350))
    DEBATE_WORKERS: int = field(default_factory=lambda: _env("DEBATE_WORKERS", 2))
    # Re-judge with sides swapped (position-bias check) when this much expected revenue is at stake.
    CONSISTENCY_CHECK_MIN_STAKE: float = field(default_factory=lambda: _env("CONSISTENCY_CHECK_MIN_STAKE", 100000.0))

    # --- alerts ---------------------------------------------------------------
    # Optional Slack-compatible webhook: POSTs {"text": ...} when a verdict of this severity is ready.
    ALERT_WEBHOOK_URL: str = field(default_factory=lambda: _env("ALERT_WEBHOOK_URL", ""))
    ALERT_MIN_SEVERITY: str = field(default_factory=lambda: _env("ALERT_MIN_SEVERITY", "high"))

    # --- monitoring -----------------------------------------------------------
    MONITOR_ENABLED: bool = field(default_factory=lambda: _env("MONITOR_ENABLED", True))
    MONITOR_INTERVAL_S: float = field(default_factory=lambda: _env("MONITOR_INTERVAL_S", 4.0))

    # --- business priors (for risk hints / priority list) ---------------------
    STAGE_WIN_PROB: dict = field(default_factory=lambda: {
        "prospecting": 0.10,
        "qualification": 0.20,
        "proposal": 0.40,
        "negotiation": 0.60,
        "closed_won": 1.00,
        "closed_lost": 0.00,
    })

    @property
    def model(self) -> str:
        return self.LLM_MODEL or DEFAULT_MODELS.get(self.LLM_PROVIDER, "")

    def public(self) -> dict:
        """Settings safe to show on the dashboard (no secrets live here)."""
        return {
            "half_life_days": self.HALF_LIFE_DAYS,
            "weights": self.WEIGHTS,
            "thresh_low": self.THRESH_LOW,
            "numeric_tolerance": self.NUMERIC_TOLERANCE,
            "reliability_window_days": self.RELIABILITY_WINDOW_DAYS,
            "gated_fields": self.GATED_FIELDS,
            "llm_provider": self.LLM_PROVIDER,
            "llm_model": self.model,
            "llm_effort": self.LLM_EFFORT,
            "max_debates_per_session": self.MAX_DEBATES_PER_SESSION,
            "max_calls_per_conflict": self.MAX_CALLS_PER_CONFLICT,
            "consistency_check_min_stake": self.CONSISTENCY_CHECK_MIN_STAKE,
            "alerts_enabled": bool(self.ALERT_WEBHOOK_URL),
            "seed": self.SEED,
            "n_deals": self.N_DEALS,
            "stage_win_prob": self.STAGE_WIN_PROB,
        }


settings = Settings()
