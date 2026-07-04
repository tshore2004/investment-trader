# Handoff — 2026-07-03: dashboard shipped, next phase is strategy/backtesting

## Where things stand

- **Widget dashboard is done and PR'd.** Branch `ui/customizable-widgets` → PR at
  `https://github.com/tshore2004/investment-trader/pull/new/ui/customizable-widgets` (open,
  not yet merged — merge is the user's call once they're happy with the diff). Manual browser
  pass was completed and confirmed working by the user. See the "Module map" and "Dashboard"
  sections of `CLAUDE.md` for the current architecture (widget registry in
  `static/js/widgets.js`, portfolio-value line chart via `PORTFOLIO_SYMBOL`, full-workspace
  localStorage persistence).
- **Secrets incident, resolved.** `.env` had been committed since the repo's first commit and
  was live on public GitHub (`tshore2004/investment-trader`, public repo) with a real DB
  password and IB paper account number; a separate local-only commit had also added a plaintext
  IB login (unused by the app). All fixed this session:
  - `.env` untracked (`git rm --cached`, then a clean commit); unused IB login lines deleted.
  - DB password rotated live in the running `hedge_timescaledb` container (`ALTER ROLE`) and
    matched in local `.env`. The old exposed password is now dead regardless of history.
  - Git history rewritten with `git-filter-repo` to strip `.env` from every commit on every
    branch, then force-pushed to `origin/master`. **All local branch commit hashes changed** —
    if this repo exists anywhere else (another machine, a fork), it needs a fresh clone or a
    hard reset to the new hashes, not a pull.
- **SMA crossover strategy is functionally complete but not yet formally signed off.**
  `src/strategies/sma_crossover.py` exists, registered in `main.py` in place of `NoOpStrategy`,
  5/5 unit tests pass. The `PositionLimitCheck` price-injection fix from the (now-deleted)
  `phase1_claude_code_prompt.md` is also done (`src/risk/checks.py` uses `last_prices` for
  market orders now, no more `# FIXME`). What's missing is the **live verification workflow**
  that file specified — it was never run end-to-end against a real boot (hit every endpoint,
  open `/ws`, confirm clean `SIGTERM` shutdown) — only pytest/ruff/mypy were checked. All of
  this work currently sits in one `wip:` commit rather than atomic ones.
- **Docs cleaned up this session** (this pass). Removed, because each was either fully
  implemented or fully superseded by current code/this doc:
  - `phase1_claude_code_prompt.md`, `docs/prompts/dashboard-ui-revamp.md`
  - `docs/superpowers/plans/2026-07-01-dashboard-legend-revamp.md`
  - `docs/superpowers/plans/2026-07-02-customizable-widget-dashboard.md`
  - `docs/superpowers/specs/2026-07-02-customizable-widget-dashboard-design.md`
  - `docs/handoff/2026-07-02-session-handoff.md` (superseded by this file)
  - `.superpowers/sdd/progress.md`, `task-1-brief.md`, `task-1-report.md` (untracked scratch
    scaffolding for the now-merged legend-revamp task)
  - `CLAUDE.md` updated to match current code (widget registry, portfolio hypertable,
    price-aware risk check, sma_crossover.py, WS message types, test count).
  - `TODO.md` left as-is — it's an active backlog (auto-populating the watchlist), not stale.

## Roadmap position (vs `Thomas_Robert_Shore_Comprehensive_Hedge_Fund_Plan.pdf`)

4 phases: **P1** multi-asset ingestion/engineering core, **P2** AI engines (regime classifier,
lead-lag models, NLP), **P3** institutional risk controls (circuit breaker, Kelly sizing,
Sharpe/Sortino), **P4** corporate shell + GIPS audit log.

**Status: Phase 1 essentially complete** (equities-only slice: IBKR via ib_insync, asyncio feed
→ TimescaleDB, dashboard, SMA crossover strategy) **plus early Phase 3** (per-order risk gating
is ahead of schedule). Phase 1's one real gap: **no backtesting engine**.

## Recommended next steps, in order

1. **Close out the SMA crossover pass formally.** Run the live verification workflow: boot the
   real stack (`docker compose up -d`, TWS paper, `python -m uv run python main.py`), hit every
   endpoint (`GET /`, `/api/snapshot`, `/api/portfolio`, `POST /api/subscribe/MSFT`) for real
   status codes/JSON, open `/ws` and confirm the initial `snapshot` message shape, send `SIGTERM`
   and confirm `shutdown_complete` logs. Then split the `wip:` commit into atomic `feat:`/`fix:`
   commits. This is coded but not yet signed off.
2. **Backtesting harness** — the biggest real Phase 1 gap and a prerequisite for all of Phase 2.
   Pragmatic approach: replay stored TimescaleDB bars through the existing
   `BarCallback`/`StrategyRegistry` path so live and backtest share one code path; consider
   QuantConnect LEAN only once multi-asset-class support actually matters.
3. **Phase 3 hardening before AI work**: an independent async circuit-breaker task in
   `main.py`'s `asyncio.gather` (3% daily drawdown → flatten/cancel/freeze per the PDF), Kelly-
   fraction position sizing to replace fixed quantities, Sharpe/Sortino surfaced on the
   dashboard.
4. **Then start Phase 2 with the Macro Regime Classifier** (scikit-learn GMM/K-Means on macro
   series) — simplest AI layer, plugs into `RiskEngine`. Defer LSTM/NLP until backtesting
   exists. `TODO.md`'s watchlist auto-populate idea is a natural bridge project first.
5. Phase 4's immutable fill/NAV audit log can start any time as a TimescaleDB table — all fills
   already flow through `IBBroker`.

## How to resume

```bash
git checkout ui/customizable-widgets   # or master, once the PR above is merged
python -m uv run pytest -x -q          # should be 47 passed
docker compose up -d && python -m uv run python main.py   # then verify per step 1 above
```

Merging the open PR is a decision for the user, not something to do automatically — ask before
merging or before any further force-push/history operation on this repo.
