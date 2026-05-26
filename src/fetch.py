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


# ---------- 7-day percentile context for the pinned ticker ----------
# Historical snapshots are immutable for past dates — cache them aggressively
# (24h TTL). Current-day refresh keeps the existing 15-min UW_TTL_S.

HISTORICAL_TTL_S = 86400   # 24h — past-date snapshots don't change
HISTORICAL_WINDOW_DAYS = 30  # 30 trading days of history per pinned ticker (UW Basic ceiling)
HISTORICAL_LOOKBACK_CALENDAR = 50  # try last 50 calendar days to find 30 trading
                                   # (accounts for weekends + occasional holidays)
HISTORICAL_MAX_CONCURRENCY = 3     # threadpool workers for historical fetch — gentler
                                   # than the live-batch concurrency (8) so we don't
                                   # trip UW Basic's 120 req/min burst limit when a
                                   # cold-cache pin fires 120 calls (30 days × 4 metrics)


def _trailing_trading_dates(days: int = HISTORICAL_WINDOW_DAYS) -> list[str]:
    """Return the last `days` weekday ISO dates ending YESTERDAY. We rely on
    UW to filter holidays — calls for closed days will return empty payloads
    and percentile will just be computed over the days that returned data."""
    import datetime as _dt
    out: list[str] = []
    d = _dt.date.today() - _dt.timedelta(days=1)
    # Walk backwards, skipping Sat/Sun
    safety = 0
    while len(out) < days and safety < HISTORICAL_LOOKBACK_CALENDAR + 5:
        if d.weekday() < 5:  # Mon-Fri
            out.append(d.isoformat())
        d -= _dt.timedelta(days=1)
        safety += 1
    return out


def _percentile_of(value: float, sample: list[float]) -> float | None:
    """Return value's percentile (0-100) within sample. None if sample empty
    or value is None. Uses the 'percent of items less than or equal' definition,
    which is the standard 'percent-rank'."""
    if value is None:
        return None
    clean = [s for s in sample if s is not None]
    if not clean:
        return None
    le = sum(1 for s in clean if s <= value)
    return round(100 * le / len(clean), 1)


@st.cache_data(ttl=HISTORICAL_TTL_S, show_spinner=False)
def _historical_concentration(ticker: str, date: str) -> float | None:
    """For one ticker on one date: pinning concentration = top |gamma| at
    near-spot strikes / sum |gamma| at wider band. Mirrors patterns.detect_pinning
    but returns the raw concentration scalar so we can build a distribution."""
    try:
        gex_payload = uw_client.fetch_spot_exposures_strike(ticker, date=date)
        recs = uw_client.gex_records(gex_payload)
        # Use max-pain as spot proxy for historical (no live spot for past dates)
        mp_payload = uw_client.fetch_max_pain(ticker, date=date)
        mp = uw_client.max_pain_value(mp_payload)
        # If max_pain row carries close, prefer that
        try:
            mp_data = mp_payload.get("data") if isinstance(mp_payload, dict) else mp_payload
            if isinstance(mp_data, list) and mp_data and isinstance(mp_data[0], dict):
                close = mp_data[0].get("close")
                if close is not None:
                    spot = float(close)
                else:
                    spot = mp
            else:
                spot = mp
        except Exception:
            spot = mp
        if not recs or not spot or spot <= 0:
            return None
        from src.patterns import PIN_BAND, PIN_NEAR
        near = [r for r in recs if abs(r["strike"] - spot) / spot <= PIN_NEAR]
        wide = [r for r in recs if abs(r["strike"] - spot) / spot <= PIN_BAND]
        if not near or not wide:
            return None
        top = max(near, key=lambda r: abs(r["gamma"]))
        denom = sum(abs(r["gamma"]) for r in wide)
        if denom == 0:
            return None
        return abs(top["gamma"]) / denom
    except Exception:
        return None


