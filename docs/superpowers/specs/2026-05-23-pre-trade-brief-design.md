# Weekly Options Pre-Trade Brief — Design Spec

**Date:** 2026-05-23
**Ship deadline:** 2026-05-24 (Sunday night)
**Project context:** See [CLAUDE.md](../../../CLAUDE.md) for permanent constraints, stack lock, and project rules. See [MEMORY.md](../../../MEMORY.md) for the running decision log.

---

## 1. Purpose

A Streamlit web app that scans a watchlist of ~15–30 tickers and shows, for each, which structural options-trade pattern is firing right now — pinning, gamma squeeze, flow conviction, or vol-regime setup — using Unusual Whales (UW) Basic-tier data and a small Gemini-generated headline summary per ticker.

**Decision moment**: a user opens the app, scans the watchlist for tickers exhibiting favorable structural conditions for a weekly options trade, then clicks one to see the supporting evidence (gamma profile chart, flow timeline, vol/skew snapshot, key strikes) in a pinned detail view.

**Out of scope (explicit):** trade signals, conviction scores, buy/sell calls, backtesting, multi-user features, real-time streaming, browser automation. See CLAUDE.md "always-true facts" for the full list.

---

## 2. Approach (chosen: A — single-page scan + pinned drill-down)

**Layout** (top → bottom on one Streamlit page — single layout, no breakpoints):

- **Sidebar**: comma-separated watchlist override input, "Refresh data" button, "Data as of HH:MM" indicator, session call-count display, "How this works" expander link, **"v0.1 calibration values" debug panel** showing the current pattern-detection thresholds (transparency: badges that "fire" are firing per these heuristics, not per a validated model).
- **Top: pinned ticker card** — empty by default with the prompt **"Tap a row below to see detailed analysis."** Auto-populates if the URL contains `?ticker=X`. When populated: AI synthesis at the top (1–2 sentences), then three charts stacked vertically (**net dealer gamma profile**, **open interest per strike** showing call/put walls and current spot, **IV term-structure**), then a small key-strikes table. An "Unpin" (✕) control clears the pinned card and removes the URL param. *(Note: flow timeline was swapped for OI-per-strike because the FLOW data is already conveyed in the row badge — the OI chart adds the structural-levels view that was missing.)*
- **Bottom: scan table** — 10 rows by default (user's fixed list trimmed + UW "hot today" leaders), with a "Load 10 more" button below revealing the next batch (cap at 30 total). Each row: a **source indicator** (📌 = user's fixed list, 🔥 = UW hot today), symbol, AI synthesis as the headline, pattern badges (per-pattern colored, non-firing patterns hidden, tooltip on each). Two-phase render: numerical badges paint in pass 1 as UW data arrives, AI synthesis text fills in per row in pass 2 as Gemini completes. Currently-pinned row gets a left-border accent. Click row → loads it into the pinned card; URL updates to `?ticker=X`.

**Approaches considered and rejected:**
- *B (multi-page app)*: cleaner long-term, but +30–50% build time risks the Sunday deadline; worse phone UX (context-loss on page switch).
- *D (hyper-compact, no drill-down)*: fastest to build, most phone-friendly, but inadequate for actually sizing a trade — would become frustrating in real use.

---

## 3. Architecture & module layout

```
UW_Project/
├── app.py                       # Streamlit entrypoint, layout, click→pin wiring
├── pyproject.toml + uv.lock     # deps via uv
├── requirements.txt             # uv-exported, committed for Streamlit Cloud
├── runtime.txt                  # "python-3.11"
├── .streamlit/
│   ├── config.toml              # dark theme, wide layout (committed)
│   └── secrets.toml             # UW_API_KEY, GEMINI_API_KEY (gitignored)
├── src/
│   ├── uw_client.py             # thin REST wrapper, returns typed dicts
│   ├── patterns.py              # pure: detect pin / gamma-squeeze / flow / vol-regime
│   ├── synth.py                 # Gemini call + cache + guardrails
│   ├── watchlist.py             # fixed list ∪ UW "hot today" merge
│   ├── charts.py                # Plotly figure builders
│   └── views/
│       ├── scan_table.py        # bottom scan table
│       └── ticker_card.py       # top pinned drill-down card
├── tests/
│   ├── fixtures/                # recorded UW JSON responses
│   ├── conftest.py              # fixture loaders + `live` marker
│   ├── test_uw_client.py
│   ├── test_patterns.py
│   ├── test_synth.py
│   ├── test_watchlist.py
│   ├── test_charts.py
│   └── test_live_schema.py      # @pytest.mark.live — schema-drift check
├── scripts/
│   ├── probe_uw.py              # manual: hit each endpoint once, print sample
│   ├── record_fixtures.py       # manual: refresh tests/fixtures/ from live
│   └── sync_requirements.sh     # uv export → requirements.txt
├── docs/superpowers/specs/      # this file lives here
├── CLAUDE.md, MEMORY.md
├── README.md                    # project overview
└── FUTURE_WORK.md               # scope-creep parking lot
```

