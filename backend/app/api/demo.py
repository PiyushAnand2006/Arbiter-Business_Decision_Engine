"""Demo controls (FR-9) + evaluation."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..agents.llm import MockClient
from ..schemas import ClockRequest, InjectRequest, MonitorRequest
from ..services import evaluation
from ..services.arbiter import ArbiterService
from .deps import get_svc, http_errors

router = APIRouter(tags=["demo"])


@router.post("/demo/inject")
@http_errors
def inject(req: InjectRequest | None = None, svc: ArbiterService = Depends(get_svc)):
    """Introduce a controlled drift into one source; the monitor / next scan catches it."""
    return svc.inject_drift(req or InjectRequest())


class ResetRequest(BaseModel):
    clear_debate_cache: bool = False


@router.post("/demo/reset")
@http_errors
def reset(req: ResetRequest | None = None, svc: ArbiterService = Depends(get_svc)):
    """Reseed the dataset to baseline (keeps the debate cache unless asked, so demos cost no quota)."""
    return svc.reset(clear_debate_cache=(req or ResetRequest()).clear_debate_cache)


@router.post("/demo/clock")
@http_errors
def clock(req: ClockRequest, svc: ArbiterService = Depends(get_svc)):
    """Fast-forward the engine clock to watch confidence decay (0 = real time)."""
    return svc.set_clock(req.offset_days)


@router.post("/demo/monitor")
def monitor(req: MonitorRequest, svc: ArbiterService = Depends(get_svc)):
    return svc.set_monitor(req.enabled)


class EvalRequest(BaseModel):
    live: bool = False


@router.post("/eval/run")
def run_eval(req: EvalRequest | None = None, svc: ArbiterService = Depends(get_svc)):
    """Evaluate on a throwaway copy of the seeded dataset. live=true uses the configured provider."""
    live = (req or EvalRequest()).live
    llm = svc.llm if live else MockClient(latency_ms=0)
    return evaluation.run_evaluation(llm=llm, cache_from=svc.store if live else None)


@router.get("/eval/latest")
def latest_eval():
    return evaluation.latest_report() or {}
