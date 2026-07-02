# Hedge Quant — Architecture Reference

## Project purpose

Multi-asset quantitative trading system connecting to Interactive Brokers via `ib_insync`.
Bars are persisted in TimescaleDB (PostgreSQL hypertable). Risk checks gate every order before
submission. A local FastAPI dashboard streams live OHLCV bars via WebSocket.

## Package management

```bash
python -m uv sync            # install all deps from lock file
python -m uv sync --dev      # include dev extras (pytest, ruff, mypy)
python -m uv add <pkg>       # add a new dependency
python -m uv run python ...  # run inside the managed virtualenv
```

> **Note:** `uv` must be invoked as `python -m uv` on this machine — the `uv` binary is not
> on the system PATH. The venv is at `.venv/`.

## Running locally

```bash
cp .env.example .env          # fill in credentials
docker compose up -d          # start TimescaleDB
python -m uv run python main.py   # start engine + dashboard
# Dashboard: http://localhost:8080
```

## Python 3.14 compatibility note

`eventkit` (a transitive dependency of `ib_insync`) calls `asyncio.get_event_loop()` at import
time. Python 3.14 no longer auto-creates a loop, so `main.py` calls
`asyncio.set_event_loop(asyncio.new_event_loop())` **before** importing `ib_insync`.
Any new entry-point scripts must do the same.

## ib_insync v0.9.86 note

This version has no `runAsync()`. After `await ib.connectAsync(...)`, ib_insync drives itself
via internal asyncio tasks — no explicit run call is needed. `MarketDataFeed.run()` waits on
`ib.disconnectedEvent` to keep the gather alive until the connection drops.

## Module map

```
src/
├── broker/
│   ├── ib_broker.py      — IBBroker: accepts optional shared ibi.IB(); connect/submit/cancel/
│   │                        portfolio_snapshot() (reads ib_insync's portfolio() for the dashboard)
│   └── order.py          — Order dataclass + OrderSide / OrderType / OrderStatus enums
├── dashboard/
│   ├── app.py            — FastAPI app: /ws WebSocket broadcast, /api/snapshot,
│   │                        /api/portfolio/history, DashboardState
│   ├── templates/
│   │   └── index.html    — Dashboard shell: header + empty <div class="grid-stack">;
│   │                        widgets are created dynamically by layout.js/widgets.js
│   └── static/js/        — ES modules (no bundler, served via FastAPI StaticFiles):
│       ├── widgets.js     — Widget registry: WIDGET_TYPES catalog, createWidget/destroyWidget,
│       │                    dispatchBar/dispatchPortfolioValue/dispatchOrder/dispatchHoldings/
│       │                    dispatchPosition fan-out to instances
│       ├── chart.js       — createChartWidget(container, config, hooks): per-instance
│       │                    lightweight-charts chart; SMA/EMA/VWAP/RSI indicators; a config.symbol
│       │                    of PORTFOLIO_SYMBOL switches to a portfolio-value line chart
│       ├── orders.js      — createOrdersWidget: per-instance trade history table
│       ├── holdings.js    — createHoldingsWidget: portfolio-wide holdings table
│       ├── compare.js     — createCompareWidget: correlation/volatility table + sparklines
│       ├── state.js       — shared `state` (bars/positions/portfolio/watchlist/tradingEnabled),
│       │                    PORTFOLIO_SYMBOL sentinel ('__PORTFOLIO__'), resampleBars
│       ├── ws.js           — WebSocket connect/reconnect; dispatches each message type to widgets.js
│       ├── layout.js       — GridStack wiring, "+ Add View" menu, full-workspace localStorage
│       │                    persistence (key `hedge-dashboard-layout`), Trading/Compare/Monitor
│       │                    starting templates
│       └── main.js         — entry point: header symbol search, initLayout(), connect()
├── data_ingestion/
│   ├── feed.py           — MarketDataFeed: yfinance polling (1-min bars), fires BarCallback list
│   └── store.py          — TimeseriesStore: bars + portfolio_value hypertables;
│                            insert_portfolio_snapshot()/get_portfolio_history()
├── risk/
│   ├── checks.py         — RiskCheck Protocol + PositionLimitCheck (USD, price-aware for market
│   │                        orders via injected last_prices) + DrawdownCheck
│   └── engine.py         — RiskEngine: DrawdownCheck first, then PositionLimitCheck
├── strategies/
│   ├── base.py            — BaseStrategy ABC: submit() always calls RiskEngine.approve() first
│   ├── noop_strategy.py   — NoOpStrategy: logs every bar, places no orders (documented template)
│   ├── sma_crossover.py   — SmaCrossoverStrategy: fast/slow SMA crossover, one position per
│   │                        symbol, respects TRADING_ENABLED (dry-run logs) and MAX_TRADES_PER_DAY
│   └── registry.py        — StrategyRegistry: register/unregister, dispatches Bar to all
└── utils/
    ├── config.py          — Settings (pydantic-settings, extra="ignore"), cached via lru_cache
    └── logging.py         — structlog setup (json or console renderer)
main.py                    — Entry point: shared IB instance, wires all components, runs gather,
                              _portfolio_poll_loop (10s: snapshot → store → WS broadcast)
```

