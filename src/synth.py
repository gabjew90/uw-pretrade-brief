"""Gemini-based AI synthesis with guardrails + deterministic fallback.

Per design spec §5 + the post-review prompt revision: synthesis must
ADD information beyond what the row badges already show. If the model
can't, it returns NO_INSIGHT and we render the deterministic fallback.

A substance check ALSO compares Gemini output to the fallback — if
synthesis isn't materially better (shorter or fewer numbers cited),
we prefer the fallback. This prevents mediocre AI prose from masquerading
as insight.
"""
from __future__ import annotations
import json
import os
import re
import sys
from typing import Any

MODEL = "gemini-3.1-flash-lite"
MAX_OUTPUT_TOKENS = 120          # scan-row synthesis (tight)
MAX_OUTPUT_TOKENS_PINNED = 1400  # pinned-card synthesis (multi-paragraph + 3-4 trades w/ Entry/Exit/Why)

# Used by SCAN-ROW synthesis only. The pinned synthesis is allowed to use
# recommendation language because the operator explicitly opted into that
# framing (see MEMORY.md).
FORBIDDEN_RE = re.compile(
    r"\b(buy|sell|short|long the|enter|exit|recommend|should|suggest|"
    r"consider taking|strong\s+(?:buy|sell)|high probability|likely to|"
    r"expect price|target|price target)\b",
    flags=re.IGNORECASE,
)

INSTRUCTION = """You write 1-2 sentence structural readouts of options data for a personal-use trading dashboard.

The four patterns referenced (these are already shown as colored BADGES next to each ticker — do NOT just list them):
- Pinning: heavy net dealer gamma concentrated at a strike near spot.
- Gamma squeeze: dealers net SHORT gamma at strikes above or below spot.
- Flow conviction: net options premium directional and large; aligned dark pool prints amplify, divergent halve.
- Vol regime: front-week IV elevated vs 30-day IV (event-driven richness).

YOUR JOB IS NOT TO RESTATE THE BADGES. The user can see them already. Add information the badges DO NOT convey:
- Cross-pattern tension (e.g. "heavy call flow into a positive-gamma wall — buyers fighting the dealer hedge")
- Context the data implies (e.g. "front-week IV spike with no flow conviction reads as scheduled-event hedging, not directional bet")
- A structural relationship between two firing patterns
- A notable absence (e.g. "pinning setup at 450 but no flow conviction — pin likely to hold absent a catalyst")

RULES (strict, enforced by a regex validator that will reject violations):
1. HARD LIMIT: MAXIMUM TWO sentences. Count them before submitting. A third sentence causes your output to be discarded entirely.
2. If you cannot add information beyond what the badges show in ≤2 sentences, output exactly the literal string "NO_INSIGHT" instead. NO_INSIGHT is the correct answer when you don't have something genuinely useful to say.
3. Use ONLY descriptive language. Forbidden words/phrases (your output is auto-rejected if any appear): buy, sell, short, long the, enter, exit, recommend, should, suggest, target, strong buy, strong sell, high probability, likely to.
4. If you produce text, reference at least one specific number from the payload.
5. Do NOT predict direction, probability, or outcome. Describe what IS, not what WILL happen.
6. Do NOT enumerate firing pattern names as a list — the badges do that. Reference a pattern only as part of a relationship or context point.
"""


def build_prompt(ticker: str, patterns: dict, key_numbers: dict) -> str:
    return (
        INSTRUCTION
        + f"\n\nTicker: {ticker}\n"
        + f"Patterns:\n{json.dumps(patterns, indent=2, default=str)}\n"
        + f"Key numbers:\n{json.dumps(key_numbers, indent=2, default=str)}\n"
        + "\nWrite the readout now (or NO_INSIGHT):"
    )


# ---------- Pinned-card synthesis (longer, walks through charts + names trades) ----------
#
# This synthesis runs when a user has pinned a ticker. It assumes the reader
# is familiar with options basics (calls, puts, strikes, IV, DTE) but NEW to
# UW-specific framings (Spot GEX, dealer hedging, dark pool tick rule,
# IV term-structure inversion). Output is multi-paragraph and DOES name
# specific trades — operator-accepted framing (see MEMORY.md).

