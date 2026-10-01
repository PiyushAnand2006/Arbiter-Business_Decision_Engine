"""Rule-based normalization (FR-2): cosmetic differences must never look like conflicts.

Each source system formats the same fact differently:
    CRM       stage "Closed Won"          value "48000"        date "2026-10-15"
    Finance   stage "Closed - Won"        value "$48,000.00"   date "10/15/2026"
    Pipeline  stage "closed-won"          value "48K"          date "15 Oct 2026"
All of these canonicalize to the same value before comparison.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

STAGES = ["prospecting", "qualification", "proposal", "negotiation", "closed_won", "closed_lost"]

_STAGE_SYNONYMS = {
    "prospecting": {"prospecting", "prospect", "lead", "new", "new lead"},
    "qualification": {"qualification", "qualified", "qualifying", "discovery"},
    "proposal": {"proposal", "proposal sent", "quote sent", "quoted", "proposing"},
    "negotiation": {"negotiation", "negotiating", "in negotiation", "contract", "contracting", "commit"},
    "closed_won": {"closed won", "won", "cw", "closed win", "booked", "signed", "closedwon"},
    "closed_lost": {"closed lost", "lost", "cl", "dead", "closedlost", "churned"},
}
_STAGE_LOOKUP = {syn: canon for canon, syns in _STAGE_SYNONYMS.items() for syn in syns}

_COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "plc", "group", "limited", "gmbh"}

_DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y",
                 "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%m-%d-%Y"]

STAGE_LABELS = {
    "crm": {"prospecting": "Prospecting", "qualification": "Qualification", "proposal": "Proposal",
            "negotiation": "Negotiation", "closed_won": "Closed Won", "closed_lost": "Closed Lost"},
    "finance": {"prospecting": "Open - Prospect", "qualification": "Open - Qualified",
                "proposal": "Open - Proposal", "negotiation": "Open - Negotiation",
                "closed_won": "Closed - Won", "closed_lost": "Closed - Lost"},
    "pipeline": {"prospecting": "prospecting", "qualification": "qualified", "proposal": "proposal-sent",
                 "negotiation": "negotiating", "closed_won": "closed-won", "closed_lost": "closed-lost"},
}
PRETTY_STAGE = STAGE_LABELS["crm"]


# --------------------------------------------------------------------------- #
# Canonicalizers
# --------------------------------------------------------------------------- #
def normalize_stage(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = re.sub(r"[^a-z]+", " ", str(raw).lower()).strip()
    if not s:
        return None
    if s.replace(" ", "_") in STAGES:
        return s.replace(" ", "_")
    if s in _STAGE_LOOKUP:
        return _STAGE_LOOKUP[s]
    for prefix in ("open ", "stage ", "status "):
        if s.startswith(prefix) and s[len(prefix):] in _STAGE_LOOKUP:
            return _STAGE_LOOKUP[s[len(prefix):]]
    if s.startswith("closed ") and s[len("closed "):] in {"won", "win"}:
        return "closed_won"
    if s.startswith("closed ") and s[len("closed "):] == "lost":
        return "closed_lost"
    return "unknown:" + s


def normalize_value(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().upper().replace("USD", "").replace("$", "").replace(",", "").replace(" ", "")
    if not s:
        return None
    mult = 1.0
    if s.endswith("K"):
        mult, s = 1_000.0, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000.0, s[:-1]
    try:
        return round(float(s) * mult, 2)
    except ValueError:
        return None


def normalize_date(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    s = str(raw).strip()
    if not s:
        return None
    if "T" in s:  # ISO datetime
        s = s.split("T", 1)[0]
    # US vs EU slash dates: first part > 12 must be a day.
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        a, b, y = map(int, m.groups())
        month, day = (a, b) if a <= 12 else (b, a)
        try:
            return date(y, month, day).isoformat()
        except ValueError:
            return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_company(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    tokens = [t for t in s.split() if t not in _COMPANY_SUFFIXES]
    return " ".join(tokens) or None


def normalize_text(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw).strip().lower().replace("-", "_"))
    return s or None


NORMALIZERS = {
    "stage": normalize_stage,
    "value": normalize_value,
    "close_date": normalize_date,
    "last_contacted": normalize_date,
    "company": normalize_company,
}


def normalize_field(field: str, raw: Any) -> Any:
    return NORMALIZERS.get(field, normalize_text)(raw)


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #
def values_equal(field: str, a: Any, b: Any, tolerance: float) -> bool:
    if a is None or b is None:
        return a is b
    if field == "value":
        scale = max(abs(a), abs(b), 1.0)
        return abs(a - b) <= tolerance * scale
    return a == b


# --------------------------------------------------------------------------- #
# Display + write-back in each system's native format
# --------------------------------------------------------------------------- #
def display_value(field: str, normalized: Any, raw_fallback: Optional[str] = None) -> str:
    if normalized is None:
        return "—"
    if field == "stage":
        return PRETTY_STAGE.get(normalized, str(normalized))
    if field == "value":
        return f"${normalized:,.0f}" if float(normalized).is_integer() else f"${normalized:,.2f}"
    if field == "company" and raw_fallback:
        return raw_fallback
    return str(normalized)


def to_source_format(source: str, field: str, normalized: Any, company_hint: Optional[str] = None) -> str:
    """Render a canonical value the way `source` natively stores it."""
    if field == "stage":
        return STAGE_LABELS[source].get(normalized, str(normalized))
    if field == "value":
        v = float(normalized)
        if source == "finance":
            return f"${v:,.2f}"
        if source == "pipeline":
            return f"{v / 1000:.2f}".rstrip("0").rstrip(".") + "K"
        return f"{v:.0f}" if v.is_integer() else f"{v:.2f}"
    if field in ("close_date", "last_contacted"):
        d = date.fromisoformat(str(normalized))
        if source == "finance":
            return d.strftime("%m/%d/%Y")
        if source == "pipeline":
            return d.strftime("%d %b %Y")
        return d.isoformat()
    if field == "company":
        name = company_hint or str(normalized).title()
        if source == "finance":
            return name.upper()
        if source == "pipeline":
            return name.replace(",", "")
        return name
    return str(normalized)


def parse_user_value(field: str, raw: str) -> Any:
    """Parse a human/LLM-supplied value (e.g. a verdict's resolved_value)."""
    return normalize_field(field, raw)
