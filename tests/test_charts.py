"""Tests for src.charts. Smoke-level: each builder returns a valid
plotly Figure with the expected number of traces for both populated
and empty input."""
from __future__ import annotations
import plotly.graph_objects as go
from src.charts import (
    gamma_profile_figure,
    oi_per_strike_figure,
    vol_term_structure_figure,
)
from src.uw_client import gex_records, oi_records, term_structure


# ---------- Gamma profile ----------

def test_gamma_profile_synthetic():
    records = [
        {"strike": 100.0, "gamma": -5e6},
        {"strike": 105.0, "gamma":  8e6},
        {"strike": 110.0, "gamma":  3e6},
    ]
    fig = gamma_profile_figure(records, spot=105.0, ticker="TEST")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


def test_gamma_profile_empty():
    fig = gamma_profile_figure([], spot=100.0, ticker="TEST")
    assert isinstance(fig, go.Figure)


def test_gamma_profile_no_spot_still_renders():
    """Missing spot shouldn't crash the chart."""
    records = [{"strike": 100.0, "gamma": 1e6}]
    fig = gamma_profile_figure(records, spot=0, ticker="TEST")
    assert isinstance(fig, go.Figure)


def test_gamma_profile_on_spy_fixture(gex_strike_spy, max_pain_spy):
    records = gex_records(gex_strike_spy)
    spot = float(max_pain_spy["data"][0]["close"])
    fig = gamma_profile_figure(records, spot=spot, ticker="SPY")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


# ---------- OI per strike ----------

def test_oi_per_strike_synthetic():
    records = [
        {"strike":  95.0, "call_oi":  600, "put_oi": 7500},
        {"strike": 100.0, "call_oi": 5000, "put_oi": 1200},
        {"strike": 105.0, "call_oi": 8000, "put_oi":  800},
    ]
    fig = oi_per_strike_figure(records, spot=100.0, max_pain=100.0, ticker="TEST")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2  # call trace + put trace


def test_oi_per_strike_empty():
    fig = oi_per_strike_figure([], spot=100.0, max_pain=None, ticker="TEST")
    assert isinstance(fig, go.Figure)


def test_oi_per_strike_no_max_pain():
    """Missing max-pain shouldn't crash the chart."""
    records = [{"strike": 100.0, "call_oi": 5000, "put_oi": 1200}]
    fig = oi_per_strike_figure(records, spot=100.0, max_pain=None, ticker="TEST")
    assert isinstance(fig, go.Figure)


def test_oi_per_strike_on_spy_fixture(oi_strike_spy, max_pain_spy):
    records = oi_records(oi_strike_spy)
    spot = float(max_pain_spy["data"][0]["close"])
    mp = float(max_pain_spy["data"][0]["max_pain"])
    fig = oi_per_strike_figure(records, spot=spot, max_pain=mp, ticker="SPY")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2


# ---------- Vol term structure ----------

def test_vol_term_structure_synthetic():
    series = [
        {"dte": 7, "iv": 0.22},
        {"dte": 14, "iv": 0.21},
        {"dte": 30, "iv": 0.20},
    ]
    fig = vol_term_structure_figure(series, ticker="TEST")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


def test_vol_term_structure_empty():
    fig = vol_term_structure_figure([], ticker="TEST")
    assert isinstance(fig, go.Figure)


def test_vol_term_structure_on_spy_fixture(volatility_spy):
    series = term_structure(volatility_spy)
    fig = vol_term_structure_figure(series, ticker="SPY")
    assert isinstance(fig, go.Figure)
