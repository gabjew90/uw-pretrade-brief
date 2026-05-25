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
MAX_OUTPUT_TOKENS = 120

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
