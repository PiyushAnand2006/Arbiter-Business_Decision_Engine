"""Build / reset the synthetic dataset.

    python -m app.data.seed            # reseed the demo DB (keeps the debate cache)
    python -m app.data.seed --wipe     # reseed and clear the debate cache too
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import settings
from ..db import Store
from . import injector
from .generator import DatasetBuilder


def build_dataset(seed: int, n_deals: int, now: datetime) -> tuple[dict, dict]:
    b = DatasetBuilder(seed, n_deals, now)
    b.build_base()
    injector.prepare(b)
    b.build_history()
    truth = injector.inject(b)
    return b.render(), truth


def seed_store(store: Store, now: Optional[datetime] = None, seed: Optional[int] = None,
               n_deals: Optional[int] = None, clear_debate_cache: bool = False,
               ground_truth_path: Optional[Path] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    dataset, truth = build_dataset(seed if seed is not None else settings.SEED,
                                   n_deals or settings.N_DEALS, now)
    store.reset(clear_debate_cache=clear_debate_cache)
    store.load_dataset(dataset)
    store.set_meta("seeded_at", now.isoformat())
    if ground_truth_path:
        ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
        ground_truth_path.write_text(json.dumps(truth, indent=2))
    return truth


def main():
    ap = argparse.ArgumentParser(description="Seed the Arbiter demo database")
    ap.add_argument("--wipe", action="store_true", help="also clear the debate cache")
    args = ap.parse_args()
    store = Store(settings.DB_PATH)
    truth = seed_store(store, clear_debate_cache=args.wipe, ground_truth_path=settings.GROUND_TRUTH_PATH)
    kinds = {}
    for item in truth["items"]:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    print(f"Seeded {truth['n_deals']} deals into {settings.DB_PATH} "
          f"({kinds.get('conflict', 0)} injected conflicts, {kinds.get('stale', 0)} stale records)")


if __name__ == "__main__":
    main()
