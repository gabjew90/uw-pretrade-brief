"""Plotly figure builders. Pure: input data → Figure.

Aesthetic direction: financial-terminal dark, Tokyo Night palette,
deliberate negative space, x-axis auto-zoomed to the actionable range
(spot-relative for strike charts, near-term for IV term structure).

All builders return a valid go.Figure even for empty input (renders a
"no data" annotation rather than erroring). Sized for vertical stacking
on phone and desktop alike.
"""
from __future__ import annotations
import plotly.graph_objects as go

# ---- Palette (Tokyo Night-derived, picked for chart legibility on dark bg) ----
COLOR_BG        = "#0E1117"   # page background
COLOR_PAPER     = "#0E1117"   # chart background (transparent to page)
COLOR_GRID      = "#2A2E3B"   # subtle gridlines
COLOR_TEXT      = "#C0CAF5"   # primary text
COLOR_AXIS      = "#7A85A8"   # axis labels (dimmer than text)
COLOR_TITLE     = "#E6E6E6"   # chart titles

COLOR_POS_GAMMA = "#7AA2F7"   # blue: positive dealer γ (stabilizing/pinning)
COLOR_NEG_GAMMA = "#F7768E"   # red: negative dealer γ (squeeze fuel)
COLOR_CALL_OI   = "#9ECE6A"   # green: call OI
COLOR_PUT_OI    = "#F7768E"   # red: put OI
COLOR_IV        = "#BB9AF7"   # purple: IV term structure
COLOR_SPOT      = "#E0AF68"   # orange: spot reference line
COLOR_MAX_PAIN  = "#BB9AF7"   # purple: max-pain reference line

CHART_HEIGHT = 320            # slightly taller for breathing room

# Auto-zoom: charts show this fraction around spot. ±7% covers the
# actionable strike range for weekly options on most tickers.
STRIKE_ZOOM_PCT = 0.07
# IV term structure: only the first 90 DTE matters for weekly + monthly thesis;
# beyond that the curve flattens and crowds the front-week detail.
VOL_TERM_DTE_CAP = 90


def _base_layout(title: str, height: int = CHART_HEIGHT) -> dict:
    """Shared layout dict — applies the dark-terminal aesthetic."""
    return dict(
        title=dict(
            text=title,
            font=dict(color=COLOR_TITLE, size=14, family="ui-monospace, SFMono-Regular, monospace"),
            x=0.01,
            xanchor="left",
        ),
        height=height,
        margin=dict(l=50, r=20, t=44, b=40),
        paper_bgcolor=COLOR_PAPER,
        plot_bgcolor=COLOR_BG,
        font=dict(color=COLOR_TEXT, family="ui-monospace, SFMono-Regular, monospace", size=11),
        xaxis=dict(
            gridcolor=COLOR_GRID,
            zerolinecolor=COLOR_GRID,
            zerolinewidth=1,
            tickfont=dict(color=COLOR_AXIS, size=10),
            title=dict(font=dict(color=COLOR_AXIS, size=10)),
            showline=False,
        ),
        yaxis=dict(
            gridcolor=COLOR_GRID,
            zerolinecolor=COLOR_AXIS,
            zerolinewidth=1,
            tickfont=dict(color=COLOR_AXIS, size=10),
            title=dict(font=dict(color=COLOR_AXIS, size=10)),
            showline=False,
        ),
        showlegend=False,
        hoverlabel=dict(
            bgcolor="#1A1E26",
            bordercolor=COLOR_GRID,
            font=dict(family="ui-monospace, SFMono-Regular, monospace", size=11, color=COLOR_TEXT),
        ),
    )


def _empty(title: str, msg: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(**_base_layout(title))
    fig.add_annotation(
        text=msg, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper",
        font=dict(color=COLOR_AXIS, size=12),
    )
    return fig


def _spot_band(spot: float | None) -> tuple[float, float] | None:
    """Return (low, high) x-axis range = ±STRIKE_ZOOM_PCT around spot.
    None if spot is unusable so caller falls back to autorange."""
    if not spot or spot <= 0:
        return None
    return (spot * (1 - STRIKE_ZOOM_PCT), spot * (1 + STRIKE_ZOOM_PCT))


def gamma_profile_figure(gex_recs: list[dict], spot: float, ticker: str) -> go.Figure:
    """Bar chart of net dealer gamma per strike. X-axis auto-zoomed to spot ±7%.
    Strikes outside that window are still in the data (hoverable if user pans)
    but the default view focuses where the action actually is."""
    if not gex_recs:
        return _empty(f"{ticker} · net dealer γ by strike", "No gamma data")

    strikes = [r["strike"] for r in gex_recs]
    gammas = [r["gamma"] for r in gex_recs]
    colors = [COLOR_POS_GAMMA if g >= 0 else COLOR_NEG_GAMMA for g in gammas]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=strikes, y=gammas, marker_color=colors, name="Net γ",
        hovertemplate="<b>%{x:.2f}</b><br>γ=%{y:,.0f}<extra></extra>",
    ))

    layout = _base_layout(f"{ticker} · net dealer γ by strike  ·  blue = positive (pinning), red = negative (squeeze fuel)")
    layout["yaxis"]["title"]["text"] = "γ exposure ($/1% move)"

    band = _spot_band(spot)
    if band:
        layout["xaxis"]["range"] = list(band)
        layout["xaxis"]["title"] = dict(text=f"Strike  (showing ±{int(STRIKE_ZOOM_PCT*100)}% around spot {spot:.2f})", font=dict(color=COLOR_AXIS, size=10))
    else:
        layout["xaxis"]["title"] = dict(text="Strike", font=dict(color=COLOR_AXIS, size=10))

    fig.update_layout(**layout)

    if spot and spot > 0:
        fig.add_vline(
            x=spot, line_color=COLOR_SPOT, line_width=2, line_dash="solid",
            annotation_text=f"spot {spot:.2f}",
            annotation_position="top",
            annotation=dict(font=dict(color=COLOR_SPOT, size=11), bgcolor=COLOR_BG),
        )
    return fig


