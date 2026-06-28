from __future__ import annotations

from src.data_ingestion.feed import Bar
from src.strategies.base import BaseStrategy
from src.utils import get_logger

log = get_logger(__name__)


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.id] = strategy
        log.info("strategy_registered", strategy_id=strategy.id)

    def unregister(self, strategy_id: str) -> None:
        self._strategies.pop(strategy_id, None)

    async def dispatch(self, bar: Bar) -> None:
        for strategy in self._strategies.values():
            await strategy.on_bar(bar)

    @property
    def active_ids(self) -> list[str]:
        return list(self._strategies.keys())
