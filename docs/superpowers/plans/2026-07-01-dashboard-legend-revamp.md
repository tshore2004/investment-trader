# Dashboard Legend-Inspired UI Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `src/dashboard/` (currently one FastAPI route + one 577-line monolithic `index.html` with an inline `<script>`) into a widget-based, Robinhood-Legend-style dashboard — draggable/resizable panels, chart indicators, a real metrics-based compare panel, and saved layouts — without changing the WebSocket contract or REST routes.

**Architecture:** Split the inline `<script>` into ES modules served as static files under `src/dashboard/static/js/` (no bundler — plain `<script type="module">`), mounted via FastAPI `StaticFiles`. Keep `templates/index.html` as the new shell, preserve the old monolithic file as `templates/index_legacy.html` reachable via `?legacy=1`. Layer in GridStack.js for widgets, client-side indicator math, and a client-side compare-metrics panel — all computed from data already in `state.bars` / already served by existing endpoints. Backend (`app.py`, `DashboardState`, REST routes, WS message shapes) is additive-only.

**Tech Stack:** FastAPI `StaticFiles`, vanilla ES modules, TradingView `lightweight-charts` (v4.1.3, upgrade to v5 only if needed for stacked panes — verified in Task 5), GridStack.js (MIT, CDN, no build step).

## Global Constraints

