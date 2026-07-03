# NN Price Predictor + Live Training Visualizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a neural-network regression model that predicts next-bar percent return for a
symbol, trained on backfilled historical 1-minute bars, with a dashboard widget that visualizes
training progress live (loss curve + predicted-vs-actual chart) as it trains.

**Architecture:** A pure-function feature-engineering module turns stored bars into windowed
`(X, y)` arrays; a `Trainer` runs chronological-split PyTorch training and reports per-epoch
progress via an injected async callback; FastAPI endpoints start/stop a background training task
per symbol and broadcast progress over the existing `/ws` WebSocket; a new dashboard widget
renders the live loss curve and predicted-vs-actual overlay.

**Tech Stack:** Python 3.11, PyTorch (CPU), pandas/numpy, FastAPI, existing vanilla-JS ES-module
dashboard with lightweight-charts.

## Global Constraints

- Python 3.11, mypy `strict` mode, ruff line-length 100, lint rules `E, F, I, UP, B, SIM`.
- All I/O methods are `async def`; use `get_logger(__name__)` with kwargs, never f-string logs.
- Settings via `get_settings()` (`lru_cache`'d) — never instantiate `Settings()` directly.
- pytest `asyncio_mode = "auto"` — async test functions need no `@pytest.mark.asyncio` decorator.
- Historical backfill window: 60 days, 1-minute interval, via `yfinance`.
- Feature window: 30 bars; feature columns: `open, high, low, close, volume, sma10, ema10, rsi14,
  vwap` (9 columns) → 270 input features per sample.
- Train/val split: chronological 80/20, no shuffling across the time axis; standardize using
  train-split mean/std only.
- Model defaults: `epochs=50, lr=0.001, hidden_size=64`.
- Only one active training run per symbol at a time.
- New WS message type: `ml_training`.
- Out of scope: feeding predictions into `RiskEngine`/strategies, persisting models to disk,
  multi-symbol models, non-MLP architectures, automated JS test harness (manual browser pass
  + `node --check` only, per project convention).

---

### Task 1: Feature engineering — `src/ml/features.py`

**Files:**
- Create: `src/ml/__init__.py` (empty)
- Create: `src/ml/features.py`
- Test: `tests/ml/__init__.py` (empty)
- Test: `tests/ml/test_features.py`

**Interfaces:**
- Produces: `FEATURE_COLUMNS: list[str]` (9 names, see Global Constraints), `compute_indicators(bars:
  list[dict[str, Any]]) -> pd.DataFrame`, `build_windows(df: pd.DataFrame, window: int = 30) ->
  tuple[np.ndarray, np.ndarray, list[Any]]` (returns `X`, `y`, and the timestamp each `y` row
  corresponds to).

- [ ] **Step 1: Create empty package dirs**

```bash
mkdir -p src/ml tests/ml
```

Create `src/ml/__init__.py` and `tests/ml/__init__.py`, both empty.

- [ ] **Step 2: Write the failing tests**

Create `tests/ml/test_features.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from src.ml.features import FEATURE_COLUMNS, build_windows, compute_indicators


def _make_bars(n: int, close: float = 100.0) -> list[dict[str, Any]]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {
            "symbol": "TEST",
            "timestamp": base + timedelta(minutes=i),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000 + i,
        }
        for i in range(n)
    ]


def test_compute_indicators_constant_series() -> None:
    bars = _make_bars(20, close=100.0)
    df = compute_indicators(bars)

    assert df["sma10"].iloc[-1] == 100.0
    assert df["ema10"].iloc[-1] == 100.0
    assert df["rsi14"].iloc[-1] == 100.0
    assert df["vwap"].iloc[-1] == 100.0


def test_compute_indicators_warmup_rows_are_nan() -> None:
    bars = _make_bars(20, close=100.0)
    df = compute_indicators(bars)

    assert df["sma10"].iloc[0:9].isna().all()
    assert df["rsi14"].iloc[0:14].isna().all()


def test_build_windows_shapes_and_no_nan() -> None:
    bars = _make_bars(60)
    for i, bar in enumerate(bars):
        bar["close"] = 100.0 + (i % 5) * 0.1
    df = compute_indicators(bars)

    X, y, timestamps = build_windows(df, window=10)

    assert X.shape[1] == 10 * len(FEATURE_COLUMNS)
    assert X.shape[0] == y.shape[0] == len(timestamps)
    assert X.shape[0] > 0
    assert not np.isnan(X).any()
    assert not np.isnan(y).any()


def test_build_windows_target_matches_next_return() -> None:
    bars = _make_bars(40)
    bars[20]["close"] = 101.0  # isolated jump: bar 20 vs bar 19 (both 100.0 before this line)
    df = compute_indicators(bars)

    X, y, timestamps = build_windows(df, window=10)

    idx = timestamps.index(bars[20]["timestamp"])
    expected_return = (101.0 - 100.0) / 100.0
    assert abs(y[idx] - expected_return) < 1e-6
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m uv run pytest tests/ml/test_features.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ml.features'`

- [ ] **Step 4: Implement `src/ml/features.py`**

```python
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

FEATURE_COLUMNS = ["open", "high", "low", "close", "volume", "sma10", "ema10", "rsi14", "vwap"]


def compute_indicators(bars: list[dict[str, Any]]) -> pd.DataFrame:
    """Turn raw bar dicts (as returned by TimeseriesStore.get_bars) into a DataFrame with
    SMA(10)/EMA(10)/RSI(14)/VWAP columns appended. The first ~14 rows have NaN indicators
    (warm-up period) — callers must drop or mask those before training."""
    df = pd.DataFrame(bars).sort_values("timestamp").reset_index(drop=True)
    df["sma10"] = df["close"].rolling(window=10).mean()
    df["ema10"] = df["close"].ewm(span=10, adjust=False).mean()
    df["rsi14"] = _rsi(df["close"], period=14)
    df["vwap"] = _vwap(df)
    return df


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.where(avg_loss != 0, 100.0)


def _vwap(df: pd.DataFrame) -> pd.Series:
    date = pd.to_datetime(df["timestamp"]).dt.date
    pv = df["close"] * df["volume"]
    cum_pv = pv.groupby(date).cumsum()
    cum_vol = df["volume"].groupby(date).cumsum()
    return cum_pv / cum_vol.replace(0, np.nan)


def build_windows(
    df: pd.DataFrame, window: int = 30
) -> tuple[np.ndarray, np.ndarray, list[Any]]:
    """For each bar i (i >= window), build a sample from the window of bars [i-window, i)
    (NOT including bar i itself, to avoid leaking bar i's own OHLCV into its own prediction)
    and a target equal to bar i's percent return vs bar i-1. Rows touching any NaN indicator
    (warm-up period) are dropped."""
    feat = df[FEATURE_COLUMNS].to_numpy(dtype=float)
    target = df["close"].pct_change().to_numpy(dtype=float)
    timestamps = df["timestamp"].tolist()
    feat_valid = ~np.isnan(feat).any(axis=1)

    X_list: list[np.ndarray] = []
    y_list: list[float] = []
    ts_list: list[Any] = []
    for i in range(window, len(df)):
        if np.isnan(target[i]) or not feat_valid[i - window:i].all():
            continue
        X_list.append(feat[i - window : i].flatten())
        y_list.append(target[i])
        ts_list.append(timestamps[i])

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)
    return X, y, ts_list
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m uv run pytest tests/ml/test_features.py -v`
Expected: 4 passed

- [ ] **Step 6: Lint and type-check**

Run: `python -m uv run ruff check src/ml/ tests/ml/ && python -m uv run mypy src/ml/`
Expected: no issues

- [ ] **Step 7: Commit**

```bash
git add src/ml/__init__.py src/ml/features.py tests/ml/__init__.py tests/ml/test_features.py
git commit -m "feat(ml): add feature engineering module for price prediction"
```

---

### Task 2: Model — `src/ml/model.py`

**Files:**
- Create: `src/ml/model.py`
- Test: `tests/ml/test_model.py`
- Modify: `pyproject.toml` (add `torch` dependency)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `PricePredictorMLP(nn.Module)` with `__init__(self, input_size: int, hidden_size: int =
  64)` and `forward(self, x: torch.Tensor) -> torch.Tensor` returning shape `(batch, 1)`.

- [ ] **Step 1: Add the `torch` dependency**

```bash
python -m uv add torch
```

Verify `torch` now appears under `[project] dependencies` in `pyproject.toml`.

- [ ] **Step 2: Write the failing test**

Create `tests/ml/test_model.py`:

```python
from __future__ import annotations

import torch

from src.ml.model import PricePredictorMLP


def test_price_predictor_mlp_forward_shape() -> None:
    model = PricePredictorMLP(input_size=12, hidden_size=8)
    x = torch.randn(5, 12)

    out = model(x)

    assert out.shape == (5, 1)


def test_price_predictor_mlp_default_hidden_size() -> None:
    model = PricePredictorMLP(input_size=270)
    x = torch.randn(2, 270)

    out = model(x)

    assert out.shape == (2, 1)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m uv run pytest tests/ml/test_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ml.model'`

- [ ] **Step 4: Implement `src/ml/model.py`**

```python
from __future__ import annotations

import torch
from torch import nn


class PricePredictorMLP(nn.Module):
    def __init__(self, input_size: int, hidden_size: int = 64) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Linear(hidden_size // 2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        result: torch.Tensor = self.net(x)
        return result
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m uv run pytest tests/ml/test_model.py -v`
Expected: 2 passed

- [ ] **Step 6: Lint and type-check**

Run: `python -m uv run ruff check src/ml/ tests/ml/ && python -m uv run mypy src/ml/`
Expected: no issues

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/ml/model.py tests/ml/test_model.py
git commit -m "feat(ml): add PricePredictorMLP model, add torch dependency"
```

---

### Task 3: Trainer — `src/ml/trainer.py`

**Files:**
- Create: `src/ml/trainer.py`
- Test: `tests/ml/test_trainer.py`

**Interfaces:**
- Consumes: `PricePredictorMLP` from Task 2 (`src/ml/model.py`).
- Produces: `ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]`,
  `TrainingResult` dataclass with fields `epochs_completed: int`, `stopped_early: bool`, and
  `Trainer` with `stop(self) -> None` and `async def run(self, symbol: str, X: np.ndarray, y:
  np.ndarray, epochs: int, lr: float, hidden_size: int, on_progress: ProgressCallback,
  timestamps: list[Any] | None = None) -> TrainingResult`. Each progress payload has keys
  `epoch, total_epochs, train_loss, val_loss, sample_preds` where `sample_preds` is a list of
  `{ts, actual, predicted}` dicts for up to the last 50 validation points.

- [ ] **Step 1: Write the failing tests**

Create `tests/ml/test_trainer.py`:

```python
from __future__ import annotations

