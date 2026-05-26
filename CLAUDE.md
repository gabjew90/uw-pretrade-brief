# CLAUDE.md

Source: Karpathy's 4 Rules for CLAUDE.md (via r/AIAgentsInAction). Reported to lift coding accuracy from 65% → 94%.

---

## Response style

Never open responses with filler phrases like "Great question!", "Of course!", "Certainly!", or similar warmups. Start every response with the actual answer. No preamble, no acknowledgment of the question.

Match response length to task complexity. Simple questions get direct, short answers. Complex tasks get full, detailed responses. Never pad responses with restatements of the question or closing sentences that repeat what you just said.

Before any significant task, show me 2-3 ways you could approach this work. Wait for me to choose before proceeding.

If you are uncertain about any fact, statistic, date, or piece of technical information: say so explicitly before including it. Never fill gaps in your knowledge with plausible-sounding information. When in doubt, say so.

---

## About me

_Intentionally omitted for now. Do not prompt me to fill this in — I'll add it when it becomes relevant._

---

## What I'm working on

- **Project name:** Weekly Options Pre-Trade Brief
- **One-line:** A dashboard that takes a ticker and tells you whether a planned weekly options trade is structurally favored, using Unusual Whales data on dealer positioning, volatility, flow, and key strike levels.
- **Goal:** Ship a working hosted demo by Sunday night (2026-05-24) that I actually use for my own weekly options trades. Deliverables: public URL, GitHub repo, short writeup explaining how it works.
- **Audience:**
  - Me, for my own weekly options trading.
  - Other weekly options traders, via self-hosting (open-source, MIT). They bring their own UW API key.
  - NOT a public hosted service — the live URL is the operator's personal-use demo only; other people use the repo by forking and deploying their own.
- **Stack context / constraints:**
  - Ship by Sunday night, 2026-05-24.
  - Budget: ~$150 for one month of UW API Basic, plus existing API spend.
  - UW Basic tier: 30-day data lookback, personal-use-only license, 120 req/min, 40k req/day.
  - Python + Streamlit on Streamlit Cloud; UW API + Google Gemini (`gemini-3.1-flash-lite`) for synthesis.
  - ~16–20 hours of focused build time across the weekend.
  - Decision-support framing only — never trade signals or predictions.
- **What to avoid:**
  - Trade signals, conviction rankings, or "buy this" calls.
  - Backtesting claims or promises of edge.
  - "Yet another flow alert wrapper" — must use cross-data joinability.
  - Leaning on commodity data (OHLC, basic news) instead of UW's differentiated endpoints.
  - Browser automation, scraping, screenshotting infrastructure.
  - Playwright or heavy testing tooling — fixture-based Python tests only.
  - Scope creep mid-build. New ideas go into a "future work" section.
  - Sharing infrastructure with the pulse bot's production setup.

Apply this context to every task. When something doesn't fit, flag it before proceeding.

---

## Writing style — always match this

- **Voice:** _[TBD]_
- **Sentence length preference:** _[TBD]_
- **Words I use:** _[TBD]_
- **Words I never use:** _[TBD]_
- **Format (prose or structured):** _[TBD]_

When writing anything on my behalf, match this exactly. Do not default to your own patterns.

---

## Behavior — guardrails

Only modify files, functions, and lines of code directly related to the current task. Do not refactor, rename, reorganize, reformat, or "improve" anything I did not explicitly ask you to change. If you notice something worth fixing elsewhere, mention it in a note at the end. Do not touch it. Ever.

Before making any change that significantly alters content I've already created (rewriting sections, removing paragraphs, restructuring flow, changing tone): stop. Describe exactly what you're about to change and why. Wait for my confirmation before proceeding.

Before deleting any file, overwriting existing code, dropping database records, or removing dependencies: stop. List exactly what will be affected. Ask for explicit confirmation. Only proceed after I say yes in the current message. "You mentioned this earlier" is not confirmation.

The following require explicit in-session confirmation, no exceptions: deploying or pushing to any environment, running migrations or schema changes, sending any external API call, executing any command with irreversible side effects. I must say yes in the current message.

After any coding task, end with:
- **Files changed** (list every file touched)
- **What was modified** (one line per file)
- **Files intentionally not touched**
- **Follow-up needed**

Never send, post, publish, share, or schedule anything on my behalf without my explicit confirmation in the current message. This includes emails, calendar invites, document shares, or any action outside this conversation. I must say yes in the current message.

For any task involving architecture decisions, debugging complex issues, or non-trivial features: work through the problem step by step before writing any code. Show your reasoning. Identify where you're uncertain. Then implement.

---

## Memory and session continuity

Maintain a file called **MEMORY.md** in this project. After any significant decision, add an entry:
- What was decided
- Why
- What was rejected and why

Read MEMORY.md at the start of every session. Never contradict a logged decision without flagging it first.

