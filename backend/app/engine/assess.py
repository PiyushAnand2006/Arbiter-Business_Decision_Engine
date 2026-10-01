"""Assess every fact of a deal: normalize -> agree -> score -> gate. No LLM, no I/O."""
from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Iterable, Optional

from ..db import SOURCE_FIELDS
from ..schemas import FactAssessment, SourceReading, ValueGroup
from . import agreement as ag
from .confidence import age_days, combine, freshness
from .gate import conflict_hash, route
from .normalize import display_value, normalize_field

SRC_CODE = {"crm": "CRM", "finance": "FIN", "pipeline": "PIPE"}
SOURCE_ORDER = ("crm", "finance", "pipeline")


def record_evidence_id(source: str, deal_id: str, field: str) -> str:
    return f"{SRC_CODE[source]}-{deal_id}-{field}"


def sources_for(field: str) -> list[str]:
    return [s for s in SOURCE_ORDER if field in SOURCE_FIELDS[s]]


def assess_fact(deal_id: str, field: str, rows: dict[str, Optional[dict]],
                rel: dict[tuple[str, str], float], now: datetime, cfg) -> FactAssessment:
    half_life = cfg.HALF_LIFE_DAYS.get(field, 30)
    readings: list[ag.Reading] = []
    detail: dict[str, SourceReading] = {}
    for s in sources_for(field):
        row = rows.get(s)
        if not row:
            continue
        raw = row.get(field)
        norm = normalize_field(field, raw)
        age = age_days(row["updated_at"], now)
        readings.append(ag.Reading(source=s, raw=raw, normalized=norm, updated_at=row["updated_at"]))
        detail[s] = SourceReading(
            source=s, evidence_id=record_evidence_id(s, deal_id, field), raw=raw, normalized=norm,
            display=display_value(field, norm, raw), updated_at=row["updated_at"], age_days=round(age, 2),
            F=round(freshness(age, half_life), 4), R=round(rel.get((s, field), 1.0), 4),
        )

    groups = ag.group_readings(field, readings, cfg.NUMERIC_TOLERANCE)
    conflicted = ag.is_conflicted(groups)
    if groups:
        top = groups[0]
        F = max(detail[r.source].F for r in top.readings)
        R = mean(detail[r.source].R for r in top.readings)
        A = ag.agreement(groups)
    else:
        F = R = A = 0.0
    C = combine(F, R, A, cfg.WEIGHTS)
    path, reason = route(conflicted, C, cfg.THRESH_LOW)
    chash = None
    if reason != "clean":
        chash = conflict_hash(deal_id, field, reason, [(r.source, r.normalized) for r in readings])

    return FactAssessment(
        deal_id=deal_id, field=field, readings=list(detail.values()),
        groups=[ValueGroup(normalized=g.normalized,
                           display=display_value(field, g.normalized, g.readings[0].raw),
                           sources=g.sources) for g in groups],
        conflicted=conflicted, F=round(F, 4), R=round(R, 4), A=round(A, 4), confidence=C,
        route=path, reason=reason, conflict_hash=chash,
    )


def assess_deal(deal_id: str, rows: dict[str, Optional[dict]], rel: dict, now: datetime, cfg,
                fields: Optional[Iterable[str]] = None) -> list[FactAssessment]:
    return [assess_fact(deal_id, f, rows, rel, now, cfg) for f in (fields or cfg.GATED_FIELDS)]


CONTEXT_FIELDS = {"crm": ["owner", "last_contacted"], "finance": ["invoice_status"], "pipeline": ["forecast_category"]}
