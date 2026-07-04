# Stock Screener — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Scope:** Quant screener only (momentum / relative strength / RSI / volume & volatility).
Cramer-picks tracking and hedge-fund 13F consensus are explicitly out of scope for this spec —
they are separable follow-on projects layered on top of this one later.

## Purpose

Add a screener that scans a configurable universe of stocks (S&P 500 by default, or a broader
market listing) and ranks them by a composite quant score, so the user can find candidates worth
a closer look without manually checking metrics one symbol at a time.

## Non-goals (this spec)

- No external scraping of media sources (Cramer picks) or SEC 13F filings — future specs.
- No automatic order submission from screener results — it is a discovery tool, not a strategy.
  A user who likes a result still adds it as a symbol/strategy through existing flows.
- No intraday screening — daily bars are sufficient for the metrics in scope.

## Module layout

New package `src/screener/`, mirroring the existing `src/ml/` package's shape:

- **`universe.py`** — returns the ticker list for a requested universe:
  - `"sp500"` — bundled static list (e.g. `src/screener/data/sp500.txt`, one ticker per line)
  - `"broad"` — bundled static NASDAQ + NYSE listing file (`src/screener/data/broad_market.txt`)
  Static files avoid a live dependency on a third-party listing API; refreshing them is a manual,
  infrequent maintenance task (documented in a module docstring), not a runtime concern.

- **`data.py`** — `fetch_universe_bars(symbols: list[str]) -> dict[str, pd.DataFrame]`. Batches
  yfinance's `download()` (which accepts a space-separated ticker string) across the universe in
  chunks (yfinance/Yahoo rate-limits large single calls), pulling ~14 months of daily OHLCV
  (enough for a trailing 12-month momentum window). Caches the combined result to disk at
  `.cache/screener/{universe}_{YYYY-MM-DD}.parquet`; a cache hit for the current calendar day
  skips the network entirely. Stale caches (prior days) are ignored, not deleted.

- **`metrics.py`** — pure functions computing, per symbol, from its OHLCV DataFrame plus SPY's:
  - Momentum: 1mo / 3mo / 6mo / 12mo trailing returns
  - Relative strength: symbol's return minus SPY's return over the same windows
  - RSI(14) — same rolling-gain/loss formula as `src/ml/features.py`'s `_rsi`, factored so both
    modules can share it (moved to a small shared helper or duplicated with a comment pointing at
    the original — decided during implementation based on import-cycle risk)
  - Relative volume: latest day's volume vs. its own 20-day average
  - Realized volatility: annualized stddev of daily returns over 20 days
  - Trend quality: % of the last 50 sessions closing above the 50-day SMA
  Returns one row per symbol as a `pd.DataFrame` indexed by symbol; rows with insufficient
  history (e.g. recent IPOs) are dropped, not zero-filled.

- **`scorer.py`** — `score(metrics_df, weights: dict[str, float]) -> pd.DataFrame`. Converts each
  metric column to a percentile rank (0–100) across the universe so differently-scaled metrics
  (a % return vs. an RSI value) combine fairly, then computes a weighted sum as the composite
  score. Ships default weights (momentum 30%, relative strength 30%, RSI 15%, volume 10%,
  volatility 15%) but accepts caller-supplied overrides. Output is sorted descending by composite
  score.

- **`service.py`** — `run_screen(universe: str, weights: dict[str, float] | None,
  on_progress: Callable[[ScreenProgress], None] | None) -> pd.DataFrame`. Orchestrates
  universe → data → metrics → scorer, calling `on_progress` at coarse milestones (universe
  loaded, data fetched, metrics computed, done) so the dashboard can show a progress indicator
  during a broad-market scan. Runs synchronously (CPU/IO-bound, no internal async) — the caller
  (dashboard endpoint or CLI) is responsible for running it off the event loop thread if needed.

## Dashboard integration

Following the existing NN-trainer pattern (`/api/ml/train`, `/api/ml/stop`, `ml_training` WS
event):

- `POST /api/screener/run` — body: `{universe, weights?}`. Starts the screen via
  `asyncio.to_thread(run_screen, ...)` (keeps yfinance's blocking I/O off the event loop) and
  returns immediately; only one screen may run at a time (subsequent calls 409 until it finishes
  or is stopped).
- `POST /api/screener/stop` — cancels the in-flight task.
- New WS message type `screener_result`: `{status: "progress"|"done"|"error", stage?, results?}`.
  `DashboardState` broadcasts progress messages as `on_progress` fires, then a final `done`
  message carrying the ranked table (list of `{symbol, score, momentum_*, rel_strength_*, rsi14,
  rel_volume, volatility, trend_quality}` rows).

- New widget `src/dashboard/static/js/screener.js` (registered in `widgets.js`'s `WIDGET_TYPES`):
  universe dropdown (S&P 500 / broad market), an optional weights panel (defaults hidden behind
  an "advanced" toggle), Run/Stop buttons, and a sortable results table. Listens for
  `screener_result` messages via a new `dispatchScreenerResult` fan-out in `widgets.js`, mirroring
  how `ml_training` events are dispatched to the training widget.

## Standalone script

`scripts/run_screener.py` — same `run_screen()` service call, CLI args for `--universe` and
`--weights` (JSON string or path), writes the ranked table to a CSV in the working directory and
prints the top N to stdout. Follows the `backfill_history.py` precedent: usable without the
dashboard or IB connection running.

## Testing

- `tests/screener/test_metrics.py` — feed synthetic price series (e.g. a steady uptrend, a flat
  series, a series with a volume spike) into each metric function and assert expected direction/
  magnitude, not exact floating-point values.
- `tests/screener/test_scorer.py` — verify percentile-rank normalization and weighted-sum
  behavior with hand-constructed metric tables (e.g. confirm the top-ranked row by one metric
  alone doesn't dominate when its weight is low).
- `tests/screener/test_universe.py` — confirm `sp500`/`broad` loaders return non-empty,
  deduplicated, uppercased ticker lists from the bundled files.
- `data.py`'s yfinance calls are mocked in tests (patch `yf.download`) — no live network calls in
  CI, matching the existing test suite's convention.
- No JS test harness exists for `screener.js`, per project convention — validate with
  `node --input-type=module --check` and a manual browser pass through Run/Stop and result
  rendering.

## Open implementation decisions (left to planning/implementation, not blocking approval)

- Exact chunk size for batched yfinance calls (tune against observed rate-limiting).
- Whether `_rsi` is extracted to a shared helper or duplicated — decide once import-cycle
  implications between `src/ml/` and `src/screener/` are checked in the plan.
- Exact bundled ticker-list source/refresh process for `sp500.txt` / `broad_market.txt`.
