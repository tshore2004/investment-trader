# Design: Neural-Network Price Predictor + Live Training Visualizer

**Date:** 2026-07-03
**Status:** Approved by user, pending implementation

## Purpose

Add an experimental neural-network regression model that predicts next-bar percent return for a
symbol, trained on backfilled historical 1-minute bars, with a dashboard widget that visualizes
training progress live (loss curve + predicted-vs-actual overlay) as it trains. This is an
exploratory/educational feature, not a new trading signal — it does not feed `RiskEngine` or any
strategy in this pass.

## Scope

In scope:
- One-off historical backfill script for 1-min bars (yfinance, 60-day window)
- Feature engineering module (indicator + windowed feature/target construction)
- PyTorch MLP model + chronological-split training loop with per-epoch progress callback
- FastAPI endpoints to start/stop a training run
- WebSocket broadcast of per-epoch training progress
- Dashboard widget visualizing the live loss curve and predicted-vs-actual chart

Out of scope (explicitly deferred):
- Feeding model predictions into `RiskEngine`, `StrategyRegistry`, or order submission
- Persisting trained models to disk / reloading for inference across restarts
- Multi-symbol or ensemble models
- Any architecture beyond a feedforward MLP (no LSTM/attention in this pass)
- Automated JS test harness (project convention: manual browser pass + `node --check`)

## Data pipeline

### Historical backfill

`scripts/backfill_history.py` — one-off CLI script, not part of the running engine:

```
python -m uv run python scripts/backfill_history.py --symbols AAPL,MSFT
```

For each symbol: `yf.download(symbol, period="60d", interval="1m")`, convert rows to `Bar`
objects, insert via `TimeseriesStore.insert_bar()`. Reuses the existing `bars` hypertable and its
`(symbol, timestamp)` primary key / `ON CONFLICT DO NOTHING` — no schema changes, and re-running
the script is idempotent. Defaults to the current watchlist symbols if `--symbols` is omitted.

### Feature engineering — `src/ml/features.py`

Pure functions, no I/O, so they're independently unit-testable:

- `compute_indicators(bars: list[dict]) -> pd.DataFrame` — SMA(10), EMA(10), RSI(14), VWAP,
  ported from the indicator math already in `chart.js` (same formulas, Python/pandas
  implementation — the two are not code-shared, just formula-equivalent).
- `build_windows(df: pd.DataFrame, window: int = 30) -> tuple[np.ndarray, np.ndarray]` — for each
  position `i >= window`, `X[i]` is the flattened OHLCV+indicators for bars `[i-window, i)`, and
  `y[i]` is the percent return of bar `i+1` vs bar `i` (the target). Rows with NaN indicators
  (warm-up period) are dropped.

Feature vector per bar: `[open, high, low, close, volume, sma10, ema10, rsi14, vwap]` (9 values),
flattened across a 30-bar window → 270 input features per sample.

## Model + training — `src/ml/model.py`, `src/ml/trainer.py`

### Model

```python
class PricePredictorMLP(nn.Module):
    def __init__(self, input_size: int, hidden_size: int = 64):
        # Linear(input_size, hidden_size) -> ReLU
        # -> Linear(hidden_size, hidden_size // 2) -> ReLU
        # -> Linear(hidden_size // 2, 1)
```

### Trainer

`Trainer.run(symbol, epochs, lr, hidden_size, on_progress)`:

1. Load bars for `symbol` from `TimeseriesStore.get_bars()`, run through `features.py`.
2. Chronological 80/20 split (first 80% of rows = train, last 20% = val) — **no shuffling across
   the time axis**, to avoid leaking future information into training.
3. Standardize features (mean/std from train split only, applied to both splits).
4. For each epoch: one full-batch gradient step (dataset is small enough — no need for
   mini-batching or a DataLoader), compute train loss (MSE) and val loss (MSE on val split).
5. After each epoch, `await on_progress({epoch, total_epochs, train_loss, val_loss, sample_preds})`
   where `sample_preds` is the last 50 validation points as
   `[{ts, actual, predicted}, ...]`.
6. Runs the sync PyTorch step via `asyncio.to_thread` per epoch so the event loop stays responsive
   for the rest of the dashboard/engine.
7. Supports cooperative cancellation: `Trainer.stop()` sets a flag checked at the top of each
   epoch loop iteration.

Only one training run may be active per symbol at a time; starting a second is rejected with a
409-equivalent error via the API layer.

## Backend wiring — `src/dashboard/app.py`

- `POST /api/ml/train` — body `{symbol, epochs, lr, hidden_size}` (all but `symbol` optional with
  defaults: `epochs=50, lr=0.001, hidden_size=64`). Starts a background `asyncio.create_task`
  running `Trainer.run(...)`, storing it in `DashboardState` keyed by symbol so status/stop can
  find it. Returns `202` with a run id.
- `POST /api/ml/stop` — body `{symbol}`. Calls `Trainer.stop()` on the active run for that symbol,
  if any; no-op (200) if none is running.
- New WS message type `ml_training`: `{type: "ml_training", symbol, epoch, total_epochs,
  train_loss, val_loss, sample_preds}`, broadcast by the `on_progress` callback via
  `DashboardState`'s existing broadcast mechanism (same path `add_bar` etc. use).

## Dashboard widget — `src/dashboard/static/js/ml.js`

`createMlWidget(container, config, hooks)` — registered in `widgets.js`'s `WIDGET_TYPES` catalog
alongside Chart/Metrics/Orders/Holdings/Compare:

- Controls: symbol picker (reuses existing watchlist), epochs/lr/hidden-size number inputs,
  Start/Stop buttons.
- Loss curve: lightweight-charts line chart with two series (train loss, val loss), one point
  appended per epoch as `ml_training` messages arrive.
- Predicted-vs-actual: second lightweight-charts chart, two line series (actual return, predicted
  return) redrawn from `sample_preds` each message (last 50 val points).
- `ws.js` gets a `dispatchMlTraining(msg)` function that fans the message out to any widget
  instances currently configured for that symbol, following the existing `dispatchBar` pattern.

## Dependencies

- Add `torch` (CPU wheels) via `python -m uv add torch`.
- Add `yfinance`'s bulk `download()` usage in the new script (already a dependency via `feed.py`).

## Testing

- `tests/ml/test_features.py` — known small bar sequences → known indicator values (e.g. SMA of
  a constant series equals that constant); `build_windows` shape and NaN-dropping behavior.
- `tests/ml/test_trainer.py` — on a synthetic dataset with an exact linear relationship between
  a feature and the target, loss should decrease monotonically-ish over epochs and end near zero;
  `on_progress` fires exactly `epochs` times; `Trainer.stop()` called mid-run stops before
  completing all epochs.
- `tests/dashboard/test_ml_api.py` — `POST /api/ml/train` returns 202 and rejects a duplicate
  in-flight run for the same symbol with an error status; `POST /api/ml/stop` is a no-op when
  nothing is running.
- JS: `node --input-type=module --check < src/dashboard/static/js/ml.js`, then a manual browser
  pass (per project convention — no automated frontend suite exists).

## Risks / open questions carried into implementation

- PyTorch CPU wheel install size (~200MB) — acceptable per user's explicit choice.
- 60-day/1-min yfinance data may have gaps (market holidays, half days) — `build_windows` must
  treat the bar sequence as ordered-but-possibly-irregular and not assume fixed time deltas
  between consecutive rows within a window.
- Full-batch gradient descent on ~23K rows × 270 features is small enough for CPU but should be
  timed during implementation; if a single epoch takes too long to feel "live," mini-batching can
  be added without changing the external protocol.