from typing import Any

import numpy as np

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m uv run pytest tests/ml/test_trainer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ml.trainer'`

- [ ] **Step 3: Implement `src/ml/trainer.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m uv run pytest tests/ml/test_trainer.py -v`
Expected: 3 passed

- [ ] **Step 5: Lint and type-check**

Run: `python -m uv run ruff check src/ml/ tests/ml/ && python -m uv run mypy src/ml/`
Expected: no issues

- [ ] **Step 6: Commit**

```bash
git add src/ml/trainer.py tests/ml/test_trainer.py
git commit -m "feat(ml): add Trainer with chronological split and per-epoch progress callback"
```

---

### Task 4: Training service glue — `src/ml/service.py`

**Files:**
- Create: `src/ml/service.py`
- Test: `tests/ml/test_service.py`

**Interfaces:**
- Consumes: `compute_indicators`, `build_windows` from Task 1; `Trainer`, `TrainingResult`,
  `ProgressCallback` from Task 3; `TimeseriesStore.get_bars(symbol: str, limit: int = 5000) ->
  list[dict[str, Any]]` (existing, in `src/data_ingestion/store.py`).
- Produces: `async def train_symbol(store: Any, symbol: str, epochs: int, lr: float, hidden_size:
  int, on_progress: ProgressCallback, trainer: Trainer | None = None) -> TrainingResult`. `store`
  is typed `Any` here (not `TimeseriesStore`) so tests can pass a lightweight fake without
  triggering a real DB import; the only contract is an async `get_bars(symbol, limit)` method.

