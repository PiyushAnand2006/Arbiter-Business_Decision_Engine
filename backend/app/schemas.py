"""Pydantic models: the contract between engine, agents, services, API and UI."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Route = Literal["direct", "debate", "provisional"]
Reason = Literal["clean", "conflict", "stale"]
DecisionStatus = Literal[
    "debating",          # debate queued / running
    "pending_approval",  # verdict ready, waiting for a human
    "needs_review",      # fallback / provisional / judge unsure - human must look closely
    "approved",          # terminal - action taken
    "rejected",          # terminal - nothing changed
    "superseded",        # terminal - another decision resolved the same facts
    "informational",     # direct answer, nothing to execute
]
SOURCES = ("crm", "finance", "pipeline")


# --------------------------------------------------------------------------- #
# Engine output
# --------------------------------------------------------------------------- #
class SourceReading(BaseModel):
    source: str
    evidence_id: str
    raw: Optional[str]
    normalized: Any
    display: str
    updated_at: str
    age_days: float
    F: float
    R: float


class ValueGroup(BaseModel):
    normalized: Any
    display: str
    sources: list[str]


class FactAssessment(BaseModel):
    deal_id: str
    field: str
    readings: list[SourceReading]
    groups: list[ValueGroup]           # largest / freshest first
    conflicted: bool
    F: float
    R: float
    A: float
    confidence: float
    route: Route
    reason: Reason
    conflict_hash: Optional[str] = None


# --------------------------------------------------------------------------- #
# Debate (LLM outputs are validated against these - strict, no extra keys)
# --------------------------------------------------------------------------- #
class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    evidence_ids: list[str]


class Argument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: str
    claims: list[Claim]
    weaknesses_of_other_side: list[str]


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    winner: Literal["A", "B", "neither"]
    resolved_value: str            # "" when winner == "neither"
    reasoning: str
    evidence_ids: list[str]
    residual_uncertainty: str
    needs_human_review: bool


class EvidenceItem(BaseModel):
    id: str
    kind: Literal["record", "audit", "context"]
    source: str
    summary: str
    at: Optional[str] = None
    cited: bool = False


class DebateSide(BaseModel):
    label: str                # "A" / "B"
    claim: str                # what this side argues, human readable
    value: Optional[str]      # display value defended ("" for re-verify side)
    normalized: Any = None
    sources: list[str] = []


class DebateRecord(BaseModel):
    field: str
    reason: Reason
    conflict_hash: str
    side_a: DebateSide
    side_b: DebateSide
    proponent: Optional[Argument] = None
    challenger: Optional[Argument] = None
    verdict: Verdict
    llm_calls: int = 0
    cache_hit: bool = False
    fallback_used: bool = False
    degraded_roles: list[str] = []
    errors: list[str] = []
    consistency: Optional[dict] = None   # position-swap re-judging on high-stakes conflicts
    provider: str = ""
    model: str = ""
    duration_ms: int = 0


class Counterfactual(BaseModel):
    field: str
    rejected_value: Optional[str]
    rejected_sources: list[str]
    why_it_lost: str
    losing_argument: Optional[str] = None


class RiskHint(BaseModel):
    value_at_stake: float
    win_probability: float
    exposure: float            # value_at_stake * (1 - confidence)
    note: str


class ApprovalRecord(BaseModel):
    id: int
    decision_id: int
    action: Literal["approve", "reject"]
    actor: str
    note: str
    at: str
    effect: str = ""


class FactSummary(BaseModel):
    field: str
    route: Route
    reason: Reason
    confidence: float
    F: float
    R: float
    A: float
    groups: list[ValueGroup]
    readings: list[SourceReading]


class DecisionCard(BaseModel):
    id: int
    deal_id: str
    company: str
    query: str
    origin: Literal["scan", "query", "drift"]
    fields: list[str]
    path: Route
    reason: Reason
    answer: dict[str, Optional[str]]
    confidence: float
    confidence_breakdown: dict[str, float]
    confidence_field: Optional[str] = None   # the weakest fact (drives the decay chart)
    facts: list[FactSummary]
    evidence: list[EvidenceItem]
    debates: list[DebateRecord]
    counterfactuals: list[Counterfactual]
    risk_hint: Optional[RiskHint]
    status: DecisionStatus
    status_note: str = ""
    created_at: str
    resolved_at: Optional[str] = None
    expires_at: Optional[str] = None
    expired: bool = False
    time_to_decision_ms: Optional[int] = None
    decided_at: Optional[str] = None
    conflict_hashes: list[str] = []
    approvals: list[ApprovalRecord] = []
    discrepancies: list[dict] = []          # deterministic taxonomy, one per debated fact
    severity: Optional[Literal["high", "medium", "low"]] = None
    progress: Optional[dict] = None         # live debate stage while status == "debating"


# --------------------------------------------------------------------------- #
# API requests
# --------------------------------------------------------------------------- #
class ApproveRequest(BaseModel):
    action: Literal["approve", "reject"]
    actor: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)


class QueryRequest(BaseModel):
    q: str = Field(min_length=1, max_length=300)


class InjectRequest(BaseModel):
    deal_id: Optional[str] = None
    field: Optional[Literal["stage", "value", "close_date"]] = None
    source: Optional[Literal["crm", "finance", "pipeline"]] = None


class ClockRequest(BaseModel):
    offset_days: float = Field(ge=0, le=365)


class MonitorRequest(BaseModel):
    enabled: bool


class SourceEdit(BaseModel):
    field: str
    value: str = Field(max_length=120)
    actor: str = Field(default="presenter", max_length=80)
