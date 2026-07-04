from __future__ import annotations

import pathlib as _pl

_DATA_DIR = _pl.Path(__file__).parent / "data"

# "broad" is a curated supplement (src/screener/data/broad_market.txt) unioned with the S&P 500
# list, not an exhaustive NYSE/NASDAQ listing. Both files are point-in-time snapshots; refreshing
# them is a manual, infrequent maintenance task, not a runtime concern.
_UNIVERSE_FILES = {
    "sp500": ["sp500.txt"],
    "broad": ["sp500.txt", "broad_market.txt"],
}


def load_universe(name: str) -> list[str]:
    if name not in _UNIVERSE_FILES:
        raise ValueError(f"unknown universe {name!r}; expected one of {sorted(_UNIVERSE_FILES)}")

    tickers: set[str] = set()
    for filename in _UNIVERSE_FILES[name]:
        text = (_DATA_DIR / filename).read_text(encoding="utf-8")
        for line in text.splitlines():
            ticker = line.strip().upper()
            if ticker:
                tickers.add(ticker)
    return sorted(tickers)
