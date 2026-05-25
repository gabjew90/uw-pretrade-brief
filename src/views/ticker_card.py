"""Top pinned ticker card. AI synthesis at the top, three charts stacked
vertically, contract picker + key strikes at the bottom."""
from __future__ import annotations
import pandas as pd
import streamlit as st

from src import charts, fetch, uw_client


def _friendly_error_message(ticker: str, raw: str) -> str:
    """Categorize the per-ticker UWError into a user-actionable message.
    Hides the exception class name from end users."""
    low = raw.lower()
    if "uw_api_key not set" in low or "gemini_api_key not set" in low:
        return (
            f"🔑 **API key not configured.** This deployment is missing the "
            f"required Unusual Whales API key in Streamlit Cloud secrets. "
            f"The app owner can fix this in share.streamlit.io → app settings → Secrets."
        )
    if " 401 " in f" {raw} " or " 403 " in f" {raw} ":
        return (
            f"🔑 **API key rejected** by Unusual Whales for {ticker}. "
            f"The configured key may be invalid or expired."
        )
    if "429" in raw:
        return f"⏱ Rate-limited fetching {ticker}. Try the Refresh button in a minute."
    if "timeout" in low or "network" in low:
        return f"📡 Network error fetching {ticker}. Try Refresh."
    # Fallback: friendly wording, no class name exposed
    return f"Couldn't load data for {ticker}. Try Refresh."


def render_empty():
    """Empty-state prompt before any row is clicked."""
    st.info("Tap a row below to see detailed analysis.")


def render(ticker: str, td: "fetch.TickerData", synthesis: str, patterns: dict):
    """Render the pinned card for a ticker."""
    head_col, close_col = st.columns([10, 1])
    with head_col:
        st.markdown(f"### {ticker}")
        st.markdown(f"_{synthesis}_")
        # Context strip: spot · IV rank · earnings · max pain
        meta = []
        if td.spot:
            meta.append(f"Spot **{td.spot:.2f}**")
        if td.iv_rank is not None:
            meta.append(f"IVR **{td.iv_rank:.0f}**")
        if td.max_pain:
            meta.append(f"Max Pain **{td.max_pain:.2f}**")
        if td.next_earnings:
            meta.append(f"Earnings **{td.next_earnings[:10]}**")
        if meta:
            st.caption(" · ".join(meta))
    with close_col:
        if st.button("✕", key="unpin", help="Unpin"):
            st.session_state.pinned_ticker = None
            if "ticker" in st.query_params:
                del st.query_params["ticker"]
            st.rerun()

    if td.error:
        msg = _friendly_error_message(ticker, td.error)
        st.error(msg)
        if st.button(f"Retry {ticker}", key=f"retry_{ticker}"):
            fetch.fetch_one.clear()
            st.rerun()
        return

    # Three charts stacked vertically — same layout on desktop and mobile per spec §4.5
    st.plotly_chart(
        charts.gamma_profile_figure(td.gex_recs, spot=td.spot or 0, ticker=ticker),
        width="stretch",
    )
    st.plotly_chart(
        charts.oi_per_strike_figure(td.oi_recs, spot=td.spot or 0,
                                    max_pain=td.max_pain, ticker=ticker),
        width="stretch",
    )
    st.plotly_chart(
        charts.vol_term_structure_figure(td.term, ticker=ticker),
        width="stretch",
    )

    _render_contract_picker(ticker, td, patterns)


def _render_contract_picker(ticker: str, td: "fetch.TickerData", patterns: dict):
    """Show front-week option contracts near the structural focus strike.

    Decision-support: lists what's available at the relevant strikes with
    current bid/ask/IV/volume/OI. Does NOT recommend specific contracts —
    the user picks. See README's 'What it is NOT' section."""
    # Pick the focus strike: pinning strike if firing, max-pain if set,
    # otherwise spot. This is the structural reference point the user
    # is most likely trading around.
    focus = None
    pin = patterns.get("pinning", {})
    if pin.get("firing"):
        focus = pin.get("note", {}).get("strike")
    if focus is None and td.max_pain:
        focus = td.max_pain
    if focus is None:
        focus = td.spot
    if focus is None:
        return  # no anchor to filter around

    records = fetch.fetch_one_contracts(ticker)
    if not records:
        return

    near = uw_client.contracts_near_focus(records, float(focus), n_strikes=4)
    if not near:
        return

    expiry = near[0]["expiry"]
    st.markdown(f"##### Contracts near {focus:.2f} ({expiry} expiry)")
    st.caption(
        "Decision-support only — lists what's available at the relevant strikes. "
        "Not a recommendation. You decide what to trade."
    )

    df = pd.DataFrame([{
        "Strike": r["strike"],
        "Type": r["type"].upper(),
        "Bid": r["bid"],
        "Ask": r["ask"],
        "Mid": round((r["bid"] + r["ask"]) / 2, 2),
        "IV": f"{r['iv'] * 100:.1f}%" if r["iv"] else "—",
        "Volume": r["volume"],
        "OI": r["oi"],
    } for r in near])
    st.dataframe(df, hide_index=True, width="stretch")
