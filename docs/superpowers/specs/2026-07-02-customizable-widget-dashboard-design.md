# Customizable Widget Dashboard — Design

## Goal

Turn the fixed 4-widget GridStack dashboard (chart, metrics, orders, holdings — built in the prior Legend-revamp pass) into a fully customizable workspace: an "Add View" menu lets the user spawn, configure, and remove widget instances freely, including multiple independent Chart widgets watching different symbols simultaneously. One of those symbols is a new synthetic "My Portfolio" option that renders total portfolio value over time instead of a stock's OHLC bars, backed by a new durable snapshot history in TimescaleDB.

## Non-goals (explicit YAGNI)

- No server-side layout sync across devices — `localStorage` only, same as the existing layout feature.
- No back-filling portfolio history from trade records — snapshots start accumulating only once this ships; there is no way to reconstruct value at a past date from data we never recorded.
- No indicators (SMA/EMA/VWAP/RSI) on the portfolio-value line — it's a single value series, not OHLC bars, and the user explicitly declined this.
- No new widget types beyond Chart (with the portfolio mode folded in), Metrics, Trade History, Holdings, and Compare — matches what the user asked for ("holdings, history, the chart... another stock") plus the earlier decision to split Compare out of the Chart widget.
- No changes to `src/risk/`, `src/strategies/` risk-check logic — this is additive read-only reporting on top of existing broker/store data.

## Architecture

### Widget catalog & instance model

Today, `chart.js` creates exactly one `lightweight-charts` instance at module scope, and `orders.js`/`holdings.js` render into fixed, singular DOM containers keyed by hardcoded element IDs. That doesn't extend to "N independent chart widgets." The core change: **each widget type becomes a factory that can be instantiated multiple times**, and each instance owns:

```
{
  id: "chart-a1b2c3",       // unique per instance, doubles as the GridStack gs-id
  type: "chart" | "metrics" | "orders" | "holdings" | "compare",
  symbol: "AAPL" | "__PORTFOLIO__" | null,   // null for holdings (portfolio-wide) and compare (see below)
  timeframeSeconds: 60,      // chart only
  indicators: ["SMA20"],     // chart only, ignored when symbol === "__PORTFOLIO__"
  baseSymbol: "AAPL",        // compare only — the symbol correlation is measured against
  compareSymbols: ["MSFT"],  // compare only — the other rows in the table
}
```

`__PORTFOLIO__` is a reserved symbol sentinel (not a valid ticker, so it can't collide with a real subscription) that the Chart factory checks for and branches on.

A new **widget registry** (`static/js/widgets.js`) maps `type` → `{ create(container, config), destroy(instance), label }`. `create()` renders into the given DOM container and returns handles the registry needs for updates and teardown (e.g. the chart's series objects, so `destroy()` can call `chart.remove()` and unsubscribe from `ws.js`'s dispatch). This registry is what the "Add View" menu and `layout.js`'s persistence loop both drive off of — neither has to know the internals of any specific widget type.

The existing `compare.js` (metrics table + sparklines, built in the prior pass) becomes this registry's `compare` factory largely as-is — its `renderCompareMetrics()`/`addCompareSymbol()`/`removeCompareSymbol()` logic is unchanged, just parameterized by the owning instance's `baseSymbol`/`compareSymbols` instead of the single global `state.activeSymbol`/`state.compareSymbols`. The Chart widget's "Compare" mode toggle (`setMode` in `compare.js`) goes away — Compare is now something you add from the menu, not a mode switch inside Chart.

### Per-widget symbol routing

Today `ws.js`'s `handleMessage` dispatches bar/order/portfolio updates by checking against a single `state.activeSymbol`. With multiple instances, dispatch has to fan out to every widget instance interested in a given symbol instead of one global active symbol. `ws.js` keeps a `Map<symbol, Set<widgetId>>` (rebuilt whenever a widget's symbol changes) and calls each subscribed widget's own update function directly instead of the current single `window.__renderChart` style global calls used by task-6-era code. The global `window.__*` hooks from the prior pass are being replaced by this registry-based dispatch — the previous approach assumed one instance per type and doesn't extend.

### GridStack integration

Each widget instance is a GridStack item (`gs-id` = instance id). "Add View" calls `grid.addWidget(...)` with a default size per type, then calls the registry's `create()` into the new item's content div. Removing a widget calls the registry's `destroy()` then `grid.removeWidget(...)`. The existing Trading/Compare/Monitor presets become *starting templates*: picking one from the menu replaces the current widget set with that template's predefined instance list (not just repositioning fixed panels, since panels are no longer fixed).

### Persistence

`layout.js`'s `localStorage` payload changes shape from "positions of 4 known widgets" to a full reconstructable workspace:

```json
{
  "widgets": [
    { "id": "chart-a1b2c3", "type": "chart", "symbol": "AAPL", "timeframeSeconds": 60, "indicators": ["SMA20"], "x": 0, "y": 0, "w": 6, "h": 6 },
    { "id": "chart-d4e5f6", "type": "chart", "symbol": "__PORTFOLIO__", "x": 6, "y": 0, "w": 6, "h": 6 },
    { "id": "holdings-1",   "type": "holdings", "x": 0, "y": 6, "w": 12, "h": 3 }
  ]
}
```

