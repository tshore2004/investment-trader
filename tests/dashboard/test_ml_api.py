from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

import src.dashboard.app as app_module
from src.dashboard.app import create_app
from src.ml.trainer import Trainer, TrainingResult


class FakeStore:
    async def get_bars(self, symbol: str, limit: int = 5000) -> list[dict[str, Any]]:
        return []


async def _fake_train_symbol(**kwargs: Any) -> TrainingResult:
    on_progress = kwargs["on_progress"]
    await on_progress(
        {"epoch": 1, "total_epochs": 1, "train_loss": 0.1, "val_loss": 0.1, "sample_preds": []}
    )
    return TrainingResult(epochs_completed=1, stopped_early=False)


def test_start_training_returns_202(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "_store", FakeStore())
    monkeypatch.setattr(app_module, "train_symbol", _fake_train_symbol)
    client = TestClient(create_app())

    resp = client.post("/api/ml/train", json={"symbol": "AAPL"})

    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_start_training_rejects_duplicate(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "_store", FakeStore())
    app_module._active_trainers["AAPL"] = Trainer()
    client = TestClient(create_app())

    resp = client.post("/api/ml/train", json={"symbol": "AAPL"})

    assert resp.status_code == 409
    app_module._active_trainers.clear()


def test_start_training_without_store_returns_503(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "_store", None)
    client = TestClient(create_app())

    resp = client.post("/api/ml/train", json={"symbol": "AAPL"})

    assert resp.status_code == 503


def test_stop_training_is_noop_when_not_running() -> None:
    client = TestClient(create_app())

    resp = client.post("/api/ml/stop", json={"symbol": "NOPE"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "not_training"


def test_start_training_broadcasts_error_on_failure(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "_store", FakeStore())

    async def _failing_train_symbol(**kwargs: Any) -> TrainingResult:
        raise ValueError("no bars available for 'AAPL' — run the backfill script first")

    monkeypatch.setattr(app_module, "train_symbol", _failing_train_symbol)

    broadcasts: list[tuple[str, dict[str, Any]]] = []
    original_broadcast = app_module._state.broadcast_ml_training

    async def _capturing_broadcast(symbol: str, payload: dict[str, Any]) -> None:
        broadcasts.append((symbol, payload))
        await original_broadcast(symbol, payload)

    monkeypatch.setattr(app_module._state, "broadcast_ml_training", _capturing_broadcast)

    client = TestClient(create_app())
    resp = client.post("/api/ml/train", json={"symbol": "AAPL"})
    assert resp.status_code == 202

    for _ in range(100):
        if broadcasts:
            break
        time.sleep(0.02)

    assert broadcasts, "expected broadcast_ml_training to be called on failure"
    symbol, payload = broadcasts[0]
    assert symbol == "AAPL"
    assert payload["status"] == "error"
    assert "no bars available" in payload["detail"]
    assert "AAPL" not in app_module._active_trainers


def test_start_training_rejects_out_of_bounds_hidden_size(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "_store", FakeStore())
    client = TestClient(create_app())

    resp = client.post("/api/ml/train", json={"symbol": "AAPL", "hidden_size": 999999999})

    assert resp.status_code == 422


def test_start_training_rejects_out_of_bounds_epochs(monkeypatch: Any) -> None:
    monkeypatch.setattr(app_module, "_store", FakeStore())
    client = TestClient(create_app())

    resp = client.post("/api/ml/train", json={"symbol": "AAPL", "epochs": 0})

    assert resp.status_code == 422


def test_stop_training_calls_trainer_stop() -> None:
    trainer = Trainer()
    app_module._active_trainers["AAPL"] = trainer
    client = TestClient(create_app())

    resp = client.post("/api/ml/stop", json={"symbol": "AAPL"})

    assert resp.status_code == 200
    assert trainer._stop_requested is True
    app_module._active_trainers.clear()
