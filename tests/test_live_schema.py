"""Live-API smoke tests. Skipped by default; run with `pytest -m live`.

These hit real UW + Gemini and assert response shapes still match what the
parsers and synthesis expect. Run on demand to catch schema drift early."""
from __future__ import annotations
import pytest
from src import uw_client
from src.synth import _call_gemini, build_prompt, validate_output


@pytest.mark.live
def test_uw_endpoints_respond_with_expected_shape():
    """All 8 UW endpoints respond and the parsed shape matches the fixture contract."""
    gex = uw_client.fetch_spot_exposures_strike("SPY")
    oi = uw_client.fetch_oi_strike("SPY")
    flow = uw_client.fetch_flow_alerts("SPY", limit=50)
    vol = uw_client.fetch_volatility("SPY")
    mp = uw_client.fetch_max_pain("SPY")
    dp = uw_client.fetch_darkpool("SPY", limit=50)
    earn = uw_client.fetch_earnings("SPY")
    iv = uw_client.fetch_interpolated_iv("SPY")

    assert uw_client.gex_records(gex), "gex_records empty"
    assert uw_client.oi_records(oi), "oi_records empty"
    assert isinstance(uw_client.flow_records(flow), list)
    assert isinstance(uw_client.term_structure(vol), list)
    assert uw_client.max_pain_value(mp) is not None
    assert isinstance(uw_client.darkpool_records(dp), list)
    # SPY earnings list is empty (it's an ETF); next_earnings returns None — that's still a valid shape
    _ = uw_client.next_earnings(earn)
    # interpolated_iv should yield an IV rank
    assert uw_client.extract_iv_rank(vol, iv) is not None


@pytest.mark.live
def test_uw_hot_today_returns_tickers():
    payload = uw_client.fetch_flow_alerts(ticker=None, limit=15)
    tickers = uw_client.hot_tickers(payload, 15)
    assert tickers, "hot_tickers empty list — UW returned no flow today?"


@pytest.mark.live
def test_gemini_responds_within_validator_constraints():
    """Live Gemini call on a synthetic payload either passes the validator or
    returns NO_INSIGHT — both are acceptable. Catches prompt drift."""
    patterns = {
        "pinning":       {"firing": True,  "intensity": 0.8, "note": {"strike": 450.0}},
        "gamma_squeeze": {"firing": False, "intensity": 0.0, "note": {}},
        "flow":          {"firing": True,  "intensity": 0.6,
                          "note": {"side": "long", "net_premium_usd": 2_000_000}},
        "vol_regime":    {"firing": False, "intensity": 0.0,
                          "note": {"front_minus_30d_pts": 2.0}},
    }
    key_numbers = {"spot": 449.50, "iv_rank": 65, "dte": 4}
    text, _usage = _call_gemini(build_prompt("NVDA", patterns, key_numbers))
    if text.strip().upper().startswith("NO_INSIGHT"):
        return  # acceptable per the prompt's own contract
    ok, reason = validate_output(text, must_contain_numbers=[450, 449.50, 65, 2_000_000])
    assert ok, f"live Gemini output failed validator: {reason}\noutput was: {text!r}"
