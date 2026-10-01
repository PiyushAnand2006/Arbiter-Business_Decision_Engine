import os
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Isolate tests from the demo database *before* app.config is imported.
_TMP = Path(tempfile.mkdtemp(prefix="arbiter-tests-"))
os.environ.update({
    "DB_PATH": str(_TMP / "api.db"),
    "GROUND_TRUTH_PATH": str(_TMP / "ground_truth.json"),
    "LLM_PROVIDER": "mock",
    "MOCK_LATENCY_MS": "0",
    "MONITOR_ENABLED": "false",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.llm import MockClient  # noqa: E402
from app.config import settings  # noqa: E402
from app.data.seed import seed_store  # noqa: E402
from app.db import Store  # noqa: E402
from app.services.arbiter import ArbiterService  # noqa: E402

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def cfg():
    return replace(settings, MONITOR_ENABLED=False, MOCK_LATENCY_MS=0, GROUND_TRUTH_PATH=_TMP / "gt.json")


@pytest.fixture
def seeded(cfg):
    store = Store(":memory:")
    truth = seed_store(store, now=NOW, seed=cfg.SEED, n_deals=cfg.N_DEALS)
    yield store, truth
    store.close()


@pytest.fixture
def svc(seeded, cfg):
    store, truth = seeded
    s = ArbiterService(store, cfg, llm=MockClient(latency_ms=0), async_debates=False)
    s.fixed_now = NOW
    s.truth = truth
    yield s
    s.shutdown()
