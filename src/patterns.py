"""Pure pattern detectors for the four trade theses.

All detectors take already-normalized inputs (lists/dicts from uw_client
parsers). None hit the network or read globals. Initial thresholds are
heuristic — calibrate as we observe real outputs (see MEMORY.md).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal

PatternKind = Literal["pinning", "gamma_squeeze", "flow", "vol_regime"]


@dataclass
class Verdict:
    kind: PatternKind
    firing: bool
    intensity: float       # 0..1, 0 if not firing
    note: dict             # detector-specific extras (strike, side, etc.)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- Pinning ----------
# Thesis: heavy net dealer gamma concentrated near spot → dealer hedging
# pins price near that strike into expiry.
#
# Heuristic:
#   - find strike with max |gamma| within ±2% of spot
#   - concentration = |top| / sum(|gamma|) across all strikes within ±5%
#   - firing if concentration > 0.30; intensity = min(1.0, conc / 0.50)

PIN_BAND = 0.05
PIN_NEAR = 0.02
PIN_THRESHOLD = 0.30


def detect_pinning(gex_recs: list[dict], spot: float) -> Verdict:
    if not gex_recs or spot is None or spot <= 0:
        return Verdict("pinning", False, 0.0, {"reason": "empty"})

    near = [r for r in gex_recs if abs(r["strike"] - spot) / spot <= PIN_NEAR]
    wide = [r for r in gex_recs if abs(r["strike"] - spot) / spot <= PIN_BAND]
    if not near or not wide:
        return Verdict("pinning", False, 0.0, {"reason": "no_nearby_strikes"})

    top = max(near, key=lambda r: abs(r["gamma"]))
    denom = sum(abs(r["gamma"]) for r in wide)
    if denom == 0:
        return Verdict("pinning", False, 0.0, {"reason": "zero_gamma"})

    conc = abs(top["gamma"]) / denom
    firing = conc > PIN_THRESHOLD
    intensity = min(1.0, conc / 0.50) if firing else 0.0
    return Verdict("pinning", firing, intensity, {
        "strike": top["strike"],
        "concentration": round(conc, 3),
    })


# ---------- Gamma squeeze ----------
# Thesis: dealers net SHORT gamma at strikes ABOVE (or BELOW) spot → if
# price crosses, dealers chase, amplifying the move.
#
# Heuristic: one side is significantly negative AND > 1.5x other side abs.

SQUEEZE_RATIO = 1.5


def detect_gamma_squeeze(gex_recs: list[dict], spot: float) -> Verdict:
    if not gex_recs or spot is None or spot <= 0:
        return Verdict("gamma_squeeze", False, 0.0, {"reason": "empty"})

    above = [r for r in gex_recs if r["strike"] > spot]
    below = [r for r in gex_recs if r["strike"] < spot]
    if not above or not below:
        return Verdict("gamma_squeeze", False, 0.0, {"reason": "one_sided"})

    above_sum = sum(r["gamma"] for r in above)
    below_sum = sum(r["gamma"] for r in below)

    direction = None
    magnitude = other = 0.0
    if above_sum < 0 and abs(above_sum) > SQUEEZE_RATIO * abs(below_sum):
        direction = "up"
        magnitude, other = abs(above_sum), abs(below_sum)
    elif below_sum < 0 and abs(below_sum) > SQUEEZE_RATIO * abs(above_sum):
        direction = "down"
        magnitude, other = abs(below_sum), abs(above_sum)
    else:
        return Verdict("gamma_squeeze", False, 0.0, {
            "above_sum": above_sum, "below_sum": below_sum,
        })

    intensity = min(1.0, magnitude / (magnitude + other + 1e-9))
    return Verdict("gamma_squeeze", True, intensity, {
        "direction": direction,
        "above_sum": above_sum,
        "below_sum": below_sum,
    })


# ---------- Flow + dark pool conviction ----------
# Thesis: net options premium directional and large → institutional positioning
# leaning. Dark pool prints aligned with the same direction → conviction
# amplifier. Divergent dark pool → conviction halved (smart money disagrees
# with options flow).
#
# Side comes from options flow (the primary signal). Dark pool acts as an
# intensity multiplier only — it does NOT flip the side.

FLOW_MIN_TOTAL = 1_000_000
FLOW_MIN_SKEW = 0.20


def detect_flow(flow_recs: list[dict], dp_net_premium: float | None = None) -> Verdict:
    if not flow_recs:
        return Verdict("flow", False, 0.0, {"side": "neutral", "reason": "empty"})

    calls = sum(r["premium_usd"] for r in flow_recs if r["side"] == "call")
    puts = sum(r["premium_usd"] for r in flow_recs if r["side"] == "put")
    total = calls + puts
    net = calls - puts

    if total == 0:
        return Verdict("flow", False, 0.0, {"side": "neutral", "reason": "zero_total"})

    skew = abs(net) / total
    firing = total >= FLOW_MIN_TOTAL and skew >= FLOW_MIN_SKEW
    if firing:
        side = "long" if net > 0 else "short"
    else:
        side = "neutral"

    intensity = min(1.0, skew * 2) if firing else 0.0

    # Dark pool corroboration: aligned amplifies, divergent halves
    dp_alignment = "n/a"
    if firing and dp_net_premium is not None:
        flow_long = (side == "long")
        dp_long = (dp_net_premium > 0)
        if dp_long == flow_long and abs(dp_net_premium) > 100_000:
            dp_alignment = "aligned"
            intensity = min(1.0, intensity * 1.25)
        elif dp_long != flow_long and abs(dp_net_premium) > 100_000:
            dp_alignment = "divergent"
            intensity *= 0.5
        else:
            dp_alignment = "weak_dp"

    return Verdict("flow", firing, intensity, {
        "side": side,
        "net_premium_usd": net,
        "total_premium_usd": total,
        "skew": round(skew, 3),
        "dp_net_premium_usd": dp_net_premium,
        "dp_alignment": dp_alignment,
    })


# ---------- Vol regime (IV term-structure inversion) ----------
# Thesis: front-week IV elevated vs 30-day IV → event-driven near-term
# richness (earnings, FOMC, scheduled catalyst).

VOL_INVERSION_THRESHOLD_PTS = 5.0
VOL_INVERSION_FULL_INTENSITY_PTS = 15.0


def detect_vol_regime(term_structure: list[dict]) -> Verdict:
    """`term_structure` is the list from uw_client.term_structure():
    [{"dte": int, "iv": float}, ...] sorted by dte ascending."""
    if not term_structure:
        return Verdict("vol_regime", False, 0.0, {"reason": "empty_term_structure"})

    front = next((e["iv"] for e in term_structure if e["dte"] <= 7), None)
    monthly = None
    if term_structure:
        monthly_entry = min(term_structure, key=lambda e: abs(e["dte"] - 30))
        if abs(monthly_entry["dte"] - 30) <= 10:
            monthly = monthly_entry["iv"]

    if front is None or monthly is None:
        return Verdict("vol_regime", False, 0.0, {"reason": "missing_front_or_30d"})

    delta_pts = (front - monthly) * 100
    note = {
        "front_iv": round(front, 4),
        "iv_30d": round(monthly, 4),
        "front_minus_30d_pts": round(delta_pts, 2),
    }

    if delta_pts >= VOL_INVERSION_THRESHOLD_PTS:
        intensity = min(1.0, delta_pts / VOL_INVERSION_FULL_INTENSITY_PTS)
        return Verdict("vol_regime", True, intensity, {"regime": "event_driven", **note})
    return Verdict("vol_regime", False, 0.0, {"regime": "normal", **note})


# ---------- Aggregator ----------

def detect_all(
    gex_recs: list[dict],
    flow_recs: list[dict],
    spot: float | None,
    term_structure: list[dict],
    dp_net_premium: float | None = None,
) -> dict[str, Verdict]:
    """Run all four detectors. Returns dict keyed by PatternKind string."""
    return {
        "pinning":       detect_pinning(gex_recs, spot or 0),
        "gamma_squeeze": detect_gamma_squeeze(gex_recs, spot or 0),
        "flow":          detect_flow(flow_recs, dp_net_premium=dp_net_premium),
        "vol_regime":    detect_vol_regime(term_structure),
    }