PINNED_INSTRUCTION = """You are writing an educational walkthrough for an options trader who knows the basics (calls, puts, strikes, IV, DTE) but is NEW to Unusual Whales' specific data framings (Spot GEX, dealer gamma hedging, dark pool tick rule, IV term-structure inversion).

═════════════════════════════════════════════════════════════════════
UW DATA CONTEXT (read first — every payload field has specific provenance)
═════════════════════════════════════════════════════════════════════

**Spot GEX → drives pinning + gamma_squeeze patterns**
- Source: UW `/api/stock/{ticker}/spot-exposures/strike`
- It's a SNAPSHOT: sum of all currently-open contracts (OI-weighted) as of yesterday's OCC close + today's volume layered on. Updates daily; does NOT change minute-to-minute within a session.
- Units: dollars per 1% spot move (the $ dealers must hedge if spot moves 1%).
- Positive γ = dealers LONG gamma (sell into strength, buy into weakness → vol-suppressing, pinning behavior).
- Negative γ = dealers SHORT gamma (buy into strength, sell into weakness → vol-amplifying, squeeze fuel).
- "intensity" 0-1 in the payload is computed by OUR pattern detector, not UW:
    pinning intensity = concentration / 0.50, capped at 1.0; firing requires concentration > 0.30
    squeeze intensity = side_magnitude / (side_magnitude + other_side); firing requires one side > 1.5× the other AND negative
  Calibration: intensity 0.5 = moderate, 0.8 = strong, 1.0 = saturated (very strong).

**Dark pool → corroborates the flow pattern**
- Source: UW `/api/darkpool/{ticker}` — recent off-exchange equity prints (NOT options).
- Each print classified by tick rule (price vs NBBO midpoint): above mid = buyer-initiated ("buy"), below = seller-initiated ("sell"), equal = "neutral". This is a HEURISTIC, not ground truth on order direction.
- "dp_alignment" field in the flow note:
    "aligned" = dark pool net premium has SAME sign as options-flow side, AND |net| > $100k → boosts flow intensity ×1.25
    "divergent" = opposite signs with |net| > $100k → halves flow intensity
    "weak_dp" = |net| < $100k → no effect on intensity
    "n/a" = no dark pool data passed

**Flow → directional options premium**
- Source: UW `/api/option-trades/flow-alerts?ticker_symbol={ticker}` (50-record window)
- net_premium_usd = total calls $ − total puts $ in that window. NOT a tick-level feed; aggregated alerts only.
- Firing requires total premium ≥ $1,000,000 AND skew (|net|/total) ≥ 0.20.
- Intensity = min(1.0, skew × 2), then adjusted by dark-pool alignment as above.

**Vol regime → IV term-structure inversion**
- Source: UW `/api/stock/{ticker}/volatility/term-structure` — average ATM call+put IV per expiry.
- We compare front-week IV (DTE ≤ 7) to 30-day IV. Inversion ≥ 5 vol points → "event_driven" (market pricing a near-term catalyst). Normal term structure slopes UPWARD with DTE; inversion is unusual and meaningful.

**Max pain**
- Source: UW `/api/stock/{ticker}/max-pain` (per-expiry rows).
- We pull the FRONT-WEEK only (first row = smallest expiry).

**IV rank (in key_numbers, when present)**
- Source: UW `/api/stock/{ticker}/interpolated-iv` (front-week percentile, 0-100).
- 50 = median, >75 = elevated (premium expensive), <25 = crushed (premium cheap).

**next_earnings (in key_numbers, when present)**
- Source: UW `/api/stock/{ticker}/earnings` (next upcoming date, or null for ETFs / no upcoming).

**Contracts summary (in the payload after key_numbers, when present)**
- Real live bid/ask/IV from UW's option-contracts endpoint for the strikes nearest the focus point.
- The user sees these EXACT numbers in the contracts table below your output.
- When you name a contract, use a strike/expiry from this list — do NOT invent prices or strikes that aren't shown.

═════════════════════════════════════════════════════════════════════
WHAT YOU DO NOT HAVE (do not invent or imply these)
═════════════════════════════════════════════════════════════════════

- NO realized volatility data — do not compare IV to "historical realized vol of X" or "20-day HV". You only have implied vol.
- NO intraday or multi-day trajectory — this is a SNAPSHOT. Do not write "the pin has been holding for 3 days" or "flow has been building over the morning". You see one moment in time.
- NO tick-level options flow — flow_alerts are pre-aggregated by UW. Do not narrate "in the last 15 minutes I saw...".
- NO analyst targets, technical levels, news catalysts beyond the `next_earnings` field. Do not say "Fed meeting tomorrow" unless that exact context is in the payload.
- NO bid/ask for strikes other than those in the Contracts summary block. If you want to name a contract not shown, just say "front-week strike near X" rather than inventing a price.
- NO data older than 30 days — UW Basic tier cap. Do not reference "quarterly trend" or "year-to-date".
- NO information about user's account size, risk tolerance, existing positions, or portfolio context. Trade sizing language ("size to 1-2% of account") is fine as generic guidance, but do not assume specifics.

═════════════════════════════════════════════════════════════════════
GROUNDING RULES (hard requirements)
═════════════════════════════════════════════════════════════════════

- Every number you cite must come from the payload. If the payload says spot is 745.9 and pin is 745.0, do NOT cite 746.2 or 744.5 — those numbers are not in the data.
- If you're tempted to add color from market intuition (e.g. "the SPY 745 strike is a key psychological level"), DON'T. Stick to what the payload shows.
- Distinguish OBSERVATION from INFERENCE. "Spot is 745.9 with pin at 745.0" is observation. "This pin is likely to hold" is inference (allowed when grounded in the firing pattern but say WHY).
- If a pattern's firing intensity is < 0.5, hedge your conviction language in that section ("moderate concentration" rather than "decisive pin").
- **CRITICAL FORMATTING: do NOT use the `$` character for currency amounts.** Streamlit's markdown renderer treats `$` as LaTeX math-mode delimiter and will mangle your text. Use `USD` or bare numbers instead.
    - WRONG: `-$8.8M net premium`, `$5,000,000 of flow`, `target $740`
    - RIGHT: `-8.8M USD net premium`, `5,000,000 USD of flow`, `target 740`
    - For strike prices (no currency symbol needed anyway): just write `745` or `745.00`.

═════════════════════════════════════════════════════════════════════
WHAT THE READER SEES
═════════════════════════════════════════════════════════════════════

Three charts in the pinned card for {ticker}:
- Net dealer gamma exposure by strike (the "GEX" chart) — bars across strikes, vertical line at spot
- Open interest per strike (calls above zero, puts mirrored below) — vertical lines at spot AND max-pain
- IV term structure (implied vol per days-to-expiry) — line curve, % on y-axis

Plus a contracts table below your output with live bid/ask for the strikes nearest the focus point.

═════════════════════════════════════════════════════════════════════
YOUR JOB
═════════════════════════════════════════════════════════════════════

Write a structured walkthrough that:
1. Translates the UW-specific concepts as you use them (using the calibration above).
2. Walks through what each chart shows for THIS ticker right now (grounded in the payload).
3. Identifies the structural trade(s) the data favors AND names specific contracts (strike + side + expiry) that fit, with Entry/Exit conditions.

OUTPUT FORMAT (markdown, 4 sections, each labeled):

**What the gamma chart shows**
- 2-3 sentences. Reference the actual numbers from the patterns/key_numbers payload (spot, max-pain, pin strike if firing).
- Translate: "dealer gamma exposure" = the amount of stock market makers need to buy/sell to stay hedged when spot moves 1%. Positive = dealers long γ (stabilizing, pinning). Negative = dealers short γ (destabilizing, squeeze fuel).
- Name what's structurally happening for this ticker: a pin? a wall? clean range?

**What the OI + flow data shows**
- 2-3 sentences. Reference flow direction + dark pool corroboration if present.
- Translate UW concepts: net options premium = $ flow direction; dark pool prints classified by tick rule (price > NBBO midpoint = buyer-initiated, etc.); "aligned" dark pool means equity desk agrees with options crowd.
- Name the directional bias (or lack of it).

**What the vol regime shows**
- 1-2 sentences. Front-week IV vs 30-day IV. If inverted (≥5 vol points), explain it means the market is pricing an event-driven near-term catalyst (earnings, FOMC, scheduled news). If normal, say so plainly.

**Best contracts for the week**
- 2-4 specific trade ideas, each formatted as a bullet with **bold name + structure** followed by THREE sub-bullets in this exact order:
  - **Entry**: when to put it on. Be specific — "at the open", "wait for SPY to break below 745", "on a reversal candle off 745 with rising volume", "only if IV rank holds above 80", etc. Reference price levels, time-of-day, or confirming signals. NEVER say "any time" or leave it vague.
  - **Exit**: target AND stop. Target = profit-taking condition (e.g., "50% of max profit", "spot reaches max-pain 737"). Stop = thesis-break condition (e.g., "close if SPY reclaims 746.5 with volume", "exit if dark pool flips long > $5M"). If the trade is meant to ride to expiry, say "let expire worthless if pin holds" instead of a target.
  - **Why**: ONE sentence tying the entry/exit to the firing patterns above.
- The Entry/Exit framework is critical — a trader needs to know WHEN to act, not just WHAT to trade. A vague "captures the move" is not enough.
- Order: most structurally-aligned trade first, alternative directional play second, lower-conviction or hedged-alternative third.
- If no patterns are firing strongly enough, say so plainly: "No high-conviction structural setup this week — wait for a fresh catalyst or sit out." Don't manufacture trades.

EXAMPLE of the Entry/Exit format (shape only — your actual content will differ):

- **Bearish Directional Play** — 745.00 put (front-week)
  - **Entry**: enter at the open if SPY trades below 745.0; wait for a break otherwise.
  - **Exit**: target 740.0 (halfway to max-pain 737); stop out if SPY reclaims 746.5 with volume.
  - **Why**: -$8.8M net flow + aligned dark pool suggests the pin breaks down once dealer hedging exhausts.

STRICT REQUIREMENTS:
- Cite at least 4 specific numbers from the payload (spot, max-pain, pin strike, flow $, IV, DTE, etc.).
- Stay grounded in the actual data shown — do not invent numbers.
- When naming a contract, use the format: "STRIKE call/put expiring YYYY-MM-DD" or just "STRIKE call/put (front-week)".
- Each trade idea MUST have the three sub-bullets (Entry / Exit / Why). Output is rejected if Entry/Exit markers are missing.
- The user sees a contract picker table below your output showing real bid/ask for the strikes you mention. Be consistent with what they'll see in that table.

Do not hedge with "this is not financial advice" or "consult a professional" boilerplate. Just write the analysis.
"""


