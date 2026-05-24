# Weekly Options Pre-Trade Brief — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Streamlit dashboard for personal weekly-options decision-support using Unusual Whales (UW) Basic-tier data and Gemini Flash Lite synthesis, deployed to Streamlit Cloud, by the 2026-05-24 deadline.

**Architecture:** Single-page Streamlit app with a bottom scan table (10 default, +10 via "Load more", cap 30) and a top pinned ticker card. Layered: HTTP (`uw_client`) → pure analytics (`patterns`, `charts`) → AI (`synth`) → Streamlit (`app.py` + `views/`). UI lives only at the edge; pure modules are tested against recorded UW fixtures.

**Tech Stack:** Python 3.11, Streamlit ≥1.35, `uv` package manager, Google Gemini `gemini-3.1-flash-lite` via the `google-genai` SDK, Unusual Whales API Basic tier, Plotly charts, pytest with fixture-based tests + opt-in live marker.

**Source of truth:** the design spec at [`docs/superpowers/specs/2026-05-23-pre-trade-brief-design.md`](../specs/2026-05-23-pre-trade-brief-design.md). If a step conflicts with the spec, the spec wins — update the plan in place.

**Operator note:** the operator works phone-only. After every meaningful artifact change, paste content into chat or upload to litterbox (`curl -F "reqtype=fileupload" -F "time=72h" -F "fileToUpload=@PATH" https://litterbox.catbox.moe/resources/internals/api.php`). The curl allow rule is already in `.claude/settings.local.json`.

---

## Phase 0: Pre-flight verification (~30 min)

Verify external dependencies before sinking hours into build. Each is a 5-minute check; if any fails, fix before proceeding.

### Task 0.1: Verify uv is installed and works

**Files:** none (environment check)

- [ ] **Step 1: Check uv version**

Run: `uv --version`
Expected: prints a version string ≥ `0.4.0`. If "command not found", install via `pip install uv` or `winget install astral-sh.uv`.

- [ ] **Step 2: Verify Python 3.11 available to uv**

Run: `uv python list`
Expected: lists at least one CPython 3.11.x entry. If none, run `uv python install 3.11`.

### Task 0.2: Verify Streamlit row-selection API

**Files:**
- Create (temporary): `_smoke_streamlit.py`

- [ ] **Step 1: Write smoke script**

Write to `_smoke_streamlit.py`:
```python
import streamlit as st
import pandas as pd

st.set_page_config(page_title="smoke", layout="wide")
st.write("Streamlit version:", st.__version__)

df = pd.DataFrame({"ticker": ["SPY", "QQQ", "NVDA"], "v": [1, 2, 3]})
event = st.dataframe(
    df,
    key="smoke",
    on_select="rerun",
    selection_mode="single-row",
)
st.write("Selection event:", event.selection)

st.query_params["ticker"] = "SPY"
st.write("Query params:", dict(st.query_params))
```

- [ ] **Step 2: Run it**

Run (in a separate terminal so the agent can keep working): `uv run streamlit run _smoke_streamlit.py --server.headless true --server.port 8765`
Expected: app starts; visit `http://localhost:8765`; clicking a row prints `Selection(rows=[N])` and the URL gains `?ticker=SPY`.

- [ ] **Step 3: If API differs, document workaround**

If `on_select="rerun"` errors (older Streamlit), append a note to `MEMORY.md` recording the actual installed version and the workaround used (e.g., upgrading the streamlit pin in `pyproject.toml`).

- [ ] **Step 4: Stop the smoke app and delete the file**

Stop the streamlit process. Then:
```bash
rm _smoke_streamlit.py
```

- [ ] **Step 5: Commit (only if MEMORY.md was updated)**

If no MEMORY.md edits were needed, skip. Otherwise:
```bash
git add MEMORY.md
git commit -m "docs: record Streamlit version constraint from smoke check"
```

### Task 0.3: Verify google-genai SDK and the exact model string

**Files:**
- Create (temporary): `_smoke_gemini.py`

- [ ] **Step 1: Set Gemini API key as env var (operator action)**

Operator: get a Gemini API key from https://aistudio.google.com/apikey and export it:
```bash
export GEMINI_API_KEY="..."        # PowerShell: $env:GEMINI_API_KEY = "..."
```

- [ ] **Step 2: Write smoke script**

Write to `_smoke_gemini.py`:
```python
import os
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
resp = client.models.generate_content(
    model="gemini-3.1-flash-lite",
    contents="Say only the word OK and nothing else.",
)
print("RESPONSE:", repr(resp.text))
```

- [ ] **Step 3: Run it**

Run: `uv run python _smoke_gemini.py`
Expected: prints `RESPONSE: 'OK'` (or `'OK.'`).

If the model name 404s, fetch https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite to verify the exact identifier and update accordingly. Document the corrected name in MEMORY.md.

- [ ] **Step 4: Delete smoke file**

```bash
rm _smoke_gemini.py
```

### Task 0.4: Verify UW API key works

**Files:**
- Create (temporary): `_smoke_uw.py`

- [ ] **Step 1: Set UW API key**

```bash
export UW_API_KEY="..."        # PowerShell: $env:UW_API_KEY = "..."
```

- [ ] **Step 2: Write smoke script**

Write to `_smoke_uw.py`:
```python
import os
import requests

key = os.environ["UW_API_KEY"]
url = "https://api.unusualwhales.com/api/stock/SPY/option-contracts"
r = requests.get(url, headers={"Accept": "application/json", "Authorization": f"Bearer {key}"}, timeout=10)
print("STATUS:", r.status_code)
print("BODY (first 400 chars):", r.text[:400])
```

- [ ] **Step 3: Run it**

Run: `uv run python _smoke_uw.py`
Expected: STATUS 200, body shows JSON with option-contract data. If 401/403, the key is invalid or the endpoint requires a different auth header — try `X-API-Key` or `api_key` query param.

- [ ] **Step 4: Delete smoke file**

```bash
rm _smoke_uw.py
```

Pre-flight done. Three secrets confirmed working: `UW_API_KEY`, `GEMINI_API_KEY`. Streamlit and Gemini SDKs verified.

---

## Phase 1: Project bootstrap (~30 min)

### Task 1.1: Initialize `pyproject.toml`

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`

- [ ] **Step 1: Init uv project**

Run: `uv init --python 3.11 --no-readme --no-pin-python --bare`
Expected: creates `pyproject.toml` skeleton.

- [ ] **Step 2: Replace pyproject.toml with the proper version**

Overwrite `pyproject.toml` with:
```toml
[project]
name = "uw-pretrade-brief"
version = "0.1.0"
description = "Weekly options decision-support dashboard using Unusual Whales data + Gemini synthesis"
requires-python = ">=3.11,<3.12"
dependencies = [
    "streamlit>=1.35.0",
    "requests>=2.31.0",
    "plotly>=5.18.0",
    "pandas>=2.1.0",
    "google-genai>=0.3.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-mock>=3.12.0",
    "responses>=0.24.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "live: hits real UW/Gemini APIs; skipped by default",
]
```

- [ ] **Step 3: Write `.python-version`**

Write to `.python-version`:
```
3.11
```

- [ ] **Step 4: Sync deps**

Run: `uv sync`
Expected: `.venv/` is created, `uv.lock` is generated.

- [ ] **Step 5: Verify install**

Run: `uv run python -c "import streamlit, plotly, pandas, requests; from google import genai; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version
git commit -m "feat: bootstrap uv project with core deps"
```

### Task 1.2: Streamlit config and secrets template

**Files:**
- Create: `.streamlit/config.toml`
- Create: `.streamlit/secrets.toml.example`
- Create: `runtime.txt`

- [ ] **Step 1: Write `.streamlit/config.toml`**

```toml
[theme]
base = "dark"
primaryColor = "#7AA2F7"
backgroundColor = "#0E1117"
secondaryBackgroundColor = "#1A1E26"
textColor = "#E6E6E6"
font = "sans serif"

[server]
headless = true

[browser]
gatherUsageStats = false
```

- [ ] **Step 2: Write `.streamlit/secrets.toml.example`**

```toml
# Copy to .streamlit/secrets.toml (gitignored) and fill in real values.
UW_API_KEY = "your-unusual-whales-api-key"
GEMINI_API_KEY = "your-google-gemini-api-key"
```

- [ ] **Step 3: Write `runtime.txt`**

```
python-3.11
```

- [ ] **Step 4: Create local `.streamlit/secrets.toml` for development**

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Then edit `.streamlit/secrets.toml` to fill in the real keys (operator: do this once).

- [ ] **Step 5: Verify secrets.toml is gitignored**

Run: `git check-ignore .streamlit/secrets.toml`
Expected: prints `.streamlit/secrets.toml` (i.e., it IS ignored).

- [ ] **Step 6: Commit**

```bash
git add .streamlit/config.toml .streamlit/secrets.toml.example runtime.txt
git commit -m "feat: Streamlit config, secrets template, runtime pin"
```

### Task 1.3: Scripts directory + `sync_requirements.sh`

**Files:**
- Create: `scripts/sync_requirements.sh`

- [ ] **Step 1: Write the sync script**

Write to `scripts/sync_requirements.sh`:
```bash
#!/usr/bin/env bash
# Regenerate requirements.txt from uv state for Streamlit Cloud.
set -euo pipefail
uv export --no-hashes --no-dev --format requirements-txt -o requirements.txt
echo "Wrote requirements.txt"
```

- [ ] **Step 2: Make it executable (Git Bash on Windows)**

Run: `chmod +x scripts/sync_requirements.sh`

- [ ] **Step 3: Run it once**

Run: `bash scripts/sync_requirements.sh`
Expected: creates `requirements.txt` at repo root.

- [ ] **Step 4: Commit**

```bash
git add scripts/sync_requirements.sh requirements.txt
git commit -m "feat: requirements.txt sync script for Streamlit Cloud"
```

### Task 1.4: Skeleton package directories with `__init__.py` stubs

**Files:**
- Create: `src/__init__.py`
- Create: `src/views/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/.gitkeep`

- [ ] **Step 1: Create empty package files**

```bash
mkdir -p src/views tests/fixtures
touch src/__init__.py src/views/__init__.py tests/__init__.py tests/fixtures/.gitkeep
```

- [ ] **Step 2: Verify pytest discovers the tests dir (and finds nothing yet)**

Run: `uv run pytest -q`
Expected: `no tests ran in 0.XXs`.

- [ ] **Step 3: Commit**

```bash
git add src tests
git commit -m "chore: package skeleton"
```

---

## Phase 2: UW client + fixture recording (~2 hr)

### Task 2.1: Skeleton `src/uw_client.py` with auth + one endpoint

**Files:**
- Create: `src/uw_client.py`

- [ ] **Step 1: Write the client**

Write to `src/uw_client.py`:
```python
"""Thin REST wrapper for Unusual Whales (Basic tier).

Endpoint paths verified against the OpenAPI spec at
https://api.unusualwhales.com/api/openapi (2026-05-23). All methods raise
UWError on non-2xx so per-ticker callers can isolate failures.

Tier (Basic): 120 req/min, 40k req/day, 30-day lookback, personal-use-only.
"""
from __future__ import annotations
import os
from typing import Any
import requests

BASE = "https://api.unusualwhales.com"
TIMEOUT_S = 10


class UWError(RuntimeError):
    """Raised when a UW API call fails (network, auth, or non-2xx)."""


def _get_key() -> str:
    key = os.environ.get("UW_API_KEY")
    if not key:
        # Streamlit secrets fallback (lazy import to keep this module CLI-runnable)
        try:
            import streamlit as st
            key = st.secrets.get("UW_API_KEY")
        except Exception:
            key = None
    if not key:
        raise UWError("UW_API_KEY not set (env var or Streamlit secrets)")
    return key


def _get(path: str, params: dict | None = None) -> Any:
    url = f"{BASE}{path}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {_get_key()}",
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise UWError(f"network error calling {path}: {e}") from e
    if r.status_code == 429:
        raise UWError(f"429 rate limited on {path}")
    if not r.ok:
        raise UWError(f"{r.status_code} on {path}: {r.text[:200]}")
    return r.json()


def fetch_spot_exposures_strike(ticker: str) -> dict:
    """Per-strike Spot GEX — dealer-positioning gamma per strike, the canonical
    'GEX' that drives pinning + gamma squeeze analysis. Returns directional
    fields (call_gamma_oi, put_gamma_oi, *_ask, *_bid). Use OI-based for net
    dealer positioning."""
    return _get(f"/api/stock/{ticker}/spot-exposures/strike")


def fetch_flow_alerts(ticker: str | None = None, limit: int = 50) -> dict:
    """Recent flow alerts. If ticker is provided, filtered to that ticker;
    otherwise returns cross-ticker (used for 'hot today' discovery).

    NOTE: the per-ticker `/api/stock/{ticker}/flow-alerts` endpoint is
    deprecated by UW; both per-ticker and cross-ticker uses go through
    this single endpoint, parameterized."""
    params: dict = {"limit": limit}
    if ticker:
        params["ticker_symbol"] = ticker
    return _get("/api/option-trades/flow-alerts", params=params)


def fetch_volatility(ticker: str) -> dict:
    """Volatility term structure / IV samples for the ticker."""
    return _get(f"/api/stock/{ticker}/volatility/term-structure")


def fetch_max_pain(ticker: str) -> dict:
    """Max pain / key strikes for the ticker."""
    return _get(f"/api/stock/{ticker}/max-pain")
```

- [ ] **Step 2: Smoke-import the module**

Run: `uv run python -c "from src import uw_client; print(uw_client.BASE)"`
Expected: `https://api.unusualwhales.com`

- [ ] **Step 3: Commit**

```bash
git add src/uw_client.py
git commit -m "feat(uw_client): skeleton with five endpoint methods"
```

### Task 2.2: Probe script — verify endpoints with real key

**Files:**
- Create: `scripts/probe_uw.py`

- [ ] **Step 1: Write the probe script**

Write to `scripts/probe_uw.py`:
```python
"""One-shot live sanity check for each UW endpoint.

Usage:  uv run python scripts/probe_uw.py [TICKER]   (default: SPY)
"""
from __future__ import annotations
import json
import sys
from src import uw_client

TICKER = sys.argv[1] if len(sys.argv) > 1 else "SPY"

PROBES = [
    ("spot_exposures_strike", lambda: uw_client.fetch_spot_exposures_strike(TICKER)),
    ("flow_alerts_ticker",    lambda: uw_client.fetch_flow_alerts(TICKER, limit=50)),
    ("volatility",            lambda: uw_client.fetch_volatility(TICKER)),
    ("max_pain",              lambda: uw_client.fetch_max_pain(TICKER)),
    ("flow_alerts_hot",       lambda: uw_client.fetch_flow_alerts(ticker=None, limit=15)),
]

for name, fn in PROBES:
    print(f"=== {name} ===")
    try:
        data = fn()
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        continue
    s = json.dumps(data, indent=2)[:600]
    print(s)
    print()
```

