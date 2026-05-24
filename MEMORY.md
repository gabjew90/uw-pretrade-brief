# MEMORY.md

Project decision log for the Weekly Options Pre-Trade Brief.
Read at session start. Never contradict a logged decision without flagging it first.

---

## 2026-05-23 — Hosting: Streamlit Cloud

**Decided:** Deploy to Streamlit Cloud.
**Why:** Free tier, zero infra to manage, fastest path to a public URL before the Sunday 2026-05-24 deadline. Native fit for a Streamlit app.
**Rejected:** Railway. Reason: would duplicate the pulse bot's hosting context and add deploy complexity (Dockerfile / Procfile) we don't need for a single-page Streamlit demo. Infra-isolation rule is easier to satisfy on a separate platform.

## 2026-05-23 — Package manager: uv

**Decided:** Use uv. Commit `pyproject.toml` and `uv.lock`. Generate `requirements.txt` via `uv export --no-hashes -o requirements.txt` before deploy (Streamlit Cloud reads `requirements.txt`).
**Why:** Fast resolves and installs, single tool for venv + deps, modern default. Time-to-build matters this weekend.
**Rejected:** pip + raw `requirements.txt` (no lockfile, reproducibility risk). Poetry (slower, heavier than needed for a 2-day project).

## 2026-05-23 — LLM provider: Gemini Flash Lite (not Anthropic)

**Decided:** Use Google Gemini `gemini-3.1-flash-lite` for AI synthesis, via the `google-genai` SDK. Secret: `GEMINI_API_KEY`.
**Why:** User-elected swap from the original Anthropic plan during brainstorming. Rationale not stated by user — likely cost (Flash Lite is the cheapest tier in Gemini's lineup) and/or already holds a Gemini key. Verify and capture rationale next session.
**Rejected:** Claude Haiku 4.5. Reason: user override. Haiku would have been the natural pick on the Anthropic side, with prompt-caching savings on a static system block. Gemini context caching has a 32K-token minimum that our small system prompt won't hit, so caching savings don't transfer — but Flash Lite per-token pricing is low enough that this likely doesn't matter at 15–30 syntheses per cycle.
**Knock-on changes:** Updated CLAUDE.md (constraints + tech stack lines). Source files will use `google-genai` not `anthropic`. Streamlit Cloud secret renamed from `ANTHROPIC_API_KEY` to `GEMINI_API_KEY`.

## 2026-05-23 — "About me" section deferred

**Decided:** Leave the "About me" section of CLAUDE.md intentionally blank for now.
**Why:** Operator says it's not relevant yet. Will add when it starts affecting how responses should be tuned.
**Rejected:** Filling with placeholder defaults — would create misleading context.
