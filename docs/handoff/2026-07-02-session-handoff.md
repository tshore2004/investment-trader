# Session Handoff — 2026-07-02 (customizable widget dashboard + roadmap check)

## What was done this session

All work is on branch **`ui/customizable-widgets`** (master untouched). Commits, oldest first:

1. `wip: carry over uncommitted SMA-crossover/risk/dashboard session work` — the ~400 lines of
   uncommitted changes from the prior session (SMA crossover strategy, risk-check updates, .env,
   tests), committed as-is so later commits stay attributable. **Nothing was lost.**
2. `feat(store): portfolio_value hypertable + snapshot insert/history` —
   `src/data_ingestion/store.py` gains a `portfolio_value(timestamp, value)` hypertable,
   `insert_portfolio_snapshot()`, `get_portfolio_history()`; tests in
   `tests/data_ingestion/test_store_portfolio.py`.
3. `feat(dashboard): portfolio value history route + WS broadcast + snapshot poll` —
   `GET /api/portfolio/history`, `DashboardState.update_portfolio_value()` broadcasting
   `{"type":"portfolio_value",...}`, and `main.py`'s `_portfolio_poll_loop` now persists a
   total-portfolio-value snapshot every 10 s; tests in `tests/dashboard/test_portfolio_history.py`.
4. `feat(dashboard): customizable multi-instance widget workspace` — the whole frontend rewrite:
   - `static/js/widgets.js` (new): widget registry — chart/metrics/orders/holdings/compare
     factories, each instantiable N times; WS dispatch helpers.
   - `chart.js`: singleton → `createChartWidget(container, config, hooks)`; per-instance
     timeframe + indicators; `__PORTFOLIO__` symbol renders a value line (no candles/indicators).
   - `ws.js`: registry fan-out replaces the old `window.__*` globals.
   - `layout.js`: full workspace persistence to localStorage (`hedge-dashboard-layout`,
     `{widgets:[{id,type,symbol,timeframeSeconds,indicators,baseSymbol,compareSymbols,x,y,w,h}]}`),
     "Add View" menu, presets are now starting templates; corrupt JSON → Trading template.
   - `index.html`: grid starts empty; widgets render their own markup.

Spec: `docs/superpowers/specs/2026-07-02-customizable-widget-dashboard-design.md`.
Plan (tasks 1–5 done): `docs/superpowers/plans/2026-07-02-customizable-widget-dashboard.md`.

**Verification done:** 47/47 pytest, ruff clean, mypy strict clean, `node --input-type=module --check`
clean on all 9 JS files.

## What is NOT done — blockers for merge

- **Manual browser pass (required, user-only):** start the stack (`docker compose up -d`, TWS paper,
  `python -m uv run python main.py`), open http://localhost:8080 and confirm: Add View for each
  widget type; two Chart widgets on different symbols updating independently; a "My Portfolio"
  chart showing the value line (flat 0 until holdings exist and snapshots accumulate);
  remove via the corner "×"; drag/resize; reload restores the workspace; the Trading/Compare/
  Monitor select replaces the widget set. The old localStorage layout from the previous UI will be
  ignored (different shape) and falls back to the Trading template — expected.
- Merge decision: once the browser pass looks good, merge `ui/customizable-widgets` → `master`.

## Warnings / cleanups

- **`.env` is tracked in git** (was before this session). It holds credentials — consider
  `git rm --cached .env` + ensure `.gitignore` covers it before any remote push.
- A GateGuard hook (`pre:edit-write:gateguard-fact-force`) blocks the first Write/Edit per file and
  re-allows on retry; it roughly doubles write cost in agent sessions. Disable via
  `ECC_GATEGUARD=off` or `ECC_DISABLED_HOOKS` if that wasn't intentional.
- Portfolio snapshots accrue ~8.6k rows/day (accepted YAGNI in the spec; revisit compression later).

## Roadmap position (vs Thomas_Robert_Shore_Comprehensive_Hedge_Fund_Plan.pdf)

The PDF has 4 phases: **P1** multi-asset ingestion/engineering core, **P2** AI engines
(regime classifier, lead-lag LSTM/Transformers, NLP), **P3** institutional risk controls
(independent circuit breaker, Kelly sizing, Sharpe/Sortino), **P4** corporate shell + GIPS audit log.

**You are: Phase 1 essentially complete (equities-only slice) + early pieces of Phase 3.**
Evidence: IBKR via ib_insync ✓, asyncio feed → TimescaleDB ✓, dashboard ✓; per-order risk gating
(Drawdown + PositionLimit) is ahead of schedule. Phase 1 gaps: single asset class, **no backtesting
engine** (PDF prescribes QuantConnect LEAN). Phase 2: not started.

### Recommended next steps, in order

1. **Finish the in-flight SMA crossover pass** (`src/strategies/sma_crossover.py` + tests are on
   the branch's WIP commit; `phase1_claude_code_prompt.md` defines the acceptance rules —
   TRADING_ENABLED dry-run gating, MAX_TRADES_PER_DAY). Verify + give it its own clean commit(s).
2. **Backtesting harness** — biggest Phase 1 gap and prerequisite for all Phase 2 models.
   Pragmatic option: historical-replay harness piping stored TimescaleDB bars through the existing
   `BarCallback`/`StrategyRegistry` path so live and backtest share one code path; evaluate LEAN
   when multi-asset matters.
3. **Phase 3 hardening before AI**: independent async circuit-breaker task in `main.py`'s gather
   (3% daily drawdown → flatten/cancel/freeze per the PDF), Kelly-fraction sizing to replace fixed
   quantities, Sharpe/Sortino on the dashboard.
4. **Then start Phase 2 with the Macro Regime Classifier** (scikit-learn GMM/K-Means on macro
   series) — simplest AI layer, plugs into RiskEngine. Defer LSTM/NLP until backtesting exists.
   `TODO.md`'s watchlist scanner is a natural bridge project.
5. Phase 4's immutable fill/NAV audit log can start any time as a TimescaleDB table (all fills
   already flow through IBBroker).

## How to resume

```bash
git checkout ui/customizable-widgets
python -m uv run pytest -x -q        # should be 47 passed
docker compose up -d && python -m uv run python main.py   # then browser-test per above
```
