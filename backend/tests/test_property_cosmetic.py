"""Property: cosmetic-only differences never produce a DEBATE route."""
import random
from datetime import date, datetime, timedelta, timezone

from app.engine.assess import assess_deal
from app.engine.normalize import STAGES, to_source_format

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def _cosmetic_variants(rng, source, field, canonical, company):
    raw = to_source_format(source, field, canonical, company_hint=company)
    if field == "value" and rng.random() < 0.5:
        v = float(canonical)
        raw = rng.choice([f"{v:.2f}", f"${v:,.0f}", f"{v/1000:.3f}K", f"USD {v:,.2f}", str(int(round(v / 10) * 10))])
    if field == "company" and rng.random() < 0.5:
        raw = rng.choice([raw.upper(), raw.lower(), raw + " Inc.", raw.replace(",", ""), f"  {raw}  "])
    if field == "stage" and rng.random() < 0.3:
        raw = raw.upper()
    if field == "close_date" and rng.random() < 0.5:
        d = date.fromisoformat(canonical)
        raw = rng.choice([d.strftime("%b %d, %Y"), d.strftime("%d-%b-%Y"), d.isoformat() + "T00:00:00Z"])
    return raw


def test_cosmetic_noise_never_triggers_debate(cfg):
    rng = random.Random(7)
    for trial in range(400):
        company = rng.choice(["Garcia, Smith and Lee", "Brown-Walsh", "Stanley LLC", "O'Neil Group", "Acme & Co"])
        canon = {
            "company": company,
            "stage": rng.choice(STAGES),
            "value": float(rng.randrange(400, 5000) * 50),
            "close_date": (date(2026, 10, 1) + timedelta(days=rng.randint(0, 200))).isoformat(),
        }
        rows = {}
        for s in ("crm", "finance", "pipeline"):
            row = {f: _cosmetic_variants(rng, s, f, v, company) for f, v in canon.items()}
            row["updated_at"] = (NOW - timedelta(days=rng.uniform(0, 8))).isoformat()
            rows[s] = row
        facts = assess_deal(f"T{trial}", rows, {}, NOW, cfg)
        for f in facts:
            assert f.route == "direct", (trial, f.field, [(r.source, r.raw) for r in f.readings])


def test_real_difference_does_trigger_debate(cfg):
    base = {"company": "Acme", "stage": "Negotiation", "value": "48000", "close_date": "2026-11-01",
            "updated_at": NOW.isoformat()}
    rows = {"crm": dict(base), "finance": {**base, "value": "$45,000.00"}, "pipeline": dict(base)}
    facts = {f.field: f for f in assess_deal("X1", rows, {}, NOW, cfg)}
    assert facts["value"].route == "debate" and facts["value"].reason == "conflict"
    assert facts["stage"].route == "direct"
