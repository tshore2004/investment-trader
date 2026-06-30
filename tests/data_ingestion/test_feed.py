from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data_ingestion.feed import Bar, MarketDataFeed


def _make_history(closes: list[float], base_ts: datetime | None = None) -> pd.DataFrame:
    """Return a DataFrame that mimics yfinance Ticker.history() output."""
    base = base_ts or datetime(2024, 6, 30, 14, 0, tzinfo=UTC)
    index = pd.DatetimeIndex(
        [pd.Timestamp(base) + pd.Timedelta(minutes=i) for i in range(len(closes))],
        tz="UTC",
    )
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 0.5 for c in closes],
            "Low": [c - 0.5 for c in closes],
            "Close": closes,
            "Volume": [1000] * len(closes),
        },
        index=index,
    )


class TestMarketDataFeed:
    def test_on_bar_registers_callback(self) -> None:
        feed = MarketDataFeed(ib=MagicMock())
        cb = MagicMock()
        feed.on_bar(cb)
        assert cb in feed._callbacks

    def test_shared_ib_connect_is_noop(self) -> None:
        mock_ib = MagicMock()
        feed = MarketDataFeed(ib=mock_ib)
        asyncio.run(feed.connect())
        mock_ib.connectAsync.assert_not_called()

    def test_shared_ib_disconnect_is_noop(self) -> None:
        mock_ib = MagicMock()
        feed = MarketDataFeed(ib=mock_ib)
        asyncio.run(feed.disconnect())
        mock_ib.disconnect.assert_not_called()

    async def test_subscribe_starts_poll_task(self) -> None:
        feed = MarketDataFeed(ib=MagicMock())
        hist = _make_history([150.0, 151.0])
        with patch("src.data_ingestion.feed.yf.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.history.return_value = hist
            await feed.subscribe("AAPL")

        assert "AAPL" in feed._subscriptions
        assert isinstance(feed._subscriptions["AAPL"], asyncio.Task)
        feed._subscriptions["AAPL"].cancel()
        with pytest.raises(asyncio.CancelledError):
            await feed._subscriptions["AAPL"]

    async def test_subscribe_idempotent(self) -> None:
        feed = MarketDataFeed(ib=MagicMock())
        hist = _make_history([150.0, 151.0])
        with patch("src.data_ingestion.feed.yf.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.history.return_value = hist
            await feed.subscribe("AAPL")
            task1 = feed._subscriptions["AAPL"]
            await feed.subscribe("AAPL")
            assert feed._subscriptions["AAPL"] is task1

        task1.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task1

    async def test_bar_emitted_from_poll(self) -> None:
        feed = MarketDataFeed(ib=MagicMock())
        received: list[Bar] = []
        feed.on_bar(lambda b: received.append(b))

        t0 = datetime(2024, 6, 30, 14, 0, tzinfo=UTC)
        hist = _make_history([150.0, 151.0, 152.0], base_ts=t0)

        with patch("src.data_ingestion.feed.yf.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.history.return_value = hist
            with patch("src.data_ingestion.feed._POLL_INTERVAL", 9999):
                await feed.subscribe("AAPL")
                task = feed._subscriptions["AAPL"]
                # Give the executor-backed poll a moment to complete
                await asyncio.sleep(0.1)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert len(received) == 1
        assert received[0].symbol == "AAPL"
        # [-2] of a 3-row frame is index 1 → close = 151.0
        assert received[0].close == 151.0

    async def test_bar_deduplication(self) -> None:
        """Same timestamp from two consecutive polls should emit only once."""
        feed = MarketDataFeed(ib=MagicMock())
        received: list[Bar] = []
        feed.on_bar(lambda b: received.append(b))

        hist = _make_history([150.0, 151.0])

        call_count = 0

        def _history(**kwargs: object) -> pd.DataFrame:
            nonlocal call_count
            call_count += 1
            return hist

        with patch("src.data_ingestion.feed.yf.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.history.side_effect = _history
            with patch("src.data_ingestion.feed._POLL_INTERVAL", 0):
                await feed.subscribe("AAPL")
                task = feed._subscriptions["AAPL"]
                await asyncio.sleep(0.2)  # allow a few poll cycles

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert call_count >= 2
        assert len(received) == 1  # same ts → deduplicated

    async def test_emit_called_on_bar(self) -> None:
        feed = MarketDataFeed(ib=MagicMock())
        bar = Bar("AAPL", datetime(2024, 1, 1, tzinfo=UTC), 1.0, 2.0, 0.5, 1.5, 100)
        received: list[Bar] = []
        feed.on_bar(lambda b: received.append(b))
        feed._emit(bar)
        assert received == [bar]

    async def test_async_callback_dispatched(self) -> None:
        feed = MarketDataFeed(ib=MagicMock())
        bar = Bar("AAPL", datetime(2024, 1, 1, tzinfo=UTC), 1.0, 2.0, 0.5, 1.5, 100)
        received: list[Bar] = []

        async def _cb(b: Bar) -> None:
            received.append(b)

        feed.on_bar(_cb)
        feed._emit(bar)
        await asyncio.sleep(0)
        assert received == [bar]
