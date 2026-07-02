from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

import src.dashboard.app as app_module
from src.dashboard.app import DashboardState, create_app


class FakeStore:
    async def get_portfolio_history(self, limit: int = 5000) -> list[dict[str, Any]]:
        return [{"timestamp": "2026-07-02T12:00:00+00:00", "value": 100.0}]


def test_portfolio_history_route_returns_store_rows(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "_store", FakeStore())
    client = TestClient(create_app())
    resp = client.get("/api/portfolio/history")
    assert resp.status_code == 200
    assert resp.json() == [{"timestamp": "2026-07-02T12:00:00+00:00", "value": 100.0}]


def test_portfolio_history_route_empty_without_store(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "_store", None)
    client = TestClient(create_app())
    resp = client.get("/api/portfolio/history")
    assert resp.status_code == 200
    assert resp.json() == []


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


async def test_update_portfolio_value_broadcasts_message() -> None:
    state = DashboardState()
    ws = FakeWS()
    state._clients.append(ws)  # type: ignore[arg-type]

    await state.update_portfolio_value(12345.67, "2026-07-02T12:00:00+00:00")

    assert len(ws.sent) == 1
    msg = json.loads(ws.sent[0])
    assert msg == {
        "type": "portfolio_value",
        "value": 12345.67,
        "timestamp": "2026-07-02T12:00:00+00:00",
    }
