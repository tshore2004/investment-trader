from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from src.data_ingestion.feed import Bar
from src.strategies.registry import StrategyRegistry


def _make_bar() -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        open=150.0, high=151.0, low=149.0, close=150.5, volume=1000,
    )


class TestStrategyRegistry:
    def test_register_and_active_ids(self) -> None:
        registry = StrategyRegistry()
        strat = MagicMock()
        strat.id = "test_strategy"
        registry.register(strat)
        assert "test_strategy" in registry.active_ids

    def test_unregister_removes_strategy(self) -> None:
        registry = StrategyRegistry()
        strat = MagicMock()
        strat.id = "test_strategy"
        registry.register(strat)
        registry.unregister("test_strategy")
        assert "test_strategy" not in registry.active_ids

    async def test_dispatch_calls_on_bar(self) -> None:
        registry = StrategyRegistry()
        strat = MagicMock()
        strat.id = "test_strategy"
        strat.on_bar = AsyncMock()
        registry.register(strat)
        bar = _make_bar()
        await registry.dispatch(bar)
        strat.on_bar.assert_called_once_with(bar)

    async def test_dispatch_multiple_strategies(self) -> None:
        registry = StrategyRegistry()
        strategies = []
        for i in range(3):
            s = MagicMock()
            s.id = f"strat_{i}"
            s.on_bar = AsyncMock()
            registry.register(s)
            strategies.append(s)
        bar = _make_bar()
        await registry.dispatch(bar)
        for s in strategies:
            s.on_bar.assert_called_once_with(bar)
