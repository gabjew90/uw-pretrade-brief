"""Plotly figure builders. Pure: input data → Figure.

All builders return a valid go.Figure even for empty input (renders a
"no data" annotation rather than erroring). Sized for vertical stacking
on phone and desktop alike.
"""
from __future__ import annotations
import plotly.graph_objects as go

DARK_TEMPLATE = "plotly_dark"
CHART_HEIGHT = 280


def _empty(title: str, msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, x=0.5, y=0.5,
                       xref="paper", yref="paper")
    fig.update_layout(title=title, height=CHART_HEIGHT,
                      margin=dict(l=20, r=20, t=40, b=20),
                      template=DARK_TEMPLATE)
    return fig


def gamma_profile_figure(gex_recs: list[dict], spot: float, ticker: str) -> go.Figure:
    """Bar chart of net dealer gamma per strike, vertical line at spot."""
    if not gex_recs:
        return _empty(f"{ticker} — net dealer gamma by strike", "No gamma data")

    strikes = [r["strike"] for r in gex_recs]
    gammas = [r["gamma"] for r in gex_recs]
    colors = ["#7AA2F7" if g >= 0 else "#F7768E" for g in gammas]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=strikes, y=gammas, marker_color=colors, name="Net γ"))
    if spot and spot > 0:
        fig.add_vline(x=spot, line_color="#E0AF68", line_dash="dash",
                      annotation_text=f"spot {spot:.2f}", annotation_position="top")
    fig.update_layout(
        title=f"{ticker} — net dealer gamma by strike",
        xaxis_title="Strike",
        yaxis_title="Net γ ($)",
        height=CHART_HEIGHT,
        margin=dict(l=20, r=20, t=40, b=30),
        template=DARK_TEMPLATE,
        showlegend=False,
    )
    return fig


def oi_per_strike_figure(
    oi_recs: list[dict],
    spot: float,
    max_pain: float | None,
    ticker: str,
) -> go.Figure:
    """Grouped bar: call OI above zero, put OI mirrored below.
    Vertical lines for spot (orange) and max-pain (purple)."""
    if not oi_recs:
        return _empty(f"{ticker} — open interest by strike", "No OI data")

    strikes = [r["strike"] for r in oi_recs]
    calls = [r["call_oi"] for r in oi_recs]
    puts = [-r["put_oi"] for r in oi_recs]   # mirror puts below axis

    fig = go.Figure()
    fig.add_trace(go.Bar(x=strikes, y=calls, marker_color="#9ECE6A", name="Call OI"))
    fig.add_trace(go.Bar(x=strikes, y=puts, marker_color="#F7768E", name="Put OI"))
    if spot and spot > 0:
        fig.add_vline(x=spot, line_color="#E0AF68", line_dash="dash",
                      annotation_text=f"spot {spot:.2f}", annotation_position="top")
    if max_pain and max_pain > 0:
        fig.add_vline(x=max_pain, line_color="#BB9AF7", line_dash="dot",
                      annotation_text=f"max pain {max_pain:.2f}",
                      annotation_position="bottom")
    fig.update_layout(
        title=f"{ticker} — open interest (calls above, puts below)",
        xaxis_title="Strike",
        yaxis_title="OI contracts (puts negative)",
        barmode="overlay",
        height=CHART_HEIGHT,
        margin=dict(l=20, r=20, t=40, b=30),
        template=DARK_TEMPLATE,
        legend=dict(orientation="h", y=1.12),
    )
    return fig


def vol_term_structure_figure(series: list[dict], ticker: str) -> go.Figure:
    """Line chart: days-to-expiry → implied volatility (% on y-axis)."""
    if not series:
        return _empty(f"{ticker} — IV term structure", "No vol data")

    dtes = [d["dte"] for d in series]
    ivs = [d["iv"] for d in series]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dtes, y=ivs, mode="lines+markers",
        line=dict(color="#BB9AF7", width=2),
        marker=dict(size=8, color="#BB9AF7"),
    ))
    fig.update_layout(
        title=f"{ticker} — IV term structure",
        xaxis_title="Days to expiry",
        yaxis_title="IV",
        yaxis_tickformat=".0%",
        height=CHART_HEIGHT,
        margin=dict(l=20, r=20, t=40, b=30),
        template=DARK_TEMPLATE,
    )
    return fig
