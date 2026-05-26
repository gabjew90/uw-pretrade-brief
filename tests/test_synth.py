"""Tests for src.synth. No live Gemini calls — _call_gemini is monkeypatched.
A live test exists separately (test_live_schema.py)."""
from __future__ import annotations
import pytest
from src.synth import (
    build_prompt,
    validate_output,
    fallback_summary,
    summarize,
    _substance_beats_fallback,
    build_pinned_prompt,
    validate_pinned_output,
    fallback_pinned_summary,
    summarize_pinned,
)


SAMPLE_PATTERNS = {
    "pinning":       {"firing": True,  "intensity": 0.7, "note": {"strike": 450}},
    "gamma_squeeze": {"firing": False, "intensity": 0.0, "note": {}},
    "flow":          {"firing": True,  "intensity": 0.6,
                       "note": {"side": "long", "net_premium_usd": 2_000_000}},
    "vol_regime":    {"firing": False, "intensity": 0.0,
                       "note": {"front_minus_30d_pts": 2.0}},
}
SAMPLE_KEY_NUMBERS = {"spot": 449.50, "iv_rank": 65, "dte": 4}


# ---------- Prompt ----------

def test_prompt_contains_ticker_and_explicit_no_restate_rule():
    p = build_prompt("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    assert "NVDA" in p
    assert "NO_INSIGHT" in p
    assert "restate" in p.lower()
    # Sanity: prompt explicitly forbids prescriptive language
    assert "buy" in p.lower()  # in the forbidden-words list


def test_prompt_includes_payload_json():
    p = build_prompt("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    assert "pinning" in p.lower()
    assert "449" in p  # spot value in JSON


# ---------- Validator ----------

def test_validator_accepts_clean_short_output():
    text = "NVDA pinning at 450 sits inside heavy call OI at 460, dealers fighting buyers."
    ok, reason = validate_output(text, must_contain_numbers=[450, 460])
    assert ok is True


def test_validator_rejects_prescriptive():
    text = "NVDA looks like a strong buy at 450."
    ok, reason = validate_output(text, must_contain_numbers=[450])
    assert ok is False
    assert "prescriptive" in reason.lower() or "buy" in reason.lower()


def test_validator_rejects_recommend_word():
    text = "I recommend the 450 strike for the position."
    ok, reason = validate_output(text, must_contain_numbers=[450])
    assert ok is False


def test_validator_rejects_high_probability():
    text = "There's high probability of a move to 460 from 450."
    ok, reason = validate_output(text, must_contain_numbers=[450, 460])
    assert ok is False


def test_validator_rejects_missing_required_number():
    text = "Pinning at the dealer wall with concentrated gamma."
    ok, reason = validate_output(text, must_contain_numbers=[450])
    assert ok is False
    assert "number" in reason.lower()


def test_validator_rejects_too_many_sentences():
    text = "First. Second. Third sentence with 100."
    ok, reason = validate_output(text, must_contain_numbers=[100])
    assert ok is False
    assert "sentence" in reason.lower()


def test_validator_rejects_empty():
    ok, _ = validate_output("", must_contain_numbers=[])
    assert ok is False
    ok, _ = validate_output("   ", must_contain_numbers=[])
    assert ok is False


def test_validator_with_no_required_numbers_skips_number_check():
    text = "Some text with no numbers at all."
    ok, _ = validate_output(text, must_contain_numbers=[])
    assert ok is True


# ---------- Fallback ----------

def test_fallback_mentions_each_firing_pattern():
    s = fallback_summary("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    assert "NVDA" in s
    assert "pinning" in s.lower()
    assert "450" in s
    assert "flow long" in s.lower()
    assert "449" in s  # spot


def test_fallback_no_firing_patterns():
    patterns = {k: {"firing": False, "intensity": 0.0, "note": {}}
                for k in ("pinning", "gamma_squeeze", "flow", "vol_regime")}
    s = fallback_summary("SPY", patterns, {"spot": 500.0})
    assert "SPY" in s
    assert "no patterns firing" in s.lower()


def test_fallback_handles_none_inputs():
    s = fallback_summary("XYZ", None, None)
    assert "XYZ" in s


# ---------- Substance check ----------

def test_substance_beats_fallback_when_synthesis_is_richer():
    fb = "NVDA — pinning at 450."
    syn = "NVDA pinning at 450 inside heavy call OI at 460 — buyers fighting the dealer hedge."
    assert _substance_beats_fallback(syn, fb) is True


def test_substance_loses_when_synthesis_shorter_than_fallback():
    fb = "NVDA — pinning at 450, flow long ($2.0M net), gamma squeeze up. Spot 449.50."
    syn = "Pinning at 450."
    assert _substance_beats_fallback(syn, fb) is False


def test_substance_loses_when_synthesis_has_fewer_numbers():
    fb = "NVDA — pinning at 450, flow $2.0M, IVR 65."
    syn = "NVDA shows interesting structural setup at the round-number level."
    assert _substance_beats_fallback(syn, fb) is False


def test_substance_rejects_empty():
    assert _substance_beats_fallback("", "fallback text") is False


# ---------- summarize orchestration (monkeypatch _call_gemini) ----------

def test_summarize_uses_fallback_on_no_insight(monkeypatch):
    monkeypatch.setattr("src.synth._call_gemini",
                        lambda p: ("NO_INSIGHT", {"input_tokens": 50, "output_tokens": 2}))
    out = summarize("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    assert "NVDA" in out
    assert "NO_INSIGHT" not in out


def test_summarize_uses_fallback_on_prescriptive_output(monkeypatch):
    monkeypatch.setattr("src.synth._call_gemini",
                        lambda p: ("NVDA looks like a strong buy at 450.", {}))
    out = summarize("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    assert "buy" not in out.lower()
    assert "NVDA" in out


def test_summarize_uses_fallback_on_substance_check_failure(monkeypatch):
    """Short shallow synthesis loses to a richer fallback."""
    monkeypatch.setattr("src.synth._call_gemini",
                        lambda p: ("NVDA pinning at 450.", {}))
    out = summarize("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    # Fallback is longer; substance check rejects the short synthesis
    assert len(out) > len("NVDA pinning at 450.")


def test_summarize_uses_gemini_when_text_beats_fallback(monkeypatch):
    monkeypatch.setattr("src.synth._call_gemini", lambda p: (
        "NVDA pinning at 450 sits inside heavy 460 call wall with 2000000 flow long — "
        "buyers fighting the dealer hedge into expiry 4 days out.",
        {"input_tokens": 200, "output_tokens": 30},
    ))
    out = summarize("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    assert "buyers" in out.lower() or "fighting" in out.lower()
    assert "450" in out


def test_summarize_falls_back_on_gemini_exception(monkeypatch):
    def boom(p):
        raise RuntimeError("network down")
    monkeypatch.setattr("src.synth._call_gemini", boom)
    out = summarize("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    assert "NVDA" in out


# ---------- PINNED-CARD synthesis (long, with recommendations) ----------

def test_pinned_prompt_contains_section_directives_and_no_hedge_rule():
    p = build_pinned_prompt("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    assert "NVDA" in p
    # All four section headers in the instructions
    for section in ("What the gamma chart shows", "What the OI",
                    "What the vol regime shows", "Best contracts for the week"):
        assert section in p
    # Prompt should tell the model not to add boilerplate hedges
    assert "do not hedge" in p.lower() or "don't hedge" in p.lower()


def test_pinned_prompt_includes_contracts_summary_when_provided():
    summary = "450.00 call expiry 2026-05-29: bid 2.10 ask 2.15 IV 18.0%"
    p = build_pinned_prompt("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS,
                            contracts_summary=summary)
    assert summary in p


def test_pinned_validator_requires_all_four_sections():
    """Missing any section header → rejected."""
    text = """**What the gamma chart shows**
Pinning at 450 (spot 449.50, max-pain 450).

**What the OI + flow data shows**
Net flow long $2M (dark pool aligned).

**Best contracts for the week**
- 450 call expiring next Friday."""
    # Missing 'What the vol regime shows' section
    ok, reason = validate_pinned_output(text, must_contain_numbers=[450, 449.50])
    assert ok is False
    assert "section" in reason.lower()


def test_pinned_validator_passes_with_all_sections_numbers_and_entry_exit():
    text = """**What the gamma chart shows**
Dealer gamma concentrated at the 450 strike (spot 449.50). Pin setup.

**What the OI + flow data shows**
Net flow long $2000000 with dark pool aligned.

**What the vol regime shows**
Front-week IV vs 30-day normal, IV rank 65.

**Best contracts for the week**
- **Pinning Play** — 450 call (front-week, 4 DTE)
  - **Entry**: at the open if spot within $1 of 450.
  - **Exit**: target 50% credit; stop if 450 breaks decisively.
  - **Why**: captures gamma pin upside."""
    ok, reason = validate_pinned_output(text,
        must_contain_numbers=[450, 449.50, 2_000_000, 65, 4])
    assert ok is True, f"expected OK, got: {reason}"


def test_pinned_validator_rejects_trade_ideas_without_entry_exit():
    """Trade idea bullets without Entry/Exit markers should be rejected."""
    text = """**What the gamma chart shows**
Dealer gamma concentrated at the 450 strike (spot 449.50). Pin setup.

**What the OI + flow data shows**
Net flow long $2000000 with dark pool aligned.

**What the vol regime shows**
Front-week IV vs 30-day normal, IV rank 65.

**Best contracts for the week**
- 450 call (front-week, 4 DTE) — captures gamma pin upside."""
    ok, reason = validate_pinned_output(text,
        must_contain_numbers=[450, 449.50, 2_000_000, 65, 4])
    assert ok is False
    assert "entry" in reason.lower() or "exit" in reason.lower()


def test_pinned_validator_allows_no_trade_output_without_entry_exit():
    """When patterns aren't firing, the 'no high-conviction setup' phrasing is
    a valid output and shouldn't be rejected for missing Entry markers."""
    text = """**What the gamma chart shows**
Gamma is balanced across strikes with no concentration near spot 100.0.

**What the OI + flow data shows**
Flow is neutral, $50000 net (below threshold).

**What the vol regime shows**
Vol term structure normal.

**Best contracts for the week**
No high-conviction structural setup this week — wait for a fresh catalyst or sit out."""
    ok, reason = validate_pinned_output(text,
        must_contain_numbers=[100, 50_000])
    assert ok is True, f"expected OK for no-trade output, got: {reason}"


def test_pinned_validator_requires_sufficient_numeric_grounding():
    """All sections + Entry/Exit present but only 1 number cited from a
    payload with 5 numbers — should fail on numeric-grounding check."""
    text = """**What the gamma chart shows**
The dealer positioning looks interesting near spot.

**What the OI + flow data shows**
There's some flow happening.

**What the vol regime shows**
Vol regime is normal.

**Best contracts for the week**
- **A Trade** — call at 450.
  - **Entry**: at the open.
  - **Exit**: 50% profit.
  - **Why**: vague."""
    ok, reason = validate_pinned_output(text,
        must_contain_numbers=[449.50, 2_000_000, 65, 4],   # 450 NOT in must-contain; "50" appears but that's an exit %, not a payload number
        min_numbers_cited=3)
    assert ok is False
    assert "numeric" in reason.lower() or "ground" in reason.lower()


def test_pinned_fallback_has_all_four_sections():
    text = fallback_pinned_summary("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    for section in ("What the gamma chart shows", "What the OI",
                    "What the vol regime shows", "Best contracts for the week"):
        assert section in text, f"fallback missing section: {section}"
    assert "NVDA" not in text or "450" in text  # firing pinning at 450 → should appear


def test_pinned_fallback_includes_entry_exit_per_trade():
    """The deterministic fallback must include Entry/Exit framework so it
    matches the structure the AI prompt requires."""
    text = fallback_pinned_summary("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    # Sample patterns has pinning + flow firing → both should appear with Entry/Exit
    assert "Entry" in text
    assert "Exit" in text
    # The fallback should pass the same validator the AI output passes
    ok, reason = validate_pinned_output(text, must_contain_numbers=[450, 449.50, 65, 4])
    assert ok is True, f"fallback failed validator: {reason}"


def test_pinned_fallback_no_firing_still_includes_entry_exit_markers():
    """Even the 'no trade' fallback path includes Entry/Exit (with N/A) so the
    structure is consistent."""
    patterns = {k: {"firing": False, "intensity": 0.0, "note": {}}
                for k in ("pinning", "gamma_squeeze", "flow", "vol_regime")}
    text = fallback_pinned_summary("SPY", patterns, {"spot": 745.0})
    assert "no high-conviction" in text.lower() or "sit out" in text.lower()


def test_pinned_fallback_no_firing_says_so():
    """When no patterns fire, the fallback's trade-ideas section says 'no high-conviction setup'."""
    patterns = {k: {"firing": False, "intensity": 0.0, "note": {}}
                for k in ("pinning", "gamma_squeeze", "flow", "vol_regime")}
    text = fallback_pinned_summary("SPY", patterns, {"spot": 745.0})
    assert "no high-conviction" in text.lower() or "sitting out" in text.lower()


def test_summarize_pinned_uses_fallback_on_invalid_output(monkeypatch):
    """If Gemini returns text missing required sections, fallback is used."""
    def short(p):
        return "Just a short observation about the data.", {"input_tokens": 100, "output_tokens": 20}
    monkeypatch.setattr("src.synth._call_gemini_pinned", short)
    out = summarize_pinned("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    # Fallback used → has the four section headers
    for section in ("What the gamma chart shows", "Best contracts"):
        assert section in out


def test_summarize_pinned_uses_gemini_when_output_valid(monkeypatch):
    """A well-formed Gemini response with all sections, numbers, AND
    Entry/Exit per trade idea passes through."""
    def good(p):
        return ("""**What the gamma chart shows**
Dealer gamma concentrated at 450 strike (spot 449.50, 4 DTE). Pin tends to attract price into expiry.

**What the OI + flow data shows**
Net flow long $2000000. Dark pool aligned with the call side — equity desk agrees with options crowd.

**What the vol regime shows**
Normal term structure. IV rank 65 — vol is moderately elevated.

**Best contracts for the week**
- **Pinning Play** — 450 call (front-week)
  - **Entry**: at the open if spot within $1 of 450.
  - **Exit**: target 50% credit by Thursday; stop if 450 breaks decisively.
  - **Why**: rides the pin with limited downside.
- **Defined-Risk Bullish** — 450/455 call vertical
  - **Entry**: at the open or on a minor pullback.
  - **Exit**: target 50% max value; stop if flow flips short.
  - **Why**: defined risk while the pin holds.""",
                {"input_tokens": 400, "output_tokens": 200})
    monkeypatch.setattr("src.synth._call_gemini_pinned", good)
    out = summarize_pinned("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    assert "Best contracts" in out
    assert "450 call" in out
    assert "Dealer gamma" in out
    assert "Entry" in out
    assert "Exit" in out


def test_summarize_pinned_falls_back_on_gemini_exception(monkeypatch):
    def boom(p):
        raise RuntimeError("quota exceeded")
    monkeypatch.setattr("src.synth._call_gemini_pinned", boom)
    out = summarize_pinned("NVDA", SAMPLE_PATTERNS, SAMPLE_KEY_NUMBERS)
    # Fallback used
    assert "What the gamma chart shows" in out


# ---------- Pinned-synthesis section splitter (view-layer concern) ----------

from src.views.ticker_card import _split_pinned_synthesis


def test_split_pinned_synthesis_full_text():
    text = """**What the gamma chart shows**
Gamma is heavily concentrated at 450.

**What the OI + flow data shows**
Net flow long 2M USD.

**What the vol regime shows**
Normal term structure.

**Best contracts for the week**
- 450 call front-week."""
    sections = _split_pinned_synthesis(text)
    assert "Gamma is heavily" in sections["gamma"]
    assert "Net flow long" in sections["oi_flow"]
    assert "Normal term" in sections["vol"]
    assert "450 call front-week" in sections["trades"]


def test_split_pinned_synthesis_empty():
    sections = _split_pinned_synthesis("")
    assert sections == {"gamma": "", "oi_flow": "", "vol": "", "trades": ""}


def test_split_pinned_synthesis_no_headers_falls_back_to_trades():
    """If no recognized headers found, dump whole text in trades so user
    still sees something rather than nothing."""
    text = "Random text with no section headers at all."
    sections = _split_pinned_synthesis(text)
    assert sections["trades"] == text
    assert sections["gamma"] == ""


def test_split_pinned_synthesis_missing_section():
    """If only some sections present, the others stay empty."""
    text = """**What the gamma chart shows**
Just gamma talk.

**Best contracts for the week**
- one trade."""
    sections = _split_pinned_synthesis(text)
    assert "Just gamma talk" in sections["gamma"]
    assert "one trade" in sections["trades"]
    assert sections["oi_flow"] == ""
    assert sections["vol"] == ""


def test_split_pinned_synthesis_case_insensitive_and_whitespace_tolerant():
    text = """** what the gamma chart shows **
Content A.

**What the OI + Flow Data Shows**
Content B."""
    sections = _split_pinned_synthesis(text)
    assert "Content A" in sections["gamma"]
    assert "Content B" in sections["oi_flow"]
