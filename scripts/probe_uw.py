"""One-shot live sanity check for each UW endpoint.

Usage:  uv run python scripts/probe_uw.py [TICKER]   (default: SPY)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import uw_client

TICKER = sys.argv[1] if len(sys.argv) > 1 else "SPY"

PROBES = [
    ("spot_exposures_strike", lambda: uw_client.fetch_spot_exposures_strike(TICKER)),
    ("oi_strike",             lambda: uw_client.fetch_oi_strike(TICKER)),
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
        print()
        continue
    s = json.dumps(data, indent=2)[:600]
    print(s)
    print()