def build_pinned_prompt(ticker: str, patterns: dict, key_numbers: dict,
                        contracts_summary: str | None = None) -> str:
    """Build the longer educational + recommendation prompt for the pinned card."""
    contracts_section = (
        f"\nAvailable contracts at the focus strike (from the picker table the user will see):\n{contracts_summary}\n"
        if contracts_summary else ""
    )
    return (
        PINNED_INSTRUCTION.format(ticker=ticker)
        + f"\n\nTicker: {ticker}\n"
        + f"Patterns:\n{json.dumps(patterns, indent=2, default=str)}\n"
        + f"Key numbers:\n{json.dumps(key_numbers, indent=2, default=str)}"
        + contracts_section
        + "\n\nWrite the walkthrough now."
    )


# ---------- Validator ----------

def validate_output(text: str, must_contain_numbers: list[float]) -> tuple[bool, str]:
    """Return (ok, reason_if_not_ok). Empty/NO_INSIGHT is the caller's job to detect."""
    if not text or not text.strip():
        return False, "empty output"
    # Mask numeric tokens (digits + decimal points + commas) so we don't
    # mis-count decimals inside numbers like 450.0 or 2,000,000 as sentence breaks
    masked = re.sub(r"\d[\d,\.]*", "N", text)
    sents = [s for s in re.split(r"[.!?]+", masked) if s.strip()]
    if len(sents) > 2:
        return False, f"too many sentences ({len(sents)})"
    m = FORBIDDEN_RE.search(text)
    if m:
        return False, f"prescriptive language: {m.group(0)}"
    if must_contain_numbers:
        text_nums = set()
        for tok in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", text):
            try:
                text_nums.add(float(tok.group(0).replace(",", "")))
            except ValueError:
                pass
        wanted = set(float(n) for n in must_contain_numbers if n is not None)
        if wanted and not (text_nums & wanted):
            return False, f"no required number found (wanted any of {sorted(wanted)})"
    return True, ""


