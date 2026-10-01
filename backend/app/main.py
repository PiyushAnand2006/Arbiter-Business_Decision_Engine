"""FastAPI app: API under /api, built dashboard served at /.

    uvicorn app.main:app --port 8000        (from backend/)
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import decisions, demo, scan
from .config import ROOT_DIR, settings
from .db import Store
from .services.arbiter import ArbiterService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("arbiter")
DIST = ROOT_DIR / "frontend" / "dist"


def monitor_loop(svc: ArbiterService, stop: threading.Event):
    """Continuous background monitoring: re-scan every few seconds (cheap - no LLM)."""
    while not stop.wait(settings.MONITOR_INTERVAL_S):
        if not svc.monitor_enabled:
            continue
        try:
            summary = svc.scan()
            if summary["new_decisions"]:
                log.info("monitor: %d new decision(s) %s", len(summary["new_decisions"]), summary["new_decisions"])
        except Exception:
            log.exception("monitor scan failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = Store(settings.DB_PATH)
    svc = ArbiterService(store, settings)
    if not store.deal_ids():
        log.info("empty database - seeding synthetic dataset (seed=%s)", settings.SEED)
        svc.reset()
    else:
        svc.resume_pending()
        svc.scan()
    log.info("Arbiter ready - provider=%s model=%s", svc.llm.provider, svc.llm.model)
    app.state.svc = svc
    stop = threading.Event()
    threading.Thread(target=monitor_loop, args=(svc, stop), daemon=True, name="monitor").start()
    yield
    stop.set()
    svc.shutdown()
    store.close()


app = FastAPI(title="Arbiter", version="1.0.0", lifespan=lifespan,
              description="AI decision engine that only debates when business data actually disagrees.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

for r in (scan.router, decisions.router, demo.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True}


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = DIST / path
        if path and target.is_file() and DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend():
        return JSONResponse({"message": "Arbiter API is running. Build the dashboard with `npm run build` in "
                                        "frontend/, or open /docs for the API."})
