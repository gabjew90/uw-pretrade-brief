"""Concurrent per-ticker UW data fetch + pattern derivation + cached
Gemini synthesis batching. Streamlit caches sit at this layer."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional
import hashlib
import json

import streamlit as st

from src import uw_client, patterns, synth as _synth

UW_TTL_S = 900        # 15 min
SYNTH_TTL_S = 1800    # 30 min
SYNTH_SESSION_CALL_LIMIT = 100  # per spec §5 cost guard


@dataclass
class TickerData:
    ticker: str
    spot: float | None
    iv_rank: float | None
    gex_recs: list[dict]
    flow_recs: list[dict]
    oi_recs: list[dict]
    term: list[dict]
    dp_net_premium: float | None = None
    max_pain: float | None = None
    next_earnings: str | None = None
    error: Optional[str] = None


@st.cache_data(ttl=UW_TTL_S, show_spinner=False)
def fetch_one(ticker: str) -> TickerData:
    """Fetch all relevant UW endpoints for one ticker. Errors captured, not raised."""
    try:
        vol = uw_client.fetch_volatility(ticker)
        gex = uw_client.fetch_spot_exposures_strike(ticker)
        flow = uw_client.fetch_flow_alerts(ticker, limit=50)
        oi = uw_client.fetch_oi_strike(ticker)
        mp = uw_client.fetch_max_pain(ticker)
        dp = uw_client.fetch_darkpool(ticker, limit=50)
        try:
            iv_pay = uw_client.fetch_interpolated_iv(ticker)
        except Exception:
            iv_pay = None
        try:
            earn_pay = uw_client.fetch_earnings(ticker)
            next_e = uw_client.next_earnings(earn_pay)
        except Exception:
            next_e = None
        dp_records = uw_client.darkpool_records(dp)
        return TickerData(
            ticker=ticker,
            spot=uw_client.extract_spot(flow, mp, vol),
            iv_rank=uw_client.extract_iv_rank(vol, iv_pay),
            gex_recs=uw_client.gex_records(gex),
            flow_recs=uw_client.flow_records(flow),
            oi_recs=uw_client.oi_records(oi),
            term=uw_client.term_structure(vol),
            dp_net_premium=uw_client.darkpool_net_premium(dp_records),
            max_pain=uw_client.max_pain_value(mp),
            next_earnings=next_e,
        )
    except Exception as e:
        return TickerData(
            ticker=ticker, spot=None, iv_rank=None,
            gex_recs=[], flow_recs=[], oi_recs=[], term=[],
            dp_net_premium=None, max_pain=None, next_earnings=None,
            error=f"{type(e).__name__}: {e}",
        )


def fetch_batch(tickers: list[str]) -> dict[str, TickerData]:
    """Concurrently fetch a list of tickers. Returns dict keyed by ticker."""
    out: dict[str, TickerData] = {}
    if not tickers:
        return out
    with ThreadPoolExecutor(max_workers=8) as pool:
        for td in pool.map(fetch_one, tickers):
            out[td.ticker] = td
    return out


def patterns_for(td: TickerData) -> dict:
    """Run all four pattern detectors on one ticker's data."""
    if td.error or td.spot is None:
        return {
            k: {"firing": False, "intensity": 0.0, "note": {"reason": "no_data"}}
            for k in ("pinning", "gamma_squeeze", "flow", "vol_regime")
        }
    bundle = patterns.detect_all(
        gex_recs=td.gex_recs,
        flow_recs=td.flow_recs,
        spot=td.spot,
        term_structure=td.term,
        dp_net_premium=td.dp_net_premium,
    )
    return {k: v.to_dict() for k, v in bundle.items()}


@st.cache_data(ttl=UW_TTL_S, show_spinner=False)
def fetch_one_contracts(ticker: str) -> list[dict]:
    """Lazy: only fetched when a ticker is pinned. ~300 contracts per ticker
    is bigger than the other endpoints combined, so we don't include this in
    fetch_one (which runs on every scan-row)."""
    try:
        payload = uw_client.fetch_option_contracts(ticker, limit=300)
        return uw_client.contract_records(payload)
    except Exception:
        return []


@st.cache_data(ttl=UW_TTL_S, show_spinner=False)
def fetch_hot_tickers(limit: int = 15) -> list[str]:
    """Cross-ticker UW flow-alerts → list of unique hot tickers."""
    try:
        payload = uw_client.fetch_flow_alerts(ticker=None, limit=limit)
        return uw_client.hot_tickers(payload, limit)
    except Exception:
        return []


# ---------- Synthesis batching + cost guard ----------

def _patterns_hash(patterns: dict, key_numbers: dict) -> str:
    """Stable hash → cache key for synthesis output."""
    payload = json.dumps({"p": patterns, "k": key_numbers}, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()


def _bumped_call_count() -> int:
    n = st.session_state.get("synth_call_count", 0) + 1
    st.session_state.synth_call_count = n
    return n


@st.cache_data(ttl=SYNTH_TTL_S, show_spinner=False)
def synthesize_one(ticker: str, _cache_key: str, patterns: dict, key_numbers: dict) -> str:
    """Cached wrapper around synth.summarize (scan-row, short). Cache hits
    don't increment counter.

    Hard cost guard: if session synth calls exceed SYNTH_SESSION_CALL_LIMIT,
    return the deterministic fallback without hitting Gemini."""
    if _bumped_call_count() > SYNTH_SESSION_CALL_LIMIT:
        return _synth.fallback_summary(ticker, patterns, key_numbers)
    return _synth.summarize(ticker, patterns, key_numbers)


@st.cache_data(ttl=SYNTH_TTL_S, show_spinner=False)
def synthesize_pinned(ticker: str, _cache_key: str, patterns: dict, key_numbers: dict,
                      contracts_summary: str | None = None) -> str:
    """Pinned-card synthesis (long, walkthrough + trade recommendations).
    ~5-7x the token cost of synthesize_one — only called when a ticker is
    actively pinned, not for every scan row."""
    if _bumped_call_count() > SYNTH_SESSION_CALL_LIMIT:
        return _synth.fallback_pinned_summary(ticker, patterns, key_numbers)
    return _synth.summarize_pinned(ticker, patterns, key_numbers, contracts_summary)


def synthesize_batch(rows: list[dict]) -> dict[str, str]:
    """Concurrently summarize many tickers. Returns dict ticker → text."""
    out: dict[str, str] = {}
    if not rows:
        return out

    def _job(row):
        kn = {
            "spot": row.get("spot"),
            "iv_rank": row.get("iv_rank"),
            "max_pain": row.get("max_pain"),
            "next_earnings": row.get("next_earnings"),
        }
        kn = {k: v for k, v in kn.items() if v is not None}
        key = _patterns_hash(row["patterns"], kn)
        return row["ticker"], synthesize_one(row["ticker"], key, row["patterns"], kn)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for ticker, text in pool.map(_job, rows):
            out[ticker] = text
    return out
