from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from scripts.backfill_history import backfill_symbol


class FakeStore:
    def __init__(self) -> None:
        self.inserted: list[Any] = []

    async def insert_bar(self, bar: Any) -> None:
        self.inserted.append(bar)


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def history(self, period: str, interval: str) -> pd.DataFrame:
        idx = pd.DatetimeIndex(
            [datetime(2026, 1, 1, 9, 30, tzinfo=UTC), datetime(2026, 1, 1, 9, 31, tzinfo=UTC)]
        )
        return pd.DataFrame(
            {
                "Open": [100.0, 100.5],
                "High": [101.0, 101.5],
                "Low": [99.5, 100.0],
                "Close": [100.5, 101.0],
                "Volume": [1000, 1100],
            },
            index=idx,
        )


async def test_backfill_symbol_inserts_all_bars(monkeypatch: Any) -> None:
    monkeypatch.setattr("scripts.backfill_history.yf.Ticker", FakeTicker)
    store = FakeStore()

    count = await backfill_symbol(store, "AAPL")

    assert count == 2
    assert len(store.inserted) == 2
    assert store.inserted[0].symbol == "AAPL"
    assert store.inserted[0].close == 100.5
    assert store.inserted[1].close == 101.0