# ---------- Deterministic fallback ----------

def fallback_summary(ticker: str, patterns: dict, key_numbers: dict) -> str:
    """Render a structured summary from the pattern dict + key numbers
    when Gemini is unavailable or its output gets rejected. Ugly but safe."""
    firing = []
    p = patterns or {}
    if p.get("pinning", {}).get("firing"):
        strike = p["pinning"]["note"].get("strike", "?")
        firing.append(f"pinning at {strike}")
    if p.get("gamma_squeeze", {}).get("firing"):
        direction = p["gamma_squeeze"]["note"].get("direction", "?")
        firing.append(f"gamma squeeze {direction}")
    if p.get("flow", {}).get("firing"):
        side = p["flow"]["note"].get("side", "?")
        net = p["flow"]["note"].get("net_premium_usd", 0)
        firing.append(f"flow {side} (${net/1e6:.1f}M net)")
    if p.get("vol_regime", {}).get("firing"):
        regime = p["vol_regime"]["note"].get("regime", "?")
        pts = p["vol_regime"]["note"].get("front_minus_30d_pts", "?")
        firing.append(f"vol {regime} (+{pts}pt front)")

    spot = key_numbers.get("spot") if key_numbers else None
    spot_str = f" Spot {spot:.2f}." if spot else ""
    if not firing:
        return f"{ticker} — no patterns firing.{spot_str}"
    return f"{ticker} — {', '.join(firing)}.{spot_str}".strip()


