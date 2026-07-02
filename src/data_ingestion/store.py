from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.broker.order import Order
from src.data_ingestion.feed import Bar
from src.utils import get_logger, get_settings

log = get_logger(__name__)

_ENABLE_EXTENSION = "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS bars (
    symbol      TEXT        NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        FLOAT8      NOT NULL,
    high        FLOAT8      NOT NULL,
    low         FLOAT8      NOT NULL,
    close       FLOAT8      NOT NULL,
    volume      BIGINT      NOT NULL,
    PRIMARY KEY (symbol, timestamp)
)
"""

# asyncpg uses prepared statements so literal strings must be cast to name/text.
_CREATE_HYPERTABLE = (
    "SELECT create_hypertable('bars', 'timestamp'::name, if_not_exists => TRUE)"
)

_INSERT_BAR = (
    "INSERT INTO bars (symbol, timestamp, open, high, low, close, volume) "
    "VALUES (:symbol, :timestamp, :open, :high, :low, :close, :volume) "
    "ON CONFLICT DO NOTHING"
)

_CREATE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS orders (
    id           TEXT        PRIMARY KEY,
    symbol       TEXT        NOT NULL,
    side         TEXT        NOT NULL,
    quantity     INTEGER     NOT NULL,
    order_type   TEXT        NOT NULL,
    limit_price  FLOAT8,
    strategy_id  TEXT        NOT NULL,
    status       TEXT        NOT NULL,
    filled_price FLOAT8,
    submitted_at TIMESTAMPTZ,
    filled_at    TIMESTAMPTZ
)
"""

_INSERT_ORDER = """
INSERT INTO orders (id, symbol, side, quantity, order_type, limit_price, strategy_id,
                     status, filled_price, submitted_at, filled_at)
VALUES (:id, :symbol, :side, :quantity, :order_type, :limit_price, :strategy_id,
        :status, :filled_price, :submitted_at, :filled_at)
ON CONFLICT (id) DO UPDATE SET
    status = EXCLUDED.status,
    filled_price = EXCLUDED.filled_price,
    filled_at = EXCLUDED.filled_at
"""

_SELECT_ORDERS_BY_SYMBOL = """
SELECT id, symbol, side, quantity, order_type, limit_price, strategy_id,
       status, filled_price, submitted_at, filled_at
FROM orders
WHERE symbol = :symbol
ORDER BY submitted_at DESC NULLS LAST
LIMIT :limit
"""

# Innermost query grabs the most recent `limit` bars; outer ORDER BY restores
# chronological order for charting.
_SELECT_BARS_BY_SYMBOL = """
SELECT symbol, timestamp, open, high, low, close, volume
FROM (
    SELECT symbol, timestamp, open, high, low, close, volume
    FROM bars
    WHERE symbol = :symbol
    ORDER BY timestamp DESC
    LIMIT :limit
) recent
ORDER BY timestamp ASC
"""


class TimeseriesStore:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._engine: AsyncEngine | None = None

    async def connect(self) -> None:
        self._engine = create_async_engine(self._settings.database_url, echo=False)
        async with self._engine.begin() as conn:
            await conn.execute(text(_ENABLE_EXTENSION))
        async with self._engine.begin() as conn:
            await conn.execute(text(_CREATE_TABLE))
        async with self._engine.begin() as conn:
            await conn.execute(text(_CREATE_HYPERTABLE))
        async with self._engine.begin() as conn:
            await conn.execute(text(_CREATE_ORDERS_TABLE))
        log.info("timescaledb_connected")

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()

    async def insert_bar(self, bar: Bar) -> None:
        assert self._engine, "call connect() first"
        async with self._engine.begin() as conn:
            await conn.execute(
                text(_INSERT_BAR),
                {
                    "symbol": bar.symbol,
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                },
            )

    async def insert_order(self, order: Order) -> None:
        assert self._engine, "call connect() first"
        async with self._engine.begin() as conn:
            await conn.execute(
                text(_INSERT_ORDER),
                {
                    "id": str(order.id),
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "quantity": order.quantity,
                    "order_type": order.order_type.value,
                    "limit_price": order.limit_price,
                    "strategy_id": order.strategy_id,
                    "status": order.status.value,
                    "filled_price": order.filled_price,
                    "submitted_at": order.submitted_at,
                    "filled_at": order.filled_at,
                },
            )

    async def get_orders(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        assert self._engine, "call connect() first"
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(_SELECT_ORDERS_BY_SYMBOL), {"symbol": symbol, "limit": limit}
            )
            return [dict(row._mapping) for row in result]

    async def get_bars(self, symbol: str, limit: int = 5000) -> list[dict[str, Any]]:
        assert self._engine, "call connect() first"
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(_SELECT_BARS_BY_SYMBOL), {"symbol": symbol, "limit": limit}
            )
            return [dict(row._mapping) for row in result]