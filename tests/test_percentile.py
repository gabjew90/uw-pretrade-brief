"""Tests for the 7-day percentile helpers in src.fetch.

The historical-fetch functions hit UW (live) so they're not tested here —
they're covered by the opt-in `pytest -m live` schema-drift suite. These
tests cover the pure helpers (trading-date list + percentile math)."""
from __future__ import annotations
import datetime as _dt
import pytest

from src.fetch import _trailing_trading_dates, _percentile_of


# ---------- _trailing_trading_dates ----------

def test_trailing_trading_dates_returns_n_weekdays():
    dates = _trailing_trading_dates(7)
    assert len(dates) == 7
    # All dates parseable + weekdays only (Mon-Fri)
    for s in dates:
        d = _dt.date.fromisoformat(s)
        assert d.weekday() < 5, f"{s} is a weekend"


def test_trailing_trading_dates_are_in_the_past():
    dates = _trailing_trading_dates(7)
    today = _dt.date.today()
    for s in dates:
        d = _dt.date.fromisoformat(s)
        assert d < today, f"{s} is not strictly before today"


def test_trailing_trading_dates_descending_order():
    dates = _trailing_trading_dates(7)
    parsed = [_dt.date.fromisoformat(s) for s in dates]
    assert parsed == sorted(parsed, reverse=True)


def test_trailing_trading_dates_n_smaller():
    assert len(_trailing_trading_dates(3)) == 3


# ---------- _percentile_of ----------

def test_percentile_top_of_sample():
    assert _percentile_of(10.0, [1, 2, 3, 4, 5, 6, 10]) == 100.0


def test_percentile_bottom_of_sample():
    # Value at or below the minimum should be in the low end
    pct = _percentile_of(0.0, [1, 2, 3, 4, 5])
    assert pct is not None and pct < 25.0


def test_percentile_median():
    pct = _percentile_of(3.0, [1, 2, 3, 4, 5])
    # 3.0 is greater than or equal to 3 of the 5 values (1, 2, 3) → 60%
    assert pct == 60.0


def test_percentile_handles_none_value():
    assert _percentile_of(None, [1, 2, 3]) is None


def test_percentile_handles_empty_sample():
    assert _percentile_of(5.0, []) is None


def test_percentile_filters_none_from_sample():
    """None entries in the sample are removed before computing percentile."""
    pct = _percentile_of(5.0, [1, None, 5, None, 10])
    # Effective sample: [1, 5, 10]. 5 is ≤ 2 of them → 66.7%
    assert pct == 66.7


def test_percentile_handles_negative_values():
    """Net premium can be negative (-$8M etc); percentile must handle signs."""
    sample = [-10, -5, -2, 0, 3, 5, 10]
    # Today's value -3: it's ≤ -2, 0, 3, 5, 10 → wait, percentile = % ≤ today
    # Wait — my definition is % of items <= today. So for today=-3:
    #   sample items ≤ -3: just -10, -5 → 2 items
    # 2/7 = 28.6%
    pct = _percentile_of(-3.0, sample)
    assert pct == round(100 * 2 / 7, 1)


def test_percentile_handles_ties():
    """Items equal to today's value count toward the 'less than or equal' tally."""
    pct = _percentile_of(5.0, [5, 5, 5, 5])
    # All 4 items are ≤ 5 → 100%
    assert pct == 100.0
