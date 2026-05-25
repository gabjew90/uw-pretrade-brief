"""Tests for src.watchlist."""
from __future__ import annotations
from src.watchlist import (
    parse_user_list,
    merge_watchlist,
    DEFAULT_FIXED,
    DEFAULT_CAP,
    DEFAULT_FIRST_BATCH,
)


def test_parse_user_list_csv():
    assert parse_user_list("AAPL, NVDA,tsla, ") == ["AAPL", "NVDA", "TSLA"]


def test_parse_user_list_empty():
    assert parse_user_list("") == []
    assert parse_user_list(None) == []
    assert parse_user_list("   ") == []


def test_parse_user_list_normalizes_case():
    assert parse_user_list("aapl,Nvda,SpY") == ["AAPL", "NVDA", "SPY"]


def test_merge_dedups_and_caps():
    fixed = ["SPY", "QQQ", "NVDA"]
    hot = ["NVDA", "TSLA", "META", "AAPL"]
    assert merge_watchlist(fixed, hot, cap=5) == ["SPY", "QQQ", "NVDA", "TSLA", "META"]


def test_merge_preserves_fixed_order():
    out = merge_watchlist(["A", "B", "C"], ["X", "B", "Y"], cap=10)
    assert out[:3] == ["A", "B", "C"]


def test_merge_handles_empty_hot():
    out = merge_watchlist(["A", "B"], [], cap=10)
    assert out == ["A", "B"]


def test_merge_handles_empty_fixed():
    out = merge_watchlist([], ["X", "Y"], cap=10)
    assert out == ["X", "Y"]


def test_merge_normalizes_case():
    out = merge_watchlist(["spy", "qqq"], ["nvda"], cap=5)
    assert out == ["SPY", "QQQ", "NVDA"]


def test_merge_respects_cap_smaller_than_combined():
    out = merge_watchlist(["A", "B", "C"], ["D", "E", "F", "G"], cap=4)
    assert out == ["A", "B", "C", "D"]
    assert len(out) == 4


def test_default_constants_are_sensible():
    assert DEFAULT_FIRST_BATCH <= DEFAULT_CAP
    assert DEFAULT_FIRST_BATCH > 0
    assert len(DEFAULT_FIXED) > 0
    assert all(t.isupper() for t in DEFAULT_FIXED)
