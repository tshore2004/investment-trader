from __future__ import annotations

from datetime import UTC, datetime

from src.dashboard.app import DashboardState
from src.data_ingestion.feed import Bar


def _make_bar(symbol: str = "AAPL", close: float = 150.0) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        open=149.0, high=151.0, low=148.0, close=close, volume=500,
    )


class TestDashboardState:
    async def test_add_bar_stored(self) -> None:
        state = DashboardState()
        await state.add_bar(_make_bar())
        assert len(state.bars["AAPL"]) == 1

    async def test_snapshot_contains_bars(self) -> None:
        state = DashboardState()
        await state.add_bar(_make_bar())
        snap = state.snapshot()
        assert "AAPL" in snap["bars"]
        assert len(snap["bars"]["AAPL"]) == 1

    async def test_update_position(self) -> None:
        state = DashboardState()
        await state.update_position("AAPL", 10_000.0)
        snap = state.snapshot()
        assert snap["positions"]["AAPL"] == 10_000.0

    async def test_max_bars_capped(self) -> None:
        from src.dashboard.app import _MAX_BARS
        state = DashboardState()
        ts_base = datetime(2024, 1, 1, 10, 0, tzinfo=UTC).timestamp()
        for i in range(_MAX_BARS + 10):
            bar = Bar(
                symbol="AAPL",
                timestamp=datetime.fromtimestamp(ts_base + i * 5, tz=UTC),
                open=100.0, high=101.0, low=99.0, close=100.0, volume=100,
            )
            await state.add_bar(bar)
        assert len(state.bars["AAPL"]) == _MAX_BARS
