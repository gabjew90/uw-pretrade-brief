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


import re as _re


def _escape_dollars_for_markdown(text: str) -> str:
    """Streamlit's markdown renderer treats `$...$` as LaTeX math mode.
    The synthesis prompt forbids `$` for currency, but escape any that
    slip through as a defensive backstop so the output never mangles."""
    # Replace bare $ with the escaped form \$ which renders as a literal $
    # Only escape $ that aren't already escaped.
    return _re.sub(r'(?<!\\)\$', r'\\$', text)


# Section headers the pinned synthesis is required to produce (see prompt
# in src/synth.py + fallback_pinned_summary). We split the synthesis into
# these four chunks so each can render inline with its corresponding chart.
_PINNED_SECTION_PATTERNS = [
    (_re.compile(r"\*\*\s*What the gamma chart shows\s*\*\*", _re.IGNORECASE), "gamma"),
    (_re.compile(r"\*\*\s*What the OI[^*]*?\*\*", _re.IGNORECASE), "oi_flow"),
    (_re.compile(r"\*\*\s*What the vol regime shows\s*\*\*", _re.IGNORECASE), "vol"),
    (_re.compile(r"\*\*\s*Best contracts for the week\s*\*\*", _re.IGNORECASE), "trades"),
]


def _split_pinned_synthesis(text: str) -> dict[str, str]:
    """Split the 4-section pinned synthesis into per-section content.

    Returns dict with keys: gamma, oi_flow, vol, trades. Missing sections
    are empty strings. If NO recognized headers are found (parser fail),
    the entire text falls into the 'trades' bucket so the user still sees
    the content rather than nothing."""
    sections = {"gamma": "", "oi_flow": "", "vol": "", "trades": ""}
    if not text:
        return sections

    matches: list[tuple[int, int, str]] = []
    for pattern, key in _PINNED_SECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            matches.append((m.start(), m.end(), key))
    matches.sort()

    if not matches:
        sections["trades"] = text
        return sections

    for i, (_start, end, key) in enumerate(matches):
        next_start = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        sections[key] = text[end:next_start].strip()
    return sections


def render(ticker: str, td: "fetch.TickerData", synthesis: str, patterns: dict):
    """Render the pinned card for a ticker.

    Layout: each chart is followed immediately by the synthesis section
    that explains it (gamma chart → gamma walkthrough, OI chart → OI
    walkthrough, vol chart → vol walkthrough), so the explanation lives
    with the visual it's explaining. The 'Best contracts for the week'
    trade-ideas section is the conclusion at the bottom.

    `synthesis` here is the LONG pinned-card walkthrough (4-section markdown
    with trade ideas), not the short scan-row headline."""
    head_col, close_col = st.columns([10, 1])
    with head_col:
        st.markdown(f"### {ticker}")
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
        # Transparency: surface percentile-context status so the user can tell
        # whether the synth has 30-day relative-quantification data to draw on.
        pct_ctx = st.session_state.get(f"_pct_ctx_{ticker}")
        if pct_ctx is not None:
            if "_error" in pct_ctx:
                st.caption(f"📊 Rolling percentile context: failed ({pct_ctx['_error']})")
            elif pct_ctx:
                # Sample sizes can differ per metric (concentration is computed
                # only when nearby strikes exist; others fall back to any spot
                # value). Show min-max range rather than a single number so the
                # user isn't misled when one metric has thinner history. The
                # window depth is the UW history available to this subscription
                # (typically ~7 trading days on Basic tier).
                n_metrics = sum(1 for k in pct_ctx if k.endswith("_pct_7d"))
                ns = [int(v) for k, v in pct_ctx.items() if k.endswith("_sample_n") and v]
                if ns:
                    window = f"{min(ns)} trading days" if min(ns) == max(ns) else f"{min(ns)}-{max(ns)} trading days"
                else:
                    window = "available history"
                st.caption(f"📊 Percentile context: {n_metrics} metrics, window = last {window} (UW history depth)")
            else:
                st.caption("📊 Percentile context: no history available for this ticker")
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

    # Split the synthesis into per-section content so each chart can be
    # followed by the section that explains it.
    sections = _split_pinned_synthesis(synthesis)

    def _render_section(key: str, header: str):
        """Render one synthesis section under its chart, if Gemini produced one."""
        content = sections.get(key, "").strip()
        if content:
            st.markdown(
                _escape_dollars_for_markdown(f"**{header}**\n\n{content}")
            )

    # Gamma chart + walkthrough
    st.plotly_chart(
        charts.gamma_profile_figure(td.gex_recs, spot=td.spot or 0, ticker=ticker),
        width="stretch",
    )
    _render_section("gamma", "What the gamma chart shows")

    # OI chart + walkthrough
    st.plotly_chart(
        charts.oi_per_strike_figure(td.oi_recs, spot=td.spot or 0,
                                    max_pain=td.max_pain, ticker=ticker),
        width="stretch",
    )
    _render_section("oi_flow", "What the OI + flow data shows")

    # Vol chart + walkthrough
    st.plotly_chart(
        charts.vol_term_structure_figure(td.term, ticker=ticker),
        width="stretch",
    )
    _render_section("vol", "What the vol regime shows")

    # Trade-ideas section — conclusion, lives at the bottom above the picker
    _render_section("trades", "Best contracts for the week")

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
