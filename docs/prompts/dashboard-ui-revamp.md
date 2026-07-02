# Prompt: Dashboard UI Revamp (Legend-inspired)

Paste this into Claude Code at the repo root (`Hedge fund/`).

---

## Context

Read `CLAUDE.md` first and follow it exactly — especially: don't touch `src/broker/`,
`src/risk/`, `src/strategies/`, or `src/data_ingestion/`; async-only I/O; structured logging
via `get_logger`; `python -m uv` for all package commands (not bare `uv`).

The dashboard lives entirely in `src/dashboard/` (`app.py` + `templates/index.html`, one
inline `<script>`, no build step, backed by TradingView `lightweight-charts` v4.1.3 loaded
from a CDN `<script>` tag). It's a single monolithic HTML file — one big global `state` object,
manual DOM string-templating, no modules.

**Goal:** make the UI feel closer to Robinhood Legend (widget-based layout, resizable/movable
panels, technical indicators, linked charts, saved layout presets) — without breaking the
existing WebSocket contract, the FastAPI routes, or anything outside `src/dashboard/`.

**Hard constraints — do not violate these:**
1. WebSocket message shape is a public contract: `{"type": "snapshot"|"bar"|"order"|"position"|"portfolio", ...}` as currently emitted by `DashboardState` in `app.py`. Do not rename or restructure these without updating every consumer, and prefer additive changes (new optional fields) over breaking ones.
2. Existing REST routes (`/api/snapshot`, `/api/portfolio`, `/api/orders/{symbol}`, `/api/bars/{symbol}`, `/api/subscribe/{symbol}`) keep working as-is. New endpoints are additive only.
3. Keep a rollback path: preserve the current UI as `templates/index_legacy.html`, reachable via `?legacy=1`, until the new UI has been manually verified against it.
4. Run `python -m uv run pytest`, `python -m uv run ruff check src/ main.py tests/`, and `python -m uv run mypy src/ main.py` before calling any phase done.

## Why the current "Compare" mode doesn't work

It overlays every symbol as a % normalized line series on one shared scale. That collapses
actual price action into a flat squiggle and doesn't answer what someone actually wants from a
compare view: *how do these symbols relate to each other right now* (relative performance,
volatility, correlation), not just "which line is higher on a 0-100% axis."

**Replace it with a metrics comparison panel, not another chart mode:** a table of the
subscribed/watchlisted symbols with, per row: last price, session % change, volume vs. average
volume, realized volatility (stdev of 1-min returns over the visible window), and correlation
to the currently active symbol — plus a small inline sparkline per row for an at-a-glance
trend. All of this is computable client-side from bar data already in `state.bars` / already
served by `/api/bars/{symbol}` — no new backend logic required for v1. Sparklines give the
visual signal the old overlay was trying to give, the table gives the numeric signal it wasn't.

## Phase 0 — groundwork (do this first, it's what makes parallel agents safe)

The whole frontend is one `<script>` block in `index.html`. Multiple agents editing that block
concurrently will produce merge conflicts. Before spawning anything:

1. Extract the inline script into ES modules served as static files (mount via FastAPI
   `StaticFiles`, no bundler needed — plain `<script type="module">` imports work fine in
   modern browsers): `static/js/state.js`, `static/js/ws.js`, `static/js/chart.js`,
   `static/js/compare.js`, `static/js/orders.js`, `static/js/holdings.js`, `static/js/layout.js`,
   `static/js/main.js` (entry point that wires the rest together).
2. Verify the extracted app is byte-for-byte behaviorally identical to today (all existing
   features work) before moving on. Commit this as its own commit.
3. Confirm what version of `lightweight-charts` supports stacked panes (separate chart panes
   for RSI etc., not just a secondary price scale on the same pane) — check the current pinned
   v4.1.3 CDN build vs. v5. If v5 is needed for panes, upgrade the CDN `<script>` tag and
   smoke-test candlesticks + volume still render before building indicators on top of it. Don't
   assume — check the actual shipped API.

## Phase 1 — vanilla JS polish (ship this first, it's the fast win)

Spawn these as **parallel subagents** (use the Task tool) once Phase 0 is committed, since they
now touch mostly-disjoint files:

- **Agent A — `compare-metrics`**: build the new compare panel described above in
  `static/js/compare.js` — stats table + sparklines, computed client-side from
  `state.bars`/`/api/bars/{symbol}`, replacing the current normalized-overlay compare mode.
  Correlation = Pearson correlation of aligned 1-min returns between each symbol and the active
  symbol.
- **Agent B — `chart-indicators`**: in `static/js/chart.js`, add overlay indicators (SMA(20),
  EMA(9), VWAP) on the main candlestick pane and RSI(14) in a separate pane below, each
  toggleable from a small indicator menu (mirrors Legend's indicator picker, doesn't need to be
  90+ indicators — 4 is plenty for v1). Compute indicators client-side from the same bar data
  already available; don't add backend computation for this.
- **Agent C — `grid-layout`**: integrate GridStack.js (MIT, no build step, drops straight into
  a static-file setup) so the metrics/orders/holdings panels become draggable and resizable
  widgets, with the layout persisted to `localStorage`. Add 2-3 layout presets (e.g. "Trading",
  "Compare", "Monitor") selectable from a dropdown, mirroring Legend's layout templates.

Each agent should work on its own file(s) and commit independently. After all three land, run
one **verification agent**:

- **Agent D — `verify`**: run `pytest`, `ruff`, `mypy`; boot the dashboard
  (`python -m uv run python main.py`) and manually check the WebSocket messages haven't changed
  shape (compare against a snapshot taken before Phase 0); confirm `index_legacy.html` still
  works via `?legacy=1`; take before/after screenshots of both UIs for the PR description.

## Phase 2 — optional follow-up, not required for this pass

If Phase 1 ships well and the dashboard is worth investing further in, a full React rewrite
(Vite + React + Tailwind, `react-grid-layout` for widgets, FastAPI serving the built static
bundle) would get closer to Legend's actual architecture — real widget linking across tabs,
saved layouts synced server-side instead of `localStorage`, more indicators. Don't start this
until Phase 1 is merged and used for a bit; a rewrite before you know which widgets you
actually want is wasted effort. If/when this happens, build it to 1:1 parity with the Phase 1
vanilla UI first as a gate before adding anything new on top.

## Notes for whoever's driving this

- Everything above only touches `src/dashboard/`. If any agent finds itself wanting to edit
  `src/risk/`, `src/broker/`, `src/data_ingestion/`, or `src/strategies/`, stop — that's out of
  scope for a UI pass.
- Work on a branch (`ui/legend-revamp` or similar), not `main`.
- Prefer client-side computation for indicators/stats over new backend endpoints unless a
  specific feature genuinely needs server-side data it doesn't already have — keeps the surface
  area small and the WebSocket contract stable.
