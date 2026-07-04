from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from src.ml.trainer import Trainer


def _synthetic_dataset(n: int = 200, n_features: int = 4) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    X = rng.normal(size=(n, n_features)).astype(np.float32)
    y = (X[:, 0] * 2.0).astype(np.float32)
    return X, y


async def test_trainer_loss_decreases_over_epochs() -> None:
    X, y = _synthetic_dataset()
    progress: list[dict[str, Any]] = []

    async def on_progress(payload: dict[str, Any]) -> None:
        progress.append(payload)

    trainer = Trainer()
    result = await trainer.run(
        symbol="TEST", X=X, y=y, epochs=100, lr=0.01, hidden_size=16, on_progress=on_progress
    )

    assert result.epochs_completed == 100
    assert result.stopped_early is False
    assert len(progress) == 100
    assert progress[-1]["train_loss"] < progress[0]["train_loss"] * 0.5


async def test_trainer_progress_payload_shape() -> None:
    X, y = _synthetic_dataset(n=120)

    async def on_progress(payload: dict[str, Any]) -> None:
        assert set(payload.keys()) == {
            "epoch", "total_epochs", "train_loss", "val_loss", "sample_preds"
        }
        assert len(payload["sample_preds"]) <= 50
        for p in payload["sample_preds"]:
            assert set(p.keys()) == {"ts", "actual", "predicted"}

    trainer = Trainer()
    await trainer.run(
        symbol="TEST", X=X, y=y, epochs=3, lr=0.01, hidden_size=8, on_progress=on_progress
    )


async def test_trainer_stop_halts_before_all_epochs() -> None:
    X, y = _synthetic_dataset()
    trainer = Trainer()
    seen_epochs: list[int] = []

    async def on_progress(payload: dict[str, Any]) -> None:
        seen_epochs.append(payload["epoch"])
        if payload["epoch"] == 2:
            trainer.stop()

    result = await trainer.run(
        symbol="TEST", X=X, y=y, epochs=50, lr=0.01, hidden_size=8, on_progress=on_progress
    )

    assert result.stopped_early is True
    assert result.epochs_completed == 2
    assert seen_epochs == [1, 2]


async def test_trainer_stop_on_last_epoch_is_not_stopped_early() -> None:
    X, y = _synthetic_dataset()
    trainer = Trainer()
    seen_epochs: list[int] = []

    async def on_progress(payload: dict[str, Any]) -> None:
        seen_epochs.append(payload["epoch"])
        if payload["epoch"] == 3:
            trainer.stop()

    result = await trainer.run(
        symbol="TEST", X=X, y=y, epochs=3, lr=0.01, hidden_size=8, on_progress=on_progress
    )

    assert result.stopped_early is False
    assert result.epochs_completed == 3
    assert seen_epochs == [1, 2, 3]


async def test_trainer_raises_for_degenerate_split() -> None:
    X, y = _synthetic_dataset(n=1)

    async def on_progress(payload: dict[str, Any]) -> None:
        pass

    trainer = Trainer()
    with pytest.raises(ValueError, match="not enough samples"):
        await trainer.run(
            symbol="TEST", X=X, y=y, epochs=5, lr=0.01, hidden_size=8, on_progress=on_progress
        )
