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


# ---------- Rolling percentile context for the pinned ticker ----------
# Historical snapshots are immutable for past dates — cache them aggressively
# (24h TTL). Current-day refresh keeps the existing 15-min UW_TTL_S.
#
# UW Basic tier's history depth on these endpoints is account-specific (the
# 403 error: "earliest date currently available to you is YYYY-MM-DD (N trading
# days)"). Currently observed: ~7 trading days. We request a 30-day window so
# the resulting sample auto-expands if the subscription is upgraded or as the
# account ages; the extra 403s are caught + cached as empty payloads, so each
# only costs one cheap rejected request.

HISTORICAL_TTL_S = 86400   # 24h — past-date snapshots don't change
HISTORICAL_WINDOW_DAYS = 30  # max trading days requested; actual sample depth
                             # equals what UW returns (currently ~7 on Basic)
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


# ---------- Raw historical payload fetchers (cached 24h per date) ----------
# Each helper hits ONE UW endpoint and returns the raw payload. Multiple metric
# extractors share these via Streamlit's cache so we don't re-hit UW for the same
# (ticker, endpoint, date) tuple. Net result: 4 endpoints × 30 dates = 120 calls
# per pinned ticker cold cache, regardless of how many metrics we extract.

@st.cache_data(ttl=HISTORICAL_TTL_S, show_spinner=False)
def _hist_spot_exposures(ticker: str, date: str) -> dict:
    try:
        return uw_client.fetch_spot_exposures_strike(ticker, date=date)
    except Exception:
        return {}


@st.cache_data(ttl=HISTORICAL_TTL_S, show_spinner=False)
def _hist_max_pain(ticker: str, date: str) -> dict:
    try:
        return uw_client.fetch_max_pain(ticker, date=date)
    except Exception:
        return {}


@st.cache_data(ttl=HISTORICAL_TTL_S, show_spinner=False)
def _hist_volatility(ticker: str, date: str) -> dict:
    try:
        return uw_client.fetch_volatility(ticker, date=date)
    except Exception:
        return {}


@st.cache_data(ttl=HISTORICAL_TTL_S, show_spinner=False)
def _hist_net_prem_ticks(ticker: str, date: str) -> dict:
    try:
        return uw_client.fetch_net_prem_ticks(ticker, date=date)
    except Exception:
        return {}


def _spot_from_max_pain_close(mp_payload: dict) -> float | None:
    """Historical max-pain payloads include the day's close in the first row.
    We use it as a spot proxy for past dates (live spot isn't available)."""
    try:
        data = mp_payload.get("data") if isinstance(mp_payload, dict) else mp_payload
        if isinstance(data, list) and data and isinstance(data[0], dict):
            close = data[0].get("close")
            if close is not None:
                return float(close)
    except Exception:
        pass
    return None


# ---------- Metric extractors (pure: take payloads, return scalar) ----------

def _extract_concentration(gex_payload: dict, spot: float | None) -> float | None:
    """Pinning concentration: top |gamma| near spot / sum |gamma| in wider band."""
    recs = uw_client.gex_records(gex_payload)
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


def _extract_squeeze_sums(gex_payload: dict, spot: float | None) -> tuple[float | None, float | None]:
    """Net dealer gamma summed above spot, and summed below spot. Negative sums
    are the 'squeeze fuel' side. Returns (above_sum, below_sum)."""
    recs = uw_client.gex_records(gex_payload)
    if not recs or not spot or spot <= 0:
        return (None, None)
    above = sum(r["gamma"] for r in recs if r["strike"] > spot)
    below = sum(r["gamma"] for r in recs if r["strike"] < spot)
    return (above, below)


def _extract_front_iv(vol_payload: dict) -> float | None:
    term = uw_client.term_structure(vol_payload)
    for e in term:
        if e["dte"] <= 7:
            return float(e["iv"])
    return None