- [ ] **Step 2: Run the probe**

Run: `uv run python scripts/probe_uw.py SPY`

Expected: each endpoint either prints a 600-char JSON snippet or a FAIL message. Inspect for:
- Auth header style (any 401/403 → endpoint expects different auth — see Task 0.4 alternatives)
- Endpoint path correctness (any 404 → path is wrong, check UW docs and update `src/uw_client.py`)
- Response shape (note the top-level keys for each endpoint; will guide fixture loaders)

- [ ] **Step 3: If any path was wrong, fix `src/uw_client.py` and re-run**

Iterate until all five probes return data. Record any path corrections in MEMORY.md under a new dated entry:
```markdown
## 2026-05-23 — UW endpoint path corrections

**Decided:** [path X] → [path Y] for [endpoint name]
**Why:** Probe script returned 404 on the original path; UW docs show the actual path is [...].
```

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_uw.py src/uw_client.py MEMORY.md
git commit -m "feat(probe): live UW endpoint sanity script + path verification"
```

### Task 2.3: Record fixtures for SPY

**Files:**
- Create: `scripts/record_fixtures.py`
- Create (generated): `tests/fixtures/uw_gex_strike_SPY.json`
- Create (generated): `tests/fixtures/uw_flow_recent_SPY.json`
- Create (generated): `tests/fixtures/uw_volatility_SPY.json`
- Create (generated): `tests/fixtures/uw_max_pain_SPY.json`
- Create (generated): `tests/fixtures/uw_hot_today.json`

- [ ] **Step 1: Write the recorder**

Write to `scripts/record_fixtures.py`:
```python
"""Record live UW responses to tests/fixtures/ for use in pytest.

Usage:  uv run python scripts/record_fixtures.py [TICKER...]   (default: SPY)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from src import uw_client

TICKERS = sys.argv[1:] or ["SPY"]
OUT = Path("tests/fixtures")
OUT.mkdir(parents=True, exist_ok=True)

# (label, callable, depends_on_ticker)
JOBS = [
    ("spot_exposures_strike", uw_client.fetch_spot_exposures_strike, True),
    ("flow_alerts",           lambda t: uw_client.fetch_flow_alerts(t, limit=50), True),
    ("volatility",            uw_client.fetch_volatility, True),
    ("max_pain",              uw_client.fetch_max_pain, True),
    ("hot_today",             lambda _t=None: uw_client.fetch_flow_alerts(ticker=None, limit=15), False),
]

for ticker in TICKERS:
    for label, fn, per_ticker in JOBS:
        if per_ticker:
            data = fn(ticker)
            fname = OUT / f"uw_{label}_{ticker}.json"
        else:
            data = fn()
            fname = OUT / f"uw_{label}.json"
            if fname.exists():
                continue  # already recorded — non-ticker-scoped
        fname.write_text(json.dumps(data, indent=2))
        print(f"wrote {fname}")
```

- [ ] **Step 2: Run it for SPY**

Run: `uv run python scripts/record_fixtures.py SPY`
Expected: five JSON files in `tests/fixtures/`.

- [ ] **Step 3: Inspect one fixture to confirm shape**

Run: `uv run python -c "import json; d=json.load(open('tests/fixtures/uw_gex_strike_SPY.json')); print(type(d).__name__); print(list(d.keys()) if isinstance(d, dict) else d[:2])"`
Expected: prints the top-level shape so you can reference it in tests.

- [ ] **Step 4: Commit**

```bash
git add scripts/record_fixtures.py tests/fixtures/
git commit -m "feat: fixture recorder + SPY snapshot"
```

### Task 2.4: `conftest.py` with fixture loader + live marker

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Write the conftest**

Write to `tests/conftest.py`:
```python
"""Shared test fixtures and the `live` marker setup."""
from __future__ import annotations
import json
from pathlib import Path
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURE_DIR / name).read_text())


@pytest.fixture
def gex_strike_spy():
    """Per-strike Spot GEX for SPY (from /api/stock/SPY/spot-exposures/strike).
    The fixture name keeps the short 'gex_strike' label since GEX is the
    conventional shorthand."""
    return _load("uw_spot_exposures_strike_SPY.json")


@pytest.fixture
def flow_recent_spy():
    """Recent flow alerts for SPY (from /api/option-trades/flow-alerts?ticker_symbol=SPY)."""
    return _load("uw_flow_alerts_SPY.json")


@pytest.fixture
def volatility_spy():
    return _load("uw_volatility_SPY.json")


@pytest.fixture
def max_pain_spy():
    return _load("uw_max_pain_SPY.json")


@pytest.fixture
def hot_today():
    return _load("uw_hot_today.json")


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.live tests unless `-m live` was passed."""
    selected_marker = config.getoption("-m") or ""
    if "live" in selected_marker:
        return  # user explicitly requested live tests
    skip_live = pytest.mark.skip(reason="live; run with `pytest -m live`")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
```

- [ ] **Step 2: Verify pytest still collects nothing yet**

Run: `uv run pytest -q`
Expected: `no tests ran`.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: conftest with fixture loaders + live marker handling"
```

### Task 2.5: Tests for `uw_client` response shape

**Files:**
- Create: `tests/test_uw_client.py`

- [ ] **Step 1: Write the test**

Write to `tests/test_uw_client.py`:
```python
"""Tests for src.uw_client.

These don't hit the network — they verify the loaded fixture matches the shape
the rest of the code expects. A live schema-drift check (Task 9.x) hits real
endpoints with the `live` marker.
"""
from __future__ import annotations


def test_gex_strike_has_strike_records(gex_strike_spy):
    """The gex-strike payload must contain a list/dict of per-strike records."""
    data = gex_strike_spy
    # UW typically wraps payloads in {"data": [...]} or returns the list directly.
    records = data["data"] if isinstance(data, dict) and "data" in data else data
    assert isinstance(records, list), f"expected list, got {type(records).__name__}"
    assert len(records) > 0, "expected at least one strike record"
    # Each record must minimally identify a strike and a gamma value.
    sample = records[0]
    assert isinstance(sample, dict)
    has_strike = any(k in sample for k in ("strike", "strike_price"))
    has_gamma = any(k in sample for k in ("gamma", "gex", "net_gamma", "gamma_dollars"))
    assert has_strike, f"no strike key in {list(sample.keys())}"
    assert has_gamma, f"no gamma key in {list(sample.keys())}"


def test_flow_recent_has_records(flow_recent_spy):
    data = flow_recent_spy
    records = data["data"] if isinstance(data, dict) and "data" in data else data
    assert isinstance(records, list)


def test_volatility_has_term_structure(volatility_spy):
    data = volatility_spy
    # Term structure is some collection of (expiry, iv) entries
    assert isinstance(data, (dict, list))


def test_max_pain_returns_payload(max_pain_spy):
    assert max_pain_spy is not None


def test_hot_today_returns_records(hot_today):
    data = hot_today
    records = data["data"] if isinstance(data, dict) and "data" in data else data
    assert isinstance(records, list)
    assert len(records) > 0
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_uw_client.py -v`
Expected: all 5 PASS. If any FAIL, inspect the actual fixture shape and adjust the test assertions to match (this is shape-discovery — the test is the contract).

- [ ] **Step 3: Commit**

```bash
git add tests/test_uw_client.py
git commit -m "test(uw_client): shape contracts against SPY fixtures"
```

### Task 2.6: Parser helpers for known response shapes

**Files:**
- Modify: `src/uw_client.py` (append parser helpers based on observed shape)

- [ ] **Step 1: Add shape-normalizing helpers**

Append to `src/uw_client.py`:
```python
# ---------- Shape normalizers ----------
# UW wraps some endpoints in {"data": [...]} and returns others as bare lists.
# Normalize both into lists/dicts the analytics layer can rely on.

def _unwrap(payload):
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def gex_records(payload) -> list[dict]:
    """Return list of {strike: float, gamma: float, ...} dicts.

    UW's /spot-exposures/strike returns per-strike directional gamma. Per UW
    docs: net dealer gamma per strike = call_gamma_oi - put_gamma_oi (OI-based,
    standing positions). The directional volume variants (_ask, _bid) sum to
    the full directionalized exposure.

    This parser computes net gamma using OI fields if present; falls back to
    summed directional fields; falls back to single-field aggregate names.
    """
    rows = _unwrap(payload)
    out = []
    for r in rows:
        strike = r.get("strike") or r.get("strike_price")
        if strike is None:
            continue
        strike = float(strike)

        # 1. OI-based net (canonical spot-exposures shape — preferred)
        call_oi = r.get("call_gamma_oi")
        put_oi = r.get("put_gamma_oi")
        if call_oi is not None or put_oi is not None:
            gamma = float(call_oi or 0) - float(put_oi or 0)
        else:
            # 2. Directional-volume sum (alternate shape)
            call_ask = r.get("call_gamma_ask")
            call_bid = r.get("call_gamma_bid")
            put_ask = r.get("put_gamma_ask")
            put_bid = r.get("put_gamma_bid")
            if any(v is not None for v in (call_ask, call_bid, put_ask, put_bid)):
                gamma = sum(float(v or 0) for v in (call_ask, call_bid, put_ask, put_bid))
            else:
                # 3. Single-field aggregate fallback
                gamma = None
                for k in ("gamma_dollars", "net_gamma", "gex", "gamma"):
                    if r.get(k) is not None:
                        gamma = float(r[k])
                        break
                if gamma is None:
                    # 4. Generic call/put split fallback (greek-exposure shape)
                    call_g = r.get("call_gamma")
                    put_g = r.get("put_gamma")
                    if call_g is not None or put_g is not None:
                        gamma = float(call_g or 0) - float(put_g or 0)
        if gamma is None:
            continue
        out.append({"strike": strike, "gamma": gamma, "raw": r})
    return sorted(out, key=lambda x: x["strike"])


def flow_records(payload) -> list[dict]:
    """Return list of {side: 'call'|'put', premium_usd: float, ts: str, ...}."""
    rows = _unwrap(payload)
    out = []
    for r in rows:
        side = (r.get("option_type") or r.get("type") or "").lower()
        side = "call" if side.startswith("c") else "put" if side.startswith("p") else side
        prem = r.get("premium") or r.get("premium_usd") or r.get("total_premium")
        ts = r.get("executed_at") or r.get("timestamp") or r.get("ts")
        out.append({"side": side, "premium_usd": float(prem or 0), "ts": ts, "raw": r})
    return out


def hot_tickers(payload, limit: int = 15) -> list[str]:
    """Return list of unique tickers from a flow-alerts payload."""
    rows = _unwrap(payload)
    seen = []
    for r in rows:
        t = r.get("ticker") or r.get("symbol") or r.get("underlying")
        if t and t not in seen:
            seen.append(t)
        if len(seen) >= limit:
            break
    return seen
```

- [ ] **Step 2: Add a test for `gex_records` ordering**

Append to `tests/test_uw_client.py`:
```python
from src.uw_client import gex_records, flow_records, hot_tickers


def test_gex_records_sorted_by_strike(gex_strike_spy):
    records = gex_records(gex_strike_spy)
    assert len(records) > 0
    strikes = [r["strike"] for r in records]
    assert strikes == sorted(strikes)


def test_flow_records_returns_list(flow_recent_spy):
    records = flow_records(flow_recent_spy)
    assert isinstance(records, list)


def test_hot_tickers_returns_unique_symbols(hot_today):
    tickers = hot_tickers(hot_today, limit=15)
    assert isinstance(tickers, list)
    assert len(tickers) == len(set(tickers))
```

- [ ] **Step 3: Run the new tests**

Run: `uv run pytest tests/test_uw_client.py -v`
Expected: all PASS. If `gex_records` returns 0 records, the field-name search list missed UW's actual key — inspect the fixture and add the correct key to the loop.

- [ ] **Step 4: Commit**

```bash
git add src/uw_client.py tests/test_uw_client.py
git commit -m "feat(uw_client): shape normalizers for gex/flow/hot endpoints"
```

---

## Phase 3: Pattern detectors (~1.5 hr)

Each detector is a pure function. TDD-friendly: write the test against a known SPY fixture, implement the minimal logic, verify, then add edge cases.

### Task 3.1: Pattern result dataclass

**Files:**
- Create: `src/patterns.py`

- [ ] **Step 1: Write the result type**

Write to `src/patterns.py`:
```python
"""Pure pattern detectors. Input: parsed UW data. Output: verdict dict.

All detectors take already-normalized inputs (e.g., the list returned by
uw_client.gex_records). None hit the network or read globals.

Initial thresholds are guesses — see calibrate_thresholds in MEMORY.md.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal

PatternKind = Literal["pinning", "gamma_squeeze", "flow", "vol_regime"]


@dataclass
class Verdict:
    kind: PatternKind
    firing: bool
    intensity: float  # 0..1, 0 if not firing
    note: dict        # arbitrary detector-specific extras (strike, side, etc.)

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 2: Smoke-import**

Run: `uv run python -c "from src.patterns import Verdict; v = Verdict('pinning', True, 0.7, {'strike': 450}); print(v.to_dict())"`
Expected: dict prints.

- [ ] **Step 3: Commit**

```bash
git add src/patterns.py
git commit -m "feat(patterns): Verdict dataclass scaffold"
```

### Task 3.2: Pinning detector

**Files:**
- Modify: `src/patterns.py`
- Create: `tests/test_patterns.py`

- [ ] **Step 1: Write the failing test**

Write to `tests/test_patterns.py`:
```python
from src.patterns import detect_pinning, Verdict
from src.uw_client import gex_records


