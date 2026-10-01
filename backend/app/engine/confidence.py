"""Objective confidence (architecture §5.3). Pure functions of stored data + `now`.

    freshness   F = exp(-ln(2) * age_days / half_life[field])
    reliability R = 1 - min(0.5, corrections_90d / max(1, updates_90d))   per (source, field)
    agreement   A = largest agreeing group / sources holding the field
    confidence  C = wF*F + wR*R + wA*A

No LLM output ever feeds into these numbers.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

CORRECTION_REASONS = {"correction", "arbiter_sync"}


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def age_days(updated_at: str, now: datetime) -> float:
    return max(0.0, (now - parse_ts(updated_at)).total_seconds() / 86400.0)


def freshness(age: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 0.0
    return math.exp(-math.log(2) * max(0.0, age) / half_life_days)


def reliability(corrections: int, total_updates: int, floor: float = 0.5) -> float:
    return 1.0 - min(1.0 - floor, corrections / max(1, total_updates))


def reliability_table(audit_rows: Iterable[dict], floor: float = 0.5) -> dict[tuple[str, str], float]:
    """(source, field) -> R, from audit rows already filtered to the look-back window."""
    totals: dict[tuple[str, str], int] = defaultdict(int)
    fixes: dict[tuple[str, str], int] = defaultdict(int)
    for row in audit_rows:
        key = (row["source"], row["field"])
        totals[key] += 1
        if row["reason"] in CORRECTION_REASONS:
            fixes[key] += 1
    return {k: reliability(fixes[k], totals[k], floor) for k in totals}


def combine(F: float, R: float, A: float, weights: dict) -> float:
    total_w = weights["F"] + weights["R"] + weights["A"]
    c = (weights["F"] * F + weights["R"] * R + weights["A"] * A) / total_w
    return round(min(1.0, max(0.0, c)), 4)


def window_start(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).isoformat()


def validity_days(field_half_life: float, R: float, A: float, weights: dict, thresh: float) -> float:
    """Days until a *just-verified* fact (F=1) decays below the threshold (sunset timer).

    Solves wF*2^(-t/h) + wR*R + wA*A = thresh for t; capped at 3 half-lives.
    """
    total_w = weights["F"] + weights["R"] + weights["A"]
    rest = (weights["R"] * R + weights["A"] * A) / total_w
    wf = weights["F"] / total_w
    cap = 3 * field_half_life
    if rest >= thresh:
        return cap
    ratio = (thresh - rest) / wf
    if ratio >= 1:
        return 0.0
    return min(cap, -field_half_life * math.log2(ratio))
