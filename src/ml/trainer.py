from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from torch import nn, optim

from src.ml.model import PricePredictorMLP

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class TrainingResult:
    epochs_completed: int
    stopped_early: bool


class Trainer:
    def __init__(self) -> None:
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    async def run(
        self,
        symbol: str,
        X: np.ndarray,
        y: np.ndarray,
        epochs: int,
        lr: float,
        hidden_size: int,
        on_progress: ProgressCallback,
        timestamps: list[Any] | None = None,
    ) -> TrainingResult:
        self._stop_requested = False
        split = int(len(X) * 0.8)
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]
        ts_val = timestamps[split:] if timestamps is not None else list(range(len(X_val)))

        mean = X_train.mean(axis=0)
        std = X_train.std(axis=0)
        std[std == 0] = 1.0
        X_train_n = (X_train - mean) / std
        X_val_n = (X_val - mean) / std

        model = PricePredictorMLP(input_size=X.shape[1], hidden_size=hidden_size)
        optimizer = optim.Adam(model.parameters(), lr=lr)
        loss_fn = nn.MSELoss()

        X_train_t = torch.tensor(X_train_n, dtype=torch.float32)
        y_train_t = torch.tensor(y_train, dtype=torch.float32).unsqueeze(1)
        X_val_t = torch.tensor(X_val_n, dtype=torch.float32)
        y_val_t = torch.tensor(y_val, dtype=torch.float32).unsqueeze(1)

        epochs_completed = 0
        for epoch in range(1, epochs + 1):
            if self._stop_requested:
                break

            def _step() -> tuple[float, float, torch.Tensor]:
                model.train()
                optimizer.zero_grad()
                preds = model(X_train_t)
                loss = loss_fn(preds, y_train_t)
                loss.backward()
                optimizer.step()

                model.eval()
                with torch.no_grad():
                    val_preds = model(X_val_t)
                    val_loss = loss_fn(val_preds, y_val_t)
                return float(loss.item()), float(val_loss.item()), val_preds

            train_loss, val_loss, val_preds = await asyncio.to_thread(_step)
            epochs_completed = epoch

            tail = min(50, len(y_val))
            sample_preds = [
                {
                    "ts": ts_val[len(ts_val) - tail + j] if tail else None,
                    "actual": float(y_val[len(y_val) - tail + j]),
                    "predicted": float(val_preds[len(val_preds) - tail + j].item()),
                }
                for j in range(tail)
            ]

            await on_progress(
                {
                    "epoch": epoch,
                    "total_epochs": epochs,
                    "train_loss": train_loss,
                    "val_loss": val_loss,
                    "sample_preds": sample_preds,
                }
            )

        return TrainingResult(
            epochs_completed=epochs_completed, stopped_early=self._stop_requested
        )
