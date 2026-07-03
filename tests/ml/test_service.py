from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.ml.service import train_symbol
from src.ml.trainer import TrainingResult


class FakeStore:
    def __init__(self, bars: list[dict[str, Any]]) -> None:
        self._bars = bars

    async def get_bars(self, symbol: str, limit: int = 5000) -> list[dict[str, Any]]:
        return self._bars


def _make_bars(n: int) -> list[dict[str, Any]]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {
            "symbol": "TEST",
            "timestamp": base + timedelta(minutes=i),
            "open": 100.0 + (i % 3),
            "high": 100.5 + (i % 3),
            "low": 99.5 + (i % 3),
            "close": 100.0 + (i % 3) * 0.5,
            "volume": 1000 + i,
        }
        for i in range(n)
    ]


async def test_train_symbol_runs_end_to_end() -> None:
    store = FakeStore(_make_bars(80))
    progress: list[dict[str, Any]] = []

    async def on_progress(payload: dict[str, Any]) -> None:
        progress.append(payload)

    result = await train_symbol(
        store=store, symbol="TEST", epochs=2, lr=0.01, hidden_size=8, on_progress=on_progress
    )

    assert isinstance(result, TrainingResult)
    assert result.epochs_completed == 2
    assert len(progress) == 2
