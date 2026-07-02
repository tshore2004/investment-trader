from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.data_ingestion.feed import Bar
from src.risk.engine import RiskEngine
from src.strategies.sma_crossover import SmaCrossoverStrategy


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    from src.utils.config import get_settings
    get_settings.cache_clear()


def _bar(symbol: str, close: float, ts: datetime) -> Bar:
    return Bar(symbol=symbol, timestamp=ts, open=close, high=close, low=close,
               close=close, volume=1000)


def _make_broker() -> MagicMock:
    broker = MagicMock()
    broker.submit = AsyncMock()
    return broker


async def _feed_closes(strategy: SmaCrossoverStrategy, symbol: str, closes: list[float],
                        start: datetime) -> None:
    for i, close in enumerate(closes):
        await strategy.on_bar(_bar(symbol, close, start + timedelta(minutes=i)))


def _bullish_then_bearish_closes(slow: int) -> list[float]:
    # Flat prices to fill the buffer, then a ramp up (bullish cross), then a
    # ramp down (bearish cross), giving clean fast/slow crossovers.
    flat = [100.0] * slow
    up = [100.0 + i * 2.0 for i in range(1, slow + 1)]
    down = [up[-1] - i * 2.0 for i in range(1, slow + 1)]
    return flat + up + down


class TestSmaCrossoverDryRun:
    async def test_dry_run_never_submits_across_bullish_and_bearish_sequence(self) -> None:
        broker = _make_broker()
        risk = RiskEngine()
        strategy = SmaCrossoverStrategy(broker, risk, fast_period=3, slow_period=5)
        closes = _bullish_then_bearish_closes(5)
        await _feed_closes(strategy, "AAPL", closes, datetime(2024, 1, 1, tzinfo=UTC))
        broker.submit.assert_not_awaited()


class TestSmaCrossoverSignals:
    async def test_no_signal_while_flat_and_no_crossover(self) -> None:
        broker = _make_broker()
        risk = RiskEngine()
        strategy = SmaCrossoverStrategy(broker, risk, fast_period=3, slow_period=5)
        # Monotonically increasing series never produces a cross once fast > slow
        # is already established from the first qualifying bar (no "previous" yet),
        # and then stays fast > slow throughout — no crossover event.
        closes = [100.0 + i for i in range(20)]
        await _feed_closes(strategy, "AAPL", closes, datetime(2024, 1, 1, tzinfo=UTC))
        from src.strategies.sma_crossover import _Position
        assert strategy._positions.get("AAPL", _Position.FLAT) is _Position.FLAT
        broker.submit.assert_not_awaited()

    async def test_insufficient_bars_produces_no_position(self) -> None:
        broker = _make_broker()
        risk = RiskEngine()
        strategy = SmaCrossoverStrategy(broker, risk, fast_period=3, slow_period=5)
        closes = [100.0, 101.0, 102.0]  # fewer than slow_period
        await _feed_closes(strategy, "AAPL", closes, datetime(2024, 1, 1, tzinfo=UTC))
        assert "AAPL" not in strategy._positions

    async def test_bullish_then_bearish_cross_trading_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.utils.config as config_module
        config_module.get_settings.cache_clear()
        monkeypatch.setenv("TRADING_ENABLED", "true")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
        config_module.get_settings.cache_clear()

        broker = _make_broker()
        risk = RiskEngine()
        strategy = SmaCrossoverStrategy(broker, risk, fast_period=3, slow_period=5)
        closes = _bullish_then_bearish_closes(5)
        await _feed_closes(strategy, "AAPL", closes, datetime(2024, 1, 1, tzinfo=UTC))

        assert broker.submit.await_count == 2
        config_module.get_settings.cache_clear()

    async def test_max_trades_per_day_cap_limits_submits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.utils.config as config_module
        monkeypatch.setenv("TRADING_ENABLED", "true")
        monkeypatch.setenv("MAX_TRADES_PER_DAY", "1")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
        config_module.get_settings.cache_clear()

        broker = _make_broker()
        risk = RiskEngine()
        strategy = SmaCrossoverStrategy(broker, risk, fast_period=3, slow_period=5)
        # Bullish then bearish then bullish again -- three potential trade
        # signals, but MAX_TRADES_PER_DAY=1 should cap submissions to 1 within
        # the same UTC day.
        closes = _bullish_then_bearish_closes(5) + [
            v + 2.0 for v in _bullish_then_bearish_closes(5)
        ]
        await _feed_closes(strategy, "AAPL", closes, datetime(2024, 1, 1, tzinfo=UTC))

        assert broker.submit.await_count <= 1
        config_module.get_settings.cache_clear()
