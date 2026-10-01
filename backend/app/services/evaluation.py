"""Evaluation against injected ground truth (PRD §7 metrics / evaluation slide).

Runs on a throwaway database seeded with the same seed, so it never disturbs
the live demo. Also scores a "majority + recency" rule baseline on the exact
same evidence packets, to show what the debate adds.

    python -m app.services.evaluation            # mock provider
    python -m app.services.evaluation --live     # configured provider (spends quota)
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..agents.debate import rule_based_verdict
from ..agents.llm import LLMClient, MockClient, make_client
from ..config import ROOT_DIR, settings
from ..db import Store
from ..data.seed import seed_store
from ..engine.normalize import display_value, normalize_field, values_equal
from .arbiter import ArbiterService

REPORT_PATH = ROOT_DIR / "data" / "eval_report.json"
TARGETS = {
    "conflict_recall": (">=", 0.95), "false_conflict_rate": ("<=", 0.05),
    "reconciliation_accuracy": (">=", 0.80), "clean_debate_rate": ("<=", 0.0),
    "max_time_to_decision_s": ("<", 60.0), "citation_validity": (">=", 1.0),
}


def _meets(metric: str, value: Optional[float]) -> Optional[bool]:
    if value is None or metric not in TARGETS:
        return None
    op, target = TARGETS[metric]
    return {">=": value >= target, "<=": value <= target, "<": value < target}[op]


def run_evaluation(llm: Optional[LLMClient] = None, now: Optional[datetime] = None,
                   cache_from: Optional[Store] = None, save: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    cfg = replace(settings, MAX_DEBATES_PER_SESSION=10_000, MONITOR_ENABLED=False)
    llm = llm or MockClient(latency_ms=0)
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "eval.db")
        truth = seed_store(store, now=now, seed=cfg.SEED, n_deals=cfg.N_DEALS)
        if cache_from is not None:  # reuse already-paid-for debates from the demo DB
            for row in cache_from.query("SELECT * FROM debates"):
                with store.tx() as c:
                    c.execute("INSERT OR IGNORE INTO debates(conflict_hash,deal_id,field,transcript_json,verdict_json,"
                              "llm_calls,provider,model,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                              [row["conflict_hash"], row["deal_id"], row["field"], row["transcript_json"],
                               row["verdict_json"], row["llm_calls"], row["provider"], row["model"], row["created_at"]])
        svc = ArbiterService(store, cfg, llm=llm, async_debates=False)
        svc.fixed_now = now

        t0 = time.perf_counter()
        facts_by_deal, _ = svc.assess_all()
        scan_only_ms = int((time.perf_counter() - t0) * 1000)
        t1 = time.perf_counter()
        summary = svc.scan()  # debates run inline
        total_s = time.perf_counter() - t1

        conflict_truth = {(i["deal_id"], i["field"]): i for i in truth["items"] if i["kind"] == "conflict"}
        stale_truth = {i["deal_id"]: i for i in truth["items"] if i["kind"] == "stale"}
        injected_deals = set(conflict_truth_deals := {d for d, _ in conflict_truth}) | set(stale_truth)

        detected, stale_detected, clean_facts, clean_debated = set(), set(), 0, 0
        for did, facts in facts_by_deal.items():
            for f in facts:
                if f.reason == "conflict":
                    detected.add((did, f.field))
                if f.reason == "stale":
                    stale_detected.add(did)
                if did not in injected_deals:
                    clean_facts += 1
                    clean_debated += f.route != "direct"
        compared_clean = sum(len(fs) for d, fs in facts_by_deal.items()) - len(conflict_truth)
        false_conflicts = detected - set(conflict_truth)

        cards = store.list_decisions(limit=5000)
        debates_by_key: dict = {}
        for card in cards:
            for rec in card["debates"]:
                key = (card["deal_id"], rec["field"])
                debates_by_key[key] = (rec, card)

        rows, correct, base_correct, judged = [], 0, 0, 0
        verdicts_total = verdicts_valid = fallbacks = 0
        for card in cards:
            for rec in card["debates"]:
                verdicts_total += 1
                fallbacks += rec["fallback_used"]
                verdicts_valid += not rec["fallback_used"]
        for key, item in sorted(conflict_truth.items()) + sorted(((d, "record"), i) for d, i in stale_truth.items()):
            did, fieldname = key
            rec, card = debates_by_key.get(key, (None, None))
            if item["kind"] == "conflict":
                truth_val = item["truth"]
                if rec and rec["verdict"]["winner"] in ("A", "B"):
                    side = rec["side_a"] if rec["verdict"]["winner"] == "A" else rec["side_b"]
                    got, got_disp = side["normalized"], side["value"]
                else:
                    got, got_disp = None, "unresolved"
                ok = got is not None and values_equal(fieldname, got, truth_val, settings.NUMERIC_TOLERANCE)
            else:
                expected = item["expected_verdict"]
                w = rec["verdict"]["winner"] if rec else None
                got_disp = {"A": "holds", "B": "reverify"}.get(w, "unresolved")
                ok = got_disp == expected
            # baseline on the identical packet
            base_disp, base_ok = "n/a", False
            if rec:
                facts = svc.assess_one(did, card["fields"])
                packet = next((p for p in svc.packets_for(did, facts) if p["field"] == fieldname), None)
                if packet:
                    bv = rule_based_verdict(packet, "baseline")
                    if item["kind"] == "conflict":
                        bside = packet["sides"][bv.winner]
                        base_disp = bside["value"]
                        base_ok = values_equal(fieldname, bside["normalized"], item["truth"], settings.NUMERIC_TOLERANCE)
                    else:
                        base_disp = {"A": "holds", "B": "reverify"}[bv.winner]
                        base_ok = base_disp == item["expected_verdict"]
            judged += 1
            correct += ok
            base_correct += base_ok
            rows.append({
                "deal_id": did, "field": fieldname, "pattern": item["pattern"], "kind": item["kind"],
                "truth": item["truth_display"], "arbiter": got_disp, "arbiter_correct": bool(ok),
                "baseline": base_disp, "baseline_correct": bool(base_ok),
                "path": card["path"] if card else None, "cached": bool(rec and rec.get("cache_hit")),
                "llm_calls": rec["llm_calls"] if rec else 0,
            })

        ttd = [c["time_to_decision_ms"] for c in cards if c.get("time_to_decision_ms") is not None and c["path"] != "direct"]
        budget = svc.budget.snapshot()
        live = [d for c in cards for d in c["debates"] if not d["cache_hit"] and d["provider"] != "rules"]
        standard = [d["llm_calls"] for d in live if not d.get("consistency")]
        checked = [d for d in live if d.get("consistency")]
        metrics = {
            "conflict_recall": round(len(detected & set(conflict_truth)) / max(1, len(conflict_truth)), 4),
            "stale_recall": round(len(stale_detected & set(stale_truth)) / max(1, len(stale_truth)), 4),
            "false_conflict_rate": round(len(false_conflicts) / max(1, compared_clean), 4),
            "reconciliation_accuracy": round(correct / max(1, judged), 4),
            "baseline_accuracy": round(base_correct / max(1, judged), 4),
            "clean_debate_rate": round(clean_debated / max(1, clean_facts), 4),
            "citation_validity": round(verdicts_valid / max(1, verdicts_total), 4) if verdicts_total else None,
            "avg_time_to_decision_s": round(sum(ttd) / len(ttd) / 1000, 3) if ttd else None,
            "max_time_to_decision_s": round(max(ttd) / 1000, 3) if ttd else None,
            "scan_ms": scan_only_ms,
            "end_to_end_s": round(total_s, 2),
            "llm_calls": budget["llm_calls"],
            "avg_calls_per_debate": round(budget["llm_calls"] / max(1, budget["debates_run"]), 2),
            "avg_calls_standard": round(sum(standard) / len(standard), 2) if standard else None,
            "consistency_checks": len(checked),
            "consistency_agreement": round(sum(1 for d in checked if d["consistency"].get("agreed")) / len(checked), 4)
            if checked else None,
        }
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider": llm.provider, "model": llm.model, "seed": cfg.SEED, "deals": truth["n_deals"],
            "facts_scanned": summary["facts_scanned"], "facts_direct": summary["direct"],
            "facts_debated": summary["debate"], "injected_conflicts": len(conflict_truth),
            "injected_stale": len(stale_truth), "false_conflicts": sorted(f"{d}.{f}" for d, f in false_conflicts),
            "metrics": metrics,
            "targets": {k: {"op": op, "target": t, "met": _meets(k, metrics.get(k))} for k, (op, t) in TARGETS.items()},
            "fallbacks": fallbacks, "items": rows,
            "note": ("Mock provider = deterministic evidence-weighing reasoner (no LLM). Run with a live provider "
                     "for model numbers." if llm.provider == "mock" else ""),
        }
        svc.shutdown()
        store.close()
    if save:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2))
    return report


def latest_report() -> Optional[dict]:
    if REPORT_PATH.exists():
        return json.loads(REPORT_PATH.read_text())
    return None


def main():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Evaluate Arbiter against injected ground truth")
    ap.add_argument("--live", action="store_true", help="use the configured LLM provider (spends quota)")
    args = ap.parse_args()
    llm = make_client(settings) if args.live else MockClient(latency_ms=0)
    r = run_evaluation(llm=llm, cache_from=Store(settings.DB_PATH) if args.live and settings.DB_PATH.exists() else None)
    m = r["metrics"]
    print(f"\nArbiter evaluation - provider={r['provider']} model={r['model']} seed={r['seed']} deals={r['deals']}")
    print(f"facts scanned {r['facts_scanned']}: {r['facts_direct']} direct, {r['facts_debated']} debated\n")
    for k, v in m.items():
        t = r["targets"].get(k)
        mark = "" if not t else ("  PASS" if t["met"] else "  FAIL") + f" (target {t['op']} {t['target']})"
        print(f"  {k:<26} {v}{mark}")
    print("\n  deal   field       pattern                 truth          arbiter        baseline")
    for it in r["items"]:
        print(f"  {it['deal_id']:<6} {it['field']:<11} {it['pattern']:<23} {str(it['truth']):<14} "
              f"{str(it['arbiter']):<12}{'✓' if it['arbiter_correct'] else '✗'}  {str(it['baseline']):<12}"
              f"{'✓' if it['baseline_correct'] else '✗'}")
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