**Layering**:

HTTP (`uw_client`) → pure analytics (`patterns`, `charts`) → AI (`synth`) → Streamlit (`app.py` + `views/`).

Streamlit lives only at the edge. Everything else is testable without it. `patterns.py` and `charts.py` are pure functions — input dict → output verdict or Plotly Figure. `synth.py` is pure-with-I/O — it makes a Gemini call but takes a fully-resolved input payload and returns a string; it does not fetch its own data.

**Why this layering**: keeps the AI synthesis and pattern detection isolated from the rendering layer, so we can iterate on prompts/thresholds without touching Streamlit, and we can test verdicts deterministically against recorded fixtures.

---

## 4. Data flow & caching

**Session lifecycle on a fresh page load:**

1. `watchlist.get_tickers()` → resolves `fixed_list ∪ uw_hot_today()`, deduped. First-pass cap: 10 (default visible batch). "Load 10 more" button extends the visible set in batches up to a hard cap of 30.
2. For each ticker, `uw_client` fetches five data shapes concurrently via `ThreadPoolExecutor`:
   - per-strike net dealer gamma (for gamma profile chart + pinning/squeeze detection)
   - per-strike open interest, calls + puts split (for OI chart + key-strikes table)
   - recent flow records (side, premium, time) — used only for the FLOW badge, not a chart
   - IV term-structure samples (for IV chart + vol-regime detection)
   - max-pain / key-strikes scalar (for the key-strikes table below the charts)
3. For each ticker, `patterns.detect_all(data)` → pure verdict dict:
   ```python
   {
     "pinning":       {"firing": True,  "strike": 450, "intensity": 0.8},
     "gamma_squeeze": {"firing": False, ...},
     "flow":          {"firing": True,  "side": "long", "premium_usd": 2_000_000},
     "vol_regime":    {"firing": False, "iv_rank": 28},
   }
   ```
4. For each ticker, `synth.summarize(ticker, patterns, key_numbers)` → 1–2 sentence headline string. Cached.
5. `scan_table.render(rows)` paints the bottom; row click → `st.session_state.pinned_ticker = ticker`.
6. If `pinned_ticker` is set, `ticker_card.render(ticker)` paints the top section using the same cached UW data + cached synthesis (no new Gemini call).

**Caching — three layers:**

| Layer | Tool | Key | TTL | Reason |
|---|---|---|---|---|
| UW responses | `@st.cache_data` | `(endpoint, ticker, expiry)` | 15 min | Respect rate limits; intraday data doesn't need real-time. |
| Pattern verdicts | `@st.cache_data` | `(ticker, sha1(uw_data))` | tied to UW | Pure; only re-run if data changed. |
| AI synthesis | `@st.cache_data` | `(ticker, sha1(patterns + key_numbers))` | 30 min | Gemini is the expensive call; re-synth only when inputs change. |

**Manual refresh**: sidebar "Refresh data" button calls `.clear()` on the UW-layer cached functions specifically (e.g. `uw_client.fetch_gamma.clear()`, etc.) — *not* the global `st.cache_data.clear()`. Patterns + synthesis caches re-derive automatically because their cache keys hash the freshly-fetched UW data and miss on the new hash.

**"Hot today" merge** (`watchlist.uw_hot_today`): pull top-N from UW's flow-alerts endpoint by unusual premium → top 15, union with user's fixed list, dedupe, cap at 30. Cached 15 min.

