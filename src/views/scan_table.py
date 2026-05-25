"""Bottom scan table view. Renders one row per ticker with source icon,
ticker, AI synthesis headline, then a colored badges row beneath."""
from __future__ import annotations
import pandas as pd
import streamlit as st

from src import badge_help


def _badges_html(patterns: dict) -> str:
    """Inline HTML of firing badges only. Non-firing patterns hidden per spec §4.5."""
    parts = []
    for kind in ("pinning", "gamma_squeeze", "flow", "vol_regime"):
        p = patterns.get(kind, {})
        if not p.get("firing"):
            continue
        color = badge_help.color_for(kind, p.get("note"))
        label = badge_help.label_for(kind, p.get("note"))
        opacity = max(0.3, min(1.0, p.get("intensity", 0.5)))
        tooltip = badge_help.TOOLTIPS.get(kind, "")
        parts.append(
            f"<span title='{tooltip}' style='background:{color};opacity:{opacity:.2f};"
            f"color:#0E1117;padding:2px 8px;border-radius:6px;"
            f"font-size:0.78em;margin-right:4px;font-weight:600;"
            f"display:inline-block;margin-bottom:4px;'>"
            f"{label}</span>"
        )
    return " ".join(parts) if parts else "<span style='color:#666;font-size:0.78em;'>—</span>"


def render(rows: list[dict], pinned: str | None = None) -> str | None:
    """Render the scan table. Returns the clicked ticker (or None).

    `rows` is a list of dicts with keys: ticker, synthesis, patterns,
    source_icon (📌 or 🔥 or '').
    """
    df = pd.DataFrame([{
        "": r.get("source_icon", ""),
        "Ticker": r["ticker"],
        "Analysis": r["synthesis"],
    } for r in rows])

    event = st.dataframe(
        df,
        key="scan_table",
        on_select="rerun",
        selection_mode="single-row",
        width="stretch",
        hide_index=True,
        column_config={
            "": st.column_config.TextColumn(width=40),
            "Ticker": st.column_config.TextColumn(width="small"),
            "Analysis": st.column_config.TextColumn(width="large"),
        },
    )

    # Badge row beneath the table (Streamlit dataframe cells can't render HTML)
    st.markdown("##### Pattern badges (firing only)")
    for r in rows:
        prefix = "▶ " if r["ticker"] == pinned else ""
        icon = r.get("source_icon", "")
        st.markdown(
            f"{prefix}{icon} **{r['ticker']}** &nbsp; {_badges_html(r['patterns'])}",
            unsafe_allow_html=True,
        )

    if event.selection and event.selection.rows:
        idx = event.selection.rows[0]
        return rows[idx]["ticker"]
    return None
