from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.data_ingestion.feed import Bar, MarketDataFeed


def _make_bar(symbol: str = "AAPL") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        open=150.0, high=151.0, low=149.0, close=150.5, volume=1000,
    )


class TestMarketDataFeed:
    def test_on_bar_registers_callback(self) -> None:
        mock_ib = MagicMock()
        feed = MarketDataFeed(ib=mock_ib)
        cb = MagicMock()
        feed.on_bar(cb)
        assert cb in feed._callbacks

    def test_subscribe_calls_req_real_time_bars(self) -> None:
        mock_ib = MagicMock()
        mock_bars = MagicMock()
        mock_ib.reqRealTimeBars.return_value = mock_bars
        feed = MarketDataFeed(ib=mock_ib)
        feed.subscribe("AAPL")
        mock_ib.reqRealTimeBars.assert_called_once()
        args = mock_ib.reqRealTimeBars.call_args
        assert args[1]["whatToShow"] == "TRADES"
        assert args[1]["barSize"] == 5

    def test_subscribe_registers_update_event(self) -> None:
        mock_ib = MagicMock()
        mock_bars = MagicMock()
        mock_ib.reqRealTimeBars.return_value = mock_bars
        feed = MarketDataFeed(ib=mock_ib)
        # Capture the updateEvent mock BEFORE subscribe() calls `updateEvent += handler`,
        # because Python's augmented-assignment reassigns the attribute to the __iadd__
        # return value, so checking mock_bars.updateEvent afterwards reads a different mock.
        update_event = mock_bars.updateEvent
        feed.subscribe("AAPL")
        # updateEvent should have a handler attached
        update_event.__iadd__.assert_called_once()

    def test_shared_ib_connect_is_noop(self) -> None:
        mock_ib = MagicMock()
        feed = MarketDataFeed(ib=mock_ib)
        import asyncio
        asyncio.run(feed.connect())
        mock_ib.connectAsync.assert_not_called()

    def test_shared_ib_disconnect_is_noop(self) -> None:
        mock_ib = MagicMock()
        feed = MarketDataFeed(ib=mock_ib)
        import asyncio
        asyncio.run(feed.disconnect())
        mock_ib.disconnect.assert_not_called()

    async def test_bar_callback_called_on_update(self) -> None:
        mock_ib = MagicMock()
        mock_bars_list = MagicMock()
        mock_ib.reqRealTimeBars.return_value = mock_bars_list
        feed = MarketDataFeed(ib=mock_ib)

        received: list[Bar] = []

        async def _cb(bar: Bar) -> None:
            received.append(bar)

        feed.on_bar(_cb)
        # Capture the updateEvent mock BEFORE subscribe() reassigns it via +=
        update_event = mock_bars_list.updateEvent
        feed.subscribe("AAPL")

        # Grab the handler that was registered
        handler = update_event.__iadd__.call_args[0][0]

        # Build a mock IB bar
        raw = MagicMock()
        raw.time = datetime(2024, 1, 1, 10, 0, tzinfo=UTC).timestamp()
        raw.open_ = 150.0
        raw.high = 151.0
        raw.low = 149.0
        raw.close = 150.5
        raw.volume = 1000

        mock_bars = [raw]
        handler(mock_bars, True)

        # give ensure_future a chance to run
        import asyncio
        await asyncio.sleep(0)

        assert len(received) == 1
        assert received[0].symbol == "AAPL"
        assert received[0].close == 150.5