def test_pinning_on_spy_fixture(gex_strike_spy):
    """SPY at any given time may or may not have a pin. The test verifies the
    detector returns a Verdict with a numeric intensity, regardless of firing."""
    records = gex_records(gex_strike_spy)
    spot = float(records[len(records) // 2]["strike"])  # crude: assume center≈spot
    v = detect_pinning(records, spot=spot)
    assert isinstance(v, Verdict)
    assert v.kind == "pinning"
    assert 0.0 <= v.intensity <= 1.0
    if v.firing:
        assert "strike" in v.note


def test_pinning_synthetic_strong_pin():
    """Synthetic: huge positive gamma concentrated at the spot strike → fires."""
    records = [
        {"strike": 100.0, "gamma": 1e6},
        {"strike": 101.0, "gamma": 5e7},  # massive concentration here
        {"strike": 102.0, "gamma": 1e6},
    ]
    v = detect_pinning(records, spot=101.0)
    assert v.firing is True
    assert v.intensity > 0.5
    assert v.note["strike"] == 101.0


def test_pinning_synthetic_no_pin():
    """Synthetic: gamma spread evenly → does not fire."""
    records = [
        {"strike": 100.0, "gamma": 1e6},
        {"strike": 101.0, "gamma": 1e6},
        {"strike": 102.0, "gamma": 1e6},
    ]
    v = detect_pinning(records, spot=101.0)
    assert v.firing is False
```

- [ ] **Step 2: Run — should FAIL (function doesn't exist)**

Run: `uv run pytest tests/test_patterns.py -v`
Expected: ImportError or AttributeError on `detect_pinning`.

- [ ] **Step 3: Implement the detector**

Append to `src/patterns.py`:
```python
# ---------- Pinning ----------
# Thesis: heavy net dealer gamma concentrated near spot → dealer hedging
# pins price near that strike into expiry.
#
# Heuristic (initial):
#   - find the strike with max abs(gamma) within ±2% of spot
#   - "concentration" = that strike's |gamma| / sum(|gamma|) across all strikes within ±5% of spot
#   - firing if concentration > 0.30
#   - intensity = min(1.0, concentration / 0.50)  (full intensity at 50%+ concentration)

PIN_BAND = 0.05   # ±5% of spot for denominator
PIN_NEAR = 0.02   # ±2% of spot for the candidate strike
PIN_THRESHOLD = 0.30


def detect_pinning(gex_recs: list[dict], spot: float) -> Verdict:
    if not gex_recs or spot <= 0:
        return Verdict("pinning", False, 0.0, {"reason": "empty"})

    near_band = [r for r in gex_recs if abs(r["strike"] - spot) / spot <= PIN_NEAR]
    wide_band = [r for r in gex_recs if abs(r["strike"] - spot) / spot <= PIN_BAND]
    if not near_band or not wide_band:
        return Verdict("pinning", False, 0.0, {"reason": "no_nearby_strikes"})

    top = max(near_band, key=lambda r: abs(r["gamma"]))
    denom = sum(abs(r["gamma"]) for r in wide_band)
    if denom == 0:
        return Verdict("pinning", False, 0.0, {"reason": "zero_gamma"})

    concentration = abs(top["gamma"]) / denom
    firing = concentration > PIN_THRESHOLD
    intensity = min(1.0, concentration / 0.50) if firing else 0.0
    note = {"strike": top["strike"], "concentration": round(concentration, 3)}
    return Verdict("pinning", firing, intensity, note)
```

- [ ] **Step 4: Run — should PASS**

Run: `uv run pytest tests/test_patterns.py -v`
Expected: 3 tests pass. If SPY fixture test fails because `firing` returned True but `"strike"` isn't in note — that means the implementation diverged from the test contract; reconcile.

- [ ] **Step 5: Commit**

```bash
git add src/patterns.py tests/test_patterns.py
git commit -m "feat(patterns): pinning detector + tests"
```

### Task 3.3: Gamma squeeze detector

**Files:**
- Modify: `src/patterns.py`
- Modify: `tests/test_patterns.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_patterns.py`:
```python
from src.patterns import detect_gamma_squeeze


def test_gamma_squeeze_synthetic_short_dealers_above_spot():
    """Negative dealer gamma stacked above spot → squeeze setup upward."""
    records = [
        {"strike": 100.0, "gamma": 5e6},
        {"strike": 105.0, "gamma": -8e6},   # dealers short gamma here
        {"strike": 110.0, "gamma": -1e7},   # more so here
    ]
    v = detect_gamma_squeeze(records, spot=100.0)
    assert v.firing is True
    assert v.note["direction"] == "up"
    assert v.intensity > 0.3


def test_gamma_squeeze_synthetic_balanced():
    """Symmetric gamma → no squeeze."""
    records = [
        {"strike": 95.0,  "gamma": 1e6},
        {"strike": 100.0, "gamma": 1e6},
        {"strike": 105.0, "gamma": 1e6},
    ]
    v = detect_gamma_squeeze(records, spot=100.0)
    assert v.firing is False
```

- [ ] **Step 2: Run — FAIL**

Run: `uv run pytest tests/test_patterns.py::test_gamma_squeeze_synthetic_short_dealers_above_spot -v`
Expected: ImportError on `detect_gamma_squeeze`.

- [ ] **Step 3: Implement**

Append to `src/patterns.py`:
```python
# ---------- Gamma squeeze ----------
# Thesis: dealers are net SHORT gamma at strikes ABOVE (or BELOW) spot →
# if price crosses, dealers must chase, amplifying the move.
#
# Heuristic (initial):
#   - sum gamma above spot, sum below
#   - if min(above_sum, below_sum) < 0 and |that sum| > 1.5x |other side|
#     → squeeze in that direction
#   - intensity = min(1.0, |short side| / (|short side| + |long side|))

SQUEEZE_RATIO = 1.5


def detect_gamma_squeeze(gex_recs: list[dict], spot: float) -> Verdict:
    above = [r for r in gex_recs if r["strike"] > spot]
    below = [r for r in gex_recs if r["strike"] < spot]
    if not above or not below:
        return Verdict("gamma_squeeze", False, 0.0, {"reason": "one_sided"})

    above_sum = sum(r["gamma"] for r in above)
    below_sum = sum(r["gamma"] for r in below)

    # A squeeze setup is: one side is significantly NEGATIVE (short dealers)
    # while the other is non-negative or much smaller in absolute terms.
    direction = None
    if above_sum < 0 and abs(above_sum) > SQUEEZE_RATIO * abs(below_sum):
        direction = "up"
        magnitude = abs(above_sum)
        other = abs(below_sum)
    elif below_sum < 0 and abs(below_sum) > SQUEEZE_RATIO * abs(above_sum):
        direction = "down"
        magnitude = abs(below_sum)
        other = abs(above_sum)
    else:
        return Verdict("gamma_squeeze", False, 0.0,
                       {"above_sum": above_sum, "below_sum": below_sum})

    intensity = min(1.0, magnitude / (magnitude + other + 1e-9))
    return Verdict(
        "gamma_squeeze", True, intensity,
        {"direction": direction, "above_sum": above_sum, "below_sum": below_sum},
    )
```

- [ ] **Step 4: Run — PASS**

Run: `uv run pytest tests/test_patterns.py -v`
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/patterns.py tests/test_patterns.py
git commit -m "feat(patterns): gamma squeeze detector + tests"
```

### Task 3.4: Flow conviction detector

**Files:**
- Modify: `src/patterns.py`
- Modify: `tests/test_patterns.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_patterns.py`:
```python
from src.patterns import detect_flow


def test_flow_synthetic_heavy_call_buying():
    records = [
        {"side": "call", "premium_usd": 1_500_000, "ts": "2026-05-23T15:00:00Z"},
        {"side": "call", "premium_usd": 900_000,   "ts": "2026-05-23T15:01:00Z"},
        {"side": "put",  "premium_usd": 200_000,   "ts": "2026-05-23T15:02:00Z"},
    ]
    v = detect_flow(records)
    assert v.firing is True
    assert v.note["side"] == "long"
    assert v.note["net_premium_usd"] > 0


def test_flow_synthetic_neutral():
    records = [
        {"side": "call", "premium_usd": 500_000, "ts": "2026-05-23T15:00:00Z"},
        {"side": "put",  "premium_usd": 500_000, "ts": "2026-05-23T15:01:00Z"},
    ]
    v = detect_flow(records)
    assert v.firing is False
    assert v.note.get("side") == "neutral"


def test_flow_empty_input_does_not_fire():
    v = detect_flow([])
    assert v.firing is False
```

- [ ] **Step 2: Run — FAIL**

Run: `uv run pytest tests/test_patterns.py -v`
Expected: FAIL on flow tests.

- [ ] **Step 3: Implement**

Append to `src/patterns.py`:
```python
# ---------- Flow conviction ----------
# Thesis: net premium directional, sized → institutional positioning leaning.
#
# Heuristic (initial):
#   - net_premium = sum(calls) - sum(puts)
#   - skew = |net| / (calls + puts)
#   - firing if total > $1M AND skew > 0.20
#   - side = "long" if net > 0 and firing, "short" if net < 0 and firing, else "neutral"
#   - intensity = min(1.0, skew * 2)  (50% skew = full intensity)

FLOW_MIN_TOTAL = 1_000_000
FLOW_MIN_SKEW = 0.20


def detect_flow(flow_recs: list[dict]) -> Verdict:
    if not flow_recs:
        return Verdict("flow", False, 0.0, {"side": "neutral", "reason": "empty"})

    calls = sum(r["premium_usd"] for r in flow_recs if r["side"] == "call")
    puts = sum(r["premium_usd"] for r in flow_recs if r["side"] == "put")
    total = calls + puts
    net = calls - puts

    if total == 0:
        return Verdict("flow", False, 0.0, {"side": "neutral", "reason": "zero_total"})

    skew = abs(net) / total
    firing = total >= FLOW_MIN_TOTAL and skew >= FLOW_MIN_SKEW
    if firing:
        side = "long" if net > 0 else "short"
    else:
        side = "neutral"

    intensity = min(1.0, skew * 2) if firing else 0.0
    return Verdict("flow", firing, intensity, {
        "side": side,
        "net_premium_usd": net,
        "total_premium_usd": total,
        "skew": round(skew, 3),
    })
```

- [ ] **Step 4: Run — PASS**

Run: `uv run pytest tests/test_patterns.py -v`
Expected: 8 tests total now pass.

- [ ] **Step 5: Commit**

```bash
git add src/patterns.py tests/test_patterns.py
git commit -m "feat(patterns): flow conviction detector + tests"
```

### Task 3.5: Vol regime detector (IV term-structure inversion)

Redefined per product-review item #3: "IV rank elevated" was too fuzzy — IVR 80 in a tight range means something very different from IVR 80 going into earnings. The sharp, tradeable signal for weekly options is **front-week vs monthly IV inversion**: when front-week IV exceeds 30-day IV by ≥5 vol points, the market is pricing event-driven near-term richness (earnings, FOMC, scheduled catalyst).

**Files:**
- Modify: `src/patterns.py`
- Modify: `tests/test_patterns.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_patterns.py`:
```python
from src.patterns import detect_vol_regime


def test_vol_regime_inverted_front_week_event_driven():
    """Front-week IV >> 30-day IV → event-driven richness, firing."""
    term = [{"dte": 4, "iv": 0.48}, {"dte": 30, "iv": 0.32}]   # 16 vol-pt premium
    v = detect_vol_regime(term)
    assert v.firing is True
    assert v.note["regime"] == "event_driven"
    assert v.note["front_minus_30d_pts"] >= 5


def test_vol_regime_normal_term_structure_does_not_fire():
    """Front-week IV ≈ 30-day IV → calendar normal, not firing."""
    term = [{"dte": 4, "iv": 0.22}, {"dte": 30, "iv": 0.21}]
    v = detect_vol_regime(term)
    assert v.firing is False


def test_vol_regime_empty_term_structure():
    v = detect_vol_regime([])
    assert v.firing is False
```

- [ ] **Step 2: Run — FAIL**

Run: `uv run pytest tests/test_patterns.py -v`
Expected: FAIL on vol_regime tests.

- [ ] **Step 3: Implement**

Append to `src/patterns.py`:
```python
# ---------- Vol regime (IV term-structure inversion) ----------
# Thesis: front-week IV elevated relative to 30-day IV → market pricing
# event-driven near-term richness (earnings, FOMC, scheduled catalyst).
# Tradeable: premium-selling on the front week if you're skeptical of the
# catalyst; premium-buying if you want exposure to it.
#
# Heuristic (initial — calibrate during build):
#   - "event_driven" if front-week IV (DTE ≤ 7) - 30-day IV >= 5 vol points
#   - intensity = min(1.0, (front - 30d) / 15) — full intensity at 15+ pt inversion

VOL_INVERSION_THRESHOLD_PTS = 5.0
VOL_INVERSION_FULL_INTENSITY_PTS = 15.0


def detect_vol_regime(term_structure: list[dict]) -> Verdict:
    """
    `term_structure` is the list returned by uw_client.term_structure():
    [{"dte": int, "iv": float}, ...], sorted by dte ascending.
    """
    if not term_structure:
        return Verdict("vol_regime", False, 0.0, {"reason": "empty_term_structure"})

    # Front-week IV: any entry with dte <= 7
    front = next((e["iv"] for e in term_structure if e["dte"] <= 7), None)
    # 30-day IV: closest entry to dte=30
    monthly = None
    if term_structure:
        monthly_entry = min(term_structure, key=lambda e: abs(e["dte"] - 30))
        if abs(monthly_entry["dte"] - 30) <= 10:  # within 20-40 dte window
            monthly = monthly_entry["iv"]

    if front is None or monthly is None:
        return Verdict("vol_regime", False, 0.0, {"reason": "missing_front_or_30d"})

    # IV expressed as decimal (0.32 = 32%). Convert delta to vol POINTS (×100).
    delta_pts = (front - monthly) * 100
    note = {
        "front_iv": round(front, 4),
        "iv_30d": round(monthly, 4),
        "front_minus_30d_pts": round(delta_pts, 2),
    }

    if delta_pts >= VOL_INVERSION_THRESHOLD_PTS:
        intensity = min(1.0, delta_pts / VOL_INVERSION_FULL_INTENSITY_PTS)
        return Verdict("vol_regime", True, intensity,
                       {"regime": "event_driven", **note})
    return Verdict("vol_regime", False, 0.0, {"regime": "normal", **note})
```

- [ ] **Step 4: Run — PASS**

Run: `uv run pytest tests/test_patterns.py -v`
Expected: 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/patterns.py tests/test_patterns.py
git commit -m "feat(patterns): vol regime via IV term-structure inversion"
```

### Task 3.6: Aggregator + IV-rank extractor

**Files:**
- Modify: `src/patterns.py`
- Modify: `src/uw_client.py`
- Modify: `tests/test_patterns.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_patterns.py`:
```python
from src.patterns import detect_all


def test_detect_all_returns_four_verdicts():
    bundle = detect_all(
        gex_recs=[{"strike": 100.0, "gamma": 1e6}],
        flow_recs=[],
        spot=100.0,
        term_structure=[{"dte": 4, "iv": 0.22}, {"dte": 30, "iv": 0.21}],
    )
    assert set(bundle.keys()) == {"pinning", "gamma_squeeze", "flow", "vol_regime"}
    for v in bundle.values():
        assert v.kind in {"pinning", "gamma_squeeze", "flow", "vol_regime"}
```

- [ ] **Step 2: Implement aggregator**

Append to `src/patterns.py`:
```python
# ---------- Aggregator ----------

def detect_all(
    gex_recs: list[dict],
    flow_recs: list[dict],
    spot: float,
    term_structure: list[dict],
) -> dict[PatternKind, Verdict]:
    return {
        "pinning":       detect_pinning(gex_recs, spot),
        "gamma_squeeze": detect_gamma_squeeze(gex_recs, spot),
        "flow":          detect_flow(flow_recs),
        "vol_regime":    detect_vol_regime(term_structure),
    }
```

- [ ] **Step 3: Add IV-rank + spot extractors to `uw_client`**

Append to `src/uw_client.py`:
```python
# ---------- Scalar extractors (best-effort across UW response shapes) ----------

def extract_spot(volatility_payload) -> float | None:
    """Pull the current underlying spot price from a volatility/term-structure payload."""
    p = _unwrap(volatility_payload)
    if isinstance(p, dict):
        for k in ("spot", "underlying_price", "last_price", "price"):
            if p.get(k) is not None:
                return float(p[k])
    return None


def extract_iv_rank(volatility_payload) -> float | None:
    """Pull IV rank (0-100) from a volatility payload."""
    p = _unwrap(volatility_payload)
    if isinstance(p, dict):
        for k in ("iv_rank", "ivr", "iv_percentile"):
            if p.get(k) is not None:
                v = float(p[k])
                # Some endpoints return 0-1, others 0-100.
                return v * 100 if v <= 1.0 else v
    return None
```

- [ ] **Step 4: Run — PASS**

Run: `uv run pytest -v`
Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/patterns.py src/uw_client.py tests/test_patterns.py
git commit -m "feat(patterns): detect_all aggregator + scalar extractors"
```

---

## Phase 4: Chart builders (~1 hr)

Pure functions: input data → Plotly Figure. Tests are smoke-level (returns a Figure with expected number of traces).

### Task 4.1: Gamma profile chart

**Files:**
- Create: `src/charts.py`
- Create: `tests/test_charts.py`

- [ ] **Step 1: Write failing test**

Write to `tests/test_charts.py`:
```python
import plotly.graph_objects as go
from src.charts import gamma_profile_figure


def test_gamma_profile_returns_figure():
    records = [
        {"strike": 100.0, "gamma": -5e6},
        {"strike": 105.0, "gamma":  8e6},
        {"strike": 110.0, "gamma":  3e6},
    ]
    fig = gamma_profile_figure(records, spot=105.0, ticker="TEST")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1  # at least one trace


def test_gamma_profile_empty_returns_empty_figure():
    fig = gamma_profile_figure([], spot=100.0, ticker="TEST")
    assert isinstance(fig, go.Figure)
```

- [ ] **Step 2: Run — FAIL**

Run: `uv run pytest tests/test_charts.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Write to `src/charts.py`:
```python
"""Plotly figure builders. Pure: input data → Figure."""
from __future__ import annotations
import plotly.graph_objects as go


def gamma_profile_figure(gex_recs: list[dict], spot: float, ticker: str) -> go.Figure:
    """Bar chart of per-strike net dealer gamma, with a vertical line at spot."""
    fig = go.Figure()
    if not gex_recs:
        fig.add_annotation(text="No gamma data", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")
        fig.update_layout(title=f"{ticker} — net dealer gamma by strike", height=280, margin=dict(l=20, r=20, t=40, b=20))
        return fig

    strikes = [r["strike"] for r in gex_recs]
    gammas = [r["gamma"] for r in gex_recs]
    colors = ["#7AA2F7" if g >= 0 else "#F7768E" for g in gammas]

    fig.add_trace(go.Bar(x=strikes, y=gammas, marker_color=colors, name="Net γ"))
    fig.add_vline(x=spot, line_color="#E0AF68", line_dash="dash", annotation_text=f"spot {spot:.2f}")
    fig.update_layout(
        title=f"{ticker} — net dealer gamma by strike",
        xaxis_title="Strike",
        yaxis_title="Net γ ($)",
        height=280,
        margin=dict(l=20, r=20, t=40, b=30),
        template="plotly_dark",
    )
    return fig
```

- [ ] **Step 4: Run — PASS**

Run: `uv run pytest tests/test_charts.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/charts.py tests/test_charts.py
git commit -m "feat(charts): gamma profile builder + tests"
```

### Task 4.2: Open-interest-per-strike chart

Swapped in for the flow timeline per product-review item #5: the FLOW badge in each scan row already conveys flow direction and size, so a flow timeline chart in the pinned card was partially redundant. The structural levels for a weekly trade (call wall, put wall, max pain) are what the user actually needs to see in the drill-down. OI-per-strike surfaces those directly.

**Files:**
- Modify: `src/uw_client.py` (new endpoint + parser)
- Modify: `src/charts.py`
- Modify: `tests/test_charts.py`
- Modify: `scripts/probe_uw.py` (add the new endpoint to the probe)
- Modify: `scripts/record_fixtures.py` (record OI fixture)

- [ ] **Step 1: Add the OI endpoint to `uw_client.py`**

Append to `src/uw_client.py`:
```python
def fetch_oi_strike(ticker: str) -> dict:
    """Per-strike open interest, calls + puts split."""
    return _get(f"/api/stock/{ticker}/oi-per-strike")


def oi_records(payload) -> list[dict]:
    """Return list of {strike: float, call_oi: int, put_oi: int} dicts."""
    rows = _unwrap(payload)
    out = []
    for r in rows:
        strike = r.get("strike") or r.get("strike_price")
        if strike is None:
            continue
        call_oi = int(r.get("call_oi") or r.get("calls_oi") or r.get("call_open_interest") or 0)
        put_oi = int(r.get("put_oi") or r.get("puts_oi") or r.get("put_open_interest") or 0)
        out.append({"strike": float(strike), "call_oi": call_oi, "put_oi": put_oi})
    return sorted(out, key=lambda x: x["strike"])
```

- [ ] **Step 2: Add the OI probe to `scripts/probe_uw.py`**

In the PROBES list in `scripts/probe_uw.py`, add:
```python
    ("oi_strike",   lambda: uw_client.fetch_oi_strike(TICKER)),
```

Run: `uv run python scripts/probe_uw.py SPY`
Expected: oi_strike returns data. If 404, check UW docs for the correct path (e.g. `/api/stock/{ticker}/option-chains` might bundle OI). Update both the client and the probe.

- [ ] **Step 3: Add to fixture recorder**

In `scripts/record_fixtures.py` JOBS list, add:
```python
    ("oi_strike",   uw_client.fetch_oi_strike, True),
```

Run: `uv run python scripts/record_fixtures.py SPY`
Expected: `tests/fixtures/uw_oi_strike_SPY.json` exists.

- [ ] **Step 4: Add the conftest fixture loader**

In `tests/conftest.py`, append a new fixture:
```python
@pytest.fixture
def oi_strike_spy():
    return _load("uw_oi_strike_SPY.json")
```

- [ ] **Step 5: Write the chart's failing test**

Append to `tests/test_charts.py`:
```python
from src.charts import oi_per_strike_figure


def test_oi_per_strike_returns_figure():
    records = [
        {"strike": 100.0, "call_oi": 5000, "put_oi": 1200},
        {"strike": 105.0, "call_oi": 8000, "put_oi": 800},   # call wall
        {"strike":  95.0, "call_oi":  600, "put_oi": 7500},  # put wall
    ]
    fig = oi_per_strike_figure(records, spot=100.0, max_pain=100.0, ticker="TEST")
    assert isinstance(fig, go.Figure)


def test_oi_per_strike_empty_returns_empty_figure():
    fig = oi_per_strike_figure([], spot=100.0, max_pain=None, ticker="TEST")
    assert isinstance(fig, go.Figure)
```

- [ ] **Step 6: Implement**

Append to `src/charts.py`:
```python
def oi_per_strike_figure(
    oi_recs: list[dict],
    spot: float,
    max_pain: float | None,
    ticker: str,
) -> go.Figure:
    """Grouped bar chart: call OI vs put OI per strike, with vlines at spot + max pain."""
    fig = go.Figure()
    if not oi_recs:
        fig.add_annotation(text="No OI data", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")
        fig.update_layout(title=f"{ticker} — open interest by strike", height=280, margin=dict(l=20, r=20, t=40, b=20))
        return fig

    strikes = [r["strike"] for r in oi_recs]
    calls = [r["call_oi"] for r in oi_recs]
    puts = [-r["put_oi"] for r in oi_recs]   # negative so puts render below the axis

    fig.add_trace(go.Bar(x=strikes, y=calls, marker_color="#9ECE6A", name="Call OI"))
    fig.add_trace(go.Bar(x=strikes, y=puts, marker_color="#F7768E", name="Put OI"))
    if spot:
        fig.add_vline(x=spot, line_color="#E0AF68", line_dash="dash",
                      annotation_text=f"spot {spot:.2f}", annotation_position="top")
    if max_pain:
        fig.add_vline(x=max_pain, line_color="#BB9AF7", line_dash="dot",
                      annotation_text=f"max pain {max_pain:.2f}", annotation_position="bottom")

    fig.update_layout(
        title=f"{ticker} — open interest by strike (calls above / puts below)",
        xaxis_title="Strike",
        yaxis_title="OI contracts (puts shown negative)",
        barmode="overlay",
        height=280,
        margin=dict(l=20, r=20, t=40, b=30),
        template="plotly_dark",
        legend=dict(orientation="h", y=1.1),
    )
    return fig
```

- [ ] **Step 7: Add a `max_pain_value` extractor in `uw_client.py`**

Append:
```python
def max_pain_value(payload) -> float | None:
    """Pull the max-pain strike from the max-pain endpoint payload."""
    p = _unwrap(payload)
    if isinstance(p, dict):
        for k in ("max_pain", "max_pain_strike", "strike"):
            if p.get(k) is not None:
                return float(p[k])
    if isinstance(p, list) and p:
        # Some UW endpoints return a list of {expiry, strike}; pick the nearest expiry
        return float(p[0].get("strike") or p[0].get("max_pain"))
    return None
```

- [ ] **Step 8: Run — PASS**

Run: `uv run pytest tests/test_charts.py -v`
Expected: 4 chart tests pass (gamma profile + oi-per-strike, with empty-state cases).

- [ ] **Step 9: Commit**

```bash
git add src/uw_client.py src/charts.py scripts/probe_uw.py scripts/record_fixtures.py tests/conftest.py tests/test_charts.py tests/fixtures/uw_oi_strike_SPY.json
git commit -m "feat(charts): swap flow timeline for OI-per-strike chart"
```

### Task 4.3: Vol / skew chart

**Files:**
- Modify: `src/charts.py`
- Modify: `tests/test_charts.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_charts.py`:
```python
from src.charts import vol_term_structure_figure


def test_vol_term_structure_returns_figure():
    series = [
        {"dte": 7, "iv": 0.22},
        {"dte": 14, "iv": 0.21},
        {"dte": 30, "iv": 0.20},
    ]
    fig = vol_term_structure_figure(series, ticker="TEST")
    assert isinstance(fig, go.Figure)


def test_vol_term_structure_empty_returns_empty_figure():
    fig = vol_term_structure_figure([], ticker="TEST")
    assert isinstance(fig, go.Figure)
```

- [ ] **Step 2: Implement**

Append to `src/charts.py`:
```python
def vol_term_structure_figure(series: list[dict], ticker: str) -> go.Figure:
    """Line chart: days-to-expiry → implied volatility."""
    fig = go.Figure()
    if not series:
        fig.add_annotation(text="No vol data", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")
        fig.update_layout(title=f"{ticker} — IV term structure", height=280, margin=dict(l=20, r=20, t=40, b=20))
        return fig

    dtes = [d["dte"] for d in series]
    ivs = [d["iv"] for d in series]
    fig.add_trace(go.Scatter(
        x=dtes, y=ivs, mode="lines+markers",
        line=dict(color="#BB9AF7", width=2),
        marker=dict(size=8, color="#BB9AF7"),
    ))
    fig.update_layout(
        title=f"{ticker} — IV term structure",
        xaxis_title="Days to expiry",
        yaxis_title="IV",
        yaxis_tickformat=".0%",
        height=280,
        margin=dict(l=20, r=20, t=40, b=30),
        template="plotly_dark",
    )
    return fig
```

- [ ] **Step 3: Add a term-structure parser to `uw_client`**

Append to `src/uw_client.py`:
```python
def term_structure(volatility_payload) -> list[dict]:
    """Return list of {dte: int, iv: float} from a volatility payload."""
    p = _unwrap(volatility_payload)
    # UW may return a list of {expiry, iv} or {dte, iv}.
    if isinstance(p, list):
        rows = p
    elif isinstance(p, dict):
        rows = p.get("term_structure") or p.get("expiries") or p.get("series") or []
    else:
        rows = []
    out = []
    for r in rows:
        dte = r.get("dte") or r.get("days_to_expiry")
        iv = r.get("iv") or r.get("atm_iv") or r.get("implied_volatility")
        if dte is None or iv is None:
            continue
        out.append({"dte": int(dte), "iv": float(iv)})
    return sorted(out, key=lambda x: x["dte"])
```

- [ ] **Step 4: Run — PASS**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/charts.py src/uw_client.py tests/test_charts.py
git commit -m "feat(charts): IV term-structure builder + parser"
```

---

## Phase 5: Watchlist (~30 min)

### Task 5.1: Watchlist merge logic

**Files:**
- Create: `src/watchlist.py`
- Create: `tests/test_watchlist.py`

- [ ] **Step 1: Write failing tests**

Write to `tests/test_watchlist.py`:
```python
from src.watchlist import merge_watchlist, parse_user_list


def test_parse_user_list_csv_string():
    assert parse_user_list("AAPL, NVDA,tsla, ") == ["AAPL", "NVDA", "TSLA"]


def test_parse_user_list_empty():
    assert parse_user_list("") == []


def test_merge_dedups_and_caps():
    fixed = ["SPY", "QQQ", "NVDA"]
    hot = ["NVDA", "TSLA", "META", "AAPL"]
    out = merge_watchlist(fixed, hot, cap=5)
    assert out == ["SPY", "QQQ", "NVDA", "TSLA", "META"]


def test_merge_preserves_fixed_order():
    out = merge_watchlist(["A", "B", "C"], ["X", "B", "Y"], cap=10)
    assert out[:3] == ["A", "B", "C"]
```

- [ ] **Step 2: Run — FAIL**

Run: `uv run pytest tests/test_watchlist.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Write to `src/watchlist.py`:
```python
"""Watchlist resolution: user's fixed list ∪ UW 'hot today' leaders, deduped, capped."""
from __future__ import annotations

DEFAULT_FIXED = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA", "META", "AMZN", "GOOGL", "MSFT"]
DEFAULT_CAP = 30
DEFAULT_FIRST_BATCH = 10


def parse_user_list(csv: str) -> list[str]:
    """Parse a comma-separated ticker string into a list, normalized to uppercase."""
    if not csv:
        return []
    return [t.strip().upper() for t in csv.split(",") if t.strip()]


def merge_watchlist(fixed: list[str], hot: list[str], cap: int = DEFAULT_CAP) -> list[str]:
    """Union of fixed (preserved order) + hot (filling remaining slots), deduped, capped."""
    seen: set[str] = set()
    out: list[str] = []
    for t in [*fixed, *hot]:
        t = t.upper()
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= cap:
            break
    return out
```

- [ ] **Step 4: Run — PASS**

Run: `uv run pytest tests/test_watchlist.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/watchlist.py tests/test_watchlist.py
git commit -m "feat(watchlist): merge + parse functions with tests"
```

---

## Phase 6: Gemini synthesis (~1.5 hr)

### Task 6.1: Synth prompt + skeleton

**Files:**
- Create: `src/synth.py`
- Create: `tests/test_synth.py`

- [ ] **Step 1: Write failing test for prompt construction**

Write to `tests/test_synth.py`:
```python
from src.synth import build_prompt


def test_prompt_contains_ticker_and_pattern_names():
    patterns = {
        "pinning":       {"firing": True,  "intensity": 0.7, "note": {"strike": 450}},
        "gamma_squeeze": {"firing": False, "intensity": 0.0, "note": {}},
        "flow":          {"firing": True,  "intensity": 0.6, "note": {"side": "long", "net_premium_usd": 2_000_000}},
        "vol_regime":    {"firing": False, "intensity": 0.0, "note": {"iv_rank": 50}},
    }
    key_numbers = {"spot": 449.50, "max_gamma_strike": 450, "iv_rank": 50, "dte": 4}
    p = build_prompt("NVDA", patterns, key_numbers)
    assert "NVDA" in p
    assert "pinning" in p.lower()
    assert "buy" not in p.lower()  # prompt explicitly forbids prescriptive language
```

- [ ] **Step 2: Run — FAIL**

Run: `uv run pytest tests/test_synth.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement prompt builder**

Write to `src/synth.py`:
```python
"""Gemini-based AI synthesis with guardrails + deterministic fallback."""
from __future__ import annotations
import json
import os
import re
from typing import Any

MODEL = "gemini-3.1-flash-lite"
MAX_OUTPUT_TOKENS = 120
FORBIDDEN_RE = re.compile(
    r"\b(buy|sell|short|long the|enter|exit|recommend|should|suggest|consider taking|"
    r"strong (?:buy|sell)|high probability|likely to|expect price|target)\b",
    flags=re.IGNORECASE,
)

INSTRUCTION = """You write 1-2 sentence structural readouts of options data for a personal-use trading dashboard.

The four patterns you may reference (these are already shown as colored BADGES next to each ticker, so do not just list them):
- Pinning: heavy net dealer gamma concentrated at a strike near spot.
- Gamma squeeze: dealers net SHORT gamma at strikes above or below spot.
- Flow conviction: net premium directional and large.
- Vol regime: front-week IV elevated vs 30-day IV (event-driven richness).

YOUR JOB IS NOT TO RESTATE THE BADGES. The user can already see them. Your job is to add information the badges DO NOT convey:
- Cross-pattern tension (e.g. "heavy call flow into a positive-gamma wall — buyers fighting the dealer hedge")
- Context the data implies (e.g. "front-week IV spike with no flow conviction reads as scheduled-event hedging, not directional bet")
- A structural relationship between two firing patterns
- A notable absence (e.g. "pinning setup at 450 but no flow conviction — pin likely to hold absent a catalyst")

RULES (strict):
1. Output 1-2 short sentences OR the literal string "NO_INSIGHT" if you cannot add information beyond what the badges show. NO_INSIGHT is preferred over a restatement.
2. Use ONLY descriptive language. Forbidden words: buy, sell, short, long the, enter, exit, recommend, should, suggest, target, strong (buy|sell), high probability, likely to.
3. If you do produce text, reference at least one specific number from the payload.
4. Do NOT predict direction, probability, or outcome. Describe what IS, not what WILL happen.
5. Do NOT enumerate firing pattern names — the badges do that. Reference a pattern only as part of a relationship or context point.
"""


def build_prompt(ticker: str, patterns: dict, key_numbers: dict) -> str:
    return (
        INSTRUCTION
        + f"\n\nTicker: {ticker}\n"
        + f"Patterns:\n{json.dumps(patterns, indent=2)}\n"
        + f"Key numbers:\n{json.dumps(key_numbers, indent=2)}\n"
        + "\nWrite the readout now:"
    )
```

- [ ] **Step 4: Run — PASS**

Run: `uv run pytest tests/test_synth.py -v`
Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add src/synth.py tests/test_synth.py
git commit -m "feat(synth): prompt builder with strict guardrails"
```

### Task 6.2: Output validator

**Files:**
- Modify: `src/synth.py`
- Modify: `tests/test_synth.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_synth.py`:
```python
from src.synth import validate_output


def test_validator_accepts_clean_output():
    text = "NVDA pinning setup at 450 with dealer gamma concentrated. Flow neutral."
    ok, reason = validate_output(text, must_contain_numbers=[450, 50])
    assert ok is True


def test_validator_rejects_prescriptive_language():
    text = "NVDA looks like a strong buy at 450."
    ok, reason = validate_output(text, must_contain_numbers=[450])
    assert ok is False
    assert "buy" in reason.lower() or "prescriptive" in reason.lower()


def test_validator_rejects_missing_number():
    text = "NVDA showing a pinning setup with concentrated gamma."
    ok, reason = validate_output(text, must_contain_numbers=[450])
    assert ok is False


def test_validator_rejects_too_many_sentences():
    text = "First sentence. Second sentence. Third sentence."
    ok, reason = validate_output(text, must_contain_numbers=[])
    assert ok is False
```

- [ ] **Step 2: Run — FAIL**

Run: `uv run pytest tests/test_synth.py -v`
Expected: validator tests FAIL.

- [ ] **Step 3: Implement**

Append to `src/synth.py`:
```python
def validate_output(text: str, must_contain_numbers: list[float]) -> tuple[bool, str]:
    """Return (ok, reason_if_not_ok)."""
    if not text or not text.strip():
        return False, "empty output"
    # Sentence count (rough): split on . ! ?; cap at 2
    sents = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if len(sents) > 2:
        return False, f"too many sentences ({len(sents)})"
    if FORBIDDEN_RE.search(text):
        return False, f"prescriptive language detected: {FORBIDDEN_RE.search(text).group(0)}"
    if must_contain_numbers:
        # Pull every numeric token from the text (incl. comma-formatted)
        text_nums = set()
        for m in re.finditer(r"-?\d[\d,\.]*", text):
            try:
                text_nums.add(float(m.group(0).replace(",", "")))
            except ValueError:
                pass
        wanted = set(float(n) for n in must_contain_numbers)
        if not (text_nums & wanted):
            return False, f"no required number found (wanted any of {sorted(wanted)})"
    return True, ""
```

- [ ] **Step 4: Run — PASS**

Run: `uv run pytest tests/test_synth.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/synth.py tests/test_synth.py
git commit -m "feat(synth): output validator (no prescriptive lang + numeric grounding)"
```

### Task 6.3: Deterministic fallback template

**Files:**
- Modify: `src/synth.py`
- Modify: `tests/test_synth.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_synth.py`:
```python
from src.synth import fallback_summary


def test_fallback_mentions_firing_pattern():
    patterns = {
        "pinning":       {"firing": True,  "intensity": 0.7, "note": {"strike": 450}},
        "gamma_squeeze": {"firing": False, "intensity": 0.0, "note": {}},
        "flow":          {"firing": False, "intensity": 0.0, "note": {}},
        "vol_regime":    {"firing": False, "intensity": 0.0, "note": {}},
    }
    s = fallback_summary("NVDA", patterns, {"spot": 449.50})
    assert "NVDA" in s
    assert "pin" in s.lower()
    assert "450" in s


def test_fallback_handles_no_firing():
    patterns = {k: {"firing": False, "intensity": 0.0, "note": {}}
                for k in ("pinning", "gamma_squeeze", "flow", "vol_regime")}
    s = fallback_summary("SPY", patterns, {"spot": 500.0})
    assert "SPY" in s
    assert "no" in s.lower() or "neutral" in s.lower()
```

- [ ] **Step 2: Implement**

Append to `src/synth.py`:
```python
def fallback_summary(ticker: str, patterns: dict, key_numbers: dict) -> str:
    """Deterministic synthesis when Gemini is unavailable or output is rejected."""
    firing = []
    if patterns.get("pinning", {}).get("firing"):
        strike = patterns["pinning"]["note"].get("strike", "?")
        firing.append(f"pinning setup at {strike}")
    if patterns.get("gamma_squeeze", {}).get("firing"):
        direction = patterns["gamma_squeeze"]["note"].get("direction", "?")
        firing.append(f"gamma squeeze setup {direction}")
    if patterns.get("flow", {}).get("firing"):
        side = patterns["flow"]["note"].get("side", "?")
        net = patterns["flow"]["note"].get("net_premium_usd", 0)
        firing.append(f"flow {side} (${net/1e6:.1f}M net)")
    if patterns.get("vol_regime", {}).get("firing"):
        regime = patterns["vol_regime"]["note"].get("regime", "?")
        iv = patterns["vol_regime"]["note"].get("iv_rank", "?")
        firing.append(f"IV {regime} (IVR {iv})")

    spot = key_numbers.get("spot")
    spot_str = f" Spot {spot:.2f}." if spot else ""
    if not firing:
        return f"{ticker} — no patterns firing.{spot_str}"
    return f"{ticker} — {', '.join(firing)}.{spot_str}".strip()
```

- [ ] **Step 3: Run — PASS**

Run: `uv run pytest tests/test_synth.py -v`
Expected: 7 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/synth.py tests/test_synth.py
git commit -m "feat(synth): deterministic fallback template"
```

### Task 6.4: Gemini call wrapper with validation + fallback

**Files:**
- Modify: `src/synth.py`
- Modify: `tests/test_synth.py`

- [ ] **Step 1: Write a test that monkeypatches the Gemini client**

Append to `tests/test_synth.py`:
```python
from src.synth import summarize


def test_summarize_uses_fallback_when_validation_fails(monkeypatch):
    """If Gemini returns prescriptive text, validator rejects → fallback used."""
    def fake_call(prompt: str):
        return "NVDA looks like a strong buy at 450.", {}   # prescriptive → rejected
    monkeypatch.setattr("src.synth._call_gemini", fake_call)

    patterns = {
        "pinning":       {"firing": True,  "intensity": 0.7, "note": {"strike": 450}},
        "gamma_squeeze": {"firing": False, "intensity": 0.0, "note": {}},
        "flow":          {"firing": False, "intensity": 0.0, "note": {}},
        "vol_regime":    {"firing": False, "intensity": 0.0, "note": {}},
    }
    out = summarize("NVDA", patterns, {"spot": 449.50, "iv_rank": 50})
    assert "buy" not in out.lower()  # fallback was used
    assert "NVDA" in out


def test_summarize_uses_fallback_when_no_insight(monkeypatch):
    """If Gemini returns NO_INSIGHT sentinel, fallback is used."""
    def fake_call(prompt: str):
        return "NO_INSIGHT", {"input_tokens": 50, "output_tokens": 2}
    monkeypatch.setattr("src.synth._call_gemini", fake_call)

    patterns = {
        "pinning":       {"firing": True,  "intensity": 0.7, "note": {"strike": 450}},
        "gamma_squeeze": {"firing": False, "intensity": 0.0, "note": {}},
        "flow":          {"firing": False, "intensity": 0.0, "note": {}},
        "vol_regime":    {"firing": False, "intensity": 0.0, "note": {}},
    }
    out = summarize("NVDA", patterns, {"spot": 449.50})
    assert "NVDA" in out
    assert "NO_INSIGHT" not in out


def test_summarize_uses_gemini_when_text_beats_fallback(monkeypatch):
    """Substantive synthesis text (longer than fallback, has numbers) wins."""
    def fake_call(prompt: str):
        return (
            "NVDA pinning at 450 sits inside heavy call OI at 460, suggesting buyers "
            "are fighting the dealer hedge into expiry 4 days out.",
            {"input_tokens": 200, "output_tokens": 30},
        )
    monkeypatch.setattr("src.synth._call_gemini", fake_call)

    patterns = {
        "pinning":       {"firing": True,  "intensity": 0.7, "note": {"strike": 450}},
        "gamma_squeeze": {"firing": False, "intensity": 0.0, "note": {}},
        "flow":          {"firing": False, "intensity": 0.0, "note": {}},
        "vol_regime":    {"firing": False, "intensity": 0.0, "note": {}},
    }
    out = summarize("NVDA", patterns, {"spot": 449.50})
    assert "fighting" in out.lower() or "buyers" in out.lower()
    assert "450" in out
```

- [ ] **Step 2: Implement Gemini call + summarize orchestration**

Append to `src/synth.py`:
```python
def _get_gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            key = None
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set (env var or Streamlit secrets)")
    return key


def _call_gemini(prompt: str) -> tuple[str, dict]:
    """Single Gemini call. Returns (response_text, usage_dict)."""
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
    """Heuristic: synthesis is 'better than fallback' if it's at least as long AND
    contains at least as many distinct numeric tokens. Else prefer fallback."""
    import re as _re
    def _numbers(s: str) -> set:
        nums = set()
        for m in _re.finditer(r"-?\d[\d,\.]*", s or ""):
            try:
                nums.add(float(m.group(0).replace(",", "")))
            except ValueError:
                pass
        return nums
    if not synthesis or not synthesis.strip():
        return False
    if len(synthesis) < len(fallback) * 0.7:
        return False
    if len(_numbers(synthesis)) < len(_numbers(fallback)):
        return False
    return True


def summarize(ticker: str, patterns: dict, key_numbers: dict) -> str:
    """Build prompt → call Gemini → validate → substance-check vs fallback → return."""
    must_contain = [n for n in key_numbers.values() if isinstance(n, (int, float))]
    for p in patterns.values():
        for v in p.get("note", {}).values():
            if isinstance(v, (int, float)):
                must_contain.append(v)

    fallback = fallback_summary(ticker, patterns, key_numbers)

    try:
        text, usage = _call_gemini(build_prompt(ticker, patterns, key_numbers))
    except Exception:
        return fallback

    # Token logging — print to stderr for build-time observability.
    if usage:
        import sys as _sys
        print(f"[gemini] {ticker} in={usage.get('input_tokens',0)} out={usage.get('output_tokens',0)}",
              file=_sys.stderr)

    # NO_INSIGHT sentinel: model explicitly declined to add information beyond badges.
    if text.strip().upper().startswith("NO_INSIGHT"):
        return fallback

    ok, _reason = validate_output(text, must_contain_numbers=must_contain)
    if not ok:
        return fallback

    # Substance check: if synthesis isn't materially better than fallback, use fallback.
    if not _substance_beats_fallback(text, fallback):
        return fallback

    return text
```

- [ ] **Step 3: Run — PASS**

Run: `uv run pytest tests/test_synth.py -v`
Expected: 9 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/synth.py tests/test_synth.py
git commit -m "feat(synth): summarize orchestrator (Gemini call + validator + fallback)"
```

### Task 6.5: Live Gemini schema-drift test (opt-in)

**Files:**
- Create: `tests/test_live_schema.py`

- [ ] **Step 1: Write the live test**

Write to `tests/test_live_schema.py`:
```python
"""Live-API smoke tests. Skipped by default; run with `pytest -m live`."""
from __future__ import annotations
import pytest
from src import uw_client
from src.synth import _call_gemini


@pytest.mark.live
def test_uw_endpoints_respond_with_expected_shape():
    """All five UW endpoints respond and the parsed shape matches the contract."""
    gex = uw_client.fetch_spot_exposures_strike("SPY")
    flow = uw_client.fetch_flow_alerts("SPY", limit=50)
    vol = uw_client.fetch_volatility("SPY")
    mp = uw_client.fetch_max_pain("SPY")
    hot = uw_client.fetch_flow_alerts(ticker=None, limit=15)

    assert uw_client.gex_records(gex), "gex_records returned empty list for SPY"
    assert isinstance(uw_client.flow_records(flow), list)
    assert isinstance(uw_client.term_structure(vol), list)
    assert mp is not None
    assert uw_client.hot_tickers(hot, 15), "hot_tickers returned empty list"


@pytest.mark.live
def test_gemini_responds_within_validator_constraints():
    """A real Gemini call on a synthetic payload either passes validator or returns NO_INSIGHT."""
    from src.synth import build_prompt, validate_output

    patterns = {
        "pinning":       {"firing": True,  "intensity": 0.8, "note": {"strike": 450.0}},
        "gamma_squeeze": {"firing": False, "intensity": 0.0, "note": {}},
        "flow":          {"firing": False, "intensity": 0.0, "note": {}},
        "vol_regime":    {"firing": False, "intensity": 0.0, "note": {"front_minus_30d_pts": 2.0}},
    }
    key_numbers = {"spot": 449.50, "max_gamma_strike": 450.0, "dte": 4}
    text, _usage = _call_gemini(build_prompt("NVDA", patterns, key_numbers))
    # NO_INSIGHT is an acceptable response — model explicitly declined to restate.
    if text.strip().upper().startswith("NO_INSIGHT"):
        return
    ok, reason = validate_output(text, must_contain_numbers=[450, 449.50, 4])
    assert ok, f"live Gemini output failed validator: {reason}\noutput was: {text!r}"
```

- [ ] **Step 2: Run plain pytest (should skip live)**

Run: `uv run pytest -v`
Expected: live tests are SKIPPED; other tests still pass.

- [ ] **Step 3: Run with `-m live`**

Run: `uv run pytest -m live -v`
Expected: live tests run and pass. If the Gemini live test fails, inspect the actual output and adjust either the prompt or the validator's tolerance — log the change in MEMORY.md.

- [ ] **Step 4: Commit**

```bash
git add tests/test_live_schema.py
git commit -m "test: opt-in live schema-drift checks for UW + Gemini"
```

---

## Phase 7: UI assembly (~5 hr)

This is the biggest phase. Build the Streamlit scaffold first with mocked data, then progressively wire in real data, then the click-to-pin interaction, then the two-phase synthesis render.

### Task 7.1: Badge help text + color constants

**Files:**
- Create: `src/badge_help.py`

- [ ] **Step 1: Write the constants**

Write to `src/badge_help.py`:
```python
"""Centralized badge tooltips and color mapping.

Edit this file when refining badge UX — every view that renders badges reads
from here, so changes propagate consistently.
"""
from __future__ import annotations

# One color per pattern category. Direction-agnostic patterns are not coerced
# into green/red. Saturation/opacity encodes firing intensity at render time.
PATTERN_COLORS = {
    "pinning":       "#7AA2F7",  # blue
    "gamma_squeeze": "#E0AF68",  # orange
    "flow_long":     "#9ECE6A",  # green (directional)
    "flow_short":    "#F7768E",  # red   (directional)
    "flow_neutral":  "#9AA5CE",  # gray  (rare; non-firing flow normally hidden)
    "vol_regime":    "#BB9AF7",  # purple
}

TOOLTIPS = {
    "pinning":       "Heavy net dealer gamma concentrated near spot — dealer hedging tends to pin price near that strike into expiry.",
    "gamma_squeeze": "Dealers net SHORT gamma at strikes above (or below) spot — if price crosses, dealers chase, amplifying the move.",
    "flow":          "Net premium is large AND directional — institutional positioning is leaning. Side shows direction.",
    "vol_regime":    "Implied vol is elevated (premium-selling favored) or crushed (premium-buying favored), based on IV rank.",
}


def color_for(pattern_kind: str, note: dict | None = None) -> str:
    """Return the hex color string for a pattern badge."""
    if pattern_kind == "flow" and note:
        side = note.get("side", "neutral")
        return PATTERN_COLORS.get(f"flow_{side}", PATTERN_COLORS["flow_neutral"])
    return PATTERN_COLORS.get(pattern_kind, "#9AA5CE")


def label_for(pattern_kind: str, note: dict | None = None) -> str:
    """Short text label for the badge body."""
    note = note or {}
    if pattern_kind == "pinning":
        strike = note.get("strike")
        return f"PIN @ {strike:g}" if strike else "PIN"
    if pattern_kind == "gamma_squeeze":
        direction = note.get("direction", "")
        arrow = "↑" if direction == "up" else "↓" if direction == "down" else ""
        return f"Γ-WALL {arrow}".strip()
    if pattern_kind == "flow":
        side = note.get("side", "?")
        net_m = note.get("net_premium_usd", 0) / 1e6
        sign = "+" if net_m >= 0 else ""
        return f"FLOW {sign}${net_m:.1f}M ({side})"
    if pattern_kind == "vol_regime":
        ivr = note.get("iv_rank", "?")
        return f"IVR {ivr:.0f}" if isinstance(ivr, (int, float)) else "IVR ?"
    return pattern_kind.upper()
```

- [ ] **Step 2: Smoke-import**

Run: `uv run python -c "from src.badge_help import color_for, label_for; print(color_for('pinning'), label_for('pinning', {'strike': 450}))"`
Expected: `#7AA2F7 PIN @ 450`

- [ ] **Step 3: Commit**

```bash
git add src/badge_help.py
git commit -m "feat(badge): central color + tooltip constants"
```

### Task 7.2: App skeleton — page header + sidebar shell

**Files:**
- Create: `app.py`

- [ ] **Step 1: Write the skeleton**

Write to `app.py`:
```python
"""Weekly Options Pre-Trade Brief — Streamlit entrypoint."""
from __future__ import annotations
import streamlit as st

from src import watchlist

# ---------- Page config ----------
st.set_page_config(
    page_title="Weekly Options Pre-Trade Brief",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Header ----------
st.title("Weekly Options Pre-Trade Brief")
st.caption(
    "Decision-support for personal weekly options trades. "
    "Not financial advice. Personal use only."
)

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Watchlist")
    user_input = st.text_input(
        "Override (comma-separated tickers)",
        value="",
        help="Leave blank to use the default list + UW's 'hot today' leaders.",
    )
    if st.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

    with st.expander("How this works"):
        st.markdown("""
**What this dashboard does**

Each row shows whether a ticker is exhibiting one of four structural setups for a weekly options trade:

- 🟦 **Pinning** — heavy dealer gamma at a strike pulls price toward it.
- 🟧 **Gamma squeeze** — dealers short gamma at strikes that, if crossed, force them to chase price.
- 🟩/🟥 **Flow** — net premium is directional and large.
- 🟪 **Vol regime** — implied vol is unusually high (premium-selling favored) or low (premium-buying favored).

Data comes from Unusual Whales (Basic tier, 30-day lookback, no real-time streaming). The AI-written headline on each row summarizes what's in the numbers — it does **not** give trade signals or predictions.

Tap any row to see the supporting charts in the pinned card above.
        """)

# ---------- Resolve watchlist ----------
fixed = watchlist.parse_user_list(user_input) or watchlist.DEFAULT_FIXED
# UW "hot today" comes later — placeholder for now
tickers = watchlist.merge_watchlist(fixed, hot=[], cap=watchlist.DEFAULT_FIRST_BATCH)

st.subheader(f"Scan ({len(tickers)} tickers)")
st.write(tickers)  # placeholder — replaced in next task
```

- [ ] **Step 2: Run the app**

In a separate terminal:
```bash
uv run streamlit run app.py --server.port 8501
```
Operator: open `http://localhost:8501`. Confirm:
- Title + subtitle render
- Sidebar shows watchlist input, refresh button, "How this works" expander
- Default tickers list shows below

- [ ] **Step 3: Capture initial screenshot to litterbox for the operator to confirm**

In another terminal:
```bash
# Use your system's screenshot tool to capture localhost:8501 to ./screen.png, then:
curl -F "reqtype=fileupload" -F "time=72h" -F "fileToUpload=@screen.png" https://litterbox.catbox.moe/resources/internals/api.php
```
Send the resulting URL to the operator. (If headless, skip — operator opens local URL.)

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat(app): page skeleton with header, sidebar, watchlist resolution"
```

### Task 7.3: Concurrent data fetch + per-ticker pattern detection

**Files:**
- Create: `src/fetch.py`

- [ ] **Step 1: Write the orchestration module**

Write to `src/fetch.py`:
```python
"""Concurrent per-ticker UW data fetch + pattern detection.

Streamlit caches at this layer (15 min TTL on UW data, pattern verdicts derive
on the fly because patterns are pure and cheap).
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional
import streamlit as st

from src import uw_client, patterns

UW_TTL_S = 900   # 15 min


@dataclass
class TickerData:
    ticker: str
    spot: float | None
    iv_rank: float | None
    gex_recs: list[dict]
    flow_recs: list[dict]
    oi_recs: list[dict]
    term: list[dict]
    max_pain: float | None = None
    error: Optional[str] = None


@st.cache_data(ttl=UW_TTL_S, show_spinner=False)
def fetch_one(ticker: str) -> TickerData:
    """Fetch all five UW endpoints for one ticker. Errors are captured, not raised."""
    try:
        vol = uw_client.fetch_volatility(ticker)
        gex = uw_client.fetch_spot_exposures_strike(ticker)
        flow = uw_client.fetch_flow_alerts(ticker, limit=50)
        oi = uw_client.fetch_oi_strike(ticker)
        mp = uw_client.fetch_max_pain(ticker)
        return TickerData(
            ticker=ticker,
            spot=uw_client.extract_spot(vol),
            iv_rank=uw_client.extract_iv_rank(vol),
            gex_recs=uw_client.gex_records(gex),
            flow_recs=uw_client.flow_records(flow),
            oi_recs=uw_client.oi_records(oi),
            term=uw_client.term_structure(vol),
            max_pain=uw_client.max_pain_value(mp),
        )
    except Exception as e:
        return TickerData(
            ticker=ticker, spot=None, iv_rank=None,
            gex_recs=[], flow_recs=[], oi_recs=[], term=[],
            max_pain=None, error=f"{type(e).__name__}: {e}",
        )


def fetch_batch(tickers: list[str]) -> dict[str, TickerData]:
    """Fetch many tickers concurrently. Returns dict keyed by ticker."""
    out: dict[str, TickerData] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for td in pool.map(fetch_one, tickers):
            out[td.ticker] = td
    return out


def patterns_for(td: TickerData) -> dict:
    """Run all four pattern detectors on one ticker's data."""
    if td.error or td.spot is None:
        return {
            "pinning":       {"firing": False, "intensity": 0.0, "note": {"reason": "no_data"}},
            "gamma_squeeze": {"firing": False, "intensity": 0.0, "note": {"reason": "no_data"}},
            "flow":          {"firing": False, "intensity": 0.0, "note": {"reason": "no_data"}},
            "vol_regime":    {"firing": False, "intensity": 0.0, "note": {"reason": "no_data"}},
        }
    bundle = patterns.detect_all(
        gex_recs=td.gex_recs,
        flow_recs=td.flow_recs,
        spot=td.spot,
        term_structure=td.term,
    )
    return {k: v.to_dict() for k, v in bundle.items()}
```

- [ ] **Step 2: Add a smoke test**

Append to `tests/test_uw_client.py`:
```python
def test_fetch_module_imports():
    """The fetch module imports without side effects."""
    from src import fetch
    assert hasattr(fetch, "fetch_one")
    assert hasattr(fetch, "fetch_batch")
    assert hasattr(fetch, "patterns_for")
```

- [ ] **Step 3: Run — PASS**

Run: `uv run pytest -v`
Expected: all tests pass (the new one is a smoke import).

- [ ] **Step 4: Commit**

```bash
git add src/fetch.py tests/test_uw_client.py
git commit -m "feat(fetch): concurrent per-ticker data + cached pattern derivation"
```

### Task 7.4: Scan table view — with placeholder synthesis

**Files:**
- Create: `src/views/scan_table.py`
- Modify: `app.py`

- [ ] **Step 1: Write the scan-table renderer**

Write to `src/views/scan_table.py`:
```python
"""Render the scan table: one row per ticker, with badges and a synthesis cell."""
from __future__ import annotations
import pandas as pd
import streamlit as st

from src import badge_help

PLACEHOLDER = "Generating analysis…"


def _badges_md(patterns: dict) -> str:
    """Compose an inline HTML/markdown string of firing badges only."""
    parts = []
    for kind in ("pinning", "gamma_squeeze", "flow", "vol_regime"):
        p = patterns.get(kind, {})
        if not p.get("firing"):
            continue
        color = badge_help.color_for(kind, p.get("note"))
        label = badge_help.label_for(kind, p.get("note"))
        opacity = max(0.3, min(1.0, p.get("intensity", 0.5)))
        parts.append(
            f"<span style='background:{color};opacity:{opacity:.2f};"
            f"color:#0E1117;padding:2px 8px;border-radius:6px;"
            f"font-size:0.78em;margin-right:4px;font-weight:600;'>"
            f"{label}</span>"
        )
    return " ".join(parts) if parts else "<span style='color:#666;'>—</span>"


def render(rows: list[dict]) -> str | None:
    """Render the scan table. Returns the clicked ticker (or None).

    `rows` is a list of dicts with keys: ticker, synthesis, patterns.
    """
    df = pd.DataFrame([{
        "Ticker": r["ticker"],
        "Analysis": r["synthesis"],
    } for r in rows])

    # Render the table as a clickable dataframe
    event = st.dataframe(
        df,
        key="scan_table",
        on_select="rerun",
        selection_mode="single-row",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ticker": st.column_config.TextColumn(width="small"),
            "Analysis": st.column_config.TextColumn(width="large"),
        },
    )

    # Below the table: per-row badges (because Streamlit dataframe doesn't render HTML cells)
    st.markdown("**Pattern badges** (firing patterns only):")
    for r in rows:
        st.markdown(
            f"**{r['ticker']}** {_badges_md(r['patterns'])}",
            unsafe_allow_html=True,
        )

    if event.selection and event.selection.rows:
        idx = event.selection.rows[0]
        return rows[idx]["ticker"]
    return None
```

- [ ] **Step 2: Wire it into `app.py`**

Replace the bottom of `app.py` (everything after `st.subheader(...)`) with:
```python
from src import fetch
from src.synth import fallback_summary
from src.views import scan_table

# Fetch + derive patterns (synth comes in next task)
with st.spinner(f"Loading {len(tickers)} tickers…"):
    td_map = fetch.fetch_batch(tickers)

rows = []
for t in tickers:
    td = td_map[t]
    pats = fetch.patterns_for(td)
    rows.append({
        "ticker": t,
        "synthesis": fallback_summary(t, pats, {"spot": td.spot, "iv_rank": td.iv_rank}),
        "patterns": pats,
    })

clicked = scan_table.render(rows)
if clicked:
    st.session_state.pinned_ticker = clicked
    st.query_params["ticker"] = clicked

if td_data_errors := [td for td in td_map.values() if td.error]:
    if len(td_data_errors) > len(tickers) / 2:
        st.warning(f"UW data unavailable for {len(td_data_errors)}/{len(tickers)} tickers. "
                   "Some rows show no patterns. Check API status.")
```

- [ ] **Step 3: Restart the app and verify**

Restart `streamlit run app.py`. Confirm:
- 10 rows render with ticker + analysis (using deterministic fallback text for now)
- Badges appear below the table, only for firing patterns
- Clicking a row writes `?ticker=X` to the URL

- [ ] **Step 4: Commit**

```bash
git add src/views/scan_table.py app.py
git commit -m "feat(app): scan table with deterministic synthesis + click-to-pin URL"
```

### Task 7.5: Ticker card view — pinned drill-down with charts

**Files:**
- Create: `src/views/ticker_card.py`
- Modify: `app.py`

- [ ] **Step 1: Write the renderer**

Write to `src/views/ticker_card.py`:
```python
"""Render the pinned ticker card: synthesis + three vertically-stacked charts + key strikes."""
from __future__ import annotations
import streamlit as st

from src import charts, fetch


def render_empty():
    """Empty-state prompt when no ticker is pinned."""
    st.info("Tap a row below to see detailed analysis.")


def render(ticker: str, td: fetch.TickerData, synthesis: str, patterns: dict):
    """Render the pinned card for a ticker."""
    head_col, close_col = st.columns([10, 1])
    with head_col:
        st.markdown(f"### {ticker}")
        st.markdown(f"_{synthesis}_")
    with close_col:
        if st.button("✕", key="unpin", help="Unpin"):
            st.session_state.pinned_ticker = None
            if "ticker" in st.query_params:
                del st.query_params["ticker"]
            st.rerun()

    if td.error:
        st.error(f"Couldn't load data for {ticker}: {td.error}")
        if st.button(f"Retry {ticker}", key=f"retry_{ticker}"):
            fetch.fetch_one.clear()
            st.rerun()
        return

    # Three charts stacked vertically — same on desktop and mobile
    st.plotly_chart(
        charts.gamma_profile_figure(td.gex_recs, spot=td.spot or 0, ticker=ticker),
        use_container_width=True,
    )
    st.plotly_chart(
        charts.oi_per_strike_figure(td.oi_recs, spot=td.spot or 0,
                                    max_pain=td.max_pain, ticker=ticker),
        use_container_width=True,
    )
    st.plotly_chart(
        charts.vol_term_structure_figure(td.term, ticker=ticker),
        use_container_width=True,
    )
```

- [ ] **Step 2: Wire it into `app.py` above the scan table**

Modify `app.py` — between the `tickers = ...` line and the fetch/render block, insert:
```python
# ---------- URL persistence: read ?ticker= on cold load ----------
if "pinned_ticker" not in st.session_state:
    st.session_state.pinned_ticker = st.query_params.get("ticker")

# ---------- Pinned card (top section) ----------
from src.views import ticker_card  # placed here to keep top-of-file imports flat
```

After the fetch block (right after `td_map = fetch.fetch_batch(tickers)`), insert:
```python
pinned = st.session_state.get("pinned_ticker")
if pinned:
    if pinned not in td_map:
        # Pinned ticker isn't in the visible batch — fetch it independently
        td_map[pinned] = fetch.fetch_one(pinned)
    pinned_td = td_map[pinned]
    pinned_patterns = fetch.patterns_for(pinned_td)
    pinned_synth = fallback_summary(pinned, pinned_patterns, {"spot": pinned_td.spot, "iv_rank": pinned_td.iv_rank})
    ticker_card.render(pinned, pinned_td, pinned_synth, pinned_patterns)
else:
    ticker_card.render_empty()

st.divider()
```

(The existing scan-table block follows.)

- [ ] **Step 3: Restart and verify**

Restart streamlit. Verify:
- Naked load shows "Tap a row below…" prompt
- Clicking a row pins the card with charts stacked vertically
- ✕ unpin clears the card and the URL param
- Reloading with `?ticker=NVDA` auto-pins NVDA

- [ ] **Step 4: Commit**

```bash
git add src/views/ticker_card.py app.py
git commit -m "feat(app): pinned ticker card with stacked charts + URL persistence"
```

### Task 7.6: "Load 10 more" button

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add the load-more logic**

In `app.py`, change the watchlist resolution from:
```python
tickers = watchlist.merge_watchlist(fixed, hot=[], cap=watchlist.DEFAULT_FIRST_BATCH)
```

to:
```python
all_candidates = watchlist.merge_watchlist(fixed, hot=[], cap=watchlist.DEFAULT_CAP)
visible_count = st.session_state.get("visible_count", watchlist.DEFAULT_FIRST_BATCH)
tickers = all_candidates[:visible_count]
```

Then below the scan_table render, add:
```python
remaining = len(all_candidates) - len(tickers)
if remaining > 0:
    if st.button(f"Load 10 more ({remaining} available)"):
        st.session_state.visible_count = min(visible_count + 10, len(all_candidates))
        st.rerun()
```

- [ ] **Step 2: Restart and verify**

Restart streamlit. Verify the "Load 10 more" button appears under the scan table and reveals additional rows when clicked.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(app): 'Load 10 more' button for batch extension"
```

### Task 7.7: UW "hot today" merge

**Files:**
- Modify: `app.py`
- Modify: `src/fetch.py`

- [ ] **Step 1: Add a cached hot-today fetcher**

Append to `src/fetch.py`:
```python
@st.cache_data(ttl=UW_TTL_S, show_spinner=False)
def fetch_hot_tickers(limit: int = 15) -> list[str]:
    try:
        payload = uw_client.fetch_flow_alerts(ticker=None, limit=limit)
        return uw_client.hot_tickers(payload, limit)
    except Exception:
        return []
```

- [ ] **Step 2: Wire into app**

In `app.py`, replace:
```python
all_candidates = watchlist.merge_watchlist(fixed, hot=[], cap=watchlist.DEFAULT_CAP)
```
with:
```python
hot = fetch.fetch_hot_tickers(15)
all_candidates = watchlist.merge_watchlist(fixed, hot=hot, cap=watchlist.DEFAULT_CAP)
```

- [ ] **Step 3: Restart and verify**

Restart streamlit. Tickers list should now include UW's hot tickers after the fixed list. If the hot-today endpoint failed, the call returns `[]` and the app still works with the fixed list only.

- [ ] **Step 4: Commit**

```bash
git add src/fetch.py app.py
git commit -m "feat(app): merge UW hot-today tickers into the watchlist"
```

### Task 7.7b: Source indicator on scan rows (📌 user list vs 🔥 hot today)

Per product-review item #4: the merged watchlist confuses "tickers I always watch" with "tickers UW says are hot today." A small icon distinguishes them so the user knows what they're looking at.

**Files:**
- Modify: `app.py`
- Modify: `src/views/scan_table.py`

- [ ] **Step 1: Compute the source map in `app.py`**

In `app.py`, after `hot = fetch.fetch_hot_tickers(15)`:
```python
fixed_set = {t.upper() for t in fixed}
hot_set = {t.upper() for t in hot}
def _source_icon(t: str) -> str:
    t = t.upper()
    if t in fixed_set:
        return "📌"   # user's fixed list
    if t in hot_set:
        return "🔥"   # UW hot today
    return ""
```

- [ ] **Step 2: Thread it through to the scan table renderer**

In the row-build block in `app.py`, add the source to each row dict:
```python
prelim_rows.append({
    "ticker": t,
    "source_icon": _source_icon(t),
    "patterns": pats,
    "spot": td.spot,
    "iv_rank": td.iv_rank,
})
```

- [ ] **Step 3: Update `src/views/scan_table.py` to render the icon**

In `render()`, change the dataframe construction to prepend the source icon to the ticker column:
```python
df = pd.DataFrame([{
    "Ticker": f"{r.get('source_icon','')} {r['ticker']}".strip(),
    "Analysis": r["synthesis"],
} for r in rows])
```

And in the per-row badge loop:
```python
for r in rows:
    prefix = "▶ " if r["ticker"] == pinned else "  "
    icon = r.get("source_icon", "")
    st.markdown(
        f"{prefix}{icon} **{r['ticker']}** {_badges_md(r['patterns'])}",
        unsafe_allow_html=True,
    )
```

- [ ] **Step 4: Add a legend caption above the scan table**

In `app.py`, just before `clicked = scan_table.render(...)`:
```python
st.caption("📌 = your fixed list · 🔥 = UW hot today")
```

- [ ] **Step 5: Restart and verify**

Restart streamlit. Confirm:
- Tickers from the default fixed list show 📌
- Tickers added by UW hot-today show 🔥
- Tickers that appear in BOTH show 📌 (fixed wins — it's the user's intention)
- Legend caption is visible above the table

- [ ] **Step 6: Commit**

```bash
git add app.py src/views/scan_table.py
git commit -m "feat(ui): source indicator distinguishing fixed-list vs hot-today tickers"
```

### Task 7.8: Two-phase synthesis render (single-paint with concurrent calls)

Per design spec § 4 and the post-review decision: default to single-paint with concurrent Gemini calls (2-3 s total), not polling. Polling is the documented fallback if Gemini turns out slower than budgeted.

**Files:**
- Modify: `src/fetch.py`
- Modify: `app.py`

- [ ] **Step 1: Add a cached synthesis function + cost guard in `fetch.py`**

Append to `src/fetch.py`:
```python
from src import synth as _synth
import hashlib
import json

SYNTH_SESSION_CALL_LIMIT = 100   # per design spec § 5: hard ceiling against runaway loops


def _patterns_hash(patterns: dict, key_numbers: dict) -> str:
    """Stable hash of pattern verdicts + key numbers → cache key for synthesis."""
    payload = json.dumps({"p": patterns, "k": key_numbers}, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()


def _bumped_call_count() -> int:
    """Increment the session synthesis-call counter and return the new value."""
    n = st.session_state.get("synth_call_count", 0) + 1
    st.session_state.synth_call_count = n
    return n


@st.cache_data(ttl=1800, show_spinner=False)
def synthesize_one(ticker: str, _cache_key: str, patterns: dict, key_numbers: dict) -> str:
    """Cache-keyed wrapper around synth.summarize. _cache_key is the hash arg.

    Hard cap on real Gemini calls per session: if exceeded, returns the
    deterministic fallback without hitting the API. Cache hits don't count.
    """
    if _bumped_call_count() > SYNTH_SESSION_CALL_LIMIT:
        return _synth.fallback_summary(ticker, patterns, key_numbers)
    return _synth.summarize(ticker, patterns, key_numbers)


def synthesize_batch(rows: list[dict]) -> dict[str, str]:
    """Concurrently summarize many tickers. Returns dict ticker → text."""
    out: dict[str, str] = {}
    def _job(row):
        key_numbers = {"spot": row["spot"], "iv_rank": row["iv_rank"]}
        key = _patterns_hash(row["patterns"], key_numbers)
        return row["ticker"], synthesize_one(row["ticker"], key, row["patterns"], key_numbers)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for ticker, text in pool.map(_job, rows):
            out[ticker] = text
    return out
```

- [ ] **Step 2: Update `app.py` to use Gemini synthesis**

Replace the row-build block in `app.py`:
```python
rows = []
for t in tickers:
    td = td_map[t]
    pats = fetch.patterns_for(td)
    rows.append({
        "ticker": t,
        "synthesis": fallback_summary(t, pats, {"spot": td.spot, "iv_rank": td.iv_rank}),
        "patterns": pats,
    })
```
with:
```python
prelim_rows = []
for t in tickers:
    td = td_map[t]
    pats = fetch.patterns_for(td)
    prelim_rows.append({
        "ticker": t,
        "patterns": pats,
        "spot": td.spot,
        "iv_rank": td.iv_rank,
    })

# Single-paint concurrent synthesis (Gemini calls in parallel, total ~2-3s)
with st.spinner("Generating analyses…"):
    synth_map = fetch.synthesize_batch(prelim_rows)

rows = [
    {**r, "synthesis": synth_map.get(r["ticker"], "")}
    for r in prelim_rows
]
```

Similarly, update the pinned-card synthesis to use the real call:
```python
pinned_synth = fetch.synthesize_one(
    pinned,
    fetch._patterns_hash(pinned_patterns, {"spot": pinned_td.spot, "iv_rank": pinned_td.iv_rank}),
    pinned_patterns,
    {"spot": pinned_td.spot, "iv_rank": pinned_td.iv_rank},
)
```

- [ ] **Step 3: Restart and verify**

Restart streamlit. On cold load:
- Spinner shows "Generating analyses…" for ~2-3 s
- Then the table renders with real AI-written headlines per row
- Subsequent reloads hit cache and are fast

If single-paint feels too slow in practice (> 10 s consistently), fall back to the polling approach documented in the spec — change `synthesize_batch` to dispatch in background threads writing to `st.session_state[f"synth_{ticker}"]` and let the render show "Generating analysis…" placeholders. Document the change in MEMORY.md.

- [ ] **Step 4: Commit**

```bash
git add src/fetch.py app.py
git commit -m "feat(synth): single-paint concurrent Gemini synthesis with 30-min cache"
```

### Task 7.9: Pinned-row visual indicator + sidebar staleness

**Files:**
- Modify: `app.py`
- Modify: `src/views/scan_table.py`

- [ ] **Step 1: Show pinned ticker indicator in scan table**

In `src/views/scan_table.py`, modify the `render` function signature to accept a `pinned` arg, and modify the per-row badge render to prefix the pinned row:
```python
def render(rows: list[dict], pinned: str | None = None) -> str | None:
    # ... (existing dataframe code) ...

    st.markdown("**Pattern badges** (firing patterns only):")
    for r in rows:
        prefix = "▶ " if r["ticker"] == pinned else "  "
        st.markdown(
            f"{prefix}**{r['ticker']}** {_badges_md(r['patterns'])}",
            unsafe_allow_html=True,
        )
    # ... (existing return) ...
```

In `app.py`, update the call:
```python
clicked = scan_table.render(rows, pinned=st.session_state.get("pinned_ticker"))
```

- [ ] **Step 2: Add staleness indicator + synth call counter + threshold debug panel in sidebar**

In `app.py`, near the sidebar code, after the Refresh button:
```python
import datetime as _dt
from src.fetch import SYNTH_SESSION_CALL_LIMIT
from src import patterns as _patterns

# Staleness
last_refresh = st.session_state.get("last_refresh_ts")
if not last_refresh:
    last_refresh = _dt.datetime.now().strftime("%H:%M")
    st.session_state.last_refresh_ts = last_refresh
st.caption(f"UW data: refreshed {last_refresh}")

# Session synth call count (cost guard visibility per spec § 5)
calls = st.session_state.get("synth_call_count", 0)
st.caption(f"Gemini calls this session: {calls} / {SYNTH_SESSION_CALL_LIMIT}")

# Threshold transparency (product-review item #1 / spec § 2)
with st.expander("v0.1 calibration values"):
    st.caption("These thresholds determine when each pattern badge 'fires'. They are heuristics, not validated by a model — visible here so you can interpret the badges honestly.")
    st.code(f"""\
Pinning concentration > {_patterns.PIN_THRESHOLD}
Gamma squeeze ratio   > {_patterns.SQUEEZE_RATIO}x other side
Flow min total $      > ${_patterns.FLOW_MIN_TOTAL:,}
Flow min skew         > {_patterns.FLOW_MIN_SKEW}
Vol inversion         > {_patterns.VOL_INVERSION_THRESHOLD_PTS} vol pts (front - 30d)\
""", language="text")
```

When the Refresh button fires, update:
```python
if st.button("Refresh data"):
    st.cache_data.clear()
    st.session_state.last_refresh_ts = _dt.datetime.now().strftime("%H:%M")
    st.rerun()
```

- [ ] **Step 3: Restart and verify**

Restart streamlit. Verify:
- Pinned ticker shows `▶ TICKER` in the badge list
- Sidebar shows "UW data: refreshed HH:MM"
- Refresh button updates the time

- [ ] **Step 4: Commit**

```bash
git add app.py src/views/scan_table.py
git commit -m "feat(ui): pinned-row indicator + staleness timestamp"
```

---

## Phase 8: Deploy + portfolio writeup (~1.5 hr)

### Task 8.1: README.md (portfolio writeup)

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

Write to `README.md`:
```markdown
# Weekly Options Pre-Trade Brief

A Streamlit dashboard that takes a watchlist of tickers and shows which structural options-trade pattern is firing on each right now — using Unusual Whales data on dealer positioning, flow, vol surface, and key strikes.

**Live demo:** _[fill in Streamlit Cloud URL after deploy]_

## What it does

Each row in the scan table tells you whether a ticker is currently exhibiting one of four structural setups:

- **Pinning** — heavy net dealer gamma at a strike near spot → dealer hedging tends to pin price to that strike into expiry.
- **Gamma squeeze** — dealers net SHORT gamma at strikes above (or below) spot → crossing the strike forces dealers to chase, amplifying the move.
- **Flow conviction** — net premium directional and large → institutional positioning leaning.
- **Vol regime** — implied vol elevated (premium-selling favored) or crushed (premium-buying favored).

Click any row to see the supporting charts (gamma profile, flow timeline, IV term structure) in a pinned card at the top.

## What it is NOT

- Not a trade signal generator. No "buy this" calls, no conviction scores, no predictions.
- Not a backtester. No claims of edge.
- Not a journal — sessions don't persist; trade logging is intentionally not included (see [FUTURE_WORK.md](FUTURE_WORK.md)).
- Not multi-user — UW Basic-tier API is personal-use-only.
- Not real-time — 30-day lookback maximum, REST polling, no WebSocket.

## Demo / API usage notice

The live URL is intended for limited evaluation by the operator and a small audience. Unusual Whales' Basic-tier API is licensed for personal use; the demo is NOT a public service. Heavy traffic against the live URL would exhaust the API quota and likely violate UW's terms. If you're evaluating the project, please run a few queries and then explore the code instead of scripting traffic against the URL.

## How it works

1. Concurrently fetches per-ticker dealer gamma, flow, and volatility data from the Unusual Whales API.
2. Pure-function pattern detectors evaluate the four theses against thresholds defined in `src/patterns.py`.
3. Gemini Flash Lite writes a 1–2 sentence headline per ticker, validated against a no-prescriptive-language guardrail (with deterministic template fallback).
4. Streamlit renders the scan table + pinned drill-down. Single layout for desktop and mobile.

## Stack

- Python 3.11 + Streamlit 1.35+
- `uv` package manager
- Plotly for charts
- Unusual Whales API (Basic tier) via `requests`
- Google Gemini (`gemini-3.1-flash-lite`) via the `google-genai` SDK

## Run locally

```bash
uv sync
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml — add UW_API_KEY and GEMINI_API_KEY
uv run streamlit run app.py
```

Tests:

```bash
uv run pytest                # fixture-based, fast
uv run pytest -m live        # opt-in live API schema-drift checks
```

Live UW probe (sanity-check the API):

```bash
uv run python scripts/probe_uw.py SPY
```

## Project structure

```
src/
├── uw_client.py     # REST wrapper + response normalizers
├── patterns.py      # pure pattern detectors
├── synth.py         # Gemini prompt, validator, fallback
├── fetch.py         # cached concurrent orchestration
├── charts.py        # Plotly figure builders
├── watchlist.py     # ticker merge + dedup
├── badge_help.py    # tooltip text + per-pattern colors
└── views/
    ├── scan_table.py
    └── ticker_card.py
tests/
├── fixtures/        # recorded UW JSON
├── conftest.py
├── test_*.py
└── test_live_schema.py    # opt-in live tests
scripts/
├── probe_uw.py            # manual live sanity script
└── record_fixtures.py     # refresh tests/fixtures/
docs/superpowers/
├── specs/2026-05-23-pre-trade-brief-design.md
└── plans/2026-05-23-pre-trade-brief.md
```

## Future work

See [FUTURE_WORK.md](FUTURE_WORK.md) — intentional scope-deferrals.

---

Built by gabjew90 as the portfolio artifact for an Unusual Whales Builder Community Lead application, 2026-05.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with what-it-does, how-it-works, run-locally"
```

### Task 8.2: Resync `requirements.txt` for deploy

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Sync**

Run: `bash scripts/sync_requirements.sh`

- [ ] **Step 2: Verify content**

Run: `head -20 requirements.txt`
Expected: streamlit, requests, plotly, pandas, google-genai listed.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: sync requirements.txt for Streamlit Cloud deploy"
```

### Task 8.3: Create GitHub repo + push

**Files:** none (operator action)

- [ ] **Step 1: Operator creates GitHub repo**

Operator: open GitHub mobile app or browser, create a new PUBLIC repository named `uw-pretrade-brief` (or your preferred name). Do NOT init with README/license — local repo already has those.

- [ ] **Step 2: Send the agent the repo URL**

E.g., `https://github.com/<operator>/uw-pretrade-brief.git`

- [ ] **Step 3: Agent adds remote and pushes**

```bash
git remote add origin <URL>
git push -u origin main
```

- [ ] **Step 4: Verify**

Run: `git remote -v`
Expected: shows the remote URL for both fetch and push.

- [ ] **Step 5: Confirm on GitHub**

Operator: open the repo URL in browser, confirm all files are visible.

### Task 8.4: Deploy to Streamlit Cloud

**Files:** none (operator action via browser)

- [ ] **Step 1: Operator goes to share.streamlit.io**

Open https://share.streamlit.io and sign in with the GitHub account.

- [ ] **Step 2: New app**

Click "New app" → select the repo → branch `main` → main file path `app.py` → app URL of choice.

- [ ] **Step 3: Add secrets in dashboard**

Settings → Secrets → paste:
```toml
UW_API_KEY = "..."
GEMINI_API_KEY = "..."
```
Save.

- [ ] **Step 4: Deploy**

Click Deploy. Wait ~2 min for the build to complete.

- [ ] **Step 5: Verify live URL**

Operator: open the resulting `https://<repo-name>.streamlit.app` URL, confirm the scan table renders.

- [ ] **Step 6: Send URL to agent**

Agent then updates README.md to include the live URL, commits, pushes.

### Task 8.5: Phone-device test

**Files:** none (operator action)

- [ ] **Step 1: Operator opens the live URL on their phone**

Verify:
- Scan table is readable
- Tapping a row pins it (URL updates with `?ticker=X`)
- Three charts stack vertically and are legible
- "Load 10 more" works
- The "How this works" expander opens

Report any issues to the agent. Common fixes:
- Charts too cramped → reduce `height` in `src/charts.py` (currently 280)
- Tap targets too small → wrap rows in `st.container(border=True)`

- [ ] **Step 2: Iterate on any issues found**

Make changes, commit, push (Streamlit Cloud auto-redeploys on push).

### Task 8.6: Hero screenshot for README

**Files:**
- Create: `docs/screenshot.png` (or similar)
- Modify: `README.md`

- [ ] **Step 1: Capture canonical screenshot**

Per design spec § 4.5 demo path: pick a ticker with all four patterns firing (NVDA on a Friday usually qualifies), pin it, capture at 1440×900 desktop resolution. Save as `docs/screenshot.png`.

- [ ] **Step 2: Capture mobile screenshot**

Operator: take a screenshot from their phone. Send to agent via litterbox.

- [ ] **Step 3: Add to README**

In `README.md`, just below `**Live demo:**`, add:
```markdown
![Dashboard screenshot](docs/screenshot.png)
```

- [ ] **Step 4: Commit + push**

```bash
git add docs/screenshot.png README.md
git commit -m "docs: hero screenshot for README"
git push
```

### Task 8.7: Tag the demo and write the application

**Files:** none (git tag + external action)

- [ ] **Step 1: Tag the demo**

```bash
git tag -a v0.1-demo -m "Sunday demo for UW Builder Community Lead application"
git push --tags
```

- [ ] **Step 2: Final spec/plan check**

Run: `git log --oneline`
Confirm a clean linear history. Run final test: `uv run pytest`. Confirm green.

- [ ] **Step 3: Operator submits the application**

Operator: include the live URL, GitHub repo URL, and a short writeup pointing at the README. Send to UW.

---

## Phase 9: Self-test against design spec (~10 min)

### Task 9.1: Run the experiential success criteria

**Files:** none (manual)

- [ ] **Step 1: Real-use test**

Operator: open the live URL with a real planned weekly options trade in mind. Scan, drill in, see if the brief surfaces ≥1 piece of structural information not already known going in. Note the answer.

- [ ] **Step 2: 60-second stranger test**

Operator: show the live URL to one person who doesn't know the project context. Without explanation, ask them what the app does and who it's for. Time them. If they can't articulate it in 60 s, the "What am I looking at" affordance is failing — either revise the subtitle or the "How this works" expander before sending the link to the UW hiring team.

- [ ] **Step 3: Log outcome in MEMORY.md**

```markdown
## 2026-05-23 — Sunday demo experiential test results

**Real-use test:** [PASS/FAIL] — surfaced [X piece of info I didn't know].
**60-second stranger test:** [PASS/FAIL] — tester said "[their description]" within [N] seconds.
**Next steps if FAIL:** ...
```

- [ ] **Step 4: Commit if MEMORY.md changed**

```bash
git add MEMORY.md
git commit -m "docs: log experiential test results for v0.1-demo"
git push
```

---

## Done.

If all tasks check, you have:
- Public Streamlit Cloud URL with the scan + pinned card running
- 10-ticker default, "Load 10 more" working
- Click-to-pin with URL persistence
- AI synthesis per row (Gemini Flash Lite with validator + deterministic fallback)
- Three drill-down charts stacked vertically per pinned ticker
- Per-pattern colored badges with tooltips, non-firing hidden
- GitHub repo with README + hero screenshot + `v0.1-demo` tag
- Fixture-based pytest green, opt-in `pytest -m live` green
- Application submitted to UW Builder Community Lead with all three deliverables (URL, repo, writeup)
