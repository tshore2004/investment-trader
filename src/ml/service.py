from __future__ import annotations

from typing import Any

from src.ml.features import build_windows, compute_indicators
from src.ml.trainer import ProgressCallback, Trainer, TrainingResult


async def train_symbol(
    store: Any,
    symbol: str,
    epochs: int,
    lr: float,
    hidden_size: int,
    on_progress: ProgressCallback,
    trainer: Trainer | None = None,
) -> TrainingResult:
    bars = await store.get_bars(symbol, limit=100_000)
    df = compute_indicators(bars)
    X, y, timestamps = build_windows(df)
    active_trainer = trainer if trainer is not None else Trainer()
    return await active_trainer.run(
        symbol=symbol,
        X=X,
        y=y,
        epochs=epochs,
        lr=lr,
        hidden_size=hidden_size,
        on_progress=on_progress,
        timestamps=timestamps,
    )
