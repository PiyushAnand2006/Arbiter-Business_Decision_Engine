"""The gate (architecture §5.4): the only thing standing between data and the LLM.

    conflicted            -> DEBATE (reason="conflict")
    confidence < THRESH   -> DEBATE (reason="stale")
    otherwise             -> DIRECT (reason="clean")

If a debate is needed but the session budget is spent (and no cached debate
exists) the fact becomes PROVISIONAL: a rule-based answer, flagged for review.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable


def route(conflicted: bool, confidence: float, thresh_low: float, can_debate: bool = True) -> tuple[str, str]:
    if conflicted:
        reason = "conflict"
    elif confidence < thresh_low:
        reason = "stale"
    else:
        return "direct", "clean"
    return ("debate" if can_debate else "provisional"), reason


def _canon(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def conflict_hash(deal_id: str, field: str, reason: str, source_values: Iterable[tuple[str, Any]]) -> str:
    """sha256(deal_id + field + reason + sorted(source:value)) - the debate cache key."""
    pairs = sorted(f"{s}:{_canon(v)}" for s, v in source_values)
    payload = "|".join([deal_id, field, reason, *pairs])
    return hashlib.sha256(payload.encode()).hexdigest()[:24]
