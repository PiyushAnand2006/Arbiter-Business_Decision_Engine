"""Decision cards + human approval."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from ..schemas import ApproveRequest
from ..services.arbiter import ArbiterService
from .deps import get_svc, http_errors

router = APIRouter(tags=["decisions"])


@router.get("/decisions")
def list_decisions(status: Optional[str] = None, path: Optional[str] = None, deal_id: Optional[str] = None,
                   limit: int = 200, summary: bool = False, svc: ArbiterService = Depends(get_svc)):
    return svc.list_decisions(status=status, path=path, deal_id=deal_id, limit=min(limit, 1000), summary=summary)


@router.get("/decisions/{decision_id}")
@http_errors
def get_decision(decision_id: int, svc: ArbiterService = Depends(get_svc)):
    return svc.get_decision(decision_id)


@router.post("/decisions/{decision_id}/approve")
@http_errors
def approve(decision_id: int, req: ApproveRequest, svc: ArbiterService = Depends(get_svc)):
    """Human approval: {action: approve|reject, actor, note}. Nothing executes without it."""
    return svc.decide(decision_id, req)
