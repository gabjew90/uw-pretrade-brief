"""Weekly Options Pre-Trade Brief — Streamlit entrypoint.

Single-page layout: pinned ticker card on top (empty until a row is
clicked), scan table below. Click a row to pin; URL persists via
?ticker=X for share/reload."""
from __future__ import annotations
import datetime as _dt

import streamlit as st

from src import watchlist, fetch, patterns as _patterns
from src.fetch import SYNTH_SESSION_CALL_LIMIT
from src.synth import fallback_summary
from src.views import scan_table, ticker_card


# ---------- Page config ----------
st.set_page_config(
    page_title="Weekly Options Pre-Trade Brief",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Disclaimer (always visible, can't be dismissed) ----------
st.error(
    "⚠️ **NOT INVESTMENT ADVICE.** The AI-generated trade ideas on this dashboard are "
    "derived from structural options data (dealer positioning, flow, volatility) and "
    "represent one reading of the patterns. They are NOT recommendations to buy, sell, "
    "or hold any security. Options trading involves substantial risk of loss including "
    "loss of principal. Past patterns do not predict future outcomes. You are solely "
    "responsible for your own trading decisions. Consult a licensed financial advisor "
    "before making any trade."
)

# ---------- Header ----------
st.title("Weekly Options Pre-Trade Brief")
st.caption(
    "AI-assisted reading of Unusual Whales options-positioning data. "
    "Not financial advice. Trade at your own risk."
)

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Watchlist")
    user_input = st.text_input(
        "Override (comma-separated tickers)",
        value="",
        help="Leave blank to use the default list + UW's 'hot today' leaders.",
    )
    if st.button("Refresh data"):
        st.cache_data.clear()
        st.session_state.last_refresh_ts = _dt.datetime.now().strftime("%H:%M")
        st.session_state.synth_call_count = 0
        st.rerun()

    # Staleness
    last_refresh = st.session_state.get("last_refresh_ts")
    if not last_refresh:
        last_refresh = _dt.datetime.now().strftime("%H:%M")
        st.session_state.last_refresh_ts = last_refresh
    st.caption(f"UW data: refreshed {last_refresh}")

    # Session synth call counter (cost-guard visibility, spec §5)
    calls = st.session_state.get("synth_call_count", 0)
    st.caption(f"Gemini calls this session: {calls} / {SYNTH_SESSION_CALL_LIMIT}")

    # Threshold transparency (product-review item #1)
    with st.expander("v0.1 calibration values"):
        st.caption(
            "Thresholds that determine when each pattern badge 'fires'. "
            "These are heuristics, not a validated model — visible here "
            "so badges can be interpreted honestly."
        )
        st.code(f"""\
Pinning concentration > {_patterns.PIN_THRESHOLD}
Gamma squeeze ratio   > {_patterns.SQUEEZE_RATIO}x other side
Flow min total $      > ${_patterns.FLOW_MIN_TOTAL:,}
Flow min skew         > {_patterns.FLOW_MIN_SKEW}
Vol inversion         > {_patterns.VOL_INVERSION_THRESHOLD_PTS} vol pts (front - 30d)""",
                language="text")

    with st.expander("How this works"):
        st.markdown("""
Each row shows whether a ticker is exhibiting one of four structural setups
for a weekly options trade:

- 🟦 **Pinning** — heavy dealer gamma at a strike pulls price toward it.
- 🟧 **Gamma squeeze** — dealers short gamma at strikes that, if crossed, force them to chase price.
- 🟩/🟥 **Flow** — net options premium is directional and large. Dark pool prints corroborate or contradict.
- 🟪 **Vol regime** — front-week IV elevated vs 30-day → event-driven richness.

Data from Unusual Whales (Basic tier, 30-day lookback, REST polling).
AI headline summarizes what the data shows — **not** a trade signal.

Tap any row to see supporting charts in the pinned card above.
        """)

# ---------- Resolve watchlist ----------
fixed = watchlist.parse_user_list(user_input) or watchlist.DEFAULT_FIXED
hot = fetch.fetch_hot_tickers(15)
all_candidates = watchlist.merge_watchlist(fixed, hot=hot, cap=watchlist.DEFAULT_CAP)

visible_count = st.session_state.get("visible_count", watchlist.DEFAULT_FIRST_BATCH)
tickers = all_candidates[:visible_count]

# Source map for the 📌/🔥 icons
fixed_set = {t.upper() for t in fixed}
hot_set = {t.upper() for t in hot}
def _source_icon(t: str) -> str:
    t = t.upper()
    if t in fixed_set:
        return "📌"
    if t in hot_set:
        return "🔥"
    return ""

# ---------- URL persistence: read ?ticker= on cold load ----------
if "pinned_ticker" not in st.session_state:
    st.session_state.pinned_ticker = st.query_params.get("ticker")

# ---------- Fetch data for visible tickers ----------
with st.spinner(f"Loading {len(tickers)} tickers…"):
    td_map = fetch.fetch_batch(tickers)

# ---------- Halt-on-auth-failure (spec §6) ----------
# If EVERY ticker failed with a missing-key error, the deployment is
# misconfigured. Show one big banner and stop — don't render an empty,
# confusing dashboard.
def _is_auth_error(err: str | None) -> bool:
    if not err:
        return False
    low = err.lower()
    return ("api_key not set" in low) or (" 401 " in f" {err} ") or (" 403 " in f" {err} ")

auth_failures = [td for td in td_map.values() if _is_auth_error(td.error)]
if td_map and len(auth_failures) == len(td_map):
    st.error(
        "🔑 **API key not configured for this deployment.** "
        "Every ticker fetch failed because the Unusual Whales API key is missing "
        "from Streamlit Cloud secrets. "
        "If you're the app owner: go to share.streamlit.io → this app's Settings → "
        "Secrets, paste your `UW_API_KEY` (and `GEMINI_API_KEY`), Save. "
        "The app will auto-redeploy in ~30 seconds."
    )
    st.caption("All other features (scan table, click-to-pin, charts) work as soon as the keys are in place.")
    st.stop()

# ---------- Build prelim rows (badges + spot for synth payload) ----------
prelim_rows = []
for t in tickers:
    td = td_map[t]
    pats = fetch.patterns_for(td)
    prelim_rows.append({
        "ticker": t,
        "source_icon": _source_icon(t),
        "patterns": pats,
        "spot": td.spot,
        "iv_rank": td.iv_rank,
        "max_pain": td.max_pain,
        "next_earnings": td.next_earnings,
    })

# ---------- Single-paint concurrent Gemini synthesis ----------
with st.spinner("Generating analyses…"):
    synth_map = fetch.synthesize_batch(prelim_rows)
rows = [{**r, "synthesis": synth_map.get(r["ticker"], "")} for r in prelim_rows]

# ---------- Pinned card (top) ----------
pinned = st.session_state.get("pinned_ticker")
if pinned:
    if pinned not in td_map:
        # Pinned ticker not in visible batch — fetch independently
        td_map[pinned] = fetch.fetch_one(pinned)
    pinned_td = td_map[pinned]
    pinned_patterns = fetch.patterns_for(pinned_td)
    pinned_kn = {
        "spot": pinned_td.spot,
        "iv_rank": pinned_td.iv_rank,
        "max_pain": pinned_td.max_pain,
        "next_earnings": pinned_td.next_earnings,
    }
    pinned_kn = {k: v for k, v in pinned_kn.items() if v is not None}
    # Build a compact contracts summary string for the pinned-synth prompt.
    # Lets the AI reference real strikes/bids/asks that match what the user
    # will see in the picker table below.
    contracts_for_prompt = None
    try:
        from src import uw_client as _uwc
        contracts = fetch.fetch_one_contracts(pinned)
        focus = (pinned_patterns.get("pinning", {}).get("note", {}).get("strike")
                 or pinned_td.max_pain or pinned_td.spot)
        if focus and contracts:
            near = _uwc.contracts_near_focus(contracts, float(focus), n_strikes=3)
            if near:
                lines = []
                for c in near:
                    lines.append(
                        f"{c['strike']:.2f} {c['type']} expiry {c['expiry']}: "
                        f"bid {c['bid']:.2f} ask {c['ask']:.2f} IV {c['iv']*100:.1f}%"
                    )
                contracts_for_prompt = "\n".join(lines)
    except Exception:
        contracts_for_prompt = None

    try:
        pinned_synth = fetch.synthesize_pinned(
            pinned,
            fetch._patterns_hash(pinned_patterns, pinned_kn),
            pinned_patterns,
            pinned_kn,
            contracts_summary=contracts_for_prompt,
        )
    except Exception as _pinned_err:
        # Defensive: if the synth call itself blows up (cache hash issue, Gemini
        # SDK regression, etc.), fall back to the deterministic template rather
        # than crashing the whole page. Log to stderr for Cloud-side debugging.
        import sys as _sys
        from src.synth import fallback_pinned_summary as _fb
        print(f"[synth-pinned] {pinned} outer-fallback ({type(_pinned_err).__name__}: {_pinned_err})",
              file=_sys.stderr)
        pinned_synth = _fb(pinned, pinned_patterns, pinned_kn)
    ticker_card.render(pinned, pinned_td, pinned_synth, pinned_patterns)
else:
    ticker_card.render_empty()

st.divider()

# ---------- Scan table (bottom) ----------
st.subheader(f"Scan — {len(tickers)} tickers")
st.caption("📌 = your fixed list  ·  🔥 = UW hot today")

clicked = scan_table.render(rows, pinned=pinned)
if clicked and clicked != st.session_state.get("pinned_ticker"):
    st.session_state.pinned_ticker = clicked
    st.query_params["ticker"] = clicked
    st.rerun()

# Load 10 more
remaining = len(all_candidates) - len(tickers)
if remaining > 0:
    if st.button(f"Load 10 more ({remaining} available)"):
        st.session_state.visible_count = min(visible_count + 10, len(all_candidates))
        st.rerun()

# Failure-rate banner (>50% of tickers failed → likely auth/connectivity issue)
failed = [td for td in td_map.values() if td.error]
if failed and len(failed) > len(tickers) / 2:
    st.warning(
        f"UW data unavailable for {len(failed)}/{len(tickers)} tickers. "
        "Check API status or your UW_API_KEY."
    )