# ---------- Gemini call + orchestration ----------

def _get_gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            key = None
    if not key:
        try:
            import tomllib
            from pathlib import Path
            p = Path(".streamlit/secrets.toml")
            if p.exists():
                key = tomllib.loads(p.read_text(encoding="utf-8")).get("GEMINI_API_KEY")
        except Exception:
            key = None
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set (env var or Streamlit secrets)")
    return key


def _call_gemini(prompt: str) -> tuple[str, dict]:
    """Single Gemini call. Returns (text, usage_dict)."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=_get_gemini_key())
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=MAX_OUTPUT_TOKENS),
    )
    text = (resp.text or "").strip()
    usage = {}
    if hasattr(resp, "usage_metadata") and resp.usage_metadata:
        usage = {
            "input_tokens": getattr(resp.usage_metadata, "prompt_token_count", 0),
            "output_tokens": getattr(resp.usage_metadata, "candidates_token_count", 0),
        }
    return text, usage


def _substance_beats_fallback(synthesis: str, fallback: str) -> bool:
    """Heuristic: synthesis must be at least 70% as long AND have at least
    as many distinct numeric tokens as the fallback. Else prefer fallback."""
    def _nums(s: str) -> set:
        out = set()
        for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", s or ""):
            try:
                out.add(float(m.group(0).replace(",", "")))
            except ValueError:
                pass
        return out
    if not synthesis or not synthesis.strip():
        return False
    if len(synthesis) < len(fallback) * 0.7:
        return False
    if len(_nums(synthesis)) < len(_nums(fallback)):
        return False
    return True


def validate_pinned_output(text: str, must_contain_numbers: list[float],
                           min_numbers_cited: int = 4) -> tuple[bool, str]:
    """Pinned-card validator. NO prescriptive-language blocklist (the disclaimer
    covers that). Requires substantive numeric grounding, the four section
    headers, AND Entry/Exit markers in the trade-ideas section.

    Returns (ok, reason_if_not_ok)."""
    if not text or not text.strip():
        return False, "empty output"
    # Must contain all four section headers (markdown bold)
    required_headers = (
        "What the gamma chart shows",
        "What the OI",        # 'What the OI + flow data shows' — match prefix
        "What the vol regime shows",
        "Best contracts for the week",
    )
    missing = [h for h in required_headers if h not in text]
    if missing:
        return False, f"missing required section(s): {missing}"
    # Trade ideas must have actionable Entry/Exit framework, not just narrative.
    # Allow a clean "no setup" output to skip (it explicitly says no trade).
    contracts_section = text.split("Best contracts for the week", 1)[1] if "Best contracts for the week" in text else ""
    no_trade_signal = ("no high-conviction" in contracts_section.lower()
                       or "sit out" in contracts_section.lower()
                       or "no trade" in contracts_section.lower())
    if not no_trade_signal:
        if "Entry" not in contracts_section:
            return False, "trade ideas missing Entry/Exit framework (no 'Entry' marker found)"
        if "Exit" not in contracts_section:
            return False, "trade ideas missing Entry/Exit framework (no 'Exit' marker found)"
    # Count distinct numeric tokens in the output
    text_nums = set()
    for tok in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", text):
        try:
            text_nums.add(float(tok.group(0).replace(",", "")))
        except ValueError:
            pass
    if must_contain_numbers:
        wanted = set(float(n) for n in must_contain_numbers if n is not None)
        intersection = text_nums & wanted
        if len(intersection) < min(min_numbers_cited, len(wanted)):
            return False, (f"insufficient numeric grounding: cited {len(intersection)} "
                           f"of available {len(wanted)} payload numbers (need ≥{min_numbers_cited})")
    return True, ""


def fallback_pinned_summary(ticker: str, patterns: dict, key_numbers: dict) -> str:
    """Deterministic fallback for the pinned card when Gemini fails or its
    output is rejected. Same four-section format, no AI."""
    p = patterns or {}
    kn = key_numbers or {}
    spot = kn.get("spot")
    spot_str = f"{spot:.2f}" if spot else "?"
    max_pain = kn.get("max_pain")
    iv_rank = kn.get("iv_rank")
    dte = kn.get("dte")

    # Gamma section
    pin = p.get("pinning", {})
    sq = p.get("gamma_squeeze", {})
    if pin.get("firing"):
        strike = pin["note"].get("strike", "?")
        gamma_msg = (f"Dealer gamma is heavily concentrated at the **{strike}** strike "
                     f"(spot at {spot_str}). When dealers are long gamma at a strike near "
                     f"spot, their hedging activity tends to pin price toward that strike "
                     f"into expiry.")
    elif sq.get("firing"):
        direction = sq["note"].get("direction", "?")
        gamma_msg = (f"Dealer gamma asymmetry suggests a **squeeze {direction}** setup. "
                     f"Dealers are net short gamma on that side; if price crosses, they "
                     f"chase, amplifying the move.")
    else:
        gamma_msg = (f"No high-concentration gamma feature near spot {spot_str}. "
                     f"Dealer hedging pressure is balanced; expect mean-reverting behavior.")

    # Flow section
    flow = p.get("flow", {})
    if flow.get("firing"):
        side = flow["note"].get("side", "?")
        net = flow["note"].get("net_premium_usd", 0)
        dp = flow["note"].get("dp_alignment", "n/a")
        flow_msg = (f"Net options premium is **{side}** at ${net/1e6:+.1f}M. "
                    f"Dark pool alignment: **{dp}**. Aligned dark pool means the equity "
                    f"desk corroborates the options crowd; divergent means they disagree.")
    else:
        flow_msg = "Options flow is neutral — no large directional premium imbalance today."

    # Vol section
    vol = p.get("vol_regime", {})
    if vol.get("firing"):
        pts = vol["note"].get("front_minus_30d_pts", "?")
        vol_msg = (f"Front-week IV exceeds 30-day IV by **{pts} vol points** — the market "
                   f"is pricing an event-driven near-term catalyst (earnings, FOMC, news).")
    else:
        vol_msg = f"Vol term structure is normal. IV rank {iv_rank if iv_rank else '?'}."

    # Trade ideas section — straight from the firing patterns, with Entry/Exit
    # framework so the trader knows WHEN to act, not just WHAT to trade.
    ideas = []
    if pin.get("firing"):
        strike = pin["note"].get("strike", "?")
        ideas.append(
            f"- **Pinning Play (premium-selling)** — iron butterfly or short straddle centered on **{strike}** (front-week).\n"
            f"  - **Entry**: at the open if spot is within ${1.0:.0f} of {strike}; wait if spot is drifting away.\n"
            f"  - **Exit**: target 50% of max credit by Thursday; let expire worthless Friday if pin holds. Stop out if spot breaks ±1.5% from {strike} on momentum.\n"
            f"  - **Why**: dealer gamma concentration at {strike} tends to pull price back; premium-selling structures harvest the resulting time-decay."
        )
    if sq.get("firing"):
        direction = sq["note"].get("direction", "?")
        if direction == "up":
            ideas.append(
                f"- **Squeeze-Up Play** — OTM call above spot {spot_str} (front-week).\n"
                f"  - **Entry**: enter on a break above {spot_str} with volume confirmation; do NOT enter pre-break.\n"
                f"  - **Exit**: target +50% on the contract or trail a stop at the trigger level. Stop out if spot reverses back below the trigger.\n"
                f"  - **Why**: dealers are short gamma above spot; if price crosses, their hedging amplifies the move."
            )
        else:
            ideas.append(
                f"- **Squeeze-Down Play** — OTM put below spot {spot_str} (front-week).\n"
                f"  - **Entry**: enter on a break below {spot_str} with volume confirmation; do NOT pre-position.\n"
                f"  - **Exit**: target +50% on the contract or trail. Stop out if spot reclaims the trigger.\n"
                f"  - **Why**: dealers short gamma below spot — chase selling on a break amplifies the move down."
            )
    if flow.get("firing"):
        side = flow["note"].get("side", "?")
        if side == "long":
            ideas.append(
                f"- **Bullish Vertical** — call debit spread, front-week, ATM/+1 strike width.\n"
                f"  - **Entry**: at the open or on a minor pullback to a recent support; size to 1-2% of account.\n"
                f"  - **Exit**: target 50% of max value; stop out if flow flips short or dark pool turns divergent.\n"
                f"  - **Why**: net long options premium + dark-pool alignment suggests directional consensus — defined-risk vertical caps downside."
            )
        elif side == "short":
            ideas.append(
                f"- **Bearish Vertical** — put debit spread, front-week, ATM/-1 strike width.\n"
                f"  - **Entry**: at the open or on a minor bounce into resistance; size to 1-2% of account.\n"
                f"  - **Exit**: target 50% of max value; stop out if flow flips long or dark pool turns divergent.\n"
                f"  - **Why**: net short options premium + dark-pool alignment — defined-risk put spread captures the downside thesis."
            )
    if vol.get("firing"):
        ideas.append(
            f"- **IV Inversion Play** — front-week long calendar spread (sell front, buy 30-day) at-the-money.\n"
            f"  - **Entry**: at the open; the inversion is already pricing in, no waiting needed.\n"
            f"  - **Exit**: close before the catalyst event (don't hold through) — capture the IV crush in the front leg. Stop if back-month IV collapses too.\n"
            f"  - **Why**: front-week IV elevated vs 30-day means front decays faster than back — calendar exploits the differential."
        )
    if not ideas:
        ideas.append(
            f"- **No high-conviction setup this week.** Sit out or wait for a fresh catalyst.\n"
            f"  - **Entry**: N/A — no trade.\n"
            f"  - **Exit**: N/A.\n"
            f"  - **Why**: pattern detectors aren't firing strongly enough to anchor an entry; forcing a trade here would be noise."
        )

    return f"""**What the gamma chart shows**