## Data flow

```
yfinance (free, 15-20 min delayed)
    │
    ▼
MarketDataFeed.subscribe(symbol)        ← polls yfinance every 60s, emits completed 1-min bars
    │  Bar(symbol, ts, ohlcv)           deduplicates by timestamp
    ▼
feed callbacks (registered via on_bar):
    ├── TimeseriesStore.insert_bar()    → bars hypertable in TimescaleDB
    ├── StrategyRegistry.dispatch(bar)
    │       │  for each registered strategy
    │       ▼
    │   BaseStrategy.on_bar(bar)
    │       │  emit Order
    │       ▼
    │   RiskEngine.approve(order)       ← DrawdownCheck, PositionLimitCheck
    │       │  approved
    │       ▼
    │   IBBroker.submit(order)
    └── DashboardState.add_bar()        → WebSocket broadcast to browser clients
```

## Shared IB instance

`main.py` creates **one** `ibi.IB()` and passes it to both `IBBroker` and `MarketDataFeed`:

```python
shared_ib = ibi.IB()
await shared_ib.connectAsync(host=..., port=..., clientId=...)
feed   = MarketDataFeed(ib=shared_ib)
broker = IBBroker(ib=shared_ib)
```

When an `ib` instance is injected, `connect()` and `disconnect()` on each class are no-ops —
the caller owns the lifecycle.

## Key conventions

- **Async throughout**: all I/O methods are `async def`; use `asyncio.run()` or `await`.
- **Settings singleton**: always call `get_settings()` — it is `lru_cache`'d; never instantiate
  `Settings()` directly.
- **Structured logging**: use `get_logger(__name__)` and pass fields as kwargs, never f-strings.
- **Risk before submit**: `BaseStrategy.submit()` always calls `RiskEngine.approve()` first —
  never bypass it. DrawdownCheck runs before PositionLimitCheck (kill-switch semantics).
- **Order identity**: each `Order` gets a `uuid4` id at creation; use it for correlation in logs.
- **BarCallback**: `Callable[[Bar], Awaitable[None] | None]` — callbacks may be sync or async;
  the feed wraps coroutines in `asyncio.ensure_future`.

## Environment variables

See `.env.example` for the full list. Critical ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | asyncpg DSN for TimescaleDB |
| `IB_PORT` | 7497 paper / 7496 live TWS, 4002 Gateway paper |
| `MAX_POSITION_USD` | per-symbol USD exposure cap (checked against qty × limit_price) |
| `MAX_PORTFOLIO_DRAWDOWN_PCT` | portfolio-level drawdown kill-switch |
| `MAX_ORDER_SIZE` | share-count fallback cap for market orders (no limit_price available) |

## Risk checks