**Click-to-pin**: `st.dataframe(selection_mode="single-row", on_select="rerun")`; the selected ticker writes to `st.session_state.pinned_ticker` on rerun.

**Cost envelope (rough)**:
- UW: 10 tickers × 4 endpoints = 40 requests on initial cold load; +40 per "Load 10 more" batch (max 120 per session). Bounded by Basic-tier rate limits.
- Gemini: 10 syntheses on initial load (+10 per Load More batch); ~300 input tokens × ~80 output tokens each. Flash Lite pricing keeps this in cents per cycle.

**Two-phase render mechanics**: Pass 1 fetches UW data concurrently per ticker and renders the table with numerical badges + "Generating analysis…" placeholders in synthesis cells. Pass 2 dispatches Gemini calls per ticker on background workers (`concurrent.futures.ThreadPoolExecutor`), writes completed syntheses to `st.session_state[f"synth_{ticker}"]`, and triggers `st.rerun()` periodically (every 2s, up to 30s, or until all complete) so the table refills cells with completed text. Cache hits skip pass 2 entirely (synthesis text is already in cache).

---

## 4.5. User experience specification

UX-specific decisions, separated from the data-flow layer so they're easy to revisit without touching architecture.

### First-load behavior

- App loads with the default watchlist resolved (user's fixed list trimmed + UW "hot today" leaders, deduped, capped at 10 for the first batch).
- Scan table auto-renders. No "Start" button.
- Two-phase render: numerical badges appear immediately as UW data arrives (pass 1); AI synthesis fills in per row as Gemini completes (pass 2).
- During pass 1, a small progress indicator above the table reads `"Loaded X of 10 tickers."`
- Pinned card defaults to an empty state with the prompt: **"Tap a row below to see detailed analysis."**
- **Exception**: if the URL contains a `?ticker=NVDA` parameter (share link, refresh), the pinned card auto-loads that ticker.

### Click-to-pin interaction

- Click writes `st.session_state.pinned_ticker = ticker` AND updates the URL via `st.query_params["ticker"] = ticker`. Pinned card re-renders.
- Currently-pinned row gets a visual indicator: left-border accent.
- An "Unpin" (✕) control on the pinned card clears `pinned_ticker` and removes the URL param.
- Reload preserves the pin via URL persistence.
- Race condition: Streamlit's rerun model serializes interactions — clicking a second row while the first is loading cancels the first and renders the new ticker.

### Mobile layout

- **Single layout for all viewports** in the Sunday build. No breakpoints.
- Pinned card: three charts stack vertically, each full-width.
- Scan table renders via `st.dataframe` (responsive); on mobile, the dataframe scrolls horizontally. If real-device testing shows that's bad UX, fallback is a list of `st.container` blocks per row (logged for during-build evaluation).
- Sidebar collapses by default on mobile (Streamlit native behavior).
- "Desktop side-by-side chart layout" → `FUTURE_WORK.md`.

### Pattern badge semantics

- **One color per pattern category** — direction-agnostic patterns are not coerced into green/red:
  - **Pinning**: blue
  - **Gamma squeeze**: orange
  - **Flow**: green (net long) / red (net short) / gray (neutral)
  - **Vol regime**: purple
- **Color saturation encodes firing intensity**: `intensity ∈ [0, 1]` → opacity `∈ [0.3, 1.0]`.
- **Non-firing patterns are hidden, not greyed.** A row with only a pinning setup shows ONE blue badge, not four with three greyed out. Reduces visual noise on a 10–30 row table.
- **Every badge has a tooltip** explaining the pattern. Tooltip text lives in `src/badge_help.py` (centrally editable).
- **Accessibility**: badges always carry text labels (`PIN`, `Γ`, `FLOW`, `IVR`), not color alone. Saturation-as-intensity is supplementary. Colorblind users get the same information from the text label and the badge category.

### Staleness indicator

- Sidebar: **"UW data: refreshed HH:MM"** under the Refresh button.
- Each chart in the pinned card has a small footer: **"As of HH:MM"**.
- AI synthesis cells in the table have no per-cell staleness — implied by the watchlist-level indicator.

### Performance budget (targets, pending real measurement)

- **Cold load — badges visible**: ≤ 6 seconds for 10 tickers (4 concurrent endpoints × ~150 ms each + Streamlit overhead).
- **AI synthesis complete**: ≤ 15 seconds from initial load for all 10 syntheses.
- **Click-to-pin paint**: ≤ 2 seconds (data already cached).
- **"Load 10 more" batch**: ≤ 6 seconds for badges + ≤ 15 seconds for synthesis (same shape as cold load).
- If cold load exceeds 10 s in real conditions, drop default to 5 tickers and document the change in MEMORY.md.

### Empty / error states for the pinned card

- **All data for the ticker failed**: card shows `"Couldn't load data for {ticker}. Tap another row or refresh."` + a "Retry" button that re-runs the fetch for just that ticker.
- **One chart's data is missing** (e.g., no flow today): that chart renders a gray placeholder box with `"{Chart name}: no data for {ticker} today."` — other charts render normally. Card does not collapse.
- **Synthesis fell back to deterministic template**: render as normal — the template is acceptable user-facing content. No special UI indicator (currently).
- **Sparse data** (e.g., only 2 strikes of gamma): chart renders the 2 strikes plus a thin caption: `"Limited data ({n} strikes)."`

### "What am I looking at" affordance

- Page header (always visible): **"Weekly Options Pre-Trade Brief"**.
- Subtitle: **"Decision-support for personal weekly options trades. Not financial advice. Personal use only."**
- A **"How this works"** link in the sidebar opens an `st.expander` with a 1-screen explainer: the four patterns, what each badge means, what data sources feed the views.

### Demo path for the README screenshot

The screenshot in `README.md` is the project's primary visual. Specifying the capture path explicitly so it doesn't end up as "whatever was on screen":

1. Pick one ticker with all four patterns firing clearly — NVDA on a Friday usually qualifies.
2. Capture with that ticker pinned, scan table populated below with 8–10 tickers visible.
3. Crop to show: pinned card (synthesis + gamma chart visible) + first 4–5 rows of scan table.
4. Desktop browser at 1440×900 for the canonical hero image.
5. A second image: mobile view of the same state, for the "works on phone" implicit claim.

---

## 5. AI synthesis with Gemini

**Model**: `gemini-3.1-flash-lite` via the **`google-genai`** Python SDK (the new SDK, not legacy `google-generativeai`). Call pattern: `client.models.generate_content(model="gemini-3.1-flash-lite", contents=..., config=...)`.

**Prompt**: single combined prompt, ~400 tokens of instruction + per-call payload (ticker + patterns dict + key_numbers dict). No system/user split.

**Critical prompt rule (per post-review revision):** the synthesis must NOT restate badge values. Badges already show which patterns fire and the key numbers. The synthesis is required to add information the badges don't convey: cross-pattern tension (e.g. "strong bullish flow against a positive-gamma regime → fighting dealers"), context (e.g. "earnings tomorrow, vol elevated for that reason"), or a structural implication. If the model cannot produce non-restatement content, it MUST return the empty string — the deterministic fallback then renders instead.

**Caching note**: Gemini `CachedContent` has a 32K-token minimum prefix; our prompt is ~300 tokens, so Gemini context caching does not apply. Per-request cost stays at full Flash Lite rates. Mitigated by our own per-ticker output cache (see § 4).

**Guardrails** — in-prompt instruction + post-call validator:

| Rule | Enforcement |
|---|---|
| No prescriptive language ("buy", "sell", "should", "recommend") | In-prompt rule + regex blocklist on output → reject |
| No conviction scoring ("high probability", "likely to") | Same |
| Must cite ≥1 number from `key_numbers` payload | Validator: output must contain at least one number that appears in the payload |
| ≤ 2 sentences | `max_output_tokens=120` + post-call sentence-count check |

**Validation-failure path**: render a deterministic fallback template built from the pattern dict — e.g. `"NVDA — pinning setup at 1200 (dealer Γ +$45M). Flow neutral, IVR 62."` Ugly but safe and free.

**Cost guard**: per-session call counter in `st.session_state`. If it exceeds N (default 100), synthesis disables for the rest of the session and uses deterministic templates only. Hard ceiling against runaway loops.

**Open uncertainty (deferred to implementation, will document in MEMORY.md)**: exact per-token Flash Lite pricing wasn't in the doc page we fetched. Default cost-guard threshold may need to drop if Flash Lite is more expensive than assumed.

---

## 6. Error handling

Per-ticker isolation throughout. One ticker failing never breaks the whole scan.

| Failure | Behavior | Where handled |
|---|---|---|
| UW timeout (>10s) | Per-ticker: row shows `⚠ data unavailable`, skipped in ranking, no synth call | `uw_client.py` per-ticker try/except |
| UW 429 rate limit | Exponential backoff (1s/2s/4s), 3 retries, then mark unavailable | `uw_client.py` |
| UW 401/403 | Big red banner: "Check `UW_API_KEY` in Streamlit secrets." Halt scan. | `app.py` startup check |
| UW empty (low-volume, after-hours) | Row renders "no flow today" badge, no pattern detection | `patterns.py` |
| Gemini API error / timeout | Per-ticker: deterministic template fallback. Logged. | `synth.py` |
| Gemini content-filter block | Same as above + log `[BLOCKED]` for prompt review | `synth.py` |
| Gemini validator rejection | Deterministic template fallback. If >20% rejection rate in session → yellow banner. | `synth.py` |
| Missing secrets | Startup banner with config instructions + dev-only sample-data toggle | `app.py` startup |
| >50% of watchlist fails | Yellow banner: "UW data widely unavailable — check API status." Render whatever's available. | `app.py` post-fetch |

**Pinned-card render errors** — covered in § 4.5 "Empty / error states for the pinned card."

**Explicitly out of scope** (→ `FUTURE_WORK.md`): retry queues with persistence, error telemetry / Sentry, multi-LLM fallback.

---

## 7. Testing strategy

**Default**: fast, deterministic, fixture-based pytest. **Live API capabilities** exist as opt-in tools, not as the default test path.

**Three live capabilities, three purposes**:

| Capability | Purpose | When to run |
|---|---|---|
| `scripts/probe_uw.py SPY` | Sanity-check live UW connectivity, print status + sample per endpoint | Before each deploy. When debugging "is it me or UW?" |
| `pytest -m live` | Schema-drift detection — `test_live_schema.py` covers both UW (calls real endpoints, asserts response keys match fixture shape) and Gemini (one real call with a known payload, verifies output passes the validator: no prescriptive language, has a number, ≤2 sentences). | On demand. Weekly habit. After UW or Gemini announces an API/model change. |
| `scripts/record_fixtures.py NVDA SPY QQQ` | Refresh `tests/fixtures/` from live, timestamped filenames | When schema-drift test fails, or when adding a new ticker fixture |

**Conftest setup for the `live` marker**:

```python
# conftest.py
def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits real UW/Gemini; skipped by default")

def pytest_collection_modifyitems(config, items):
    if config.getoption("-m") != "live":
        skip_live = pytest.mark.skip(reason="live; run with `pytest -m live`")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)
```

Plain `pytest` → fixture tests only (fast). `pytest -m live` → live tests only.

**Coverage targets**:
- ✅ Pattern detection logic — highest-leverage; these verdicts drive the UI
- ✅ Synthesis prompt construction + validator + fallback template
- ✅ UW client response-shape parsing
- ✅ Watchlist merge / dedup / cap
- ✅ Chart builders return valid Plotly Figures (smoke)
- ⏸ Streamlit rendering — Streamlit's testing story is weak; verify manually in the live app
- ⏸ End-to-end click flows — no Playwright per CLAUDE.md

**Secrets in live tests**: helper reads from `.streamlit/secrets.toml` with env-var fallback (`UW_API_KEY`, `GEMINI_API_KEY`); skips with clear message if missing.

**Explicitly out of scope** (→ `FUTURE_WORK.md`): GitHub Actions / CI, scheduled schema-drift runs, coverage reporting, mutation testing.

---

## 8. Deploy & repo workflow

**Deploy target**: Streamlit Community Cloud (locked in MEMORY.md 2026-05-23).

**Deploy steps**:
1. Public GitHub repo (`UW_Project`).
2. Connect repo to share.streamlit.io → New app → point at `app.py`.
3. Add secrets in dashboard (TOML):
   ```toml
   UW_API_KEY = "..."
   GEMINI_API_KEY = "..."
   ```
4. Auto-redeploys on push to `main`. URL: `https://<repo-name>.streamlit.app`.

**uv → Streamlit Cloud bridge**: Cloud reads `requirements.txt`. Pre-push step:
```bash
uv export --no-hashes --no-dev -o requirements.txt
git add requirements.txt && git commit -m "sync requirements.txt"
```
Encapsulated in `scripts/sync_requirements.sh`. Optional pre-commit hook to regenerate when `pyproject.toml` changes.

**Python version**: `runtime.txt` at repo root contains `python-3.11`.

**Git workflow**: single `main` branch for Sunday. No PR workflow at this scale. Tag the demo commit `v0.1-demo` so the project link points at a known-good snapshot.

**README.md as project overview** (explicit deliverable for the demo):
- 1-paragraph what-it-does + live URL at top
- Screenshot
- "How it works" — 3–4 bullets on data → patterns → synthesis → UI pipeline
- "What it's NOT" — non-goals (no signals, personal-use license, decision-support only)
- "Stack" — Python, Streamlit, UW Basic, Gemini Flash Lite, uv
- "Run locally" — `uv sync` / set secrets / `streamlit run app.py`
- "Future work" — link to `FUTURE_WORK.md`

**Phone-workflow caveat**: the operator works from a phone (see `feedback-phone-workflow` memory). The GitHub repo creation and Streamlit Cloud connect steps require a browser click the agent cannot perform. The agent will set up everything to that point; the operator clicks "Deploy" from mobile browser.

**Out of scope for Sunday** (→ `FUTURE_WORK.md`): CI/CD beyond Streamlit Cloud's built-in auto-deploy, custom domain, multi-environment (staging vs prod), Docker, migration off Streamlit Cloud.

---

## 9. Open questions to resolve at implementation start

1. **Exact UW endpoint URLs and response schemas** for: per-strike net dealer gamma, flow records, IV term structure, key strikes, "hot today" / flow alerts. To be verified from UW API docs as the first implementation step.
2. **Pattern-detection thresholds** for each of the four theses (what gamma intensity counts as "firing pinning"? what IV rank counts as "vol elevated"?). Initial values are a guess; will be calibrated by running against real tickers during build.
3. **Gemini Flash Lite per-token pricing** for accurate cost-guard threshold. Verify on Google's pricing page and document in MEMORY.md.
4. **Fixed watchlist default**: what tickers seed the user's list before they override? Suggested starting set: SPY, QQQ, IWM, AAPL, NVDA, TSLA, META, AMZN, GOOGL, MSFT — confirm or override.

---

## 10. Success criteria for Sunday demo

**Technical**:
- Public Streamlit Cloud URL renders the scan view for 10 tickers (default batch) without per-page errors; "Load 10 more" extends correctly.
- Click-to-pin works on desktop AND on the operator's actual phone (real-device test, not browser-simulated).
- URL pin-persistence works: opening `?ticker=NVDA` auto-pins NVDA on cold load.
- Each ticker has an AI synthesis headline that passes the validator (or falls back gracefully to the deterministic template).
- Three drill-down charts render correctly for any pinned ticker, stacked vertically.
- The four pattern detectors all fire on at least one real ticker each (proves end-to-end wiring across the four theses).
- `pytest` (fixture-only) is green; `pytest -m live` passes against current UW + Gemini.
- GitHub repo is public, has a README with the live URL and a hero screenshot, and a `v0.1-demo` tag.

**Experiential**:
- **Real-use test**: operator opens the app on Sunday night for an actual planned weekly options trade. The brief surfaces ≥1 piece of structural information the operator didn't already know going in.
- **60-second stranger test**: a person who doesn't know the project context opens the live URL and can describe what the app does AND who it's for within 60 seconds, without explanation from the operator. If they can't, the "What am I looking at" affordance has failed and needs revision before sharing the link more widely.
