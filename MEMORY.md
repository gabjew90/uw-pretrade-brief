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

## 2026-05-23 — UW tier verified against pricing page (Basic $150/mo confirmed)

**Decided:** Operator is on **API Basic** ($150/mo). 120 req/min, 40k req/day, 30-day lookback, personal-use-only. WebSockets included in tier but intentionally unused for v0.1 scope.
**Why:** Fetched https://unusualwhales.com/pricing?product=api via firecrawl after WebFetch couldn't render the JS table. Settled an open uncertainty: my CLAUDE.md framing of "no WebSocket" looked like a tier-limit but is actually a scope choice — corrected in CLAUDE.md to be honest about what the tier includes vs what we use.
**Rejected:** API Advanced ($375/mo, 90-day lookback) — would relax the 30-day data window but isn't justified for a Sunday demo. Startup tier ($625/mo) — would unlock commercial use + redistribution but the operator's framing is personal portfolio + decision-support.
**Knock-on:** CLAUDE.md updated. README license disclaimer still correct as written.

## 2026-05-23 — UW endpoint paths corrected via OpenAPI spec

**Decided:** Use these UW endpoints (verified in the OpenAPI YAML):
- `/api/stock/{ticker}/greek-exposure/strike` (NOT `gex-strike`)
- `/api/stock/{ticker}/oi-per-strike`
- `/api/option-trades/flow-alerts?ticker_symbol={ticker}&limit=N` (the per-ticker `/api/stock/{ticker}/flow-alerts` is DEPRECATED — UW directs you to the cross-ticker endpoint with a query filter)
- `/api/stock/{ticker}/volatility/term-structure`
- `/api/stock/{ticker}/max-pain`
- `/api/option-trades/flow-alerts?limit=15` (same endpoint, no ticker filter → cross-ticker hot today)
**Why:** Fetched the OpenAPI YAML from https://api.unusualwhales.com/api/openapi. Two of my guessed paths in the plan were wrong; the rest were correct. The deprecation of per-ticker flow-alerts collapses two `uw_client` functions into one parameterized one.
**Rejected:** Continuing with guessed paths and relying on the Phase 2 probe script to discover errors — works but wastes a build cycle.

## 2026-05-23 — Execution: inline on main, no worktree

**Decided:** Execute the implementation plan via `superpowers:executing-plans` (inline in the working session), working directly on the `main` branch. No git worktree.
**Why:** Project is single-developer, single-session ("we doing all today"); the operator works phone-only and the added path-juggling of a worktree would complicate the litterbox file-sharing workflow. Subagent-driven approach (originally chosen) was reconsidered: ~37 tasks × 3 subagents per task = orchestration overhead too high for a timeline-constrained build. Safety net = the spec/plan commit (`13ce75b`) is the rollback point if a task corrupts state (`git reset --hard 13ce75b`).
**Rejected:** Worktree (skill default) — added complexity not justified at this project size. Subagent-driven (operator's prior choice) — re-evaluated against orchestration cost; operator switched explicitly.

## 2026-05-23 — "About me" section deferred

**Decided:** Leave the "About me" section of CLAUDE.md intentionally blank for now.
**Why:** Operator says it's not relevant yet. Will add when it starts affecting how responses should be tuned.
**Rejected:** Filling with placeholder defaults — would create misleading context.
