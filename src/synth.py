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
MAX_OUTPUT_TOKENS = 120         # scan-row synthesis (tight)
MAX_OUTPUT_TOKENS_PINNED = 700  # pinned-card synthesis (multi-paragraph walkthrough + rec)

# Used by SCAN-ROW synthesis only. The pinned synthesis is allowed to use
# recommendation language because the user explicitly opted in with the
# top-of-app NOT-INVESTMENT-ADVICE disclaimer accepting the legal exposure.
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
# specific trades — the app carries a top-of-page NOT-INVESTMENT-ADVICE
# disclaimer and the operator explicitly accepted that legal framing.

PINNED_INSTRUCTION = """You are writing an educational walkthrough for an options trader who knows the basics (calls, puts, strikes, IV, DTE) but is NEW to Unusual Whales' specific data framings (Spot GEX, dealer gamma hedging, dark pool tick rule, IV term-structure inversion).

The reader is looking at three charts for {ticker} in the pinned card:
- Net dealer gamma exposure by strike (the "GEX" chart)
- Open interest per strike (calls above zero, puts mirrored below)
- IV term structure (implied vol per days-to-expiry)

YOUR JOB: write a structured walkthrough that:
1. Translates UW-specific concepts as you use them.
2. Walks through what each chart shows for THIS ticker right now.
3. Identifies the structural trade(s) the data favors AND names specific contracts (strike + side + expiry) that fit. The reader expects concrete trade ideas, not vague suggestions.

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
- 2-4 specific trade ideas. Each must include:
  - Trade structure (e.g., "ATM straddle", "30-delta call vertical", "short iron condor centered on 450")
  - Specific strikes + side(s) + DTE
  - One-sentence justification tied to the firing patterns above
- Order: most structurally-aligned trade first, alternative directional play second, lower-conviction or hedged-alternative third.
- If no patterns are firing strongly enough, say so: "No high-conviction structural setup this week — consider sitting out or waiting for a fresh catalyst." Don't manufacture a trade.

STRICT REQUIREMENTS:
- Cite at least 4 specific numbers from the payload (spot, max-pain, pin strike, flow $, IV, DTE, etc.).
- Stay grounded in the actual data shown — do not invent numbers.
- When naming a contract, use the format: "STRIKE call/put expiring YYYY-MM-DD" or just "STRIKE call/put (front-week)".
- The user sees a contract picker table below your output showing real bid/ask for the strikes you mention. Be consistent with what they'll see in that table.

Do not hedge with "this is not financial advice" or "consult a professional" — the dashboard has a prominent disclaimer at the top of the page covering that. Just write the analysis.
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
        for tok in re.finditer(r"-?\d[\d,\.]*", text):
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
        for m in re.finditer(r"-?\d[\d,\.]*", s or ""):
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
    covers that). Requires substantive numeric grounding and the four section
    headers from the prompt.

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
    # Count distinct numeric tokens in the output
    text_nums = set()
    for tok in re.finditer(r"-?\d[\d,\.]*", text):
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

    # Trade ideas section — straight from the firing patterns
    ideas = []
    if pin.get("firing"):
        strike = pin["note"].get("strike", "?")
        ideas.append(f"- **Short straddle or iron condor centered on {strike}** (front-week expiry). The pin favors range-bound premium-selling structures.")
    if sq.get("firing"):
        direction = sq["note"].get("direction", "?")
        if direction == "up":
            ideas.append(f"- **OTM call** at the first squeeze trigger above spot ({spot_str}). The structure amplifies if price crosses.")
        else:
            ideas.append(f"- **OTM put** below spot ({spot_str}). Squeeze-down setup amplifies on a break lower.")
    if flow.get("firing"):
        side = flow["note"].get("side", "?")
        if side == "long":
            ideas.append(f"- **Bullish vertical (call debit spread)** to ride the flow direction with defined risk.")
        elif side == "short":
            ideas.append(f"- **Bearish vertical (put debit spread)** to ride the flow direction with defined risk.")
    if vol.get("firing"):
        ideas.append(f"- **Front-week vertical or calendar spread** to exploit the IV inversion before the catalyst resolves.")
    if not ideas:
        ideas.append(f"- **No high-conviction structural setup this week.** Consider sitting out or waiting for a fresh catalyst.")

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