When I say "session end", "wrapping up", or "let's stop here": write a session summary to MEMORY.md. Include:
- Worked on
- Completed
- In progress
- Decisions made
- Next session priorities

Maintain a file called **ERRORS.md**. When an approach takes more than 2 attempts to work, log it:
- What didn't work
- What worked instead
- Note for next time

Check ERRORS.md before suggesting approaches to similar tasks.

---

## Always-true facts for this project

Apply these to every session without exception. If any task conflicts with one of these, flag it before proceeding.

- **Operator works from a phone — no local file access.** I cannot open, diff, or run files locally. After every file create/edit, paste the full content (or the diff for small edits) back into chat so I can read it. For anything that won't render in chat — screenshots, generated images, PDFs, long binary output — upload to **litterbox.catbox.moe** (72h) and give me the URL. Never assume I can "just open the file."
- **License framing:** UW API Basic tier is personal-use-only. No public endpoints that re-serve UW data to other users. Demo is decision-support for the operator only.
- **Data window:** 30-day lookback maximum (UW Basic tier cap). REST polling only — WebSocket streaming is included in the tier but intentionally NOT used in v0.1 to keep state model simple (decision-support framing doesn't need sub-minute updates).
- **Differentiation rule:** Every analytical view must lean on UW's differentiated, cross-joinable endpoints (dealer positioning, flow, gamma, volatility surface, key strikes). Do not substitute commodity data (OHLC, basic news headlines) as the centerpiece of a view.
- **No backtested edge claims, no win-rate stats, no past-performance promises.** The pinned-card synthesis MAY name specific trade structures + contracts that fit a firing pattern (operator-approved 2026-05-25, with a top-of-app NOT-INVESTMENT-ADVICE disclaimer). The SCAN-ROW synthesis stays observational only (no prescriptive language). Two-tier rule.
- **No browser automation:** No Playwright, Selenium, Puppeteer, scraping, or screenshotting infrastructure.
- **Testing scope:** Fixture-based Python tests as the default (pytest with recorded UW responses) — fast and deterministic. Live API calls are allowed where they make sense: manual probe scripts, a `pytest -m live` opt-in marker for schema-drift checks, and the fixture-recording script. What's ruled out is Playwright and other heavy E2E tooling.
- **Infra isolation:** This project must NOT share infrastructure, env vars, secrets, or deploy targets with the pulse bot's production setup. Separate Streamlit Cloud app, separate secrets store.
- **Scope discipline:** Anything that isn't required for the Sunday demo goes into a `FUTURE_WORK.md` section, not into the build.

---

## Tech stack

Always use these. Never suggest alternatives unless I ask.

- **Language:** Python 3.11+
- **Framework:** Streamlit
- **Hosting:** **Streamlit Cloud** (locked 2026-05-23). Streamlit Cloud reads `requirements.txt` at the repo root, so the uv lockfile must be exportable to `requirements.txt` before deploy.
- **External APIs:** Unusual Whales API (Basic tier), Google Gemini API — model `gemini-3.1-flash-lite` (for AI synthesis). SDK: `google-genai` (the new SDK, not the legacy `google-generativeai`). Secret name: `GEMINI_API_KEY`.
- **Package manager:** **uv** (locked 2026-05-23). Use `uv add` / `uv sync`; commit `pyproject.toml` and `uv.lock`. Generate `requirements.txt` via `uv export --no-hashes -o requirements.txt` for Streamlit Cloud compatibility.
- **Database / persistence:** None for the Sunday demo. If any becomes necessary, default to on-disk parquet for cached UW responses. Confirm before adding any persistence layer.
- **Testing:** pytest, fixture-based by default (recorded UW API responses). Live API calls are fine for manual probe scripts and an opt-in `-m live` marker. What's ruled out is Playwright and other heavy E2E tooling.
- **Styling:** Streamlit native components — no separate CSS framework unless I ask.

If something seems like the wrong tool, flag it. But use the defined stack unless I explicitly say otherwise.

---

## Extended thinking triggers

For questions involving system architecture, performance tradeoffs, database design, or long-term technical decisions: use extended thinking mode. Work through the problem step by step. Surface tradeoffs I haven't considered. Flag assumptions that might not hold at scale. Then give your recommendation.

---

## Karpathy's 4 Rules (core)

1. **Ask, don't assume.** If something is unclear, ask before writing a single line. Never make silent assumptions about intent, architecture, or requirements.

2. **Simplest solution first.** Always implement the simplest thing that could work. Do not add abstractions or flexibility that weren't explicitly requested.

3. **Don't touch unrelated code.** If a file or function is not directly part of the current task, do not modify it, even if you think it could be improved.

4. **Flag uncertainty explicitly.** If you are not confident about an approach or technical detail, say so before proceeding. Confidence without certainty causes more damage than admitting a gap.
