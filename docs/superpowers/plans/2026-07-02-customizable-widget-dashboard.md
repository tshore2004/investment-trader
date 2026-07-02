# Customizable Widget Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed 4-widget GridStack dashboard with an "Add View" driven workspace of multi-instance widgets (Chart/Metrics/Trade History/Holdings/Compare), including a `__PORTFOLIO__` chart mode backed by a durable TimescaleDB portfolio-value history.

**Architecture:** Each widget type becomes a factory in a new `static/js/widgets.js` registry; `ws.js` fans messages out to instances via a symbol→widgets map; `layout.js` persists the full widget list (type + config + position) to localStorage. Backend adds a `portfolio_value` hypertable, a `GET /api/portfolio/history` route, and a `portfolio_value` WS broadcast fed by `main.py`'s existing 10s poll loop.

**Tech Stack:** FastAPI, SQLAlchemy async + TimescaleDB, lightweight-charts 4.1.3, GridStack 12.6, vanilla ES modules. Spec: `docs/superpowers/specs/2026-07-02-customizable-widget-dashboard-design.md`.

## Global Constraints

- Branch: `ui/customizable-widgets` off master.
- Reserved symbol sentinel: `__PORTFOLIO__` (exact string).
- localStorage key stays `hedge-dashboard-layout`; corrupt JSON falls back to the "Trading" template.
- No changes to `src/risk/` or `src/strategies/`.
- No JS test harness exists: verify JS with `node --check`, backend with pytest; **manual browser pass required before merge** (blocked on user confirmation).
- Commands: `python -m uv run pytest -x -q`, `python -m uv run ruff check src/ main.py tests/`, `python -m uv run mypy src/ main.py`.

---

### Task 1: Backend — portfolio_value hypertable + store methods

**Files:**
- Modify: `src/data_ingestion/store.py`
- Test: `tests/data_ingestion/test_store_portfolio.py` (new)

**Produces:**
- `TimeseriesStore.insert_portfolio_snapshot(value: float, timestamp: datetime) -> None`
- `TimeseriesStore.get_portfolio_history(limit: int = 5000) -> list[dict[str, Any]]` (rows: `{"timestamp": ..., "value": ...}` chronological ASC)

Mirror the existing bars pattern exactly:

```sql
CREATE TABLE IF NOT EXISTS portfolio_value (
    timestamp TIMESTAMPTZ NOT NULL,
    value     FLOAT8      NOT NULL,
    PRIMARY KEY (timestamp)
)
-- SELECT create_hypertable('portfolio_value', 'timestamp'::name, if_not_exists => TRUE)
-- INSERT ... ON CONFLICT DO NOTHING
-- SELECT with innermost DESC LIMIT :limit subquery, outer ORDER BY timestamp ASC
```

`connect()` gains two more separate `conn.execute()` calls (asyncpg: one statement per execute).

- [ ] Write failing tests (mock engine, same style as existing store tests: assert SQL executed with right params)
- [ ] Implement; run `python -m uv run pytest tests/data_ingestion -x -q` → PASS
- [ ] Commit: `feat(store): portfolio_value hypertable + snapshot insert/history`

### Task 2: Backend — WS broadcast, /api/portfolio/history, poll-loop insert

**Files:**
- Modify: `src/dashboard/app.py` (DashboardState + route), `main.py` (`_portfolio_poll_loop`)
- Test: `tests/dashboard/test_portfolio_history.py` (new; TestClient)

**Produces:**
- `DashboardState.update_portfolio_value(value: float, timestamp: str) -> None` — broadcasts `{"type": "portfolio_value", "value": float, "timestamp": iso-str}`
- `GET /api/portfolio/history` → `store.get_portfolio_history()` (empty list if store unset)

`_portfolio_poll_loop(broker)` becomes `_portfolio_poll_loop(broker, store)`:

```python
rows = broker.portfolio_snapshot()
await get_state().update_portfolio(rows)
total_value = sum(r["qty"] * r["price"] for r in rows if r.get("price"))
now = datetime.now(UTC)
await store.insert_portfolio_snapshot(total_value, now)
await get_state().update_portfolio_value(total_value, now.isoformat())
```

(inside the existing broad `except Exception: log.exception(...)` loop).