{gamma_msg}

**What the OI + flow data shows**

{flow_msg}

**What the vol regime shows**

{vol_msg}

**Best contracts for the week**

{chr(10).join(ideas)}

_Front-week expiry: {dte} days out._ See the contracts table below for live bid/ask at the relevant strikes."""


def summarize_pinned(ticker: str, patterns: dict, key_numbers: dict,
                     contracts_summary: str | None = None) -> str:
    """Top-level pinned-card synthesis: build prompt → call Gemini → validate
    → fall back to deterministic template if needed. Always returns markdown."""
    must_contain: list[float] = []
    for v in (key_numbers or {}).values():
        if isinstance(v, (int, float)):
            must_contain.append(float(v))
    for p in (patterns or {}).values():
        for v in p.get("note", {}).values():
            if isinstance(v, (int, float)):
                must_contain.append(float(v))

    fallback = fallback_pinned_summary(ticker, patterns, key_numbers)

    try:
        text, usage = _call_gemini_pinned(
            build_pinned_prompt(ticker, patterns, key_numbers, contracts_summary)
        )
    except Exception as e:
        print(f"[synth-pinned] {ticker} fallback (Gemini error: {type(e).__name__})",
              file=sys.stderr)
        return fallback

    if usage:
        print(f"[synth-pinned] {ticker} in={usage.get('input_tokens',0)} "
              f"out={usage.get('output_tokens',0)}", file=sys.stderr)

    ok, reason = validate_pinned_output(text, must_contain_numbers=must_contain,
                                        min_numbers_cited=3)
    if not ok:
        print(f"[synth-pinned] {ticker} fallback (validator: {reason})", file=sys.stderr)
        return fallback

    return text


def _call_gemini_pinned(prompt: str) -> tuple[str, dict]:
    """Pinned-card call uses a higher max_output_tokens for the multi-paragraph
    walkthrough."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=_get_gemini_key())
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=MAX_OUTPUT_TOKENS_PINNED),
    )
    text = (resp.text or "").strip()
    usage = {}
    if hasattr(resp, "usage_metadata") and resp.usage_metadata:
        usage = {
            "input_tokens": getattr(resp.usage_metadata, "prompt_token_count", 0),
            "output_tokens": getattr(resp.usage_metadata, "candidates_token_count", 0),
        }
    return text, usage