- Do not touch `src/broker/`, `src/risk/`, `src/strategies/`, or `src/data_ingestion/` — out of scope for this UI pass.
- WebSocket message shape is a public contract: `{"type": "snapshot"|"bar"|"order"|"position"|"portfolio", ...}` as emitted by `DashboardState` in `src/dashboard/app.py:46-93`. No renames/restructures — additive optional fields only.
- Existing REST routes stay working as-is: `/api/snapshot`, `/api/portfolio`, `/api/orders/{symbol}`, `/api/bars/{symbol}`, `/api/subscribe/{symbol}` (`src/dashboard/app.py:129-159`). New endpoints are additive only.
- `templates/index_legacy.html` (byte-identical copy of today's `index.html`) must stay reachable via `GET /?legacy=1` until the new UI is manually verified.
- Prefer client-side computation (indicators, compare stats) over new backend endpoints — all needed bar data is already in `state.bars` or served by `/api/bars/{symbol}`.
- Run `python -m uv run pytest`, `python -m uv run ruff check src/ main.py tests/`, and `python -m uv run mypy src/ main.py` before calling any phase done. Use `python -m uv`, never bare `uv`.
- No JS test harness exists in this repo today — this plan does not introduce one. Each frontend task's "test" step is a scripted manual browser check (steps to perform + exact expected DOM/console state), not an automated test file. Backend changes (the new `StaticFiles` mount) do get a pytest test.
- No comments explaining *what* code does — only non-obvious *why* (e.g. the resample dedup-by-timestamp behavior already commented in `index.html:219-220,257-258`).

## File Structure

```
src/dashboard/
├── app.py                          — MODIFY: mount StaticFiles at /static, add ?legacy=1 branch to GET /
├── templates/
│   ├── index.html                  — REPLACE: new shell (header, grid containers, GridStack root, <script type="module" src="/static/js/main.js">)
│   └── index_legacy.html           — CREATE: byte-identical copy of today's index.html (frozen rollback)
└── static/
    └── js/
        ├── state.js                — CREATE: shared `state` object + pure helpers (resampleBars, colorForCompareSymbol)
        ├── ws.js                   — CREATE: WebSocket connect/reconnect + handleMessage dispatch
        ├── chart.js                — CREATE: lightweight-charts init, candle/volume series, renderChart, timeframe handling, indicator overlays (Phase 1 Agent B)
        ├── compare.js               — CREATE: compare-metrics panel — stats table + sparklines (Phase 1 Agent A, replaces old overlay-mode compare)
        ├── orders.js                — CREATE: renderOrders, loadOrderHistory
        ├── holdings.js              — CREATE: renderHoldings
        ├── layout.js                — CREATE: GridStack wiring, layout presets, localStorage persistence (Phase 1 Agent C)
        └── main.js                  — CREATE: entry point — imports all modules, wires DOM event listeners, calls connect()
tests/dashboard/
└── test_app.py                     — CREATE (Task 1): tests for StaticFiles mount + ?legacy=1 route behavior
```

**Interfaces every module must respect** (so Phase 1's three parallel agents don't collide):

- `state.js` exports a single mutable `state` object with exactly the fields currently on the inline `state` (`bars, orders, positions, activeSymbol, portfolio, watchlist, tradingEnabled, timeframeSeconds, mode, compareSymbols, compareColors`) plus whatever Phase 1 tasks need to add (documented per-task below). Only `state.js` defines `state` — every other module imports it: `import { state } from './state.js';`
- `state.js` exports `resampleBars(bars, seconds)` and `colorForCompareSymbol(sym)` unchanged from `index.html:221-236,248-255`.
- `chart.js` exports `renderChart(sym)`, `updateMetrics(sym, rawBars, displayedBars)`, and the `chart`/`candleSeries`/`volSeries` objects (needed by `ws.js` and `layout.js` for resize).
- `ws.js` exports `connect()` and owns `handleMessage`, calling into `chart.js`/`compare.js`/`orders.js`/`holdings.js` render functions via `window.__*` registrations (documented in Task 2).
- `orders.js` exports `renderOrders()`, `loadOrderHistory(sym)`.
- `holdings.js` exports `renderHoldings()`.
- `compare.js` exports `renderCompareMetrics()` and `setMode(mode)` (mode toggle now lives here since it decides chart-vs-compare view).
- `layout.js` exports `initLayout()`.
- `main.js` imports `connect` from `ws.js`, `initLayout` from `layout.js`, wires the DOM `onclick`/`keydown` handlers currently at the bottom of `index.html` (`sym-btn`, `tf-menu`, `mode-toggle`), and calls `connect()` + `initLayout()` on load.

---

### Task 1: Mount static files + legacy rollback route

**Files:**
- Modify: `src/dashboard/app.py:1-22` (imports, `_MAX_BARS`), `src/dashboard/app.py:121-128` (`create_app`, `index` route)
- Create: `src/dashboard/templates/index_legacy.html` (byte-identical copy of current `src/dashboard/templates/index.html`)
- Test: `tests/dashboard/test_app.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `GET /` serves `index.html` normally; `GET /?legacy=1` serves `index_legacy.html`; `GET /static/js/*.js` serves files from `src/dashboard/static/js/` with `Content-Type: text/javascript` (FastAPI's `StaticFiles` sets this from the `.js` extension automatically).

- [ ] **Step 1: Copy current index.html to index_legacy.html**

```bash
cp "src/dashboard/templates/index.html" "src/dashboard/templates/index_legacy.html"
```

- [ ] **Step 2: Create the static/js directory placeholder so StaticFiles has a mount target**

```bash
mkdir -p "src/dashboard/static/js"
```

- [ ] **Step 3: Write the failing test**

```python
# tests/dashboard/test_app.py
from __future__ import annotations

import pathlib

from fastapi.testclient import TestClient

from src.dashboard.app import create_app


def test_index_serves_new_ui_by_default() -> None:
    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.status_code == 200


def test_index_legacy_query_param_serves_legacy_html() -> None:
    client = TestClient(create_app())
    resp = client.get("/?legacy=1")
    legacy_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "src" / "dashboard" / "templates" / "index_legacy.html"
    )
    assert resp.status_code == 200
    assert resp.text == legacy_path.read_text(encoding="utf-8")


def test_static_js_directory_is_mounted() -> None:
    client = TestClient(create_app())
    static_dir = (
        pathlib.Path(__file__).parent.parent.parent
        / "src" / "dashboard" / "static" / "js"
    )
    static_dir.mkdir(parents=True, exist_ok=True)
    probe = static_dir / "_mount_probe.js"
    probe.write_text("export const probe = true;\n", encoding="utf-8")
    try:
        resp = client.get("/static/js/_mount_probe.js")
        assert resp.status_code == 200
        assert "probe" in resp.text
    finally:
        probe.unlink()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m uv run pytest tests/dashboard/test_app.py -v`
Expected: FAIL — `tests/dashboard/__init__.py` missing / `/?legacy=1` returns same content as `/` (no `legacy` branch yet) / `/static/js/...` 404s (`StaticFiles` not mounted).

- [ ] **Step 5: Write minimal implementation**

```python
# src/dashboard/app.py — add import near top (after existing fastapi imports)
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
```

```python
# src/dashboard/app.py — replace the existing `index` route in create_app()
    _static_dir = _pl.Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> str:
        templates_dir = _pl.Path(__file__).parent / "templates"
        filename = "index_legacy.html" if request.query_params.get("legacy") == "1" else "index.html"
        return (templates_dir / filename).read_text(encoding="utf-8")
```

Move `import pathlib as _pl` to module level (top of `app.py`, with the other imports) since it's now needed at `create_app()` scope for `_static_dir` too — remove the old in-function `import pathlib as _pl` that lived inside the previous `index()` body.

- [ ] **Step 6: Create tests/dashboard/__init__.py if tests/ subpackages require it**

Check whether `tests/data_ingestion/` and `tests/risk/` have `__init__.py`; mirror that convention for `tests/dashboard/`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m uv run pytest tests/dashboard/test_app.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Run full verification suite**

Run: `python -m uv run pytest && python -m uv run ruff check src/ main.py tests/ && python -m uv run mypy src/ main.py`
Expected: all green

- [ ] **Step 9: Commit**

```bash
git add src/dashboard/app.py src/dashboard/templates/index_legacy.html tests/dashboard/
git commit -m "feat(dashboard): mount static files, add ?legacy=1 rollback route"
```

---

### Task 2: Extract state.js and ws.js

**Files:**
- Create: `src/dashboard/static/js/state.js`, `src/dashboard/static/js/ws.js`
- Note: `index.html`'s inline script stays untouched until Task 4 — this task only adds new files, so the page keeps working exactly as before via the old inline script in the meantime.

**Interfaces:**
- Consumes: nothing (these are the base modules).
- Produces: `state` object, `resampleBars`, `colorForCompareSymbol` from `state.js`; `connect()` from `ws.js`. `ws.js`'s `handleMessage` calls `window.__renderChart`, `window.__renderCompareMetrics`, `window.__renderOrders`, `window.__renderHoldings`, `window.__updateMetrics`, `window.__ensureTab`, `window.__switchSymbol`, `window.__setModeBadge` — indirection via `window` is intentional so `ws.js` doesn't need to import every render module directly (avoids a circular-import-shaped dependency graph across the 8 files); each render module registers its function onto `window` at the bottom of its own file, e.g. `window.__renderOrders = renderOrders;`.

- [ ] **Step 1: Write state.js**

```javascript
// src/dashboard/static/js/state.js
export const state = {
  bars: {}, orders: [], positions: {}, activeSymbol: null, portfolio: [], watchlist: [],
  tradingEnabled: false, timeframeSeconds: 60, mode: 'chart', compareSymbols: [], compareColors: {},
};

export const COMPARE_PALETTE = ['#F5C518', '#79c0ff', '#3fb950', '#f85149', '#c586ff', '#ff9d5c', '#5ce1e6', '#eaeaea'];

// Aggregates raw 1-minute bars into `seconds`-wide candles (open=first, high=max,
// low=min, close=last, volume=sum). Bars must already be in ascending time order.
export function resampleBars(bars, seconds) {
  const buckets = new Map();
  for (const b of bars) {
    const bucketTime = Math.floor(b.time / seconds) * seconds;
    const agg = buckets.get(bucketTime);
    if (!agg) {
      buckets.set(bucketTime, { time: bucketTime, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume });
    } else {
      agg.high = Math.max(agg.high, b.high);
      agg.low = Math.min(agg.low, b.low);
      agg.close = b.close;
      agg.volume += b.volume;
    }
  }
  return Array.from(buckets.values()).sort((a, b) => a.time - b.time);
}

export function colorForCompareSymbol(sym) {
  if (!state.compareColors[sym]) {
    const used = new Set(Object.values(state.compareColors));
    const next = COMPARE_PALETTE.find(c => !used.has(c)) || COMPARE_PALETTE[state.compareSymbols.length % COMPARE_PALETTE.length];
    state.compareColors[sym] = next;
  }
  return state.compareColors[sym];
}
```

- [ ] **Step 2: Write ws.js**

```javascript
// src/dashboard/static/js/ws.js
import { state } from './state.js';

function handleMessage(msg) {
  if (msg.type === 'snapshot') {
    state.positions = msg.positions || {};
    state.portfolio = msg.portfolio || [];
    state.watchlist = msg.watchlist || [];
    state.tradingEnabled = !!msg.trading_enabled;
    for (const [sym, bars] of Object.entries(msg.bars || {})) {
      state.bars[sym] = bars;
      window.__ensureTab(sym);
    }
    if (state.activeSymbol) window.__switchSymbol(state.activeSymbol);
    window.__renderHoldings();
    window.__setModeBadge(state.tradingEnabled);
  } else if (msg.type === 'bar') {
    const sym = msg.symbol;
    if (!state.bars[sym]) state.bars[sym] = [];
    const last = state.bars[sym][state.bars[sym].length - 1];
    if (last && last.time === msg.data.time) {
      state.bars[sym][state.bars[sym].length - 1] = msg.data;
    } else {
      state.bars[sym].push(msg.data);
    }
    window.__ensureTab(sym);
    if (state.mode === 'chart' && state.activeSymbol === sym) {
      window.__renderChart(sym);
    } else if (state.mode === 'compare') {
      window.__renderCompareMetrics();
    }
  } else if (msg.type === 'order') {
    if (msg.data.symbol === state.activeSymbol) {
      state.orders.push(msg.data);
      window.__renderOrders();
    }
  } else if (msg.type === 'position') {
    state.positions[msg.symbol] = msg.value;
    if (state.activeSymbol === msg.symbol) window.__updateMetrics(msg.symbol);
  } else if (msg.type === 'portfolio') {
    state.portfolio = msg.data || [];
    window.__renderHoldings();
  }
}

export function connect() {
  const badge = document.getElementById('conn-badge');
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { badge.textContent = 'LIVE'; badge.className = 'badge live'; };
  ws.onclose = () => { badge.textContent = 'DISCONNECTED'; badge.className = 'badge disconnected'; setTimeout(connect, 3000); };
  ws.onerror = () => ws.close();
  ws.onmessage = e => { try { handleMessage(JSON.parse(e.data)); } catch(err) { console.error(err); } };
}
```

- [ ] **Step 3: Manual check — files are valid syntax**

Open each file in a text editor / browser devtools Sources tab after Task 4 wires them in and confirm no syntax errors reported in the console. (No Node toolchain is assumed to be installed in this repo — do not add one.)

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/static/js/state.js src/dashboard/static/js/ws.js
git commit -m "refactor(dashboard): extract state.js and ws.js from inline script"
```

---

### Task 3: Extract chart.js, orders.js, holdings.js (baseline parity, no new features yet)

**Files:**
- Create: `src/dashboard/static/js/chart.js`, `src/dashboard/static/js/orders.js`, `src/dashboard/static/js/holdings.js`

**Interfaces:**
- Consumes: `state`, `resampleBars` from `state.js`.
- Produces: `chart.js` exports `chart, candleSeries, volSeries, renderChart, updateMetrics, ensureTab, switchSymbol, loadBarHistory, setModeBadge`; registers `window.__renderChart`, `window.__updateMetrics`, `window.__ensureTab`, `window.__switchSymbol`, `window.__setModeBadge`. `orders.js` exports `renderOrders, loadOrderHistory`; registers `window.__renderOrders`. `holdings.js` exports `renderHoldings`; registers `window.__renderHoldings`.

- [ ] **Step 1: Write chart.js** (verbatim port of `index.html:180-210,238-246,339-365,447-469` plus the resize listener)

```javascript
// src/dashboard/static/js/chart.js
import { state, resampleBars } from './state.js';
import { loadOrderHistory } from './orders.js';

const chartEl = document.getElementById('chart');
export const chart = LightweightCharts.createChart(chartEl, {
  layout: { background: { color: '#0a0a0a' }, textColor: '#a39c8f' },
  grid: { vertLines: { color: '#1a1a1a' }, horzLines: { color: '#1a1a1a' } },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  rightPriceScale: { borderColor: '#262626' },
  timeScale: {
    borderColor: '#262626',
    timeVisible: true,
    secondsVisible: true,
    tickMarkFormatter: (time) => new Date(time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  },
  localization: {
    timeFormatter: (time) => new Date(time * 1000).toLocaleTimeString(),
  },
  width: chartEl.offsetWidth,
  height: chartEl.offsetHeight,
});

export const candleSeries = chart.addCandlestickSeries({
  upColor: '#3fb950', downColor: '#f85149',
  borderUpColor: '#3fb950', borderDownColor: '#f85149',
  wickUpColor: '#3fb950', wickDownColor: '#f85149',
});

export const volSeries = chart.addHistogramSeries({
  priceFormat: { type: 'volume' },
  priceScaleId: 'vol',
  color: '#F5C51833',
});
chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

export function renderChart(sym) {
  sym = sym || state.activeSymbol;
  if (!sym) return;
  const raw = state.bars[sym] || [];
  const displayed = resampleBars(raw, state.timeframeSeconds);
  candleSeries.setData(displayed);
  volSeries.setData(displayed.map(b => ({ time: b.time, value: b.volume, color: b.close >= b.open ? '#3fb95044' : '#f8514944' })));
  updateMetrics(sym, raw, displayed);
}

export function updateMetrics(sym, rawBars, displayedBars) {
  rawBars = rawBars || state.bars[sym] || [];
  displayedBars = displayedBars || resampleBars(rawBars, state.timeframeSeconds);
  const last = rawBars[rawBars.length - 1];
  if (last) {
    const cl = last.close;
    const prev = rawBars.length > 1 ? rawBars[rawBars.length - 2].close : cl;
    const pct = ((cl - prev) / prev * 100).toFixed(2);
    const color = cl >= prev ? 'green' : 'red';
    document.getElementById('m-close').textContent = `$${cl.toFixed(2)} (${pct}%)`;
    document.getElementById('m-close').className = `metric-value ${color}`;
    document.getElementById('m-vol').textContent = last.volume.toLocaleString();
    document.getElementById('m-bars').textContent = displayedBars.length;
    document.getElementById('last-ts').textContent = new Date(last.time * 1000).toLocaleTimeString();
  }
  const pos = state.positions[sym];
  document.getElementById('m-pos').textContent = pos !== undefined ? `$${pos.toLocaleString(undefined, {maximumFractionDigits: 0})}` : '—';
}

export async function loadBarHistory(sym) {
  try {
    const r = await fetch('/api/bars/' + encodeURIComponent(sym));
    const rows = await r.json();
    const fetched = rows.map(row => ({
      time: Math.floor(new Date(row.timestamp).getTime() / 1000),
      open: row.open, high: row.high, low: row.low, close: row.close, volume: row.volume,
    }));
    const merged = new Map();
    for (const b of fetched) merged.set(b.time, b);
    for (const b of (state.bars[sym] || [])) merged.set(b.time, b);
    state.bars[sym] = Array.from(merged.values()).sort((a, b) => a.time - b.time);
  } catch (e) {
    // keep whatever bars we already have in memory
  }
  if (state.activeSymbol === sym) renderChart(sym);
}

export function switchSymbol(sym) {
  state.activeSymbol = sym;
  document.querySelectorAll('#symbol-tabs .sym-tab').forEach(t => t.classList.toggle('active', t.dataset.sym === sym));
  renderChart(sym);
  loadOrderHistory(sym);
  loadBarHistory(sym);
}

export function ensureTab(sym) {
  const tabs = document.getElementById('symbol-tabs');
  if (!tabs.querySelector(`[data-sym="${sym}"]`)) {
    const btn = document.createElement('button');
    btn.className = 'sym-tab';
    btn.dataset.sym = sym;
    btn.textContent = sym;
    btn.onclick = () => switchSymbol(sym);
    tabs.appendChild(btn);
  }
  if (!state.activeSymbol) switchSymbol(sym);
}

export function setModeBadge(enabled) {
  const el = document.getElementById('mode-badge');
  if (enabled) {
    el.textContent = 'LIVE PAPER TRADING';
    el.className = 'badge live-trading';
  } else {
    el.textContent = 'DRY RUN';
    el.className = 'badge dryrun';
  }
}

window.__renderChart = renderChart;
window.__updateMetrics = updateMetrics;
window.__ensureTab = ensureTab;
window.__switchSymbol = switchSymbol;
window.__setModeBadge = setModeBadge;

window.addEventListener('resize', () => {
  chart.applyOptions({ width: chartEl.offsetWidth, height: chartEl.offsetHeight });
});
```

- [ ] **Step 2: Write orders.js** (verbatim port of `index.html:384-412`)

```javascript
// src/dashboard/static/js/orders.js
import { state } from './state.js';

export function renderOrders() {
  const tbody = document.getElementById('orders-body');
  const none = document.getElementById('no-orders');
  const orders = state.orders || [];
  if (orders.length === 0) { tbody.innerHTML = ''; none.style.display = 'block'; return; }
  none.style.display = 'none';
  tbody.innerHTML = orders.slice().reverse().map(o => {
    const rawTs = o.submitted_at || o.timestamp;
    const ts = rawTs ? new Date(rawTs).toLocaleString() : '—';
    return `
    <tr>
      <td>${ts}</td>
      <td class="side-${(o.side || '').toLowerCase()}">${o.side}</td>
      <td>${o.quantity}</td>
      <td class="status-${(o.status || '').toLowerCase()}">${o.status}</td>
    </tr>`;
  }).join('');
}

export async function loadOrderHistory(sym) {
  document.getElementById('orders-header-label').textContent = `Trade History — ${sym}`;
  try {
    const r = await fetch('/api/orders/' + encodeURIComponent(sym));
    state.orders = await r.json();
  } catch (e) {
    state.orders = [];
  }
  renderOrders();
}

window.__renderOrders = renderOrders;
```

- [ ] **Step 3: Write holdings.js** (verbatim port of `index.html:414-445`)

```javascript
// src/dashboard/static/js/holdings.js
import { state } from './state.js';

export function renderHoldings() {
  const tbody = document.getElementById('holdings-body');
  const none = document.getElementById('no-holdings');
  const portfolio = Array.isArray(state.portfolio) ? state.portfolio : [];
  const watchlist = Array.isArray(state.watchlist) ? state.watchlist : [];
  const seen = new Set(portfolio.map(p => p.symbol));
  const placeholders = watchlist
    .filter(sym => !seen.has(sym))
    .map(sym => ({ symbol: sym, qty: 0, avg_cost: null, price: null, unrealized_pnl: null, unrealized_pnl_pct: null }));
  const rows = portfolio.concat(placeholders);

  if (rows.length === 0) { tbody.innerHTML = ''; none.style.display = 'block'; return; }
  none.style.display = 'none';

  tbody.innerHTML = rows.map(r => {
    const isPlaceholder = r.avg_cost === null || r.avg_cost === undefined;
    const hasPnl = typeof r.unrealized_pnl === 'number';
    const pnlClass = hasPnl ? (r.unrealized_pnl >= 0 ? 'pnl-green' : 'pnl-red') : '';
    const pnlStr = hasPnl ? `$${r.unrealized_pnl.toFixed(2)}` : '—';
    const pnlPctStr = typeof r.unrealized_pnl_pct === 'number' ? `${r.unrealized_pnl_pct.toFixed(2)}%` : '—';
    const avgCostStr = typeof r.avg_cost === 'number' ? `$${r.avg_cost.toFixed(2)}` : '—';
    const priceStr = typeof r.price === 'number' ? `$${r.price.toFixed(2)}` : '—';
    return `<tr${isPlaceholder ? ' class="placeholder-row"' : ''}>
      <td>${r.symbol}</td>
      <td>${r.qty ?? 0}</td>
      <td>${avgCostStr}</td>
      <td>${priceStr}</td>
      <td class="${pnlClass}">${pnlStr}</td>
      <td class="${pnlClass}">${pnlPctStr}</td>
    </tr>`;
  }).join('');
}

window.__renderHoldings = renderHoldings;
```

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/static/js/chart.js src/dashboard/static/js/orders.js src/dashboard/static/js/holdings.js
git commit -m "refactor(dashboard): extract chart.js, orders.js, holdings.js from inline script"
```

---

### Task 4: Extract main.js, wire index.html to modules, verify byte-for-byte behavioral parity

**Files:**
- Create: `src/dashboard/static/js/main.js`
- Modify: `src/dashboard/templates/index.html` (replace inline `<script>...</script>` block, `index.html:179-575`, with `<script type="module" src="/static/js/main.js"></script>`; keep everything above it — head, styles, body markup — unchanged)

**Interfaces:**
- Consumes: `state`, `colorForCompareSymbol`, `resampleBars` from `state.js`; `connect` from `ws.js`; `chart`, `candleSeries`, `volSeries`, `renderChart`, `switchSymbol`, `ensureTab` from `chart.js`.
- Produces: page boot sequence identical to today's inline script's bottom section (`index.html:527-574`).

Note: for this task, the compare-mode toggle and legend rendering (`index.html:248-337`) plus the timeframe dropdown wiring stay temporarily inline in `main.js` as a straight port — Phase 1 Subtask 6A replaces the compare logic, and this task's only job is achieving parity, not building new features.

- [ ] **Step 1: Write main.js** — port `index.html:248-337` (compare/legend, temporary straight port) and `513-574` (event wiring + boot)

```javascript
// src/dashboard/static/js/main.js
import { state, colorForCompareSymbol, resampleBars } from './state.js';
import { connect } from './ws.js';
import { chart, candleSeries, volSeries, renderChart, switchSymbol, ensureTab } from './chart.js';

const lineSeriesBySymbol = {};

function renderCompare() {
  for (const sym of state.compareSymbols) {
    const raw = state.bars[sym] || [];
    const displayed = resampleBars(raw, state.timeframeSeconds);
    const series = lineSeriesBySymbol[sym];
    if (!series || displayed.length === 0) continue;
    const base = displayed[0].close;
    series.setData(displayed.map(b => ({ time: b.time, value: base ? (b.close - base) / base * 100 : 0 })));
  }
}

function renderLegend() {
  const el = document.getElementById('compare-legend');
  el.innerHTML = state.compareSymbols.map(sym => `
    <span class="legend-chip" data-sym="${sym}">
      <span class="legend-dot" style="background:${state.compareColors[sym]}"></span>${sym}
      <span class="legend-remove" data-remove="${sym}">&times;</span>
    </span>`).join('') + `<input id="compare-add-input" class="legend-add-input" placeholder="+ Add symbol" maxlength="8" />`;

  el.querySelectorAll('.legend-remove').forEach(x => {
    x.onclick = () => removeCompareSymbol(x.dataset.remove);
  });
  const input = document.getElementById('compare-add-input');
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const sym = input.value.toUpperCase().trim();
      if (sym) addCompareSymbol(sym);
      input.value = '';
    }
  });
}

async function addCompareSymbol(sym) {
  sym = sym.toUpperCase().trim();
  if (!sym || state.compareSymbols.includes(sym)) return;
  state.compareSymbols.push(sym);
  colorForCompareSymbol(sym);
  ensureTab(sym);
  try {
    await fetch('/api/subscribe/' + sym, { method: 'POST' });
  } catch (e) {
    // best effort — chart will just stay flat until data arrives
  }
  lineSeriesBySymbol[sym] = chart.addLineSeries({
    color: state.compareColors[sym], lineWidth: 2, priceFormat: { type: 'percent' },
  });
  renderLegend();
  renderCompare();
}

function removeCompareSymbol(sym) {
  state.compareSymbols = state.compareSymbols.filter(s => s !== sym);
  const series = lineSeriesBySymbol[sym];
  if (series) { chart.removeSeries(series); delete lineSeriesBySymbol[sym]; }
  renderLegend();
}

function setMode(mode) {
  state.mode = mode;
  const isCompare = mode === 'compare';
  document.querySelectorAll('#mode-toggle .sym-tab').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  document.getElementById('compare-legend').style.display = isCompare ? 'flex' : 'none';
  document.getElementById('symbol-tabs').style.display = isCompare ? 'none' : 'flex';
  candleSeries.applyOptions({ visible: !isCompare });
  volSeries.applyOptions({ visible: !isCompare });
  if (isCompare) {
    renderLegend();
    if (state.compareSymbols.length === 0 && state.activeSymbol) {
      addCompareSymbol(state.activeSymbol);
    } else {
      renderCompare();
    }
  } else {
    renderChart();
  }
}

window.__renderChart = renderChart;

document.getElementById('sym-btn').onclick = async () => {
  const sym = document.getElementById('sym-input').value.toUpperCase().trim();
  const status = document.getElementById('search-status');
  if (!sym) return;
  status.textContent = 'subscribing...';
  try {
    const r = await fetch('/api/subscribe/' + sym, { method: 'POST' });
    const j = await r.json();
    if (j.status === 'subscribed' || j.status === 'already_subscribed') {
      if (!state.bars[sym]) state.bars[sym] = [];
      ensureTab(sym);
      switchSymbol(sym);
      status.textContent = j.status === 'subscribed' ? sym + ' subscribed — loading data...' : sym + ' already active';
    } else {
      status.textContent = j.detail || 'error';
    }
  } catch(e) { status.textContent = 'request failed'; }
  setTimeout(() => document.getElementById('search-status').textContent = '', 3000);
};
document.getElementById('sym-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('sym-btn').click();
});

document.getElementById('tf-toggle').onclick = (e) => {
  e.stopPropagation();
  document.getElementById('tf-menu').classList.toggle('hidden');
};
document.querySelectorAll('#tf-menu .tf-option').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('#tf-menu .tf-option').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.timeframeSeconds = parseInt(btn.dataset.tf, 10);
    document.getElementById('tf-current').textContent = btn.textContent;
    document.getElementById('chart-label').textContent = `${btn.textContent} Bars (delayed)`;
    document.getElementById('tf-menu').classList.add('hidden');
    if (state.mode === 'compare') renderCompare(); else renderChart();
  };
});
document.addEventListener('click', (e) => {
  const dd = document.getElementById('tf-dropdown');
  if (dd && !dd.contains(e.target)) document.getElementById('tf-menu').classList.add('hidden');
});

document.querySelectorAll('#mode-toggle .sym-tab').forEach(btn => {
  btn.onclick = () => setMode(btn.dataset.mode);
});

connect();
```

- [ ] **Step 2: Replace index.html's inline script with the module script tag**

Delete `src/dashboard/templates/index.html` lines 179–575 (the entire `<script>...</script>` block) and replace with:

```html
<script type="module" src="/static/js/main.js"></script>
```

- [ ] **Step 3: Manual parity check against index_legacy.html**

Run: `python -m uv run python main.py`, open `http://localhost:8080/` and `http://localhost:8080/?legacy=1` side by side. For both pages:
1. Confirm candlestick + volume render for the default watchlist symbol.
2. Subscribe to a new symbol via the search box — confirm a new tab appears and the chart switches to it.
3. Switch timeframes via the hamburger dropdown (1m → 1h) — confirm bars resample and the label updates.
4. Toggle Chart → Compare mode — confirm the legend appears and a normalized line renders.
5. Confirm the orders table and holdings table populate identically.
6. Open browser devtools console on the new UI — confirm zero errors.

Expected: identical behavior on both pages.

- [ ] **Step 4: Run full verification suite**

Run: `python -m uv run pytest && python -m uv run ruff check src/ main.py tests/ && python -m uv run mypy src/ main.py`
Expected: all green (this task touches no Python logic, so this just guards against accidental breakage)

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/static/js/main.js src/dashboard/templates/index.html
git commit -m "refactor(dashboard): wire index.html to ES modules, remove inline script"
```

---

### Task 5: Verify lightweight-charts pane support, upgrade CDN version if needed

**Files:**
- Modify (conditionally): `src/dashboard/templates/index.html:7` (CDN `<script>` tag). `src/dashboard/templates/index_legacy.html` stays pinned to v4.1.3 always — it's the frozen rollback, never touch it.

**Interfaces:**
- Produces: a confirmed answer, recorded in this task's commit message, on whether v4.1.3 supports `chart.addPane()` / multi-pane layouts (needed for Subtask 6B's RSI sub-pane) or whether v5's pane API is required.

- [ ] **Step 1: Check the v4.1.3 API surface**

Open the CDN URL `https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js` in a browser and search (Ctrl+F) the source for `addPane`. v4.x only supports secondary price scales on the same pane via `priceScaleId` (already used for the volume histogram at `index.html:205-210`) — true stacked panes are a v5.0+ feature. Confirm this against the actual shipped build rather than assuming.

- [ ] **Step 2: If panes are needed for Subtask 6B (RSI), bump the CDN version**

```html
<!-- src/dashboard/templates/index.html:7 -->
<script src="https://unpkg.com/lightweight-charts@5.0.0/dist/lightweight-charts.standalone.production.js"></script>
```

- [ ] **Step 3: Smoke-test candlesticks + volume still render after the version bump**

Run: `python -m uv run python main.py`, open `http://localhost:8080/`, confirm candles and the volume histogram still render with no console errors. `addCandlestickSeries`/`addHistogramSeries` remain available in v5.0 as compatibility methods alongside the new `addSeries(SeriesType, options)` form — verify this at runtime against the actual v5.0 build, not from memory, since API surface can shift between minor versions.

- [ ] **Step 4: Commit (only if the version was bumped)**

```bash
git add src/dashboard/templates/index.html
git commit -m "chore(dashboard): bump lightweight-charts to v5 for stacked-pane support"
```

If v4.1.3 already supports panes, skip Steps 2-4 and instead note the finding directly in the Task 6 dispatch brief for Subtask 6B (no separate doc file, per Global Constraints).

---

### Task 6: Dispatch Phase 1 parallel agents (compare-metrics, chart-indicators, grid-layout)

This task is a dispatch step, not a code-writing step. Once Tasks 1-5 are committed, use `superpowers:dispatching-parallel-agents` to launch three agents against disjoint files. Each subtask below is the full brief for one agent — hand it the corresponding subtask verbatim plus this plan's Global Constraints and File Structure sections.

#### Subtask 6A — compare-metrics (owns `static/js/compare.js` only)

**Files:**
- Create: `src/dashboard/static/js/compare.js`
- Modify: `src/dashboard/static/js/main.js` — remove the inline `renderCompare`/`renderLegend`/`addCompareSymbol`/`removeCompareSymbol`/`setMode` functions added in Task 4 and import the equivalents from `compare.js` instead.
- Modify: `src/dashboard/templates/index.html` — replace `<div id="compare-legend"></div>` with a compare panel container: `<div id="compare-panel" style="display:none"></div>`.

**Interfaces:**
- Consumes: `state`, `resampleBars`, `colorForCompareSymbol` from `state.js`; `ensureTab` from `chart.js`; `candleSeries`, `volSeries` from `chart.js` (only to hide/show them when compare mode is active — no line series added to the main chart anymore).
- Produces: `compare.js` exports `setMode(mode)`, `renderCompareMetrics()`, `addCompareSymbol(sym)`, `removeCompareSymbol(sym)`. Registers `window.__renderCompareMetrics = renderCompareMetrics;` (matching the call already wired into `ws.js` in Task 2).

**Behavior spec:**
- Compare mode shows a table, one row per symbol in `state.compareSymbols` (plus the active symbol if not already in the list): columns are Symbol, Last Price, Session % Change, Volume vs Avg Volume, Realized Volatility (stdev of 1-min returns over the visible/resampled window — raw stdev-of-returns is fine for v1, label the column clearly), Correlation to `state.activeSymbol` (Pearson correlation of aligned 1-min returns; 1.0 for the active symbol's own row), and a small inline SVG or `<canvas>` sparkline of the last N closes.
- Compute correlation only over timestamps present in both symbols' bar arrays (inner join on `time`); if fewer than 2 overlapping points, render "—" instead of a number.
- Volume vs average volume = latest bar's volume / mean volume over the resampled window, shown as e.g. "1.8x".
- All computation reads `state.bars[sym]` already populated by `ws.js`/`chart.js`'s `loadBarHistory` — for symbols not yet subscribed, call `/api/subscribe/{symbol}` and `/api/bars/{symbol}` exactly as Task 4's `addCompareSymbol` did, no new backend endpoint.
- Adding/removing symbols from compare uses the same legend-chip UI pattern as before (`.legend-chip`, `.legend-remove`, `.legend-add-input` CSS classes already exist in `index.html`'s `<style>` — reuse them for the panel's symbol-picker row above the table).

**Manual test steps:** boot the app, subscribe to 2+ symbols, switch to Compare mode, confirm the table renders with non-"—" correlation once 2+ overlapping bars exist, confirm sparklines render, confirm removing a symbol updates the table live on the next `bar` WS message.

#### Subtask 6B — chart-indicators (owns `static/js/chart.js` only)

**Files:**
- Modify: `src/dashboard/static/js/chart.js` — add indicator overlay logic.
- Modify: `src/dashboard/templates/index.html` — add an indicator-picker control near `#tf-dropdown` (same toggle-button/menu pattern as `.tf-dropdown`/`.tf-menu`), and an RSI sub-pane container if v5 panes are in use per Task 5's outcome.

**Interfaces:**
- Consumes: `state`, `resampleBars` from `state.js`; `chart` (already owned by this module).
- Produces: exports `toggleIndicator(name, enabled)` and `SUPPORTED_INDICATORS = ['SMA20', 'EMA9', 'VWAP', 'RSI14']`; each toggle adds/removes a `lightweight-charts` line series (SMA/EMA/VWAP on the main pane via `chart.addLineSeries`; RSI in a separate pane if Task 5 upgraded to v5, else falls back to a secondary price scale via `priceScaleId: 'rsi'` with its own `scaleMargins`, the same technique already used for the volume histogram).

**Behavior spec:**
- SMA(20): simple moving average of `close` over the last 20 resampled bars — skip until 20 bars exist (no plotted point before that).
- EMA(9): seed with the first 9-bar SMA, then `EMA[t] = close[t] * k + EMA[t-1] * (1-k)`, `k = 2/(9+1)`.
- VWAP: cumulative `(close*volume)` / cumulative `volume`, reset whenever the resampled bar's local calendar date changes from the previous bar's (bars carry no explicit session marker).
- RSI(14): standard Wilder's RSI over 14-period average gain/loss of `close`-to-`close` changes.
- Recompute all active indicators whenever `renderChart()` runs (new bar arrives, timeframe changes, symbol switches) — indicators operate on the same `resampleBars()` output already used for candles.
- Indicator picker state persists per-session only (no `localStorage` requirement here — Subtask 6C's layout presets own persistence).

**Manual test steps:** boot the app, toggle each of the 4 indicators on, confirm lines render on/near the candlestick series (RSI in its own scale/pane), toggle off, confirm removal, switch timeframe and confirm indicators recompute without console errors.

#### Subtask 6C — grid-layout (owns `static/js/layout.js` + GridStack wiring only)

**Files:**
- Create: `src/dashboard/static/js/layout.js`
- Modify: `src/dashboard/templates/index.html` — wrap the existing panels (`#chart` panel, metrics panel, orders panel, holdings panel, and the compare panel from 6A) in GridStack's required markup (`<div class="grid-stack">` containing `<div class="grid-stack-item"><div class="grid-stack-item-content">...</div></div>` per widget), add the GridStack CDN `<script>`/`<link>` tags pinned to an exact version (e.g. `https://cdn.jsdelivr.net/npm/gridstack@10.1.2/dist/gridstack-all.js` and matching CSS — verify the exact latest stable version at implementation time rather than assuming `10.1.2`), and add a layout-preset `<select>` dropdown in the header.

**Interfaces:**
- Consumes: nothing from other Phase 1 modules directly — reads/writes `localStorage` under a single namespaced key (`hedge-dashboard-layout`) so it can't collide with anything else.
- Produces: exports `initLayout()` (called once from `main.js` after DOM ready, alongside `connect()`), which: (1) initializes `GridStack.init()` on `.grid-stack`, (2) restores a saved layout from `localStorage` if present, (3) wires the preset `<select>` to apply one of `PRESETS = { trading: [...], compare: [...], monitor: [...] }` (each preset is a GridStack layout array — widget id, x, y, w, h — matching the widget ids from the modified `index.html` markup), (4) saves to `localStorage` on GridStack's `change` event (debounced ~500ms).

**Behavior spec:**
- Widgets: chart panel, metrics panel, orders panel, holdings panel, compare panel (hidden/shown by 6A's `setMode`, but still a draggable widget when visible) — 5 widget ids total: `w-chart`, `w-metrics`, `w-orders`, `w-holdings`, `w-compare`.
- "Trading" preset: chart large/left, metrics+orders+holdings stacked right (mirrors today's default `.grid` layout — required as the default so first-load parity with `index_legacy.html` holds).
- "Compare" preset: compare panel large/left, chart smaller/top-right, holdings bottom-right.
- "Monitor" preset: metrics + holdings prominent, chart smaller, orders collapsed/small.
- On first load with no saved `localStorage` layout, apply the "Trading" preset as default.
- Must not break the resize handling already registered in `chart.js` (`window.addEventListener('resize', ...)` calling `chart.applyOptions({width, height})`) — additionally wire GridStack's `resizestop` event to call the same `chart.applyOptions({ width: chartEl.offsetWidth, height: chartEl.offsetHeight })` logic (import `chart` from `chart.js`), since dragging/resizing a GridStack widget doesn't fire a window `resize` event.

**Manual test steps:** boot the app, confirm "Trading" preset renders by default and matches `index_legacy.html`'s panel arrangement, drag a widget to a new position, resize a widget, reload the page — confirm the dragged/resized layout persists. Switch preset dropdown to "Compare" and "Monitor" — confirm layouts change. Clear `localStorage` and reload — confirm it falls back to "Trading".

---

### Task 7: Verification pass (Agent D)

**Files:** none created/modified — read-only verification. Any issues found get fixed in the relevant Task/Subtask's files directly, not written to a separate doc.

- [ ] **Step 1: Run backend verification**

Run: `python -m uv run pytest && python -m uv run ruff check src/ main.py tests/ && python -m uv run mypy src/ main.py`
Expected: all green.

- [ ] **Step 2: Confirm the WS snapshot shape is unchanged**

Run: `python -m uv run python -c "import json; from src.dashboard.app import DashboardState; print(json.dumps(DashboardState().snapshot(), default=str))"` and confirm the keys are exactly `type, bars, orders, positions, portfolio, watchlist, trading_enabled` — matching `src/dashboard/app.py:66-71`, which no task in this plan touches.

- [ ] **Step 3: Boot and manually verify both UIs**

Run: `python -m uv run python main.py`. Open `http://localhost:8080/` (new UI) and `http://localhost:8080/?legacy=1` (frozen old UI). Walk both through: subscribe to a symbol, switch timeframes, toggle compare mode, drag/resize a widget (new UI only), toggle an indicator (new UI only). Confirm no console errors on either page, and confirm `index_legacy.html` is byte-identical to the version committed in Task 1 (`git diff <task-1-commit>..HEAD -- src/dashboard/templates/index_legacy.html` should be empty).

- [ ] **Step 4: Confirm scope boundary held**

Run: `git diff --stat master...HEAD -- src/broker src/risk src/strategies src/data_ingestion`
Expected: empty output (no changes outside `src/dashboard/` and `tests/dashboard/`).

- [ ] **Step 5: Report findings**

Summarize pass/fail for each check above in the final integration commit message or PR description — no separate doc file.

---

## Self-Review Notes

- **Spec coverage:** Phase 0 (module extraction, parity check, lightweight-charts version check) → Tasks 1-5. Phase 1 Agent A/B/C → Subtasks 6A/6B/6C. Phase 1 Agent D (verify) → Task 7. `index_legacy.html` + `?legacy=1` rollback → Task 1. WebSocket contract preservation → Global Constraints + Task 7 Step 2. REST route preservation → Global Constraints + Task 1 (additive `?legacy=1` query param, no route renames). Compare-metrics replacing overlay compare → Subtask 6A. Indicators (SMA/EMA/VWAP/RSI) → Subtask 6B. GridStack widgets + presets + `localStorage` → Subtask 6C. Phase 2 (React rewrite) is explicitly out of scope for this plan per the spec ("don't start this until Phase 1 is merged").
- **Placeholder scan:** none found on re-read — Task 4's `setMode` uses real `candleSeries`/`volSeries` calls directly (no stub function), consistent with the exports declared in Task 3.
- **Type/interface consistency:** `window.__*` registration names verified to match between producer (`chart.js` in Task 3, `compare.js` in Subtask 6A) and consumer (`ws.js` in Task 2) — `window.__renderCompareMetrics` is called by `ws.js` from Task 2 onward (before Subtask 6A exists, compare mode simply won't update on new bars until 6A lands, which is expected mid-plan behavior, not a bug) and is registered by `compare.js` in Subtask 6A.
