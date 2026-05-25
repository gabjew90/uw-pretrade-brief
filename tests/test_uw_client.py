"""Tests for src.uw_client.

Fixture-based — no network calls. Verifies the loaded fixtures match the shape
the rest of the code expects. A live schema-drift test exists separately
(test_live_schema.py, opt-in via `pytest -m live`).
"""
from __future__ import annotations
import pytest
from src.uw_client import (
    _unwrap,
    gex_records,
    oi_records,
    flow_records,
    hot_tickers,
    term_structure,
    extract_spot,
    extract_iv_rank,
    max_pain_value,
    darkpool_records,
    darkpool_net_premium,
    next_earnings,
)


# ---------- Shape contracts on raw payloads ----------

def test_gex_payload_has_strike_records(gex_strike_spy):
    rows = _unwrap(gex_strike_spy)
    assert isinstance(rows, list) and len(rows) > 0
    sample = rows[0]
    assert "strike" in sample
    assert "call_gamma_oi" in sample and "put_gamma_oi" in sample


def test_oi_payload_has_strike_records(oi_strike_spy):
    rows = _unwrap(oi_strike_spy)
    assert isinstance(rows, list) and len(rows) > 0
    sample = rows[0]
    assert "strike" in sample
    assert "call_oi" in sample and "put_oi" in sample


def test_flow_payload_has_records(flow_alerts_spy):
    rows = _unwrap(flow_alerts_spy)
    assert isinstance(rows, list) and len(rows) > 0
    sample = rows[0]
    assert "type" in sample
    assert "total_premium" in sample
    assert "ticker" in sample


def test_volatility_payload_has_dte_volatility(volatility_spy):
    rows = _unwrap(volatility_spy)
    assert isinstance(rows, list) and len(rows) > 0
    sample = rows[0]
    assert "dte" in sample
    assert "volatility" in sample


def test_max_pain_payload_has_front_week(max_pain_spy):
    rows = _unwrap(max_pain_spy)
    assert isinstance(rows, list) and len(rows) > 0
    first = rows[0]
    assert "max_pain" in first
    assert "expiry" in first


# ---------- Parser outputs ----------

def test_gex_records_sorted_by_strike(gex_strike_spy):
    records = gex_records(gex_strike_spy)
    assert len(records) > 0
    strikes = [r["strike"] for r in records]
    assert strikes == sorted(strikes)
    # Every record must have a numeric gamma (the parser computed call_oi - put_oi)
    for r in records:
        assert isinstance(r["gamma"], float)


def test_oi_records_sorted_by_strike(oi_strike_spy):
    recs = oi_records(oi_strike_spy)
    assert len(recs) > 0
    assert [r["strike"] for r in recs] == sorted(r["strike"] for r in recs)
    for r in recs:
        assert isinstance(r["call_oi"], int)
        assert isinstance(r["put_oi"], int)


def test_flow_records_returns_list_with_sides_and_premiums(flow_alerts_spy):
    records = flow_records(flow_alerts_spy)
    assert isinstance(records, list)
    assert len(records) > 0
    for r in records[:5]:
        assert r["side"] in ("call", "put"), f"unexpected side: {r['side']}"
        assert isinstance(r["premium_usd"], float)
        assert r["premium_usd"] >= 0


def test_hot_tickers_returns_unique_symbols(hot_today):
    tickers = hot_tickers(hot_today, limit=15)
    assert isinstance(tickers, list)
    assert len(tickers) == len(set(tickers))
    assert len(tickers) > 0


def test_term_structure_sorted_by_dte(volatility_spy):
    ts = term_structure(volatility_spy)
    assert len(ts) > 0
    assert [r["dte"] for r in ts] == sorted(r["dte"] for r in ts)
    for r in ts:
        assert isinstance(r["dte"], int)
        assert isinstance(r["iv"], float)
        assert 0 < r["iv"] < 5  # IV expressed as decimal (0.25 = 25%)


# ---------- Scalar extractors ----------

def test_extract_spot_finds_from_flow_underlying_price(flow_alerts_spy, max_pain_spy):
    # extract_spot accepts variadic payloads — try flow first (has underlying_price),
    # fall through to max_pain (has close).
    spot = extract_spot(flow_alerts_spy, max_pain_spy)
    assert spot is not None
    assert spot > 0


def test_extract_spot_returns_none_for_empty():
    assert extract_spot(None, {"data": []}) is None


def test_max_pain_value_returns_front_week_strike(max_pain_spy):
    mp = max_pain_value(max_pain_spy)
    assert mp is not None
    assert mp > 0


def test_extract_iv_rank_returns_none_when_absent(volatility_spy):
    # /volatility/term-structure response doesn't include IV rank
    assert extract_iv_rank(volatility_spy) is None


def test_extract_iv_rank_uses_interpolated_iv_when_provided(volatility_spy, interpolated_iv_spy):
    # /interpolated-iv has a 'percentile' field per DTE row; we pick front-week
    rank = extract_iv_rank(volatility_spy, interpolated_iv_spy)
    assert rank is not None
    assert 0 <= rank <= 100  # normalized to 0-100 scale


# ---------- New endpoints: dark pool, earnings ----------

def test_darkpool_records_classify_by_nbbo_midpoint(darkpool_spy):
    records = darkpool_records(darkpool_spy)
    assert len(records) > 0
    valid_sides = {"buy", "sell", "neutral"}
    for r in records:
        assert r["side"] in valid_sides
        assert isinstance(r["price"], float) and r["price"] > 0
        assert isinstance(r["premium"], float)
        assert isinstance(r["size"], int)


def test_darkpool_net_premium_returns_signed_value(darkpool_spy):
    records = darkpool_records(darkpool_spy)
    net = darkpool_net_premium(records)
    assert isinstance(net, float)


def test_darkpool_net_premium_synthetic():
    """Pure unit test on synthetic records."""
    recs = [
        {"side": "buy", "premium": 1_000_000, "ts": "", "price": 0, "size": 0, "raw": {}},
        {"side": "sell", "premium": 300_000, "ts": "", "price": 0, "size": 0, "raw": {}},
        {"side": "neutral", "premium": 500_000, "ts": "", "price": 0, "size": 0, "raw": {}},
    ]
    assert darkpool_net_premium(recs) == 700_000.0


def test_next_earnings_returns_none_for_etf(earnings_spy):
    """SPY is an ETF — earnings list is empty, parser returns None."""
    assert next_earnings(earnings_spy) is None


def test_next_earnings_synthetic_picks_nearest_future():
    """Synthetic: with multiple dates, pick the nearest future one."""
    import datetime as _dt
    future_near = (_dt.date.today() + _dt.timedelta(days=10)).isoformat()
    future_far = (_dt.date.today() + _dt.timedelta(days=100)).isoformat()
    past = (_dt.date.today() - _dt.timedelta(days=30)).isoformat()
    payload = {"data": [
        {"expected_date": past},
        {"expected_date": future_far},
        {"expected_date": future_near},
    ]}
    result = next_earnings(payload)
    assert result == future_near


# ---------- Smoke imports ----------

def test_fetch_module_imports():
    """fetch module imports without side effects (proven by other tests)."""
    from src import uw_client
    for name in (
        "fetch_spot_exposures_strike", "fetch_oi_strike", "fetch_flow_alerts",
        "fetch_volatility", "fetch_max_pain",
        "fetch_darkpool", "fetch_earnings", "fetch_interpolated_iv",
    ):
        assert hasattr(uw_client, name), f"missing endpoint method: {name}"
