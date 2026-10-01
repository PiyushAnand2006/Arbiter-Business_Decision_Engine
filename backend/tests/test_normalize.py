import pytest

from app.engine.normalize import (normalize_company, normalize_date, normalize_stage, normalize_value,
                                  to_source_format, values_equal)


@pytest.mark.parametrize("raw", ["Closed Won", "closed_won", "closed-won", "Closed - Won", "WON", "won", "Closed Won "])
def test_closed_won_synonyms(raw):
    assert normalize_stage(raw) == "closed_won"


@pytest.mark.parametrize("raw,expected", [
    ("Open - Negotiation", "negotiation"), ("negotiating", "negotiation"), ("Negotiation", "negotiation"),
    ("proposal-sent", "proposal"), ("Open - Proposal", "proposal"), ("qualified", "qualification"),
    ("Open - Prospect", "prospecting"), ("Closed - Lost", "closed_lost"), ("closed-lost", "closed_lost"),
])
def test_stage_vocabulary(raw, expected):
    assert normalize_stage(raw) == expected


def test_unknown_stage_is_kept_distinct():
    assert normalize_stage("on hold").startswith("unknown:")
    assert normalize_stage(None) is None


@pytest.mark.parametrize("raw", ["48000", "$48,000.00", "48K", "48k", "48,000", "USD 48000", 48000, "48000.00", "0.048M"])
def test_currency_formats(raw):
    assert normalize_value(raw) == 48000.0


def test_fractional_k():
    assert normalize_value("48.13K") == 48130.0


def test_bad_value():
    assert normalize_value("n/a") is None


@pytest.mark.parametrize("raw", ["2026-10-15", "10/15/2026", "15 Oct 2026", "Oct 15, 2026", "2026-10-15T09:30:00+00:00",
                                 "15/10/2026", "15-Oct-2026"])
def test_date_formats(raw):
    assert normalize_date(raw) == "2026-10-15"


def test_invalid_date():
    assert normalize_date("13/13/2026") is None


@pytest.mark.parametrize("a,b", [
    ("Garcia, Smith and Lee", "GARCIA, SMITH AND LEE"), ("Brown-Walsh", "Brown Walsh Inc."),
    ("Acme Corp", "ACME CORP."), ("Stanley LLC", "stanley llc"), ("Smith & Sons", "Smith and Sons Ltd"),
])
def test_company_cosmetics(a, b):
    assert normalize_company(a) == normalize_company(b)


def test_numeric_tolerance():
    assert values_equal("value", 48000.0, 48200.0, 0.005)      # 0.4 % - rounding
    assert not values_equal("value", 48000.0, 45000.0, 0.005)  # real conflict


@pytest.mark.parametrize("source", ["crm", "finance", "pipeline"])
@pytest.mark.parametrize("field,value", [("stage", "negotiation"), ("value", 48130.0), ("close_date", "2026-11-05")])
def test_round_trip_through_every_source_format(source, field, value):
    from app.engine.normalize import normalize_field
    raw = to_source_format(source, field, value)
    assert values_equal(field, normalize_field(field, raw), value, 0.005)
