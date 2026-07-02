from __future__ import annotations

from collections import deque
from datetime import UTC, date
from enum import Enum

from src.broker.ib_broker import IBBroker
from src.broker.order import Order, OrderSide, OrderType
from src.data_ingestion.feed import Bar
from src.risk.engine import RiskEngine
from src.strategies.base import BaseStrategy
from src.utils import get_logger, get_settings

log = get_logger(__name__)

DEFAULT_QUANTITY = 10


class _Position(Enum):
    FLAT = "flat"
    LONG = "long"


class SmaCrossoverStrategy(BaseStrategy):
    """Simple moving-average crossover strategy.

    Tracks a bounded rolling window of closes per symbol, computes fast/slow
    SMAs from bar-close data only (no lookahead), and detects crossovers by
    comparing the previous bar's fast/slow relationship to the current one.
    Trading is gated by `TRADING_ENABLED` (dry-run logs the intended order
    instead of submitting) and `MAX_TRADES_PER_DAY` (per-strategy-instance,
    resets at UTC day rollover).
    """

    def __init__(
        self,
        broker: IBBroker,
        risk: RiskEngine,
        fast_period: int = 20,
        slow_period: int = 50,
        quantity: int = DEFAULT_QUANTITY,
    ) -> None:
        super().__init__(broker, risk)
        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")

        self._settings = get_settings()
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._quantity = quantity

        self._buffers: dict[str, deque[float]] = {}
        # None until we have >= slow_period bars and can form a first fast/slow pair.
        self._prev_relationship: dict[str, bool | None] = {}
        self._positions: dict[str, _Position] = {}

        self._trade_count = 0
        self._trade_count_date: date | None = None

    @property
    def id(self) -> str:
        return "sma_crossover"

    def _reset_trade_count_if_new_day(self, bar_date: date) -> None:
        if self._trade_count_date != bar_date:
            self._trade_count_date = bar_date
            self._trade_count = 0

    def _trade_cap_reached(self) -> bool:
        return self._trade_count >= self._settings.max_trades_per_day

    async def on_bar(self, bar: Bar) -> None:
        # Keep the risk engine's last-price map fresh before any order is
        # evaluated/submitted for this bar — this is what lets PositionLimitCheck
        # compute real USD exposure for market orders.
        self._risk.update_price(bar.symbol, bar.close)

        bar_date = bar.timestamp.astimezone(UTC).date()
        self._reset_trade_count_if_new_day(bar_date)

        buffer = self._buffers.setdefault(bar.symbol, deque(maxlen=self._slow_period))
        buffer.append(bar.close)

        if len(buffer) < self._slow_period:
            return

        fast_sma = sum(list(buffer)[-self._fast_period :]) / self._fast_period
        slow_sma = sum(buffer) / len(buffer)
        current_relationship = fast_sma > slow_sma  # True = fast above slow

        prev_relationship = self._prev_relationship.get(bar.symbol)
        self._prev_relationship[bar.symbol] = current_relationship

        if prev_relationship is None:
            # First time we have enough data — record state, no signal yet.
            return

        position = self._positions.setdefault(bar.symbol, _Position.FLAT)

        bullish_cross = (not prev_relationship) and current_relationship
        bearish_cross = prev_relationship and (not current_relationship)

        if bullish_cross and position is _Position.FLAT:
            await self._handle_signal(bar, OrderSide.BUY)
            self._positions[bar.symbol] = _Position.LONG
        elif bearish_cross and position is _Position.LONG:
            await self._handle_signal(bar, OrderSide.SELL)
            self._positions[bar.symbol] = _Position.FLAT
        # Ignore buy signals while already long, and sell signals while flat.

    async def _handle_signal(self, bar: Bar, side: OrderSide) -> None:
        order = Order(
            symbol=bar.symbol,
            side=side,
            quantity=self._quantity,
            order_type=OrderType.MARKET,
        )

        if not self._settings.trading_enabled:
            log.info(
                "dry_run_order",
                strategy=self.id,
                symbol=bar.symbol,
                side=side,
                qty=self._quantity,
            )
            return

        if self._trade_cap_reached():
            log.warning(
                "max_trades_per_day_reached",
                strategy=self.id,
                symbol=bar.symbol,
                max_trades_per_day=self._settings.max_trades_per_day,
            )
            return

        self._trade_count += 1
        await self.submit(order)
