"""Central badge tooltip + color constants. Edit here to retune every
view that renders pattern badges."""
from __future__ import annotations

# One color per pattern category. Direction-agnostic patterns are NOT
# coerced into green/red — they get their own hue. Saturation/opacity
# is applied at render time to encode firing intensity.
PATTERN_COLORS = {
    "pinning":       "#7AA2F7",  # blue
    "gamma_squeeze": "#E0AF68",  # orange
    "flow_long":     "#9ECE6A",  # green (directional)
    "flow_short":    "#F7768E",  # red   (directional)
    "flow_neutral":  "#9AA5CE",  # gray  (non-firing flow normally hidden)
    "vol_regime":    "#BB9AF7",  # purple
}

TOOLTIPS = {
    "pinning":       "Heavy net dealer gamma concentrated near spot — dealer hedging tends to pin price near that strike into expiry.",
    "gamma_squeeze": "Dealers net SHORT gamma at strikes above (or below) spot — if price crosses, dealers chase, amplifying the move.",
    "flow":          "Net options premium is large AND directional — institutional positioning leaning. Dark pool alignment amplifies; divergence halves.",
    "vol_regime":    "Front-week IV elevated vs 30-day IV — market is pricing event-driven near-term richness (earnings, FOMC, scheduled catalyst).",
}


def color_for(pattern_kind: str, note: dict | None = None) -> str:
    if pattern_kind == "flow" and note:
        side = note.get("side", "neutral")
        return PATTERN_COLORS.get(f"flow_{side}", PATTERN_COLORS["flow_neutral"])
    return PATTERN_COLORS.get(pattern_kind, "#9AA5CE")


def label_for(pattern_kind: str, note: dict | None = None) -> str:
    """Short label rendered inside the badge body."""
    note = note or {}
    if pattern_kind == "pinning":
        strike = note.get("strike")
        return f"PIN @ {strike:g}" if strike else "PIN"
    if pattern_kind == "gamma_squeeze":
        direction = note.get("direction", "")
        arrow = "↑" if direction == "up" else "↓" if direction == "down" else ""
        return f"Γ-WALL {arrow}".strip()
    if pattern_kind == "flow":
        side = note.get("side", "?")
        net_m = note.get("net_premium_usd", 0) / 1e6
        sign = "+" if net_m >= 0 else ""
        return f"FLOW {sign}${net_m:.1f}M ({side})"
    if pattern_kind == "vol_regime":
        pts = note.get("front_minus_30d_pts")
        return f"VOL +{pts:.1f}pt" if isinstance(pts, (int, float)) else "VOL"
    return pattern_kind.upper()
