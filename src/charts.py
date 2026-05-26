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


# ---- Percentile dashboard --------------------------------------------------
# Compact horizontal strip showing where TODAY sits within the trailing
# history window for each of the 8 percentile-tracked metrics. Same 0–100
# X-axis for every row so the eye can compare across metrics at a glance.

# Display labels keyed by the metric stem in pct_ctx (without the _pct_7d /
# _7d_sample_n suffixes). Kept short — these are y-axis tick labels.
_PERCENTILE_METRIC_LABELS: list[tuple[str, str]] = [
    ("concentration",         "Pin concentration"),
    ("squeeze_above",         "Net γ above spot"),
    ("squeeze_below",         "Net γ below spot"),
    ("net_premium",           "Net premium"),
    ("skew",                  "Flow skew"),
    ("max_pain_distance_pct", "Max-pain distance"),
    ("front_iv",              "Front-week IV"),
    ("term_spread_pts",       "Term-structure spread"),
]


def _percentile_dot_color(pct: float) -> str:
    """Red for extremes (≥90 or ≤10), orange for elevated/quiet quartiles
    (75-90 or 10-25), blue for the typical interquartile zone (25-75)."""
    if pct >= 90 or pct <= 10:
        return COLOR_NEG_GAMMA   # extreme — red
    if pct >= 75 or pct <= 25:
        return COLOR_SPOT        # elevated/quiet — orange
    return COLOR_POS_GAMMA       # typical — blue


def percentile_dashboard_figure(pct_ctx: dict, ticker: str) -> go.Figure:
    """One row per metric. X-axis = 0-100 percentile space (shared across
    metrics). Today's value plotted as a colored dot at its percentile; gray
    vertical guides at the 25/50/75 marks; sample size annotated on the right.

    `pct_ctx` is the dict returned by fetch.percentile_context — keys ending
    in `_pct_7d` (the percentile) and `_7d_sample_n` (the actual sample size).
    """
    if not pct_ctx:
        return _empty(f"{ticker} · percentile dashboard", "No percentile context")

    # Filter to the metrics that have data this session, preserving the
    # display order above (logical grouping: gamma → flow → vol).
    rows: list[tuple[str, float, int | None]] = []
    for key, label in _PERCENTILE_METRIC_LABELS:
        pct = pct_ctx.get(f"{key}_pct_7d")
        n = pct_ctx.get(f"{key}_7d_sample_n")
        if pct is None:
            continue
        rows.append((label, float(pct), int(n) if n else None))

    if not rows:
        return _empty(f"{ticker} · percentile dashboard", "No percentile context")

    labels = [r[0] for r in rows]
    pcts = [r[1] for r in rows]
    ns = [r[2] for r in rows]
    colors = [_percentile_dot_color(p) for p in pcts]

    # Right-side annotation text per metric: percentile + sample size
    annotations_text = [
        f"{int(round(p))}th pctile" + (f" · n={n}" if n else "")
        for p, n in zip(pcts, ns)
    ]

    fig = go.Figure()

    # Faint horizontal lane lines so each metric row reads as its own track.
    # Plot first so dots/markers sit on top.
    for i in range(len(labels)):
        fig.add_shape(
            type="line",
            x0=0, x1=100, y0=i, y1=i,
            line=dict(color=COLOR_GRID, width=1),
            layer="below",
        )

    # Today's dots, colored by zone (red extremes, orange quartiles, blue typical)
    fig.add_trace(go.Scatter(
        x=pcts,
        y=labels,
        mode="markers",
        marker=dict(
            size=14,
            color=colors,
            line=dict(color=COLOR_BG, width=2),
            symbol="circle",
        ),
        hovertemplate="<b>%{y}</b><br>today = %{x:.0f}th percentile<extra></extra>",
        showlegend=False,
    ))

    # Right-side text annotations for each row
    n_rows = len(labels)
    for i, (label, text) in enumerate(zip(labels, annotations_text)):
        fig.add_annotation(
            x=105, y=label,
            text=text,
            showarrow=False,
            xanchor="left",
            font=dict(color=COLOR_AXIS, size=10, family="ui-monospace, SFMono-Regular, monospace"),
        )

    # Sizing: ~26px per row plus chart chrome. Keeps the strip compact even
    # with 8 metrics; phone-friendly.
    height = max(180, 26 * n_rows + 80)

    layout = _base_layout(
        f"{ticker} · percentile dashboard  ·  today's reading vs trailing history",
        height=height,
    )
    layout["margin"] = dict(l=160, r=140, t=44, b=40)
    layout["xaxis"]["range"] = [-2, 102]
    layout["xaxis"]["tickmode"] = "array"
    layout["xaxis"]["tickvals"] = [0, 25, 50, 75, 100]
    layout["xaxis"]["ticktext"] = ["0", "25", "50", "75", "100"]
    layout["xaxis"]["title"] = dict(
        text="Percentile (0 = lowest in window · 50 = median · 100 = highest)",
        font=dict(color=COLOR_AXIS, size=10),
    )
    layout["yaxis"]["title"]["text"] = ""
    layout["yaxis"]["autorange"] = "reversed"  # first metric at top
    layout["yaxis"]["gridcolor"] = COLOR_PAPER  # hide y gridlines; lanes provide structure
    layout["showlegend"] = False
    fig.update_layout(**layout)

    # Vertical guide lines at quartile marks — drawn after layout so they pick
    # up the final y range. Using shapes rather than vlines so we don't get
    # arrow heads or labels.
    for x_mark, label_text in [(25, "Q1"), (50, "median"), (75, "Q3")]:
        fig.add_shape(
            type="line",
            x0=x_mark, x1=x_mark,
            y0=-0.5, y1=n_rows - 0.5,
            line=dict(
                color=COLOR_AXIS,
                width=1,
                dash="dot" if x_mark != 50 else "dash",
            ),
            layer="below",
        )
        fig.add_annotation(
            x=x_mark, y=-0.7,
            text=label_text,
            showarrow=False,
            font=dict(color=COLOR_AXIS, size=9),
            yshift=2,
        )
    return fig