`PositionLimitCheck` computes **USD exposure** = `order.quantity × price` and compares it
against `MAX_POSITION_USD`. For limit orders, `price` is `order.limit_price`; for market orders
(no `limit_price`), it uses the last-traded price injected via the `last_prices` dict (populated
from the most recent `Bar` seen for that symbol) so USD exposure is still computed correctly.
Only if truly no price is available yet does it fall back to comparing raw share count against
`MAX_ORDER_SIZE`.

`DrawdownCheck` uses `portfolio` values set by `RiskEngine.update_position(symbol, usd_value)`.
An empty portfolio always passes (no recorded drawdown).

## Database

TimescaleDB runs in Docker. `TimeseriesStore.connect()`:
1. Runs `CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE` (idempotent)
2. Creates the `bars` table if absent
3. Promotes it to a hypertable (idempotent via `if_not_exists => TRUE`)

Each step is a **separate** `conn.execute()` call — asyncpg does not support multi-statement
strings. Raw DDL is also in `db/init/01_bars.sql` for fresh container initialisation.

## Dashboard

FastAPI app runs in the **same asyncio event loop** as the trading engine via `asyncio.gather`.
The UI is a customizable GridStack workspace, not a fixed layout: the "+ Add View" menu spawns
any number of Chart / Metrics / Trade History / Holdings / Compare widgets, each independently
configured (symbol, timeframe, indicators) and independently draggable/resizable. The full
workspace (widget types, configs, grid positions) persists to `localStorage`
(`hedge-dashboard-layout`); corrupt or missing state falls back to a "Trading" starting template.
A reserved sentinel symbol `PORTFOLIO_SYMBOL` (`'__PORTFOLIO__'`, exported from `state.js`) lets a
Chart widget render total portfolio value as a line instead of OHLC candles.

- `GET /` — dashboard shell (see `templates/index.html` in the module map)
- `GET /api/snapshot` — full JSON snapshot of current state
- `GET /api/portfolio/history` — chronological `portfolio_value` rows for the portfolio chart mode
- `WS /ws` — streams `bar`, `order`, `position`, `portfolio`, `portfolio_value`, and `snapshot`
  messages; `src/dashboard/static/js/ws.js` fans each type out to every relevant widget instance
  via `widgets.js`'s `dispatch*` functions (not global `window.__*` callbacks)

`DashboardState` is a module-level singleton (`get_state()`). Feed callbacks call
`await get_state().add_bar(bar)` which broadcasts to all connected WebSocket clients;
`main.py`'s `_portfolio_poll_loop` (10s) does the same for `portfolio`/`portfolio_value`, also
persisting each portfolio snapshot via `TimeseriesStore.insert_portfolio_snapshot()`.

## Adding a strategy

1. Create `src/strategies/my_strategy.py` subclassing `BaseStrategy`.
2. Implement `id` property and `async on_bar(bar)`.
3. In `main.py`, instantiate and pass to `registry.register(MyStrategy(broker, risk))`.

See `src/strategies/noop_strategy.py` for the minimal template, or
`src/strategies/sma_crossover.py` for the current live (dry-run by default) strategy.

## Market data source

**Paper trading / development:** `MarketDataFeed` uses **yfinance** (free, no IB subscription
required). Bars are 15-20 min delayed and polled every 60 seconds. No TWS market data
configuration needed — any stock symbol works immediately.

**Live trading:** Replace the yfinance polling in `feed.py` with IB's
`reqHistoricalData(keepUpToDate=True)` once a paid market data subscription is active.
IB's API requires a subscription even for delayed data (Error 10089 otherwise).

## Testing

```bash
python -m uv run pytest              # run all tests (47 tests)
python -m uv run pytest -x -q        # fail fast, quiet
python -m uv run mypy src/ main.py   # type check (strict)
python -m uv run ruff check src/ main.py tests/   # lint
```

Tests live in `tests/`, mirroring `src/` layout. Uses `pytest-asyncio` (`asyncio_mode = "auto"`).
No JS test harness exists for `src/dashboard/static/js/`; validate with
`node --input-type=module --check < file.js` and a manual browser pass — there is no automated
frontend suite to run instead.