On load: if a saved workspace exists, `layout.js` recreates every widget from this list (calling the registry, not GridStack's own `load()`, since GridStack only knows positions — widget *content* has to be rebuilt by us). If not, it falls back to the "Trading" template exactly as today.

## Backend: portfolio value history

- `src/data_ingestion/store.py` gets a `portfolio_value` hypertable (mirrors the existing `bars` table pattern exactly): `timestamp TIMESTAMPTZ NOT NULL, value FLOAT8 NOT NULL, PRIMARY KEY (timestamp)`. New methods `insert_portfolio_snapshot(value, timestamp)` and `get_portfolio_history(limit=5000)`, following the same `INSERT ... ON CONFLICT DO NOTHING` / `SELECT ... ORDER BY timestamp` shape as the bar methods.
- `main.py`'s existing `_portfolio_poll_loop` (10s interval, already polling `broker.portfolio_snapshot()`) gets one addition: `total_value = sum(row["qty"] * row["price"] for row in rows if row.get("price"))`, then `await store.insert_portfolio_snapshot(total_value, datetime.now(UTC))`, before the existing `update_portfolio` broadcast call.
- `DashboardState.update_portfolio` (or a small sibling method) also broadcasts `{"type": "portfolio_value", "value": total_value, "timestamp": ...}` — additive to the WS contract, doesn't touch existing message types.
- New route `GET /api/portfolio/history` returns `store.get_portfolio_history()` — same pattern as `GET /api/bars/{symbol}`.
- **Known tradeoff, accepted for now:** a snapshot every 10 seconds is ~8,640 rows/day. TimescaleDB handles this fine at this scale; no compression/downsampling policy is being added in this pass (YAGNI — revisit if/when it matters).

### Chart widget's portfolio mode

When a Chart widget's `symbol === "__PORTFOLIO__"`:
- On creation and on each `portfolio_value` WS message, it fetches/accumulates `{time, value}` points and renders a single `lightweight-charts` line series (no candles, no volume histogram, no indicator menu — the indicator dropdown is hidden entirely for this mode, matching "no volume/indicators" from the design conversation).
- Empty state (no holdings, value always 0): render the line at 0 rather than showing an empty/error chart, consistent with how `holdings.js` already renders a "No holdings" placeholder row instead of a blank table.
- Symbol picker offers "My Portfolio" as a distinct option alongside typed-in tickers (e.g. a small dropdown/typeahead with "My Portfolio" pinned at the top, tickers below).

## Data flow

**Adding a widget:** click "Add View" → menu shows widget types (Chart/Metrics/Trade History/Holdings/Compare) with a symbol input for Chart/Metrics/Trade History ("My Portfolio" pinned as a Chart option) or a base+compare symbol picker for Compare → `widgets.js` registry creates the instance + GridStack item → `ws.js` registers the new instance in its symbol→widgets dispatch map → `layout.js` persists the updated widget list (debounced, same pattern as today).

**Removing a widget:** click the widget's "×" → registry `destroy()` (tears down chart instance / unsubscribes) → `grid.removeWidget()` → `layout.js` persists.

**Portfolio snapshot:** `_portfolio_poll_loop` (10s) → `store.insert_portfolio_snapshot()` (durable) → `DashboardState` broadcasts `portfolio_value` over `/ws` (live) → every Chart widget in portfolio mode appends the point and re-renders its line series. On page load, each portfolio-mode Chart widget also calls `GET /api/portfolio/history` once to backfill, same pattern `loadBarHistory` already uses for stock charts.

## Error handling

- Adding a Chart widget with a symbol not yet subscribed: reuse the existing `/api/subscribe/{symbol}` best-effort flow already in `compare.js`/`chart.js` — widget shows "waiting for data" until the first bar arrives.
- Removing the last widget of a type is allowed (unlike today's fixed 4-widget assumption) — an empty grid is a valid, if unhelpful, state; no special-casing needed.
- `store.insert_portfolio_snapshot` failure (DB hiccup): caught inside `_portfolio_poll_loop`'s existing broad `except Exception: log.exception(...)` — one missed snapshot doesn't crash the poll loop, matches existing error handling in that function.
- Corrupt/unparseable `localStorage` workspace JSON on load: fall back to the "Trading" template, same recovery behavior `layout.js` already has today for corrupt saved layouts.

## Testing

- Backend: pytest coverage for `TimeseriesStore.insert_portfolio_snapshot`/`get_portfolio_history` (mirroring existing `test_store.py`-style tests for bars, if present, or a new focused test module), and for the new `/api/portfolio/history` route via `TestClient`.
- Frontend: no JS test harness exists in this repo (same constraint as the prior dashboard plan) — verification is via `node --check` syntax validation, `TestClient`-based markup/routing checks, and a **required manual browser pass** before merging, since the prior branch's GridStack drag/resize behavior was never visually confirmed (main.py needs a live IB connection to boot, which wasn't available during that work). This time, explicitly block "done" on the user confirming the add/remove/drag/persist flow works in a real browser.

## Branching

New branch off current `master` (which already includes the Legend-revamp GridStack work). Suggested name: `ui/customizable-widgets`.

## Open questions resolved during brainstorming

- Multiple independent Chart widgets, each with its own symbol/timeframe/indicators: **yes**.
- Widget catalog: Chart, Metrics, Trade History, Holdings — Compare panel splits out into its own addable widget type too (revisiting a shortcut taken in the prior pass).
- Metrics/Trade History also get per-instance symbols, not tied to one global active symbol: **yes**.
- Full workspace (widget set + per-widget config, not just position) persists to `localStorage`: **yes**.
- Portfolio value history: **backend-durable** (TimescaleDB), not browser-only.
- Portfolio is not a separate widget type — it's a symbol mode (`__PORTFOLIO__`) on the existing Chart widget.
- Portfolio chart mode: line only, no volume/indicators.
