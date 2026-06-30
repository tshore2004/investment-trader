from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import ib_insync as ibi
import yfinance as yf

from src.utils import get_logger, get_settings

log = get_logger(__name__)

# How often to poll yfinance for new bars (seconds).
# yfinance provides 1-min bars with ~15-20 min delay; polling every 60s is sufficient.
_POLL_INTERVAL = 60.0


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
        self._subscriptions: dict[str, asyncio.Task[None]] = {}
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

    async def subscribe(self, symbol: str) -> None:
        if symbol in self._subscriptions:
            log.info("already_subscribed", symbol=symbol)
            return
        # Use yfinance for market data — free, no IB subscription required.
        # IB is kept for order execution only.
        task = asyncio.ensure_future(self._poll_bars(symbol))
        self._subscriptions[symbol] = task
        log.info("subscribed", symbol=symbol)

    async def _poll_bars(self, symbol: str) -> None:
        loop = asyncio.get_event_loop()
        last_ts: datetime | None = None

        while True:
            try:
                # Run blocking yfinance call in a thread so the event loop stays free.
                ticker_obj = yf.Ticker(symbol)
                hist = await loop.run_in_executor(
                    None,
                    lambda: ticker_obj.history(period="1d", interval="1m"),
                )

                if hist is not None and len(hist) >= 2:
                    row = hist.iloc[-2]  # [-1] is still forming; [-2] is last completed bar
                    ts: datetime = row.name.to_pydatetime()
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    else:
                        ts = ts.astimezone(timezone.utc)

                    if ts != last_ts:
                        last_ts = ts
                        bar = Bar(
                            symbol=symbol,
                            timestamp=ts,
                            open=float(row["Open"]),
                            high=float(row["High"]),
                            low=float(row["Low"]),
                            close=float(row["Close"]),
                            volume=int(row["Volume"]),
                        )
                        self._emit(bar)

            except Exception:
                log.exception("poll_bars_failed", symbol=symbol)

            await asyncio.sleep(_POLL_INTERVAL)

    def _emit(self, bar: Bar) -> None:
        log.debug("bar_received", symbol=bar.symbol, close=bar.close, ts=bar.timestamp.isoformat())
        for cb in self._callbacks:
            result = cb(bar)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    async def run(self) -> None:
        # ib_insync v0.9.x drives itself via asyncio tasks started in connectAsync();
        # there is no runAsync(). We just wait here until the IB connection drops.
        stopped = asyncio.Event()
        self._ib.disconnectedEvent += lambda: stopped.set()
        await stopped.wait()
