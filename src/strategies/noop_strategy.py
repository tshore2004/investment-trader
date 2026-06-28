from __future__ import annotations

from src.broker.ib_broker import IBBroker
from src.data_ingestion.feed import Bar
from src.risk.engine import RiskEngine
from src.strategies.base import BaseStrategy
from src.utils import get_logger

log = get_logger(__name__)


class NoOpStrategy(BaseStrategy):
    """Placeholder strategy that logs every bar without placing orders."""

    def __init__(self, broker: IBBroker, risk: RiskEngine) -> None:
        super().__init__(broker, risk)

    @property
    def id(self) -> str:
        return "noop"

    async def on_bar(self, bar: Bar) -> None:
        log.info(
            "bar_received",
            strategy=self.id,
            symbol=bar.symbol,
            close=bar.close,
            volume=bar.volume,
        )