def _extract_term_spread_pts(vol_payload: dict) -> float | None:
    term = uw_client.term_structure(vol_payload)
    if not term:
        return None
    front = next((e["iv"] for e in term if e["dte"] <= 7), None)
    monthly_entry = min(term, key=lambda e: abs(e["dte"] - 30))
    if abs(monthly_entry["dte"] - 30) > 10 or front is None:
        return None
    return (front - monthly_entry["iv"]) * 100


def _extract_net_premium_and_skew(npt_payload: dict) -> tuple[float | None, float | None]:
    """Returns (net_premium, skew) for one day from net-prem-ticks payload.
    skew = |net| / total — 0 means 50/50 calls vs puts, 1 means 100% one side."""
    data = npt_payload.get("data") if isinstance(npt_payload, dict) else npt_payload
    if not isinstance(data, list) or not data:
        return (None, None)
    total_calls = 0.0
    total_puts = 0.0
    for tick in data:
        try:
            total_calls += float(tick.get("net_call_premium") or 0)
            total_puts += float(tick.get("net_put_premium") or 0)
        except (TypeError, ValueError):
            continue
    net = total_calls - total_puts
    gross = abs(total_calls) + abs(total_puts)
    if gross == 0:
        return (net, None)
    skew = abs(net) / gross
    return (net, skew)


def _extract_max_pain_distance(mp_payload: dict, spot: float | None) -> tuple[float | None, float | None]:
    """Returns (max_pain_strike, distance_pct). distance_pct = (spot - mp) / spot * 100.
    Positive = spot above max pain; negative = below."""
    mp = uw_client.max_pain_value(mp_payload)
    if mp is None or spot is None or spot <= 0:
        return (mp, None)
    return (mp, (spot - mp) / spot * 100)


# ---------- Single-date bulk extractor ----------

def _all_metrics_for_date(ticker: str, date: str) -> dict[str, float | None]:
    """Fetch all 4 endpoints for this date (cached), extract all 8 metrics in
    one pass. Used by fetch_pinned_history."""
    spot_exp = _hist_spot_exposures(ticker, date)
    mp = _hist_max_pain(ticker, date)
    vol = _hist_volatility(ticker, date)
    npt = _hist_net_prem_ticks(ticker, date)

    spot = _spot_from_max_pain_close(mp)
    above, below = _extract_squeeze_sums(spot_exp, spot)
    net_prem, skew = _extract_net_premium_and_skew(npt)
    _mp_strike, mp_distance_pct = _extract_max_pain_distance(mp, spot)

    return {
        "concentration": _extract_concentration(spot_exp, spot),
        "squeeze_above": above,
        "squeeze_below": below,
        "front_iv": _extract_front_iv(vol),
        "term_spread_pts": _extract_term_spread_pts(vol),
        "net_premium": net_prem,
        "skew": skew,
        "max_pain_distance_pct": mp_distance_pct,
    }


def fetch_pinned_history(ticker: str) -> dict[str, list[float]]:
    """Concurrently fetch up to HISTORICAL_WINDOW_DAYS trading days of all
    extractable metrics for one ticker.

    Returns dict keyed by metric name; values are lists of historical scalars
    (None entries removed). 4 UW endpoints × N dates fetched concurrently;
    Streamlit caches each (endpoint, date) so retries / shared tickers reuse.
    """
    dates = _trailing_trading_dates(HISTORICAL_WINDOW_DAYS)
    metric_keys = ("concentration", "squeeze_above", "squeeze_below",
                   "front_iv", "term_spread_pts", "net_premium",
                   "skew", "max_pain_distance_pct")
    out: dict[str, list[float]] = {k: [] for k in metric_keys}

    def _job(date: str) -> dict[str, float | None]:
        return _all_metrics_for_date(ticker, date)

    with ThreadPoolExecutor(max_workers=HISTORICAL_MAX_CONCURRENCY) as pool:
        for result in pool.map(_job, dates):
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
