"""Record live UW responses to tests/fixtures/ for use in pytest.

Usage:  uv run python scripts/record_fixtures.py [TICKER...]   (default: SPY)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import uw_client

TICKERS = sys.argv[1:] or ["SPY"]
OUT = Path("tests/fixtures")
OUT.mkdir(parents=True, exist_ok=True)

# (label, callable_taking_ticker, depends_on_ticker)
JOBS = [
    ("spot_exposures_strike", uw_client.fetch_spot_exposures_strike, True),
    ("oi_strike",             uw_client.fetch_oi_strike, True),
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
                continue
        fname.write_text(json.dumps(data, indent=2))
        print(f"wrote {fname}")
