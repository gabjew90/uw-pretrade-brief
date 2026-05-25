"""Tests for src.patterns. Mix of synthetic edge cases + real SPY fixtures."""
from __future__ import annotations
from src.patterns import (
    Verdict,
    detect_pinning,
    detect_gamma_squeeze,
    detect_flow,
    detect_vol_regime,
    detect_all,
)
from src.uw_client import gex_records, flow_records, term_structure


# ---------- Verdict ----------

def test_verdict_to_dict_roundtrip():
    v = Verdict("pinning", True, 0.7, {"strike": 450})
    d = v.to_dict()
    assert d == {"kind": "pinning", "firing": True, "intensity": 0.7, "note": {"strike": 450}}


# ---------- Pinning ----------

def test_pinning_synthetic_strong_pin():
    records = [
        {"strike": 100.0, "gamma": 1e6},
        {"strike": 101.0, "gamma": 5e7},   # massive concentration at spot
        {"strike": 102.0, "gamma": 1e6},
    ]
    v = detect_pinning(records, spot=101.0)
    assert v.firing is True
    assert v.intensity > 0.5
    assert v.note["strike"] == 101.0


def test_pinning_synthetic_no_pin_when_spread_even():
    """Five evenly-spread strikes within ±5% of spot → max concentration is
    1/5 = 0.20, below the 0.30 threshold."""
    records = [{"strike": 100.0 + i, "gamma": 1e6} for i in range(-2, 3)]
    v = detect_pinning(records, spot=100.0)
    assert v.firing is False


def test_pinning_empty_input():
    v = detect_pinning([], spot=100.0)
    assert v.firing is False
    assert "reason" in v.note


def test_pinning_invalid_spot():
    v = detect_pinning([{"strike": 100.0, "gamma": 1e6}], spot=0)
    assert v.firing is False


def test_pinning_on_spy_fixture(gex_strike_spy, max_pain_spy):
    """SPY at any time may or may not have a pin firing. Just verify the
    detector returns a well-formed Verdict given real data."""
    records = gex_records(gex_strike_spy)
    spot = float(max_pain_spy["data"][0]["close"])  # close from front-week max-pain row
    v = detect_pinning(records, spot=spot)
    assert isinstance(v, Verdict)
    assert v.kind == "pinning"
    assert 0.0 <= v.intensity <= 1.0


# ---------- Gamma squeeze ----------

def test_squeeze_synthetic_short_dealers_above_spot():
    """Spot=100, strikes 95 below + 105/110 short above → squeeze up."""
    records = [
        {"strike": 95.0,  "gamma": 5e6},   # positive gamma below spot
        {"strike": 105.0, "gamma": -8e6},  # dealers short above
        {"strike": 110.0, "gamma": -1e7},
    ]
    v = detect_gamma_squeeze(records, spot=100.0)
    assert v.firing is True
    assert v.note["direction"] == "up"
    assert v.intensity > 0.3


def test_squeeze_synthetic_balanced_does_not_fire():
    records = [
        {"strike": 95.0,  "gamma": 1e6},
        {"strike": 100.0, "gamma": 1e6},
        {"strike": 105.0, "gamma": 1e6},
    ]
    v = detect_gamma_squeeze(records, spot=100.0)
    assert v.firing is False


def test_squeeze_one_sided_strikes():
    """If all strikes are above OR below spot, squeeze can't be computed."""
    v = detect_gamma_squeeze([{"strike": 110.0, "gamma": -1e6}], spot=100.0)
    assert v.firing is False


def test_squeeze_on_spy_fixture(gex_strike_spy, max_pain_spy):
    records = gex_records(gex_strike_spy)
    spot = float(max_pain_spy["data"][0]["close"])
    v = detect_gamma_squeeze(records, spot=spot)
    assert isinstance(v, Verdict)
    assert 0.0 <= v.intensity <= 1.0


# ---------- Flow ----------

def test_flow_synthetic_heavy_call_buying():
    records = [
        {"side": "call", "premium_usd": 1_500_000, "ts": "x"},
        {"side": "call", "premium_usd": 900_000,   "ts": "x"},
        {"side": "put",  "premium_usd": 200_000,   "ts": "x"},
    ]
    v = detect_flow(records)
    assert v.firing is True
    assert v.note["side"] == "long"
    assert v.note["net_premium_usd"] > 0


def test_flow_synthetic_neutral_does_not_fire():
    records = [
        {"side": "call", "premium_usd": 500_000, "ts": "x"},
        {"side": "put",  "premium_usd": 500_000, "ts": "x"},
    ]
    v = detect_flow(records)
    assert v.firing is False
    assert v.note["side"] == "neutral"


def test_flow_empty_input():
    v = detect_flow([])
    assert v.firing is False