- [ ] **Step 1: Write the failing test**

Create `tests/ml/test_service.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.ml.service import train_symbol
from src.ml.trainer import TrainingResult


class FakeStore:
    def __init__(self, bars: list[dict[str, Any]]) -> None:
        self._bars = bars

    async def get_bars(self, symbol: str, limit: int = 5000) -> list[dict[str, Any]]:
        return self._bars


def _make_bars(n: int) -> list[dict[str, Any]]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {
            "symbol": "TEST",
            "timestamp": base + timedelta(minutes=i),
            "open": 100.0 + (i % 3),
            "high": 100.5 + (i % 3),
            "low": 99.5 + (i % 3),
            "close": 100.0 + (i % 3) * 0.5,
            "volume": 1000 + i,
        }
        for i in range(n)
    ]


async def test_train_symbol_runs_end_to_end() -> None:
    store = FakeStore(_make_bars(80))
    progress: list[dict[str, Any]] = []

    async def on_progress(payload: dict[str, Any]) -> None:
        progress.append(payload)

    result = await train_symbol(
        store=store, symbol="TEST", epochs=2, lr=0.01, hidden_size=8, on_progress=on_progress
    )

    assert isinstance(result, TrainingResult)
    assert result.epochs_completed == 2
    assert len(progress) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m uv run pytest tests/ml/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ml.service'`

