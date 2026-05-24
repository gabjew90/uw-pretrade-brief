"""Thin REST wrapper for Unusual Whales (Basic tier).

Endpoint paths verified against the OpenAPI spec at
https://api.unusualwhales.com/api/openapi (2026-05-24). All methods raise
UWError on non-2xx so per-ticker callers can isolate failures.

Tier (Basic): 120 req/min, 40k req/day, 30-day lookback, personal-use-only.
"""
from __future__ import annotations
import os
from typing import Any
import requests

BASE = "https://api.unusualwhales.com"
TIMEOUT_S = 10


class UWError(RuntimeError):
    """Raised when a UW API call fails (network, auth, or non-2xx)."""


def _get_key() -> str:
    key = os.environ.get("UW_API_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("UW_API_KEY")
        except Exception:
            key = None
    if not key:
        # Last-resort: read .streamlit/secrets.toml directly (for CLI/script callers
        # that aren't inside a Streamlit runtime)
        try:
            import tomllib
            from pathlib import Path
            p = Path(".streamlit/secrets.toml")
            if p.exists():
                key = tomllib.loads(p.read_text(encoding="utf-8")).get("UW_API_KEY")
        except Exception:
            key = None
    if not key:
        raise UWError("UW_API_KEY not set (env var or Streamlit secrets)")
    return key


def _get(path: str, params: dict | None = None) -> Any:
    url = f"{BASE}{path}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {_get_key()}",
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise UWError(f"network error calling {path}: {e}") from e
    if r.status_code == 429:
        raise UWError(f"429 rate limited on {path}")
    if not r.ok:
        raise UWError(f"{r.status_code} on {path}: {r.text[:200]}")
    return r.json()


# ---------- Endpoint methods ----------

def fetch_spot_exposures_strike(ticker: str) -> dict:
    """Per-strike Spot GEX — dealer-positioning gamma per strike. Drives
    pinning + gamma squeeze detection. Returns directional fields
    (call_gamma_oi, put_gamma_oi, *_ask, *_bid)."""
    return _get(f"/api/stock/{ticker}/spot-exposures/strike")


def fetch_oi_strike(ticker: str) -> dict:
    """Per-strike open interest, calls + puts split."""
    return _get(f"/api/stock/{ticker}/oi-per-strike")


def fetch_flow_alerts(ticker: str | None = None, limit: int = 50) -> dict:
    """Recent flow alerts. With `ticker`: filtered to that ticker. Without:
    cross-ticker hot today. Per-ticker /api/stock/{t}/flow-alerts is
    DEPRECATED; this single endpoint serves both uses."""
    params: dict = {"limit": limit}
    if ticker:
        params["ticker_symbol"] = ticker
    return _get("/api/option-trades/flow-alerts", params=params)


def fetch_volatility(ticker: str) -> dict:
    """IV term structure for the ticker (avg ATM call+put IV per expiry)."""
    return _get(f"/api/stock/{ticker}/volatility/term-structure")


def fetch_max_pain(ticker: str) -> dict:
    """Max pain across expirations for the ticker."""
    return _get(f"/api/stock/{ticker}/max-pain")


# ---------- Shape normalizers ----------

def _unwrap(payload):
    """UW wraps most endpoint responses in {'data': [...]}. Normalize."""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def gex_records(payload) -> list[dict]:
    """Return list of {strike: float, gamma: float, raw: dict} sorted by strike.

    UW's /spot-exposures/strike returns per-strike directional gamma. Per UW
    docs: net dealer gamma per strike = call_gamma_oi - put_gamma_oi (OI-based,
    standing positions). Falls back to summed directional fields, then to
    single-field aggregates.
    """
    rows = _unwrap(payload)
    out = []
    for r in rows:
        strike = r.get("strike") or r.get("strike_price")
        if strike is None:
            continue
        strike = float(strike)

        call_oi = r.get("call_gamma_oi")
        put_oi = r.get("put_gamma_oi")
        gamma = None
        if call_oi is not None or put_oi is not None:
            gamma = float(call_oi or 0) - float(put_oi or 0)
        else:
            ca = r.get("call_gamma_ask"); cb = r.get("call_gamma_bid")
            pa = r.get("put_gamma_ask");  pb = r.get("put_gamma_bid")
            if any(v is not None for v in (ca, cb, pa, pb)):
                gamma = sum(float(v or 0) for v in (ca, cb, pa, pb))
            else:
                for k in ("gamma_dollars", "net_gamma", "gex", "gamma"):
                    if r.get(k) is not None:
                        gamma = float(r[k])
                        break
                if gamma is None:
                    cg = r.get("call_gamma")
                    pg = r.get("put_gamma")
                    if cg is not None or pg is not None:
                        gamma = float(cg or 0) - float(pg or 0)
        if gamma is None:
            continue
        out.append({"strike": strike, "gamma": gamma, "raw": r})
    return sorted(out, key=lambda x: x["strike"])


def oi_records(payload) -> list[dict]:
    """Return list of {strike, call_oi, put_oi} sorted by strike."""
    rows = _unwrap(payload)
    out = []
    for r in rows:
        strike = r.get("strike") or r.get("strike_price")
        if strike is None:
            continue
        call_oi = int(r.get("call_oi") or r.get("calls_oi") or r.get("call_open_interest") or 0)
        put_oi = int(r.get("put_oi") or r.get("puts_oi") or r.get("put_open_interest") or 0)
        out.append({"strike": float(strike), "call_oi": call_oi, "put_oi": put_oi})
    return sorted(out, key=lambda x: x["strike"])


def flow_records(payload) -> list[dict]:
    """Return list of {side, premium_usd, ts, raw} from flow-alerts payload.

    UW flow_alerts row shape (verified): type='call'|'put', total_premium=str,
    created_at=ISO timestamp. Other useful fields kept in 'raw' for downstream.
    """
    rows = _unwrap(payload)
    out = []
    for r in rows:
        side = (r.get("type") or r.get("option_type") or "").lower()
        side = "call" if side.startswith("c") else "put" if side.startswith("p") else side
        prem = r.get("total_premium") or r.get("premium") or r.get("premium_usd")
        ts = r.get("created_at") or r.get("executed_at") or r.get("timestamp") or r.get("ts")
        out.append({"side": side, "premium_usd": float(prem or 0), "ts": ts, "raw": r})
    return out


def hot_tickers(payload, limit: int = 15) -> list[str]:
    """Return list of unique tickers from a flow-alerts payload."""
    rows = _unwrap(payload)
    seen: list[str] = []
    for r in rows:
        t = r.get("ticker") or r.get("ticker_symbol") or r.get("symbol") or r.get("underlying")
        if t and t not in seen:
            seen.append(t)
        if len(seen) >= limit:
            break
    return seen


def term_structure(payload) -> list[dict]:
    """Return list of {dte: int, iv: float} sorted by dte.

    UW volatility/term-structure row shape: {dte, volatility, expiry, ...}.
    The 'volatility' field name is what UW uses; we normalize it to 'iv'.
    """
    p = _unwrap(payload)
    if isinstance(p, list):
        rows = p
    elif isinstance(p, dict):
        rows = p.get("term_structure") or p.get("expiries") or p.get("series") or []
    else:
        rows = []
    out = []
    for r in rows:
        dte = r.get("dte") or r.get("days_to_expiry")
        iv = r.get("volatility") or r.get("iv") or r.get("atm_iv") or r.get("implied_volatility")
        if dte is None or iv is None:
            continue
        out.append({"dte": int(dte), "iv": float(iv)})
    return sorted(out, key=lambda x: x["dte"])


# ---------- Scalar extractors ----------

def extract_spot(*payloads) -> float | None:
    """Find current/last spot price from any of the given payloads.

    Order of preference per payload: dict roots (spot/underlying_price/...),
    then list[0] row. Pass any combination of flow_alerts, max_pain, etc. —
    we'll find the first usable value.
    """
    for payload in payloads:
        if payload is None:
            continue
        p = _unwrap(payload)
        if isinstance(p, dict):
            for k in ("spot", "underlying_price", "last_price", "price", "close"):
                if p.get(k) is not None:
                    return float(p[k])
        if isinstance(p, list) and p:
            row = p[0] if isinstance(p[0], dict) else None
            if row:
                for k in ("underlying_price", "close", "spot", "last_price"):
                    if row.get(k) is not None:
                        return float(row[k])
    return None


def extract_iv_rank(volatility_payload) -> float | None:
    """IV rank isn't in UW's /volatility/term-structure response (it's in
    /volatility/stats which we don't fetch in v0.1). Returns None — synthesis
    treats IV rank as an optional key_number."""
    p = _unwrap(volatility_payload)
    if isinstance(p, dict):
        for k in ("iv_rank", "ivr", "iv_percentile"):
            if p.get(k) is not None:
                v = float(p[k])
                return v * 100 if v <= 1.0 else v
    return None


def max_pain_value(payload) -> float | None:
    """Pull the FRONT-WEEK max-pain strike. UW returns a list of per-expiry
    rows sorted by expiry; index 0 is nearest expiry — the one that matters
    for weekly options."""
    p = _unwrap(payload)
    if isinstance(p, list) and p:
        first = p[0] if isinstance(p[0], dict) else None
        if first:
            mp = first.get("max_pain") or first.get("strike")
            if mp is not None:
                return float(mp)
    if isinstance(p, dict):
        for k in ("max_pain", "max_pain_strike", "strike"):
            if p.get(k) is not None:
                return float(p[k])
    return None
