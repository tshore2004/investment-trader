from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.data_ingestion.feed import Bar
from src.utils import get_logger, get_settings

log = get_logger(__name__)

_CREATE_BARS = """
CREATE TABLE IF NOT EXISTS bars (
    symbol      TEXT        NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        FLOAT8      NOT NULL,
    high        FLOAT8      NOT NULL,
    low         FLOAT8      NOT NULL,
    close       FLOAT8      NOT NULL,
    volume      BIGINT      NOT NULL,
    PRIMARY KEY (symbol, timestamp)
);
SELECT create_hypertable('bars', 'timestamp', if_not_exists => TRUE);
"""


class TimeseriesStore:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._engine: AsyncEngine | None = None

    async def connect(self) -> None:
        self._engine = create_async_engine(self._settings.database_url, echo=False)
        async with self._engine.begin() as conn:
            await conn.execute(text(_CREATE_BARS))
        log.info("timescaledb_connected")

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()

    async def insert_bar(self, bar: Bar) -> None:
        assert self._engine, "call connect() first"
        sql = text(
            "INSERT INTO bars (symbol, timestamp, open, high, low, close, volume) "
            "VALUES (:symbol, :timestamp, :open, :high, :low, :close, :volume) "
            "ON CONFLICT DO NOTHING"
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                sql,
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
