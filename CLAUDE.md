# Hedge Quant — Architecture Reference

## Project purpose

Multi-asset quantitative trading system connecting to Interactive Brokers via `ib_insync`.
Bars are persisted in TimescaleDB (PostgreSQL hypertable). Risk checks gate every order before submission.

## Package management

```bash
uv sync            # install all deps from lock file
uv sync --dev      # include dev extras (pytest, ruff, mypy)
uv add <pkg>       # add a new dependency
uv run python ...  # run inside the managed virtualenv
```

## Running locally

```bash
cp .env.example .env          # fill in credentials
docker compose up -d          # start TimescaleDB
uv run python main.py         # start the trading engine
```

## Module map

```
src/
├── broker/
│   ├── ib_broker.py      — IBBroker: async connect/disconnect/submit/cancel via ib_insync
│   └── order.py          — Order dataclass + OrderSide / OrderType / OrderStatus enums
├── data_ingestion/
│   ├── feed.py           — MarketDataFeed: subscribes to IB real-time bars, fires callbacks
│   └── store.py          — TimeseriesStore: async SQLAlchemy engine, creates bars hypertable
├── risk/
│   ├── checks.py         — RiskCheck Protocol + PositionLimitCheck + DrawdownCheck
│   └── engine.py         — RiskEngine: runs checks in sequence, gates orders
├── strategies/
│   ├── base.py           — BaseStrategy ABC: wraps submit() with risk approval
│   └── registry.py       — StrategyRegistry: register/unregister, dispatches Bar to all strategies
└── utils/
    ├── config.py          — Settings (pydantic-settings, reads .env), cached via lru_cache
    └── logging.py         — structlog setup (json or console renderer)
```

## Data flow

```
IB TWS / Gateway
    │
    ▼
MarketDataFeed.subscribe(symbol, callback)
    │  Bar(symbol, ts, ohlcv)
    ▼
StrategyRegistry.dispatch(bar)
    │  for each registered strategy
    ▼
BaseStrategy.on_bar(bar)
    │  emit Order
    ▼
RiskEngine.approve(order)     ← PositionLimitCheck, DrawdownCheck
    │  approved
    ▼
IBBroker.submit(order)
    │
    ▼
TimeseriesStore.insert_bar()  ← bars hypertable in TimescaleDB
```

## Key conventions

- **Async throughout**: all I/O methods are `async def`; use `asyncio.run()` or `await` at the top level.
- **Settings singleton**: always call `get_settings()` — it is `lru_cache`'d; never instantiate `Settings()` directly.
- **Structured logging**: use `get_logger(__name__)` and pass fields as kwargs, never f-strings.
- **Risk before submit**: `BaseStrategy.submit()` always calls `RiskEngine.approve()` first — never bypass it.
- **Order identity**: each `Order` gets a `uuid4` id at creation; use it for correlation in logs.

## Environment variables

See `.env.example` for the full list. Critical ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | asyncpg DSN for TimescaleDB |
| `IB_PORT` | 7497 paper / 7496 live TWS, 4002 Gateway paper |
| `MAX_POSITION_USD` | per-symbol USD exposure cap |
| `MAX_PORTFOLIO_DRAWDOWN_PCT` | portfolio-level drawdown kill-switch |

## Database

TimescaleDB runs in Docker. The `bars` hypertable is created automatically by `TimeseriesStore.connect()`.
Raw DDL is also in `db/init/01_bars.sql` for reference and external tooling.

## Adding a strategy

1. Create `src/strategies/my_strategy.py` subclassing `BaseStrategy`.
2. Implement `id` property and `on_bar(bar)`.
3. Register with `registry.register(MyStrategy(broker, risk))`.

## Testing

```bash
uv run pytest            # run all tests
uv run pytest -x -q      # fail fast, quiet
uv run mypy src/         # type check
uv run ruff check src/   # lint
```

Tests live in `tests/`. Mirror the `src/` layout: `tests/broker/`, `tests/risk/`, etc.
Use `pytest-asyncio` (configured for `asyncio_mode = "auto"`).
