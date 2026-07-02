from __future__ import annotations

# eventkit (a dependency of ib_insync) calls asyncio.get_event_loop() at import
# time. Python 3.14 no longer auto-creates a loop, so we must set one before
# the first ib_insync import.
import asyncio

asyncio.set_event_loop(asyncio.new_event_loop())

import signal  # noqa: E402
import sys  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Any  # noqa: E402

import ib_insync as ibi  # noqa: E402
import uvicorn  # noqa: E402

from src.broker.ib_broker import IBBroker  # noqa: E402
from src.broker.order import Order  # noqa: E402
from src.dashboard.app import (  # noqa: E402
    OrderEvent,
    create_app,
    get_state,
    set_broker,
    set_feed,
    set_store,
)
from src.data_ingestion.feed import Bar, MarketDataFeed  # noqa: E402
from src.data_ingestion.store import TimeseriesStore  # noqa: E402
from src.risk.engine import RiskEngine  # noqa: E402
from src.strategies.registry import StrategyRegistry  # noqa: E402
from src.strategies.sma_crossover import SmaCrossoverStrategy  # noqa: E402
from src.utils import get_logger, get_settings  # noqa: E402
from src.utils.logging import configure_logging  # noqa: E402

log = get_logger(__name__)

# Paper-trading only: refuse to run against a live TWS/Gateway port.
_ALLOWED_IB_PORTS = {7497, 4002}

_PORTFOLIO_POLL_INTERVAL = 10.0


async def _bar_to_dashboard(bar: Bar) -> None:
    await get_state().add_bar(bar)


async def _order_to_dashboard(order: Order) -> None:
    await get_state().add_order(
        OrderEvent(
            order_id=str(order.id),
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
            status=order.status.value,
            timestamp=(order.submitted_at or datetime.now(UTC)).isoformat(),
        )
    )


async def shutdown(
    shared_ib: ibi.IB,
    store: TimeseriesStore,
    server: uvicorn.Server,
    portfolio_task: asyncio.Task[None],
) -> None:
    log.info("shutdown_initiated")
    server.should_exit = True
    portfolio_task.cancel()
    shared_ib.disconnect()  # type: ignore[no-untyped-call]
    await store.close()
    log.info("shutdown_complete")


async def _portfolio_poll_loop(broker: IBBroker) -> None:
    """Periodically push the current IB portfolio to the dashboard over /ws."""
    while True:
        try:
            rows = broker.portfolio_snapshot()
            await get_state().update_portfolio(rows)
        except Exception:
            log.exception("portfolio_poll_failed")
        await asyncio.sleep(_PORTFOLIO_POLL_INTERVAL)


async def main() -> None:
    configure_logging()
    settings = get_settings()

    if settings.ib_port not in _ALLOWED_IB_PORTS:
        raise RuntimeError(
            f"Refusing to start: IB_PORT={settings.ib_port} is not a paper-trading port "
            f"(allowed: {sorted(_ALLOWED_IB_PORTS)}). This system is paper-only."
        )

    symbols = settings.watchlist()

    log.info(
        "starting",
        symbols=symbols,
        ib_port=settings.ib_port,
        trading_enabled=settings.trading_enabled,
    )

    shared_ib = ibi.IB()  # type: ignore[no-untyped-call]

    feed = MarketDataFeed(ib=shared_ib)
    broker = IBBroker(ib=shared_ib)
    store = TimeseriesStore()
    risk = RiskEngine(peak_nav=100_000.0)
    registry = StrategyRegistry()

    # Connect to IB (single shared connection)
    await shared_ib.connectAsync(
        host=settings.ib_host,
        port=settings.ib_port,
        clientId=settings.ib_client_id,
    )
    log.info("ib_connected", host=settings.ib_host, port=settings.ib_port)

    # Connect to TimescaleDB
    await store.connect()

    # Register the baseline SMA crossover strategy (dry-run unless TRADING_ENABLED=true)
    strategy = SmaCrossoverStrategy(broker=broker, risk=risk)
    strategy.on_order(store.insert_order)
    strategy.on_order(_order_to_dashboard)
    registry.register(strategy)

    # Wire feed callbacks: persist bars + dispatch to strategies + push to dashboard
    feed.on_bar(store.insert_bar)
    feed.on_bar(registry.dispatch)
    feed.on_bar(_bar_to_dashboard)

    set_feed(feed)
    set_broker(broker)
    set_store(store)

    dashboard_state = get_state()
    dashboard_state.watchlist = symbols
    dashboard_state.trading_enabled = settings.trading_enabled

    for symbol in symbols:
        await feed.subscribe(symbol)

    portfolio_task = asyncio.ensure_future(_portfolio_poll_loop(broker))

    # Build dashboard server (runs in the same asyncio loop)
    app = create_app()
    uv_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8080,
        loop="none",
        log_level="warning",
    )
    server = uvicorn.Server(uv_config)

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()

    def _signal_handler(*_: Any) -> None:
        asyncio.ensure_future(shutdown(shared_ib, store, server, portfolio_task))

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            signal.signal(sig, _signal_handler)

    log.info("dashboard_starting", url="http://localhost:8080")

    await asyncio.gather(
        feed.run(),
        server.serve(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)