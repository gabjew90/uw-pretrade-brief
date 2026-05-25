"""Watchlist resolution: user's fixed list ∪ UW 'hot today' leaders,
deduped, capped. Pure logic — UW fetching lives in src/fetch.py."""
from __future__ import annotations

DEFAULT_FIXED = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA",
                 "META", "AMZN", "GOOGL", "MSFT"]
DEFAULT_CAP = 30
DEFAULT_FIRST_BATCH = 10


def parse_user_list(csv: str) -> list[str]:
    """Parse a comma-separated ticker string into a list, normalized uppercase.
    Empty / None / whitespace-only returns []."""
    if not csv:
        return []
    return [t.strip().upper() for t in csv.split(",") if t.strip()]


def merge_watchlist(fixed: list[str], hot: list[str], cap: int = DEFAULT_CAP) -> list[str]:
    """Union: fixed first (preserves user's intended order), then hot
    filling remaining slots. Deduped, capped at `cap`."""
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
