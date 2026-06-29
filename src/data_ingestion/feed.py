from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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


BarCallback = Callable[[Bar], Awaitable[None] | None]


class MarketDataFeed:
    def __init__(self, ib: ibi.IB | None = None) -> None:
        self._settings = get_settings()
        self._owns_ib = ib is None
        self._ib: ibi.IB = ib if ib is not None else ibi.IB()  # type: ignore[no-untyped-call]
        self._subscriptions: dict[str, Any] = {}
        self._callbacks: list[BarCallback] = []

    async def connect(self) -> None:
        if not self._owns_ib:
            return
        await self._ib.connectAsync(  # type: ignore[no-untyped-call]
            host=self._settings.ib_host,
            port=self._settings.ib_port,
            clientId=self._settings.ib_client_id,
        )
        log.info("market_feed_connected", host=self._settings.ib_host, port=self._settings.ib_port)

    async def disconnect(self) -> None:
        if not self._owns_ib:
            return
        self._ib.disconnect()

    def on_bar(self, callback: BarCallback) -> None:
        self._callbacks.append(callback)

    def subscribe(self, symbol: str) -> None:
        contract = ibi.Stock(symbol, "SMART", "USD")
        # reqHistoricalData with keepUpToDate=True streams live bars via the
        # historical data channel — no per-symbol market data subscription needed
        # (unlike reqRealTimeBars which requires an exchange subscription).
        bars_list: Any = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="5 secs",
            whatToShow="TRADES",
            useRTH=False,
            keepUpToDate=True,
        )

        def _on_update(bars: Any, hasNewBar: bool) -> None:
            if not hasNewBar or not bars:
                return
            raw = bars[-1]
            # Historical bar .date is a datetime (naive UTC); make it timezone-aware.
            raw_date: Any = raw.date
            if isinstance(raw_date, datetime):
                ts = raw_date if raw_date.tzinfo is not None else raw_date.replace(tzinfo=timezone.utc)
            else:
                ts = datetime.fromtimestamp(float(raw_date), tz=timezone.utc)
            bar = Bar(
                symbol=symbol,
                timestamp=ts,
                open=float(raw.open),
                high=float(raw.high),
                low=float(raw.low),
                close=float(raw.close),
                volume=int(raw.volume),
            )
            log.debug("bar_received", symbol=symbol, close=bar.close, ts=bar.timestamp.isoformat())
            for cb in self._callbacks:
                result = cb(bar)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)

        bars_list.updateEvent += _on_update
        self._subscriptions[symbol] = bars_list
        log.info("subscribed", symbol=symbol)

    async def run(self) -> None:
        # ib_insync v0.9.x drives itself via asyncio tasks started in connectAsync();
        # there is no runAsync(). We just wait here until the IB connection drops
        # so that callers can await this coroutine to keep things alive.
        stopped = asyncio.Event()
        self._ib.disconnectedEvent += lambda: stopped.set()
        await stopped.wait()