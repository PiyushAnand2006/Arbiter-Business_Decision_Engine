"""Engine-facing routes: scan, stats, query, deals, sources, priorities, config."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import settings
from ..schemas import QueryRequest, SourceEdit
from ..services.arbiter import ArbiterService
from .deps import get_svc, http_errors

router = APIRouter(tags=["engine"])


@router.post("/scan")
@http_errors
def scan(svc: ArbiterService = Depends(get_svc)):
    """Run the engine over every deal; create/refresh conflicts and decision cards."""
    return svc.scan()


@router.get("/stats")
def stats(svc: ArbiterService = Depends(get_svc)):
    return svc.stats()


@router.get("/config")
def config(svc: ArbiterService = Depends(get_svc)):
    return {**settings.public(), "llm_provider": svc.llm.provider, "llm_model": svc.llm.model,
            "formula": "C = wF·F + wR·R + wA·A",
            "freshness": "F = exp(-ln2 · age_days / half_life[field])",
            "reliability": "R = 1 - min(0.5, corrections_90d / max(1, updates_90d))",
            "agreement": "A = largest agreeing group / sources holding the field"}


@router.post("/query")
@http_errors
def query(req: QueryRequest, svc: ArbiterService = Depends(get_svc)):
    """Rule-parsed question ("status and value of D1042", "which open deals should we follow up on first?")."""
    return svc.query(req.q)


@router.get("/priorities")
def priorities(svc: ArbiterService = Depends(get_svc)):
    return svc.priorities()


@router.get("/deals")
def deals(svc: ArbiterService = Depends(get_svc)):
    return svc.deals()


@router.get("/deals/{deal_id}")
@http_errors
def deal(deal_id: str, svc: ArbiterService = Depends(get_svc)):
    return svc.deal_detail(deal_id.upper())


@router.get("/activity")
def activity(limit: int = 40, svc: ArbiterService = Depends(get_svc)):
    """Event timeline: detections, verdicts, approvals, edits, drift, resets."""
    return svc.activity(min(limit, 200))


@router.get("/sources/health")
def source_health(svc: ArbiterService = Depends(get_svc)):
    """Per-system scorecard: agreement rate, reliability, freshness, debates lost, corrections."""
    return svc.source_health()


@router.get("/export/decisions.csv")
def export_decisions(svc: ArbiterService = Depends(get_svc)):
    from fastapi.responses import Response
    return Response(svc.export_csv(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="arbiter-decisions.csv"'})


@router.get("/sources/{source}")
@http_errors
def source(source: str, svc: ArbiterService = Depends(get_svc)):
    return svc.source_table(source)


@router.patch("/sources/{source}/{deal_id}")
@http_errors
def edit_source(source: str, deal_id: str, edit: SourceEdit, svc: ArbiterService = Depends(get_svc)):
    """Live-edit a synthetic source record (S4 demo). Written with an audit entry."""
    return svc.edit_source(source, deal_id.upper(), edit)
