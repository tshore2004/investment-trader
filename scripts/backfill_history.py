from __future__ import annotations

import argparse
import asyncio
from datetime import UTC
from typing import Any

import yfinance as yf

from src.data_ingestion.feed import Bar
from src.data_ingestion.store import TimeseriesStore
from src.utils import get_logger, get_settings

log = get_logger(__name__)


async def backfill_symbol(store: Any, symbol: str) -> int:
    hist = yf.Ticker(symbol).history(period="60d", interval="1m")
    inserted = 0
    for ts, row in hist.iterrows():
        ts_utc = ts.to_pydatetime()
        ts_utc = ts_utc.replace(tzinfo=UTC) if ts_utc.tzinfo is None else ts_utc.astimezone(UTC)
        bar = Bar(
            symbol=symbol,
            timestamp=ts_utc,
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row["Volume"]),
        )
        await store.insert_bar(bar)
        inserted += 1
    log.info("backfill_complete", symbol=symbol, bars=inserted)
    return inserted


async def _main(symbols: list[str]) -> None:
    store = TimeseriesStore()
    await store.connect()
    try:
        for symbol in symbols:
            await backfill_symbol(store, symbol.upper().strip())
    finally:
        await store.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill 60 days of 1-min bars from yfinance into the bars hypertable"
    )
    parser.add_argument(
        "--symbols", type=str, default=None,
        help="Comma-separated symbols; defaults to WATCHLIST_SYMBOLS from settings",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    syms = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else get_settings().watchlist()
    )
    asyncio.run(_main(syms))