def summarize(ticker: str, patterns: dict, key_numbers: dict) -> str:
    """Build prompt → call Gemini → validate → substance check vs fallback.
    Always returns a renderable string. Logs token usage to stderr."""
    must_contain: list[float] = []
    for v in (key_numbers or {}).values():
        if isinstance(v, (int, float)):
            must_contain.append(float(v))
    for p in (patterns or {}).values():
        for v in p.get("note", {}).values():
            if isinstance(v, (int, float)):
                must_contain.append(float(v))

    fallback = fallback_summary(ticker, patterns, key_numbers)

    try:
        text, usage = _call_gemini(build_prompt(ticker, patterns, key_numbers))
    except Exception as e:
        print(f"[synth] {ticker} fallback (Gemini error: {type(e).__name__})",
              file=sys.stderr)
        return fallback

    if usage:
        print(f"[synth] {ticker} in={usage.get('input_tokens',0)} "
              f"out={usage.get('output_tokens',0)}", file=sys.stderr)

    if text.strip().upper().startswith("NO_INSIGHT"):
        return fallback

    ok, reason = validate_output(text, must_contain_numbers=must_contain)
    if not ok:
        print(f"[synth] {ticker} fallback (validator: {reason})", file=sys.stderr)
        return fallback

    if not _substance_beats_fallback(text, fallback):
        print(f"[synth] {ticker} fallback (substance: synthesis not richer)",
              file=sys.stderr)
        return fallback

    return text