- [ ] TestClient test for route (monkeypatch store) + broadcast unit test → fail → implement → PASS
- [ ] `ruff` + `mypy` clean on touched files
- [ ] Commit: `feat(dashboard): portfolio value history route + WS broadcast + snapshot poll`

### Task 3: Frontend — widget registry (`widgets.js`)

**Files:**
- Create: `src/dashboard/static/js/widgets.js`
- Modify: `src/dashboard/static/js/chart.js` (chart becomes a factory: `createChartWidget(container, config)` returning `{ update(sym), setTimeframe(s), destroy() }`; module-scope singleton chart removed), `orders.js`, `holdings.js`, `compare.js` (parameterize by container + config), `state.js` (drop `mode`; keep bars cache global)

**Registry contract (what Tasks 4–5 consume):**

```js
// widgets.js
export const WIDGET_TYPES = {
  chart:    { label: 'Chart',         defaultSize: { w: 6, h: 6 } },
  metrics:  { label: 'Metrics',       defaultSize: { w: 4, h: 3 } },
  orders:   { label: 'Trade History', defaultSize: { w: 4, h: 3 } },
  holdings: { label: 'Holdings',      defaultSize: { w: 6, h: 3 } },
  compare:  { label: 'Compare',       defaultSize: { w: 8, h: 4 } },
};
export const PORTFOLIO_SYMBOL = '__PORTFOLIO__';
export const instances = new Map();  // id -> { id, type, config, handle }
export function createWidget(type, config, container) // renders, registers, returns instance
export function destroyWidget(id)                     // teardown + unregister
export function widgetsForSymbol(sym)                 // instances whose config.symbol === sym
export function allInstances()                        // for layout persistence
```

Chart factory: per-instance lightweight-charts instance, per-instance timeframe dropdown + indicator menu (hidden when `symbol === PORTFOLIO_SYMBOL`), portfolio mode = single line series fed by `GET /api/portfolio/history` backfill + `portfolio_value` WS pushes; renders a 0-line when empty. Stock mode reuses existing resample/indicator functions (moved to pure helpers taking `(chartHandle, bars, timeframe)`).

- [ ] `node --check` on every touched JS file
- [ ] Commit: `feat(dashboard): widget registry with multi-instance factories`

### Task 4: Frontend — ws.js fan-out dispatch

**Files:**
- Modify: `src/dashboard/static/js/ws.js`

Replace `window.__*` global calls with registry dispatch:
- `bar` → append to `state.bars[sym]`, then update every widget instance whose config references `sym` (charts, metrics, compare rows).
- `portfolio_value` → every chart widget with `config.symbol === PORTFOLIO_SYMBOL` gets `.appendPortfolioPoint({time, value})`.
- `order`/`position`/`portfolio`/`snapshot` → route to orders/metrics/holdings instances respectively.

- [ ] `node --check`; commit: `feat(dashboard): registry-based WS fan-out`

### Task 5: Frontend — layout.js workspace persistence + Add View menu + index.html

**Files:**
- Modify: `src/dashboard/static/js/layout.js`, `main.js`, `templates/index.html`

- Payload: `{ widgets: [{ id, type, symbol, timeframeSeconds, indicators, baseSymbol, compareSymbols, x, y, w, h }] }`.
- On load: parse → recreate each via `createWidget` + `grid.addWidget`; corrupt/absent → Trading template (chart on first watchlist symbol + metrics + orders + holdings, current preset geometry).
- Presets become templates that clear all instances and instantiate the template list.
- Header gains "Add View" button → dropdown of widget types with symbol input ("My Portfolio" pinned first for Chart); each widget gets an "×" remove control in its panel header.
- index.html: strip the four hardcoded `grid-stack-item`s (grid starts empty), keep header; per-widget markup moves into `widgets.js` template strings.

- [ ] `node --check` all JS; `python -m uv run pytest -x -q` still green
- [ ] Commit: `feat(dashboard): Add View menu + full workspace persistence`

### Task 6: Verification

- [ ] `python -m uv run pytest -x -q` (all), `ruff check`, `mypy src/ main.py`
- [ ] `node --check` every file in `src/dashboard/static/js/`
- [ ] **Manual browser pass (USER):** add/remove/drag/persist widgets, two charts w/ different symbols, portfolio chart line renders. BLOCKS merge.
