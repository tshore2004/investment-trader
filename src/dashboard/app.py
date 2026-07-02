from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from src.data_ingestion.feed import Bar
from src.utils import get_logger

if TYPE_CHECKING:
    from src.broker.ib_broker import IBBroker
    from src.data_ingestion.feed import MarketDataFeed
    from src.data_ingestion.store import TimeseriesStore

log = get_logger(__name__)
_MAX_BARS = 200


@dataclass
class OrderEvent:
    order_id: str
    symbol: str
    side: str
    quantity: int
    status: str
    timestamp: str


class DashboardState:
    def __init__(self) -> None:
        self.bars: dict[str, deque[dict[str, Any]]] = {}
        self.orders: deque[dict[str, Any]] = deque(maxlen=50)
        self.positions: dict[str, float] = {}
        self.portfolio: list[dict[str, Any]] = []
        self.watchlist: list[str] = []
        self.trading_enabled: bool = False
        self._clients: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def add_bar(self, bar: Bar) -> None:
        if bar.symbol not in self.bars:
            self.bars[bar.symbol] = deque(maxlen=_MAX_BARS)
        entry = {"time": int(bar.timestamp.timestamp()), "open": bar.open,
                 "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume}
        self.bars[bar.symbol].append(entry)
        await self._broadcast({"type": "bar", "symbol": bar.symbol, "data": entry})

    async def add_order(self, event: OrderEvent) -> None:
        self.orders.append(asdict(event))
        await self._broadcast({"type": "order", "data": asdict(event)})

    async def update_position(self, symbol: str, usd_value: float) -> None:
        self.positions[symbol] = usd_value
        await self._broadcast({"type": "position", "symbol": symbol, "value": usd_value})

    async def update_portfolio(self, rows: list[dict[str, Any]]) -> None:
        self.portfolio = rows
        await self._broadcast({"type": "portfolio", "data": rows})

    def snapshot(self) -> dict[str, Any]:
        return {"type": "snapshot",
                "bars": {s: list(b) for s, b in self.bars.items()},
                "orders": list(self.orders), "positions": dict(self.positions),
                "portfolio": list(self.portfolio), "watchlist": list(self.watchlist),
                "trading_enabled": self.trading_enabled}

    async def connect_client(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.append(ws)
        await ws.send_text(json.dumps(self.snapshot()))

    async def disconnect_client(self, ws: WebSocket) -> None:
        async with self._lock:
            with contextlib.suppress(ValueError):
                self._clients.remove(ws)

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        text = json.dumps(msg, default=str)
        for ws in list(self._clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect_client(ws)


_state = DashboardState()
_feed: MarketDataFeed | None = None
_broker: IBBroker | None = None
_store: TimeseriesStore | None = None


def get_state() -> DashboardState:
    return _state


def set_feed(feed: MarketDataFeed) -> None:
    global _feed
    _feed = feed


def set_broker(broker: IBBroker) -> None:
    global _broker
    _broker = broker


def set_store(store: TimeseriesStore) -> None:
    global _store
    _store = store


def create_app() -> FastAPI:
    app = FastAPI(title="Hedge Quant Dashboard")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        import pathlib as _pl
        return (_pl.Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")

    @app.get("/api/snapshot")
    async def snapshot() -> dict[str, Any]:
        return _state.snapshot()

    @app.get("/api/portfolio")
    async def portfolio() -> list[dict[str, Any]]:
        if _broker is None:
            return []
        return _broker.portfolio_snapshot()

    @app.get("/api/orders/{symbol}")
    async def orders_for_symbol(symbol: str) -> list[dict[str, Any]]:
        if _store is None:
            return []
        return await _store.get_orders(symbol.upper().strip())

    @app.get("/api/bars/{symbol}")
    async def bars_for_symbol(symbol: str) -> list[dict[str, Any]]:
        if _store is None:
            return []
        return await _store.get_bars(symbol.upper().strip())

    @app.post("/api/subscribe/{symbol}")
    async def subscribe(symbol: str) -> dict[str, str]:
        sym = symbol.upper().strip()
        if sym in _state.bars:
            return {"status": "already_subscribed", "symbol": sym}
        if _feed is None:
            return {"status": "error", "symbol": sym, "detail": "feed not ready"}
        await _feed.subscribe(sym)
        return {"status": "subscribed", "symbol": sym}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await _state.connect_client(ws)
        log.info("dashboard_client_connected")
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await _state.disconnect_client(ws)
            log.info("dashboard_client_disconnected")

    return app
