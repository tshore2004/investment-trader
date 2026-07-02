from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

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
        await self._ib.connectAsync(
            host=self._settings.ib_host,
            port=self._settings.ib_port,
            clientId=self._settings.ib_client_id,
        )
        log.info("market_feed_connected", host=self._settings.ib_host, port=self._settings.ib_port)

    async def disconnect(self) -> None:
        if not self._owns_ib:
            return
        self._ib.disconnect()  # type: ignore[no-untyped-call]

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
                # Yahoo's 1-minute intraday data is only available for the trailing
                # 7 days. Backfill that full window on the first poll for a symbol
                # so higher-timeframe views (10m/1h/4h/1d) have more than a single
                # session to aggregate over; subsequent polls only need today.
                period = "7d" if last_ts is None else "1d"

                # Run blocking yfinance call in a thread so the event loop stays free.
                ticker_obj = yf.Ticker(symbol)
                hist = await loop.run_in_executor(
                    None,
                    lambda t, p: t.history(period=p, interval="1m"),
                    ticker_obj,
                    period,
                )

                if hist is not None and len(hist) >= 2:
                    # [-1] is still forming; everything before it is a completed bar.
                    # Emit every completed bar newer than last_ts so a fresh subscribe
                    # backfills the day's history instead of only showing new bars.
                    for _, row in hist.iloc[:-1].iterrows():
                        ts: datetime = row.name.to_pydatetime()
                        ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)

                        if last_ts is not None and ts <= last_ts:
                            continue
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
