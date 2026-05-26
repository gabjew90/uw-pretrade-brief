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
**Rejected:** API Advanced ($375/mo, 90-day lookback) — would relax the 30-day data window but isn't justified for a Sunday demo. Startup tier ($625/mo) — would unlock commercial use + redistribution but the operator's framing is personal-use decision-support.
**Knock-on:** CLAUDE.md updated. README license disclaimer still correct as written.

## 2026-05-26 — Investment disclaimer removed (recommendation framing retained)

**Decided:** Removed the top-of-app "⚠️ NOT INVESTMENT ADVICE" banner and the corresponding README disclaimer block. The pinned-card synthesis still names specific contracts as recommendations (that framing wasn't changed). The synth prompt's reference to the disclaimer ("the dashboard has a prominent disclaimer at the top of the page covering that") was reworded to just "don't hedge with boilerplate."
**Why:** Operator request after seeing the live UX. The recommendation framing alone is the legal-exposure surface; the disclaimer banner was the mitigation but the operator chose to drop it.
**Rejected:** Keeping the disclaimer (operator override). Replacing recommendations with structural-fit-only language (separate question; operator wants to keep recommendation framing).
**Trade-off to note for future-me:** The legal exposure surface for the project is now larger than the 2026-05-25 design contemplated. The recommendation language is still there; the mitigation isn't. If this gets shared widely, revisit.

## 2026-05-26 — Pinned card layout: synthesis inlined under each chart

**Decided:** Each pinned-card chart is now followed immediately by its synthesis section (gamma chart → "What the gamma chart shows", OI chart → "What the OI + flow data shows", IV chart → "What the vol regime shows"). The "Best contracts for the week" trade-ideas section is the conclusion at the bottom, above the contracts picker table.
**Why:** Operator request. Previous layout had all four synthesis sections at the top of the pinned card BEFORE the charts, forcing the reader to scroll between explanation and visual. Inlining puts the explanation with the visual it's explaining.
**Implementation:** `_split_pinned_synthesis()` helper in ticker_card.py parses the 4-section markdown into a dict. Render now interleaves chart + section instead of dumping all synthesis up front. Falls back to "all content goes in trades section" if parser finds no headers.
**Rejected:** Restructuring the Gemini prompt to return JSON with 4 fields directly — would require validator + cache + tests overhaul; parsing the existing markdown is cheaper and equally robust.

## 2026-05-25 — Two-tier synthesis: scan-row observational, pinned-card prescriptive

**Decided:** Synthesis is now TWO functions with different prompts and validators:
- `synth.summarize()` for scan-row headlines — unchanged: 1-2 sentences, observational, FORBIDDEN_RE blocks prescriptive language
- `synth.summarize_pinned()` (new) for pinned-card walkthrough — multi-paragraph markdown with four sections (gamma walkthrough, OI+flow walkthrough, vol walkthrough, **Best contracts for the week**). MAY name specific contracts. Validator drops the prescriptive-language blocklist but requires section headers + ≥3 numbers cited from payload.
**Why:** Operator pivoted to "tell users best options to trade" framing. Acknowledged the legal exposure (Investment Advisers Act considerations) and accepted it. To minimize liability surface: top-of-app `st.error` banner with full NOT INVESTMENT ADVICE disclaimer, README disclaimer at the top, pinned-synth prompt explicitly tells the model the disclaimer is already shown so it doesn't need to hedge.
**Rejected:** "Structural-fit only" middle interpretation (recommend trade STRUCTURES but not specific contracts) — operator chose the literal recommendation interpretation. Static "How to read this chart" educational panels — rejected in favor of AI-generated walkthrough that's contextual to the actual data shown.
**Knock-on:** CLAUDE.md "no predictions" rule rewritten to allow prescriptive language in the pinned synth specifically. README "What it is NOT" rewritten — no longer claims "no buy/sell calls."

## 2026-05-24 — GEX endpoint: spot-exposures/strike (NOT greek-exposure/strike)

**Decided:** Use `/api/stock/{ticker}/spot-exposures/strike` for net dealer gamma per strike. Parser computes `call_gamma_oi - put_gamma_oi` per row.
**Why:** UW's marketing example for "Gamma Exposure (GEX)" uses `spot-exposures/strike`, not `greek-exposure/strike`. The OpenAPI description confirms: spot-exposures is **dealer-positioning** gamma per strike — exactly the "GEX in trader speak" that our pinning + gamma-squeeze detectors model. Per UW's own framing: "Positive gamma → volatility suppressed (pinning), negative gamma → volatility amplified (squeeze)." That's the precise thesis the dashboard surfaces.
**Rejected:** `/api/stock/{ticker}/greek-exposure/strike` — returns per-contract Greeks (gamma + delta + charm + vanna) which would require additional aggregation to get to dealer positioning. spot-exposures gives us the dealer-positioning view directly.
**Knock-on:** Plan, uw_client, probe, fixture-recorder, conftest all updated to use the new path. Fixture filename: `uw_spot_exposures_strike_SPY.json` (the fixture-loader name stays `gex_strike_spy` since GEX is the conventional shorthand).

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
