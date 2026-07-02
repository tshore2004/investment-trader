# TODO

Backlog of future work. Not scheduled — pull items into an implementation pass when ready.

## Auto-populate watchlist from signals

Currently `WATCHLIST_SYMBOLS` is a static, manually-configured comma-separated env var
(`src/utils/config.py`) — the strategy only ever sees symbols a human typed in ahead of time
(or added live via the dashboard's Subscribe box).

Idea: let the system grow its own watchlist by scanning a broader symbol universe for
candidate signals (e.g. symbols approaching an SMA crossover, unusual volume, etc.) and
auto-subscribing them via the existing `MarketDataFeed.subscribe()` / `POST /api/subscribe`
path, instead of requiring a human to add every symbol by hand.

Open questions to resolve before implementing:
- Where does the scan universe come from (a fixed list of liquid names? an index constituent
  list? user-configurable)?
- Scan cadence — does this run on its own poll loop, separate from the 60s yfinance bar poll?
- Cap on auto-added symbols (a runaway scanner could subscribe to hundreds of tickers and
  hammer yfinance / balloon the dashboard).
- Should auto-added symbols be visually distinguished in the dashboard from manually-added
  ones (e.g. a "auto" badge in the Holdings/Watching panel)?
- Interaction with `MAX_TRADES_PER_DAY` and position limits — more symbols in play means more
  simultaneous risk exposure to reason about.
