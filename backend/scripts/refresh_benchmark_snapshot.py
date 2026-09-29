"""Write the committed benchmark fallback snapshots from live Yahoo Finance data.

Run from backend/:  python -m scripts.refresh_benchmark_snapshot [snapshot_dir]

Each CSV holds month-end adjusted closes (the current partial month excluded), with the
retrieval timestamp, provider, and ticker on every row. Numbers come only from yfinance;
never edit them by hand.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.services.benchmarks import (
    BENCHMARK_TICKERS,
    fetch_yahoo_daily_closes,
    month_end_closes,
    write_snapshot,
)


def main(argv: list[str]) -> int:
    snapshot_dir = Path(argv[1]) if len(argv) > 1 else settings.benchmark_snapshot_dir
    retrieved_at = datetime.now(timezone.utc)
    for ticker in BENCHMARK_TICKERS:
        daily = fetch_yahoo_daily_closes(ticker, settings.market_data_timeout_seconds)
        closes = month_end_closes(daily, retrieved_at.date())
        path = write_snapshot(snapshot_dir, ticker, closes, retrieved_at)
        print(
            f"{ticker}: {len(closes)} month-end closes "
            f"{closes.index.min().date()}..{closes.index.max().date()} -> {path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