- [ ] **Step 3: Implement `src/ml/service.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m uv run pytest tests/ml/test_service.py -v`
Expected: 1 passed

- [ ] **Step 5: Lint and type-check**

Run: `python -m uv run ruff check src/ml/ tests/ml/ && python -m uv run mypy src/ml/`
Expected: no issues

- [ ] **Step 6: Commit**

```bash
git add src/ml/service.py tests/ml/test_service.py
git commit -m "feat(ml): add train_symbol service gluing store, features, and Trainer"
```

---

### Task 5: Historical backfill script — `scripts/backfill_history.py`

**Files:**
- Create: `scripts/__init__.py` (empty)
- Create: `scripts/backfill_history.py`
- Test: `tests/scripts/__init__.py` (empty)
- Test: `tests/scripts/test_backfill_history.py`

**Interfaces:**
- Consumes: `Bar` from `src/data_ingestion/feed.py` (existing), `TimeseriesStore` from
  `src/data_ingestion/store.py` (existing, method `insert_bar(bar: Bar) -> None`), `get_settings`
  from `src/utils` (existing, `Settings.watchlist() -> list[str]`).
- Produces: `async def backfill_symbol(store: Any, symbol: str) -> int` (returns count of bars
  inserted) — used directly by the test; not consumed by any later task.

- [ ] **Step 1: Create package dirs**

```bash
mkdir -p scripts tests/scripts
```

Create `scripts/__init__.py` and `tests/scripts/__init__.py`, both empty.

- [ ] **Step 2: Write the failing test**

Create `tests/scripts/test_backfill_history.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from scripts.backfill_history import backfill_symbol


class FakeStore:
    def __init__(self) -> None:
        self.inserted: list[Any] = []

    async def insert_bar(self, bar: Any) -> None:
        self.inserted.append(bar)


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def history(self, period: str, interval: str) -> pd.DataFrame:
        idx = pd.DatetimeIndex(
            [datetime(2026, 1, 1, 9, 30, tzinfo=UTC), datetime(2026, 1, 1, 9, 31, tzinfo=UTC)]
        )
        return pd.DataFrame(
            {
                "Open": [100.0, 100.5],
                "High": [101.0, 101.5],
                "Low": [99.5, 100.0],
                "Close": [100.5, 101.0],
                "Volume": [1000, 1100],
            },
            index=idx,
        )


async def test_backfill_symbol_inserts_all_bars(monkeypatch: Any) -> None:
    monkeypatch.setattr("scripts.backfill_history.yf.Ticker", FakeTicker)
    store = FakeStore()

    count = await backfill_symbol(store, "AAPL")

    assert count == 2
    assert len(store.inserted) == 2
    assert store.inserted[0].symbol == "AAPL"
    assert store.inserted[0].close == 100.5
    assert store.inserted[1].close == 101.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m uv run pytest tests/scripts/test_backfill_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.backfill_history'`

- [ ] **Step 4: Implement `scripts/backfill_history.py`**

```python
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC
from typing import Any

import yfinance as yf

from src.data_ingestion.feed import Bar
from src.data_ingestion.store import TimeseriesStore
from src.utils import get_logger, get_settings

log = get_logger(__name__)


async def backfill_symbol(store: Any, symbol: str) -> int:
    hist = yf.Ticker(symbol).history(period="60d", interval="1m")
    inserted = 0
    for ts, row in hist.iterrows():
        ts_utc = ts.to_pydatetime()
        ts_utc = ts_utc.replace(tzinfo=UTC) if ts_utc.tzinfo is None else ts_utc.astimezone(UTC)
        bar = Bar(
            symbol=symbol,
            timestamp=ts_utc,
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row["Volume"]),
        )
        await store.insert_bar(bar)
        inserted += 1
    log.info("backfill_complete", symbol=symbol, bars=inserted)
    return inserted


async def _main(symbols: list[str]) -> None:
    store = TimeseriesStore()
    await store.connect()
    try:
        for symbol in symbols:
            await backfill_symbol(store, symbol.upper().strip())
    finally:
        await store.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill 60 days of 1-min bars from yfinance into the bars hypertable"
    )
    parser.add_argument(
        "--symbols", type=str, default=None,
        help="Comma-separated symbols; defaults to WATCHLIST_SYMBOLS from settings",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    syms = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else get_settings().watchlist()
    )
    asyncio.run(_main(syms))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m uv run pytest tests/scripts/test_backfill_history.py -v`
Expected: 1 passed

- [ ] **Step 6: Lint and type-check**

Run: `python -m uv run ruff check scripts/ tests/scripts/ && python -m uv run mypy scripts/`
Expected: no issues

- [ ] **Step 7: Commit**