@st.cache_data(ttl=HISTORICAL_TTL_S, show_spinner=False)
def _historical_front_iv(ticker: str, date: str) -> float | None:
    """Front-week IV (DTE ≤ 7) on a given date."""
    try:
        payload = uw_client.fetch_volatility(ticker, date=date)
        term = uw_client.term_structure(payload)
        for e in term:
            if e["dte"] <= 7:
                return float(e["iv"])
        return None
    except Exception:
        return None


@st.cache_data(ttl=HISTORICAL_TTL_S, show_spinner=False)
def _historical_term_spread_pts(ticker: str, date: str) -> float | None:
    """Front-week IV minus 30-day IV in vol points (e.g., 5.0 = 5 pt inversion)."""
    try:
        payload = uw_client.fetch_volatility(ticker, date=date)
        term = uw_client.term_structure(payload)
        if not term:
            return None
        front = next((e["iv"] for e in term if e["dte"] <= 7), None)
        monthly_entry = min(term, key=lambda e: abs(e["dte"] - 30))
        if abs(monthly_entry["dte"] - 30) > 10:
            return None
        if front is None:
            return None
        return (front - monthly_entry["iv"]) * 100
    except Exception:
        return None


@st.cache_data(ttl=HISTORICAL_TTL_S, show_spinner=False)
def _historical_net_premium(ticker: str, date: str) -> float | None:
    """End-of-day cumulative net options premium on a given date.
    Last tick of net-prem-ticks = day's running total of (call_premium - put_premium)."""
    try:
        payload = uw_client.fetch_net_prem_ticks(ticker, date=date)
        data = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(data, list) or not data:
            return None
        # Each tick has cumulative values within the day's running totals per UW docs.
        # Strategy: sum across the day if values are per-tick deltas; otherwise the
        # last value is the cumulative. UW returns per-minute snapshots that need
        # summing per the doc example. So sum net_call_premium - net_put_premium.
        net = 0.0
        for tick in data:
            try:
                cp = float(tick.get("net_call_premium") or 0)
                pp = float(tick.get("net_put_premium") or 0)
                net += (cp - pp)
            except (TypeError, ValueError):
                continue
        return net
    except Exception:
        return None


def fetch_pinned_history(ticker: str) -> dict[str, list[float]]:
    """Concurrently fetch 7 trading days of historical metrics for one ticker.

    Returns dict with keys: 'concentration', 'front_iv', 'term_spread_pts',
    'net_premium'. Each value is a list (length ≤ 7) of historical scalars,
    None entries removed.
    """
    dates = _trailing_trading_dates(HISTORICAL_WINDOW_DAYS)
    out: dict[str, list[float]] = {
        "concentration": [],
        "front_iv": [],
        "term_spread_pts": [],
        "net_premium": [],
    }

    def _gather_one_date(date: str) -> dict[str, float | None]:
        return {
            "concentration": _historical_concentration(ticker, date),
            "front_iv": _historical_front_iv(ticker, date),
            "term_spread_pts": _historical_term_spread_pts(ticker, date),
            "net_premium": _historical_net_premium(ticker, date),
        }

    with ThreadPoolExecutor(max_workers=HISTORICAL_MAX_CONCURRENCY) as pool:
        for result in pool.map(_gather_one_date, dates):
            for k, v in result.items():
                if v is not None:
                    out[k].append(v)
    return out


def percentile_context(ticker: str, today_values: dict) -> dict[str, float]:
    """For each metric in `today_values` that has 7-day history, return its
    percentile (0-100). Returns dict like {'concentration_pct_7d': 75.0, ...}.
    Missing/insufficient-history metrics are omitted from the output."""
    history = fetch_pinned_history(ticker)
    out: dict[str, float] = {}
    for metric, sample in history.items():
        if len(sample) < 3:  # need at least 3 days for percentile to be meaningful
            continue
        today = today_values.get(metric)
        pct = _percentile_of(today, sample)
        if pct is not None:
            out[f"{metric}_pct_7d"] = pct
            out[f"{metric}_7d_sample_n"] = len(sample)
    return out


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
