# Phase 1 — Safe Baseline Strategy + Black/Gold Dashboard Overhaul

Paste this whole thing into Claude Code, running from the `Hedge fund` project root.

---

## Context

Read `CLAUDE.md` first — it's the architecture reference and is authoritative for conventions
(async-everywhere, `get_settings()` singleton, structlog with kwargs, risk-before-submit, test
layout mirroring `src/`).

Current state: `NoOpStrategy` is a placeholder that logs bars and trades nothing. Market data is
yfinance (free, 15-20 min delayed), execution is IB paper (`IB_PORT=7497` in `.env.example` —
confirm this is still true, do not proceed if it points at 7496/live). `SYMBOLS = ["AAPL"]` is
hardcoded in `main.py`. The dashboard is a single dark-themed `index.html` (GitHub-dark palette,
not yet restyled) with a candlestick chart, order log, and metrics — no portfolio/holdings view
exists yet.

This is a two-part pass: **(A) a real but deliberately simple trading strategy**, and **(B) a
dashboard restyle + new holdings view**. Do NOT build the "better" strategy or any AI/ML layer in
this pass — that's explicitly future work. Say so in your final summary so scope doesn't creep.

## Non-negotiable safety rules

1. **Paper only.** Read `IB_PORT` from settings at startup and refuse to run (raise, don't warn)
   if it's not `7497` or `4002`. This check doesn't exist yet — add it.
2. **Dry-run by default.** Add a `TRADING_ENABLED` setting (default `False`). When false, the new
   strategy computes signals and logs the order it *would* submit, but never calls
   `self.submit()`. Flip it on only after you've verified the dry-run logs look sane.
3. **Never bypass the risk engine.** Every order still flows through `BaseStrategy.submit()` →
   `RiskEngine.approve()`. Don't add a second code path to `IBBroker.submit()`.
4. **Fix the known gap before relying on it.** `src/risk/checks.py` `PositionLimitCheck` has a
   `# FIXME`: market orders (no `limit_price`) fall back to a raw share-count cap instead of a
   USD cap, because there's no price feed injected into `RiskCheck`. The new strategy will submit
   market orders, so this gap is no longer theoretical — a $500 stock and a $5 stock hit the same
   share-count limit despite wildly different USD exposure. Inject last-traded-price (you already
   have it — the feed just saw a `Bar`) so `PositionLimitCheck` can compute real USD exposure for
   market orders too. Add tests for both the old share-count path (if price truly unavailable) and
   the new price-aware path.
5. **One position per symbol, capped trade frequency.** Add `MAX_TRADES_PER_DAY` (env-configurable,
   sane default like 5) enforced per-strategy — simple overtrading guard, cheap insurance.
6. **Config-driven symbol universe, not a hardcoded list.** Replace `SYMBOLS = ["AAPL"]` in
   `main.py` with a `WATCHLIST_SYMBOLS` setting (comma-separated env var, parsed in
   `src/utils/config.py`). This is also what the new "holdings/watchlist" UI panel will read.

## Part A — Baseline strategy

Implement an **SMA crossover** strategy (`src/strategies/sma_crossover.py`, subclassing
`BaseStrategy`, template from `noop_strategy.py`): fast SMA (default 20 bars) crosses above slow
SMA (default 50 bars) → buy signal; crosses below → sell/flatten. Rationale for picking this as
the *first* strategy: fully deterministic, trivially unit-testable against a synthetic bar series,
no lookahead bias if implemented on bar-close only, and easy for you (Thomas) to sanity-check by
eye on the chart. Don't gold-plate it — no parameter optimization, no multi-timeframe logic, no
position sizing beyond the existing risk caps. That's Phase 2.

Requirements:
- Maintain a rolling price buffer per symbol (bounded deque, not unbounded list).
- Only ever hold one open position per symbol at a time; ignore duplicate signals while a position
  is open.
- Respect `TRADING_ENABLED` and `MAX_TRADES_PER_DAY` from the rules above.
- Unit tests in `tests/strategies/test_sma_crossover.py`: crossover triggers a buy, cross-back
  triggers a sell, no signal when flat, dry-run mode never calls `broker.submit`, daily trade cap
  is enforced. Use synthetic `Bar` sequences, no network/IB calls.
- Register it in `main.py` alongside (not replacing) `NoOpStrategy` isn't necessary — replace
  `NoOpStrategy` with `SmaCrossoverStrategy` in the registry, but leave `noop_strategy.py` in place
  as the documented template.

## Part B — Dashboard restyle + holdings panel

Restyle `src/dashboard/templates/index.html` to a black-and-gold theme: background near-black
(`#0a0a0a` / `#121212`), primary accent a warm gold/amber (`#F5C518` or similar — avoid a
yellow so saturated it looks like a warning color), keep green/red for P&L as-is for
legibility, neutral grays for secondary text. Keep it a single self-contained HTML file per the
existing pattern (inline `<style>`/`<script>`) — don't introduce a build step.

Add a **Holdings** panel: table of currently-held symbols (qty, avg cost, live price, unrealized
P&L $ and %), sourced from IB's `portfolio()`/`positions()` via `ib_insync` — add a small
`PortfolioService` or method on `IBBroker` that reads this, expose it as `GET /api/portfolio`, and
push updates over the existing `/ws` channel (new `type: "portfolio"` message, same pattern as
`bar`/`order`/`position`). Also show the `WATCHLIST_SYMBOLS` universe even for symbols with no
position yet (0 qty row or a separate "Watching" section) so it doubles as the symbol library the
UI is meant to complement.

Add a **prominent, unmissable mode badge** in the header: "DRY RUN" vs "LIVE PAPER TRADING",
driven by `TRADING_ENABLED`. This is a safety UX requirement, not decoration — Thomas should never
have to guess whether orders are real.

## Suggested agent split

Two work-streams are largely file-disjoint and can run as parallel subagents; the integration
point is not:

- **Agent 1 (strategy/backend):** `src/strategies/sma_crossover.py`, the `PositionLimitCheck`
  price-injection fix, `MAX_TRADES_PER_DAY` + `WATCHLIST_SYMBOLS` settings, and all new tests
  under `tests/strategies/` and `tests/risk/`.
- **Agent 2 (dashboard/frontend):** the `index.html` restyle, the holdings table markup/JS, the
  mode badge.
- **You (main thread), not a subagent:** wire everything together in `main.py` and
  `src/dashboard/app.py` (new `/api/portfolio` route, new `PortfolioService`, `IB_PORT` startup
  guard, registry swap) after both subagents finish. Both streams will want to touch `main.py`
  and `app.py` — doing that merge yourself avoids the two agents clobbering each other's edits.

## Verification workflow — do this live, don't just claim it works

1. `python -m uv sync --dev`
2. `docker compose up -d`, then poll until TimescaleDB is accepting connections (don't just sleep
   a fixed time — check with `pg_isready` or a retry loop).
3. Confirm `.env` has `IB_PORT=7497` (or 4002) and `TRADING_ENABLED` unset/false. Abort loudly if
   not.
4. Start the app in the background (`python -m uv run python main.py > /tmp/hedge.log 2>&1 &`),
   capture the PID, and poll port 8080 until it accepts connections instead of guessing a sleep.
5. Hit every endpoint for real and check status codes + JSON shape, not just "curl didn't error":
   - `GET /` — 200, HTML contains the new gold accent color and the mode badge markup.
   - `GET /api/snapshot` — 200, valid JSON.
   - `GET /api/portfolio` — 200, valid JSON (even if empty on a fresh paper account).
   - `POST /api/subscribe/MSFT` — 200, `{"status": "subscribed", ...}`.
6. Open the `/ws` WebSocket with a short Python script (`websockets` lib, add as a dev dep if
   needed), confirm the initial `snapshot` message parses and contains the expected keys, then
   disconnect cleanly.
7. `python -m uv run pytest -x -q`, `python -m uv run ruff check src/ main.py tests/`,
   `python -m uv run mypy src/ main.py` — all must be clean, including the new files.
8. Tail `/tmp/hedge.log` and grep for tracebacks/unhandled exceptions during the whole run above.
9. Send `SIGTERM` to the server PID, confirm the `shutdown_complete` log line appears (don't just
   kill -9 and assume it's fine).
10. Report a pass/fail table for steps 5-9, plus the diff summary and any deviations from this
    spec you had to make and why.

## Housekeeping

`_patch.py`, `_read.py`, `_w.py`, `_write_app.py` at the project root look like leftover scratch
scripts from prior ad-hoc edits — not part of the documented module map in `CLAUDE.md`. Grep for
any imports of them; if none, remove them so the repo root stays clean. Ask before deleting if
you're not sure they're dead.

## Explicitly out of scope for this pass

- Any strategy smarter than SMA crossover (mean reversion, momentum ranking, multi-factor, etc.)
- Any AI/ML/LLM-driven signal generation
- Live (non-paper) trading of any kind
- Position sizing beyond the existing USD/share caps

## Definition of done

- All existing + new tests pass; ruff and mypy strict are clean.
- Server boots via the exact commands in `CLAUDE.md`, and every endpoint above was verified live
  in this session, not asserted from reading the code.
- `TRADING_ENABLED=false` by default; flipping it is a deliberate, documented step, not the
  out-of-the-box behavior.
- Dashboard shows the black/gold theme, the holdings panel, and the dry-run/live badge.
- Commits are atomic and follow the existing `feat:`/`fix:`/`docs:` style.