```bash
git add scripts/__init__.py scripts/backfill_history.py tests/scripts/__init__.py tests/scripts/test_backfill_history.py
git commit -m "feat: add one-off historical bar backfill script for ML training data"
```

---

### Task 6: Backend API + WebSocket wiring — `src/dashboard/app.py`

**Files:**
- Modify: `src/dashboard/app.py`
- Test: `tests/dashboard/test_ml_api.py`

**Interfaces:**
- Consumes: `train_symbol` from `src/ml/service.py` (Task 4), `Trainer`, `TrainingResult` from
  `src/ml/trainer.py` (Task 3).
- Produces: `DashboardState.broadcast_ml_training(self, symbol: str, payload: dict[str, Any]) ->
  None`; module-level `_active_trainers: dict[str, Trainer]` (importable/patchable as
  `app_module._active_trainers`); routes `POST /api/ml/train` and `POST /api/ml/stop`.

- [ ] **Step 1: Write the failing tests**

Create `tests/dashboard/test_ml_api.py`:

```python
from __future__ import annotations

from typing import Any

import src.dashboard.app as app_module
from fastapi.testclient import TestClient
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


def test_stop_training_calls_trainer_stop() -> None:
    trainer = Trainer()
    app_module._active_trainers["AAPL"] = trainer
    client = TestClient(create_app())

    resp = client.post("/api/ml/stop", json={"symbol": "AAPL"})

    assert resp.status_code == 200
    assert trainer._stop_requested is True
    app_module._active_trainers.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m uv run pytest tests/dashboard/test_ml_api.py -v`
Expected: FAIL — `/api/ml/train` and `/api/ml/stop` routes don't exist yet (404s / AttributeError
on `_active_trainers`)

- [ ] **Step 3: Modify `src/dashboard/app.py`**

Add imports near the top (after the existing `from src.data_ingestion.feed import Bar`):

```python
from pydantic import BaseModel

from src.ml.service import train_symbol
from src.ml.trainer import Trainer
```

Change the `fastapi.responses` import line to also bring in `JSONResponse`:

```python
from fastapi.responses import HTMLResponse, JSONResponse
```

Add a method to `DashboardState` (after `update_portfolio_value`):

```python
    async def broadcast_ml_training(self, symbol: str, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": "ml_training", "symbol": symbol, **payload})
```

Add module-level state near the existing `_feed`/`_broker`/`_store` globals:

```python
_active_trainers: dict[str, Trainer] = {}
```

Add two Pydantic request models and two routes inside `create_app()`, alongside the existing
`/api/subscribe/{symbol}` route:

```python
    class TrainRequest(BaseModel):
        symbol: str
        epochs: int = 50
        lr: float = 0.001
        hidden_size: int = 64

    class StopRequest(BaseModel):
        symbol: str

    @app.post("/api/ml/train")
    async def start_ml_training(req: TrainRequest) -> JSONResponse:
        sym = req.symbol.upper().strip()
        if sym in _active_trainers:
            return JSONResponse(
                status_code=409, content={"status": "already_training", "symbol": sym}
            )
        if _store is None:
            return JSONResponse(
                status_code=503, content={"status": "error", "detail": "store not ready"}
            )

        trainer = Trainer()
        _active_trainers[sym] = trainer

        async def on_progress(payload: dict[str, Any]) -> None:
            await _state.broadcast_ml_training(sym, payload)

        async def _run() -> None:
            try:
                await train_symbol(
                    store=_store,
                    symbol=sym,
                    epochs=req.epochs,
                    lr=req.lr,
                    hidden_size=req.hidden_size,
                    on_progress=on_progress,
                    trainer=trainer,
                )
            except Exception:
                log.exception("ml_training_failed", symbol=sym)
            finally:
                _active_trainers.pop(sym, None)

        asyncio.create_task(_run())
        return JSONResponse(status_code=202, content={"status": "started", "symbol": sym})

    @app.post("/api/ml/stop")
    async def stop_ml_training(req: StopRequest) -> dict[str, str]:
        sym = req.symbol.upper().strip()
        trainer = _active_trainers.get(sym)
        if trainer is None:
            return {"status": "not_training", "symbol": sym}
        trainer.stop()
        return {"status": "stopping", "symbol": sym}
```

