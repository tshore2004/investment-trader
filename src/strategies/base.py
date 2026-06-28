from __future__ import annotations

import abc

from src.broker.ib_broker import IBBroker
from src.broker.order import Order
from src.data_ingestion.feed import Bar
from src.risk.engine import RiskEngine
from src.utils import get_logger

log = get_logger(__name__)


class BaseStrategy(abc.ABC):
    def __init__(self, broker: IBBroker, risk: RiskEngine) -> None:
        self._broker = broker
        self._risk = risk

    @property
    @abc.abstractmethod
    def id(self) -> str:
        ...

    @abc.abstractmethod
    async def on_bar(self, bar: Bar) -> None:
        ...

    async def submit(self, order: Order) -> None:
        order.strategy_id = self.id
        passed, reason = self._risk.approve(order)
        if not passed:
            log.warning("order_blocked_by_risk", strategy=self.id, reason=reason)
            return
        await self._broker.submit(order)
