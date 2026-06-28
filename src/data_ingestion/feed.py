from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import ib_insync as ibi

from src.utils import get_logger, get_settings

log = get_logger(__name__)


@dataclass
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


BarCallback = Callable[[Bar], None]


class MarketDataFeed:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._ib = ibi.IB()
        self._subscriptions: dict[str, ibi.Contract] = {}
        self._callbacks: list[BarCallback] = []

    async def connect(self) -> None:
        await self._ib.connectAsync(
            host=self._settings.ib_host,
            port=self._settings.ib_port,
            clientId=self._settings.ib_client_id,
        )
        log.info("market_feed_connected", host=self._settings.ib_host, port=self._settings.ib_port)

    async def disconnect(self) -> None:
        self._ib.disconnect()

    def subscribe(self, symbol: str, callback: BarCallback) -> None:
        contract = ibi.Stock(symbol, "SMART", "USD")
        self._ib.reqMktData(contract)
        self._subscriptions[symbol] = contract
        self._callbacks.append(callback)
        log.info("subscribed", symbol=symbol)

    def on_bar(self, callback: BarCallback) -> None:
        self._callbacks.append(callback)

    async def run(self) -> None:
        await self._ib.runAsync()
