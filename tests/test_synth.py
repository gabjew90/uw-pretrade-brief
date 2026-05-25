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
