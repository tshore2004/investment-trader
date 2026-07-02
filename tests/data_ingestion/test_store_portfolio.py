from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from src.data_ingestion.store import TimeseriesStore


class FakeConn:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self._rows = rows or []

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.executed.append((str(stmt), params))
        return [SimpleNamespace(_mapping=row) for row in self._rows]


def make_store(conn: FakeConn) -> TimeseriesStore:
    store = TimeseriesStore.__new__(TimeseriesStore)

    @asynccontextmanager
    async def begin():  # type: ignore[no-untyped-def]
        yield conn

    store._engine = SimpleNamespace(begin=begin)  # type: ignore[assignment]
    return store


@pytest.mark.asyncio
async def test_insert_portfolio_snapshot_executes_insert_with_params() -> None:
    conn = FakeConn()
    store = make_store(conn)
    ts = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)

    await store.insert_portfolio_snapshot(12345.67, ts)

    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "INSERT INTO portfolio_value" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    assert params == {"timestamp": ts, "value": 12345.67}


@pytest.mark.asyncio
async def test_get_portfolio_history_returns_rows_ascending_query() -> None:
    rows = [
        {"timestamp": datetime(2026, 7, 2, 12, 0, tzinfo=UTC), "value": 100.0},
        {"timestamp": datetime(2026, 7, 2, 12, 1, tzinfo=UTC), "value": 101.0},
    ]
    conn = FakeConn(rows=rows)
    store = make_store(conn)

    result = await store.get_portfolio_history(limit=2)

    sql, params = conn.executed[0]
    assert "FROM portfolio_value" in sql
    assert "ORDER BY timestamp ASC" in sql
    assert params == {"limit": 2}
    assert result == rows