def oi_per_strike_figure(
    oi_recs: list[dict],
    spot: float,
    max_pain: float | None,
    ticker: str,
) -> go.Figure:
    """Grouped bar: call OI above zero, put OI mirrored below. Vertical lines
    for spot (orange solid) and max-pain (purple dashed). X-axis auto-zoomed."""
    if not oi_recs:
        return _empty(f"{ticker} · open interest by strike", "No OI data")

    strikes = [r["strike"] for r in oi_recs]
    calls = [r["call_oi"] for r in oi_recs]
    puts = [-r["put_oi"] for r in oi_recs]   # mirror puts below axis

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=strikes, y=calls, marker_color=COLOR_CALL_OI, name="Call OI",
        hovertemplate="<b>%{x:.2f}</b><br>calls=%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=strikes, y=puts, marker_color=COLOR_PUT_OI, name="Put OI",
        hovertemplate="<b>%{x:.2f}</b><br>puts=%{customdata:,.0f}<extra></extra>",
        customdata=[r["put_oi"] for r in oi_recs],
    ))

    layout = _base_layout(f"{ticker} · open interest by strike  ·  calls above, puts mirrored below")
    layout["yaxis"]["title"]["text"] = "OI contracts"
    layout["barmode"] = "overlay"
    layout["showlegend"] = True
    layout["legend"] = dict(
        orientation="h", y=1.08, x=0.99, xanchor="right",
        font=dict(color=COLOR_AXIS, size=10), bgcolor="rgba(0,0,0,0)",
    )

    band = _spot_band(spot)
    if band:
        layout["xaxis"]["range"] = list(band)
        layout["xaxis"]["title"] = dict(text=f"Strike  (showing ±{int(STRIKE_ZOOM_PCT*100)}% around spot {spot:.2f})", font=dict(color=COLOR_AXIS, size=10))
    else:
        layout["xaxis"]["title"] = dict(text="Strike", font=dict(color=COLOR_AXIS, size=10))

    fig.update_layout(**layout)

    if spot and spot > 0:
        fig.add_vline(
            x=spot, line_color=COLOR_SPOT, line_width=2, line_dash="solid",
            annotation_text=f"spot {spot:.2f}", annotation_position="top",
            annotation=dict(font=dict(color=COLOR_SPOT, size=11), bgcolor=COLOR_BG),
        )
    if max_pain and max_pain > 0:
        fig.add_vline(
            x=max_pain, line_color=COLOR_MAX_PAIN, line_width=1.5, line_dash="dash",
            annotation_text=f"max pain {max_pain:.2f}", annotation_position="bottom",
            annotation=dict(font=dict(color=COLOR_MAX_PAIN, size=11), bgcolor=COLOR_BG),
        )
    return fig


def vol_term_structure_figure(series: list[dict], ticker: str) -> go.Figure:
    """Line chart: days-to-expiry → implied volatility. X-axis capped at
    VOL_TERM_DTE_CAP so the front-week/monthly detail isn't crushed by LEAPS.
    Annotates the front-week (DTE ≤ 7) and 30-day reference points."""
    if not series:
        return _empty(f"{ticker} · IV term structure", "No vol data")

    # Filter to the cap window — keep the tail but don't show it
    visible = [d for d in series if d["dte"] <= VOL_TERM_DTE_CAP]
    if not visible:
        visible = series  # fall back to whatever we have

    dtes = [d["dte"] for d in visible]
    ivs = [d["iv"] for d in visible]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dtes, y=ivs, mode="lines+markers",
        line=dict(color=COLOR_IV, width=2.5),
        marker=dict(size=7, color=COLOR_IV, line=dict(color=COLOR_BG, width=1.5)),
        hovertemplate="<b>%{x} DTE</b><br>IV=%{y:.1%}<extra></extra>",
    ))

    # Annotate the front-week and ~30-day points (these drive the vol-regime thesis)
    front = next((d for d in visible if d["dte"] <= 7), None)
    if front:
        fig.add_annotation(
            x=front["dte"], y=front["iv"],
            text=f"front {front['iv']*100:.1f}%",
            showarrow=True, arrowhead=2, ax=20, ay=-30,
            arrowcolor=COLOR_SPOT, font=dict(color=COLOR_SPOT, size=10),
        )
    monthly = min(visible, key=lambda d: abs(d["dte"] - 30))
    if abs(monthly["dte"] - 30) <= 10:
        fig.add_annotation(
            x=monthly["dte"], y=monthly["iv"],
            text=f"30d {monthly['iv']*100:.1f}%",
            showarrow=True, arrowhead=2, ax=20, ay=-30,
            arrowcolor=COLOR_AXIS, font=dict(color=COLOR_AXIS, size=10),
        )

    layout = _base_layout(f"{ticker} · IV term structure  ·  front-week vs 30-day inversion = event-driven richness")
    layout["xaxis"]["title"] = dict(
        text=f"Days to expiry  (showing 0–{VOL_TERM_DTE_CAP}; LEAPS hidden)",
        font=dict(color=COLOR_AXIS, size=10),
    )
    layout["xaxis"]["range"] = [0, VOL_TERM_DTE_CAP]
    layout["yaxis"]["title"]["text"] = "IV"
    layout["yaxis"]["tickformat"] = ".0%"
    fig.update_layout(**layout)
    return fig