def test_flow_with_dark_pool_aligned_amplifies_intensity():
    """Long options flow + dark-pool buying → intensity boosted."""
    # Use a flow signal that's firing but NOT saturated, so we can see
    # the dark-pool intensity boost
    records = [
        {"side": "call", "premium_usd": 650_000, "ts": "x"},
        {"side": "put",  "premium_usd": 350_000, "ts": "x"},
    ]
    base = detect_flow(records)
    assert base.firing and base.intensity < 1.0  # sanity: room to grow
    boosted = detect_flow(records, dp_net_premium=5_000_000)
    assert boosted.intensity > base.intensity
    assert boosted.note["dp_alignment"] == "aligned"


def test_flow_with_dark_pool_divergent_halves_intensity():
    """Long options flow + heavy dark-pool selling → intensity halved."""
    records = [
        {"side": "call", "premium_usd": 650_000, "ts": "x"},
        {"side": "put",  "premium_usd": 350_000, "ts": "x"},
    ]
    base = detect_flow(records)
    diverged = detect_flow(records, dp_net_premium=-5_000_000)
    assert diverged.intensity < base.intensity
    assert diverged.note["dp_alignment"] == "divergent"


def test_flow_with_dark_pool_weak_signal_does_not_change():
    """Dark pool net premium below the alignment threshold → no change."""
    records = [
        {"side": "call", "premium_usd": 650_000, "ts": "x"},
        {"side": "put",  "premium_usd": 350_000, "ts": "x"},
    ]
    base = detect_flow(records)
    weak = detect_flow(records, dp_net_premium=50_000)  # too small
    assert weak.intensity == base.intensity
    assert weak.note["dp_alignment"] == "weak_dp"


def test_flow_on_spy_fixture(flow_alerts_spy):
    records = flow_records(flow_alerts_spy)
    v = detect_flow(records)
    assert isinstance(v, Verdict)
    assert 0.0 <= v.intensity <= 1.0


# ---------- Vol regime ----------

def test_vol_regime_inverted_front_week_event_driven():
    term = [{"dte": 4, "iv": 0.48}, {"dte": 30, "iv": 0.32}]  # 16-pt inversion
    v = detect_vol_regime(term)
    assert v.firing is True
    assert v.note["regime"] == "event_driven"
    assert v.note["front_minus_30d_pts"] >= 5


def test_vol_regime_normal_term_structure_does_not_fire():
    term = [{"dte": 4, "iv": 0.22}, {"dte": 30, "iv": 0.21}]
    v = detect_vol_regime(term)
    assert v.firing is False


def test_vol_regime_empty():
    v = detect_vol_regime([])
    assert v.firing is False


def test_vol_regime_missing_front_or_30d():
    term = [{"dte": 90, "iv": 0.20}]  # only long-dated, no front-week or 30-day
    v = detect_vol_regime(term)
    assert v.firing is False


def test_vol_regime_on_spy_fixture(volatility_spy):
    term = term_structure(volatility_spy)
    v = detect_vol_regime(term)
    assert isinstance(v, Verdict)
    assert 0.0 <= v.intensity <= 1.0


# ---------- Aggregator ----------

def test_detect_all_returns_four_verdicts():
    bundle = detect_all(
        gex_recs=[{"strike": 100.0, "gamma": 1e6}],
        flow_recs=[],
        spot=100.0,
        term_structure=[{"dte": 4, "iv": 0.22}, {"dte": 30, "iv": 0.21}],
    )
    assert set(bundle.keys()) == {"pinning", "gamma_squeeze", "flow", "vol_regime"}
    for v in bundle.values():
        assert isinstance(v, Verdict)


def test_detect_all_passes_dp_net_premium_to_flow():
    bundle = detect_all(
        gex_recs=[],
        flow_recs=[
            {"side": "call", "premium_usd": 1_500_000, "ts": "x"},
            {"side": "put",  "premium_usd": 200_000,   "ts": "x"},
        ],
        spot=100.0,
        term_structure=[],
        dp_net_premium=5_000_000,
    )
    assert bundle["flow"].note["dp_alignment"] == "aligned"


def test_detect_all_on_full_spy_fixture(gex_strike_spy, flow_alerts_spy, max_pain_spy, volatility_spy):
    """End-to-end on real SPY data: all four detectors return valid Verdicts."""
    bundle = detect_all(
        gex_recs=gex_records(gex_strike_spy),
        flow_recs=flow_records(flow_alerts_spy),
        spot=float(max_pain_spy["data"][0]["close"]),
        term_structure=term_structure(volatility_spy),
    )
    for kind, v in bundle.items():
        assert v.kind == kind
        assert 0.0 <= v.intensity <= 1.0
