# Weekly Options Pre-Trade Brief

A Streamlit dashboard that scans a watchlist of 10–30 tickers and shows which structural options-trade pattern is firing on each right now — using Unusual Whales data on dealer positioning, dark pool prints, flow, and volatility.

**Open source** — MIT licensed. Each user runs it with their own Unusual Whales API key (see [Self-host](#self-host) below).

**Live demo:** https://uw-pretrade-brief.streamlit.app (operator's personal-use deployment; please don't load-test it)

[![Deploy to Streamlit Cloud](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://share.streamlit.io/deploy?repository=gabjew90%2Fuw-pretrade-brief&branch=main&mainModule=app.py)

---

## What it does

Each row in the scan tells you whether a ticker is currently exhibiting one of four structural setups for a weekly options trade:

- 🟦 **Pinning** — heavy net dealer gamma at a strike near spot → dealer hedging tends to pin price to that strike into expiry.
- 🟧 **Gamma squeeze** — dealers net SHORT gamma at strikes above (or below) spot → if price crosses, dealers chase, amplifying the move.
- 🟩/🟥 **Flow conviction** — net options premium directional and large; dark pool prints corroborate or contradict.
- 🟪 **Vol regime** — front-week IV elevated vs 30-day IV → market pricing an event-driven near-term catalyst.

Tap any row to see the supporting charts (net dealer gamma profile, open interest with call/put walls + max-pain, IV term structure) in a pinned card at the top.

Each row also has a **1–2 sentence AI headline** written by Gemini Flash Lite. The synthesis is constrained to add information beyond what the badges already show — it cites specific numbers, surfaces cross-pattern tensions, and is auto-rejected (falling back to a deterministic template) if it slips into prescriptive language.

## What it is NOT

- **Not a trade signal generator.** No "buy this" calls. No conviction scores. No predictions.
- **Not a backtester.** No claims of edge.
- **Not a journal.** Sessions don't persist; trade logging is intentionally not included.
- **Not multi-user.** The Unusual Whales API tier in use is licensed for personal use only.
- **Not real-time.** 30-day lookback maximum, REST polling, no WebSocket streaming.

## Demo / API usage notice

The live URL is intended for limited evaluation by the operator and a small audience. Unusual Whales' API Basic tier is licensed for **personal use only**. Heavy traffic against the live URL would exhaust the API quota and likely violate UW's terms. If you're evaluating the project, please run a few queries to get a feel for it and then explore the code.

## How it works

1. Resolves a watchlist by merging the user's fixed list (default 10 large-cap tickers + ETFs) with UW's "hot today" leaders, deduped and capped at 30.
2. For each ticker, concurrently fetches 8 UW endpoints: spot-exposures/strike, oi-per-strike, flow-alerts (per-ticker), volatility/term-structure, max-pain, darkpool, earnings, interpolated-iv.
3. Pure-function pattern detectors evaluate the four theses against tunable thresholds (visible in the sidebar's "v0.1 calibration values" panel).
4. Gemini Flash Lite writes a 1–2 sentence headline per ticker. Output passes a regex validator (no prescriptive language, must cite a number, ≤2 sentences). Substance check ensures the AI text materially beats the deterministic fallback — if not, the fallback renders.
5. Single-page Streamlit layout: pinned ticker card on top (empty until a row is clicked), scan table below. Click a row to pin; URL persists via `?ticker=X`.

## Stack

- **Python 3.11** + **Streamlit ≥1.35** (`width="stretch"` API)
- **uv** for dependency management (commits `pyproject.toml` + `uv.lock`; `requirements.txt` regenerated for Streamlit Cloud)
- **Plotly** charts (dark theme, vertical-stacking layout that works on desktop and mobile)
- **Unusual Whales API** (Basic tier — 120 req/min, 40k req/day, 30-day lookback, personal use)
- **Google Gemini** (`gemini-3.1-flash-lite`) via the new `google-genai` SDK

## Self-host

This project is open source under the MIT license. You can run your own instance — locally for personal use, or deployed to Streamlit Cloud for share-with-friends use. Either way you need your own UW API key (per UW's terms of service the API is licensed for personal use only; the code does not redistribute UW data, each user authenticates with their own key).

### Run locally

```bash
# 1. Clone
git clone https://github.com/gabjew90/uw-pretrade-brief.git
cd uw-pretrade-brief

# 2. Install dependencies (uv handles Python + venv automatically)
uv sync

# 3. Configure secrets
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml — paste YOUR UW_API_KEY and GEMINI_API_KEY

# 4. Run
uv run streamlit run app.py
```

Open <http://localhost:8501> in a browser.

### Deploy your own to Streamlit Cloud (free tier works)

1. Fork this repo on GitHub.
2. Go to <https://share.streamlit.io> → **Create app** → connect your fork → main file `app.py`.
3. **Advanced settings → Secrets** → paste your two keys:
   ```toml
   UW_API_KEY = "your-key"
   GEMINI_API_KEY = "your-key"
   ```
4. Deploy. ~2 minute build, then a live URL at `https://<your-app-name>.streamlit.app`.

### Where to get the API keys

- **Unusual Whales**: <https://unusualwhales.com/settings/api-dashboard> (requires a UW API subscription — Basic at $150/mo is sufficient and is what this project is tested against)
- **Google Gemini** (free): <https://aistudio.google.com/apikey>

## Testing

```bash
uv run pytest                # fixture-based (no network), ~92 tests, sub-2s
uv run pytest -m live        # opt-in live API schema-drift checks
```

Live sanity probe (hits each UW endpoint once with your real key):

```bash
uv run python scripts/probe_uw.py SPY
```

Re-record fixtures from live UW data:

```bash
uv run python scripts/record_fixtures.py SPY
```

## Project structure

```
src/
├── uw_client.py      # REST wrapper + response normalizers (8 endpoints)
├── patterns.py       # pure pattern detectors (pinning / squeeze / flow+darkpool / vol-regime)
├── synth.py          # Gemini prompt, validator, fallback, substance check
├── fetch.py          # cached concurrent orchestration
├── charts.py         # Plotly figure builders (gamma profile, OI, IV term structure)
├── watchlist.py      # ticker merge + dedup + cap
├── badge_help.py     # central per-pattern color + tooltip constants
└── views/
    ├── scan_table.py # bottom: clickable dataframe + badges
    └── ticker_card.py # top: synthesis + 3 charts + unpin
tests/
├── fixtures/         # recorded UW JSON (SPY snapshot)
├── conftest.py       # fixture loaders + live-marker skip logic
└── test_*.py         # 92 tests across all modules
scripts/
├── probe_uw.py       # manual live sanity check
├── record_fixtures.py
└── sync_requirements.sh
docs/superpowers/
├── specs/2026-05-23-pre-trade-brief-design.md
└── plans/2026-05-23-pre-trade-brief.md
```

## Future work

See [FUTURE_WORK.md](FUTURE_WORK.md) — intentional scope-deferrals for v0.2+.

## Design and decision log

- [docs/superpowers/specs/2026-05-23-pre-trade-brief-design.md](docs/superpowers/specs/2026-05-23-pre-trade-brief-design.md) — design spec (architecture, UX, error handling, success criteria)
- [docs/superpowers/plans/2026-05-23-pre-trade-brief.md](docs/superpowers/plans/2026-05-23-pre-trade-brief.md) — implementation plan (bite-sized TDD tasks)
- [MEMORY.md](MEMORY.md) — running decision log (why each architectural call was made + what was rejected)
- [CLAUDE.md](CLAUDE.md) — project rules + always-true facts

