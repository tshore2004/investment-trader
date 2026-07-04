from __future__ import annotations

import time
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

import src.dashboard.app as app_module
from src.dashboard.app import create_app


def _fake_run_screen(universe: str, weights: Any = None, on_progress: Any = None) -> pd.DataFrame:
    if on_progress is not None:
        from src.screener.service import ScreenProgress
        on_progress(ScreenProgress(stage="universe_loaded"))
        on_progress(ScreenProgress(stage="done"))
    return pd.DataFrame({"score": [90.0, 80.0]}, index=["AAPL", "MSFT"])


def test_start_screen_returns_202(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "run_screen", _fake_run_screen)
    client = TestClient(create_app())

    resp = client.post("/api/screener/run", json={"universe": "sp500"})

    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_start_screen_rejects_duplicate(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "run_screen", _fake_run_screen)
    app_module._active_screen["running"] = True
    client = TestClient(create_app())

    resp = client.post("/api/screener/run", json={"universe": "sp500"})

    assert resp.status_code == 409
    app_module._active_screen["running"] = False


def test_stop_screen_is_noop_when_not_running() -> None:
    client = TestClient(create_app())

    resp = client.post("/api/screener/stop", json={})

    assert resp.status_code == 200
    assert resp.json()["status"] == "not_running"


def test_start_screen_broadcasts_done_with_results(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "run_screen", _fake_run_screen)

    broadcasts: list[dict[str, Any]] = []
    original_broadcast = app_module._state.broadcast_screener_result

    async def _capturing_broadcast(payload: dict[str, Any]) -> None:
        broadcasts.append(payload)
        await original_broadcast(payload)

    monkeypatch.setattr(app_module._state, "broadcast_screener_result", _capturing_broadcast)

    with TestClient(create_app()) as client:
        resp = client.post("/api/screener/run", json={"universe": "sp500"})
        assert resp.status_code == 202

        for _ in range(100):
            if any(b.get("status") == "done" for b in broadcasts):
                break
            time.sleep(0.02)

    done = [b for b in broadcasts if b.get("status") == "done"]
    assert done, "expected a done broadcast"
    assert done[0]["results"][0]["symbol"] == "AAPL"
    assert app_module._active_screen["running"] is False