Note: `train_symbol` and `Trainer` are imported at module scope specifically so
`monkeypatch.setattr(app_module, "train_symbol", ...)` in tests replaces the name the route
closure looks up — the route function must reference the bare name `train_symbol` (not
`src.ml.service.train_symbol`) for that patch to take effect.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m uv run pytest tests/dashboard/test_ml_api.py -v`
Expected: 5 passed

- [ ] **Step 5: Run full test suite, lint, and type-check**

Run: `python -m uv run pytest -x -q && python -m uv run ruff check src/ main.py tests/ && python -m uv run mypy src/ main.py`
Expected: all green (52 tests total)

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/app.py tests/dashboard/test_ml_api.py
git commit -m "feat(dashboard): add /api/ml/train and /api/ml/stop endpoints, ml_training WS broadcast"
```

---

### Task 7: Frontend WS dispatch + widget registration

**Files:**
- Modify: `src/dashboard/static/js/widgets.js`
- Modify: `src/dashboard/static/js/ws.js`

**Interfaces:**
- Consumes: `createMlWidget(container, config)` from `src/dashboard/static/js/ml.js` (Task 8 —
  written first here as an import; Task 8 creates the file. If executing tasks in order, this
  task's `node --check` step will fail until Task 8 exists — that's expected; do Task 8's
  implementation step immediately after this task's edits, before running the check).
- Produces: `WIDGET_TYPES.ml` catalog entry; `dispatchMlTraining(msg)` exported from
  `widgets.js`; `ws.js` calls `dispatchMlTraining(msg)` when `msg.type === 'ml_training'`.

- [ ] **Step 1: Add the `ml` widget type and dispatch function to `widgets.js`**

Add the import at the top of `src/dashboard/static/js/widgets.js` (alongside the other widget
factory imports):

```javascript
import { createMlWidget } from './ml.js';
```

Add `ml` to `WIDGET_TYPES`:

```javascript
export const WIDGET_TYPES = {
  chart:    { label: 'Chart',         defaultSize: { w: 6, h: 6 }, needsSymbol: true,  allowsPortfolio: true },
  metrics:  { label: 'Metrics',       defaultSize: { w: 4, h: 3 }, needsSymbol: true,  allowsPortfolio: false },
  orders:   { label: 'Trade History', defaultSize: { w: 4, h: 3 }, needsSymbol: true,  allowsPortfolio: false },
  holdings: { label: 'Holdings',      defaultSize: { w: 6, h: 3 }, needsSymbol: false, allowsPortfolio: false },
  compare:  { label: 'Compare',       defaultSize: { w: 8, h: 4 }, needsSymbol: true,  allowsPortfolio: false },
  ml:       { label: 'NN Predictor',  defaultSize: { w: 8, h: 5 }, needsSymbol: true,  allowsPortfolio: false },
};
```

Add the `ml` branch to `createWidget`:

```javascript
export function createWidget(id, type, config, container, hooks = {}) {
  let handle;
  if (type === 'chart') handle = createChartWidget(container, config, hooks);
  else if (type === 'metrics') handle = createMetricsWidget(container, config);
  else if (type === 'orders') handle = createOrdersWidget(container, config);
  else if (type === 'holdings') handle = createHoldingsWidget(container);
  else if (type === 'compare') handle = createCompareWidget(container, config, hooks);
  else if (type === 'ml') handle = createMlWidget(container, config);
  else throw new Error(`unknown widget type: ${type}`);

  const instance = { id, type, config, handle };
  instances.set(id, instance);
  return instance;
}
```

Add the dispatch function at the end of the "WS message fan-out" section:

```javascript
export function dispatchMlTraining(msg) {
  for (const inst of instances.values()) {
    if (inst.type === 'ml' && inst.handle.handleProgress) inst.handle.handleProgress(msg);
  }
}
```

- [ ] **Step 2: Wire the new message type in `ws.js`**

Update the import line at the top of `src/dashboard/static/js/ws.js`:

```javascript
import {
  dispatchBar, dispatchPortfolioValue, dispatchOrder,
  dispatchHoldings, dispatchPosition, dispatchMlTraining,
} from './widgets.js';
```

Add a branch in `handleMessage` (after the `portfolio_value` branch):

```javascript
  } else if (msg.type === 'portfolio_value') {
    dispatchPortfolioValue({
      time: Math.floor(new Date(msg.timestamp).getTime() / 1000),
      value: msg.value,
    });
  } else if (msg.type === 'ml_training') {
    dispatchMlTraining(msg);
  }
```

- [ ] **Step 3: Commit (after Task 8's `ml.js` exists so the syntax check passes)**

This task's commit is deferred to the end of Task 8's Step 5 — the two are committed together
since `widgets.js` importing a nonexistent `ml.js` would leave the tree in a broken intermediate
state otherwise.

---

### Task 8: Training visualizer widget — `src/dashboard/static/js/ml.js`

**Files:**
- Create: `src/dashboard/static/js/ml.js`

**Interfaces:**
- Consumes: nothing new (no import from `state.js` needed — this widget doesn't read `state.bars`).
- Produces: `createMlWidget(container, config)` returning `{ handleProgress(msg), getConfig(),
  destroy() }`, matching the shape `widgets.js` (Task 7) expects.

- [ ] **Step 1: Implement `src/dashboard/static/js/ml.js`**

```javascript
// Live training visualizer: shows loss curves and predicted-vs-actual return
// as a background /api/ml/train run progresses. The loss-curve x-axis uses
// epoch number (not wall-clock time) fed into lightweight-charts' numeric
// time field, so tick labels are not meaningful dates — only the shape of
// the curve matters here.
export function createMlWidget(container, config) {
  config.epochs = config.epochs || 50;
  config.lr = config.lr || 0.001;
  config.hiddenSize = config.hiddenSize || 64;

  container.innerHTML = `
    <div class="panel">
      <div class="panel-header" style="flex-wrap:wrap;gap:6px">
        <span class="w-chart-label">NN Predictor — ${config.symbol}</span>
        <div style="display:flex;gap:8px;align-items:center;font-size:11px">
          <label>Epochs <input class="w-ml-epochs" type="number" min="1" value="${config.epochs}" style="width:56px" /></label>
          <label>LR <input class="w-ml-lr" type="number" step="0.0001" value="${config.lr}" style="width:70px" /></label>
          <label>Hidden <input class="w-ml-hidden" type="number" min="2" value="${config.hiddenSize}" style="width:56px" /></label>
          <button class="w-ml-start">Start</button>
          <button class="w-ml-stop">Stop</button>
        </div>
        <span class="w-ml-status" style="color:#a39c8f;font-size:11px;width:100%"></span>
      </div>
      <div style="display:flex;flex:1 1 auto;min-height:0">
        <div class="w-ml-loss" style="width:50%;height:100%"></div>
        <div class="w-ml-pred" style="width:50%;height:100%"></div>
      </div>
    </div>`;

  const statusEl = container.querySelector('.w-ml-status');
  const lossEl = container.querySelector('.w-ml-loss');
  const predEl = container.querySelector('.w-ml-pred');

  const chartOpts = {
    layout: { background: { color: '#0a0a0a' }, textColor: '#a39c8f' },
    grid: { vertLines: { color: '#1a1a1a' }, horzLines: { color: '#1a1a1a' } },
  };

  const lossChart = LightweightCharts.createChart(lossEl, {
    ...chartOpts, width: lossEl.offsetWidth || 200, height: lossEl.offsetHeight || 200,
  });
  const trainLossSeries = lossChart.addLineSeries({ color: '#F5C518', lineWidth: 2 });
  const valLossSeries = lossChart.addLineSeries({ color: '#f85149', lineWidth: 2 });

  const predChart = LightweightCharts.createChart(predEl, {
    ...chartOpts, width: predEl.offsetWidth || 200, height: predEl.offsetHeight || 200,
  });
  const actualSeries = predChart.addLineSeries({ color: '#3fb950', lineWidth: 2 });
  const predictedSeries = predChart.addLineSeries({ color: '#79c0ff', lineWidth: 2 });

  let lossPoints = [];

  function handleProgress(msg) {
    if (msg.symbol !== config.symbol) return;

    lossPoints.push({ time: msg.epoch, trainLoss: msg.train_loss, valLoss: msg.val_loss });
    trainLossSeries.setData(lossPoints.map(p => ({ time: p.time, value: p.trainLoss })));
    valLossSeries.setData(lossPoints.map(p => ({ time: p.time, value: p.valLoss })));

    const preds = msg.sample_preds || [];
    actualSeries.setData(preds.map((p, i) => ({ time: i + 1, value: p.actual })));
    predictedSeries.setData(preds.map((p, i) => ({ time: i + 1, value: p.predicted })));

    statusEl.textContent =
      `epoch ${msg.epoch}/${msg.total_epochs} — train loss ${msg.train_loss.toFixed(6)}, val loss ${msg.val_loss.toFixed(6)}`;
    if (msg.epoch >= msg.total_epochs) statusEl.textContent += ' — done';
  }

  container.querySelector('.w-ml-start').onclick = async () => {
    config.epochs = parseInt(container.querySelector('.w-ml-epochs').value, 10) || config.epochs;
    config.lr = parseFloat(container.querySelector('.w-ml-lr').value) || config.lr;
    config.hiddenSize = parseInt(container.querySelector('.w-ml-hidden').value, 10) || config.hiddenSize;
    lossPoints = [];
    trainLossSeries.setData([]);
    valLossSeries.setData([]);
    statusEl.textContent = 'starting...';
    try {
      const r = await fetch('/api/ml/train', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: config.symbol, epochs: config.epochs, lr: config.lr, hidden_size: config.hiddenSize,
        }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        statusEl.textContent = `could not start: ${body.status || r.status}`;
      }
    } catch (e) {
      statusEl.textContent = 'failed to start';
    }
  };

  container.querySelector('.w-ml-stop').onclick = async () => {
    try {
      await fetch('/api/ml/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: config.symbol }),
      });
      statusEl.textContent = 'stopping...';
    } catch (e) { /* best effort */ }
  };

  const resizeObserver = new ResizeObserver(() => {
    if (lossEl.offsetWidth > 0) lossChart.applyOptions({ width: lossEl.offsetWidth, height: lossEl.offsetHeight });
    if (predEl.offsetWidth > 0) predChart.applyOptions({ width: predEl.offsetWidth, height: predEl.offsetHeight });
  });
  resizeObserver.observe(lossEl);
  resizeObserver.observe(predEl);

  return {
    handleProgress,
    getConfig() {
      return { symbol: config.symbol, epochs: config.epochs, lr: config.lr, hiddenSize: config.hiddenSize };
    },
    destroy() {
      resizeObserver.disconnect();
      lossChart.remove();
      predChart.remove();
    },
  };
}
```

- [ ] **Step 2: Syntax-check all three touched/created JS files**

Run:
```bash
node --input-type=module --check < "src/dashboard/static/js/ml.js"
node --input-type=module --check < "src/dashboard/static/js/widgets.js"
node --input-type=module --check < "src/dashboard/static/js/ws.js"
```
Expected: no output (silence = valid syntax) for all three

- [ ] **Step 3: Persist ml-widget config fields through layout save/restore**

In `src/dashboard/static/js/layout.js`, update `saveWorkspace`'s per-widget spread (already
spreads `inst.handle.getConfig()`, so `epochs`/`lr`/`hiddenSize` are saved automatically — no
change needed there). In `restoreWorkspace`, extend the `config` object passed to
`addWidgetInstance` to carry the new fields through:

```javascript
    const config = {
      symbol: w.symbol,
      timeframeSeconds: w.timeframeSeconds,
      indicators: w.indicators,
      baseSymbol: w.baseSymbol,
      compareSymbols: w.compareSymbols,
      epochs: w.epochs,
      lr: w.lr,
      hiddenSize: w.hiddenSize,
    };
```

- [ ] **Step 4: Re-run syntax check on `layout.js`**

Run: `node --input-type=module --check < "src/dashboard/static/js/layout.js"`
Expected: no output

- [ ] **Step 5: Commit this task together with Task 7's edits**

```bash
git add src/dashboard/static/js/ml.js src/dashboard/static/js/widgets.js src/dashboard/static/js/ws.js src/dashboard/static/js/layout.js
git commit -m "feat(dashboard): add NN training visualizer widget (loss curve + predicted-vs-actual)"
```

---

### Task 9: Manual verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite one more time**

Run: `python -m uv run pytest -x -q && python -m uv run ruff check src/ main.py tests/ scripts/ && python -m uv run mypy src/ main.py scripts/`
Expected: all green

- [ ] **Step 2: Backfill real data for at least one symbol**

Requires `docker compose up -d` (TimescaleDB running) and a valid `.env`. Run:
```bash
python -m uv run python scripts/backfill_history.py --symbols AAPL
```
Expected: log line `backfill_complete symbol=AAPL bars=<count>` with `count` in the thousands.

- [ ] **Step 3: Boot the dashboard and drive it from a browser**

Run: `python -m uv run python main.py`, open `http://localhost:8080`. Use the "+ Add View" menu
to add an "NN Predictor" widget for AAPL. Click Start with the default hyperparameters. Confirm:
- The loss-curve chart animates (train loss trending down, val loss shown alongside).
- The predicted-vs-actual chart updates each epoch with fresh validation-window lines.
- The status line shows `epoch N/50 ...` incrementing, ending in `... — done`.
- Clicking Stop mid-run halts further updates (no more epoch increments).
- Reloading the page and re-adding the same widget config from a saved layout does not crash
  (epochs/lr/hidden-size inputs reflect the previously saved values).

- [ ] **Step 4: Confirm no regressions in existing widgets**

Spot-check that Chart/Metrics/Orders/Holdings/Compare widgets still work as before (no shared
state was mutated by this feature) — add one of each from a fresh "Trading" template and confirm
they render.

This task has no commit of its own — it's a verification gate. If any check fails, fix the
underlying issue in the relevant task's files and re-commit there.
