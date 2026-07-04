from __future__ import annotations

import datetime as _dt
import pathlib as _pl

import pandas as pd
import yfinance as yf

_DEFAULT_CACHE_DIR = _pl.Path(".cache/screener")
_CHUNK_SIZE = 100
_PERIOD = "14mo"
_BENCHMARK = "SPY"


def fetch_universe_bars(
    universe_name: str, symbols: list[str], cache_dir: _pl.Path | None = None
) -> dict[str, pd.DataFrame]:
    cache_dir = cache_dir if cache_dir is not None else _DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.datetime.now(_dt.UTC).date().isoformat()
    cache_path = cache_dir / f"{universe_name}_{today}.parquet"

    if cache_path.exists():
        combined = pd.read_parquet(cache_path)
    else:
        all_symbols = sorted(set(symbols) | {_BENCHMARK})
        combined = _download_chunked(all_symbols)
        combined.to_parquet(cache_path)

    return _split_by_symbol(combined, sorted(set(symbols) | {_BENCHMARK}))


def _download_chunked(symbols: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for i in range(0, len(symbols), _CHUNK_SIZE):
        chunk = symbols[i : i + _CHUNK_SIZE]
        raw = yf.download(
            " ".join(chunk), period=_PERIOD, interval="1d", group_by="ticker",
            auto_adjust=True, progress=False, threads=True,
        )
        frames.append(_normalize_columns(raw, chunk))
    return pd.concat(frames, axis=1)


def _normalize_columns(raw: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    # yfinance returns a single-level column index (OHLCV) when only one ticker was requested,
    # and a MultiIndex (ticker, field) for multi-ticker downloads — normalize both to MultiIndex.
    if len(symbols) == 1 and not isinstance(raw.columns, pd.MultiIndex):
        raw = pd.concat({symbols[0]: raw}, axis=1)
    return raw


def _split_by_symbol(combined: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        if sym not in combined.columns.get_level_values(0):
            continue
        df = combined[sym][["Open", "High", "Low", "Close", "Volume"]].dropna()
        df.columns = ["open", "high", "low", "close", "volume"]
        result[sym] = df.sort_index()
    return result
