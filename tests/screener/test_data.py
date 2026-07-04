from __future__ import annotations

from typing import Any

import pandas as pd

from src.screener import data as data_module
from src.screener.data import fetch_universe_bars


def _fake_download(tickers: str, **kwargs: Any) -> pd.DataFrame:
    symbols = tickers.split()
    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    columns = pd.MultiIndex.from_product([symbols, ["Open", "High", "Low", "Close", "Volume"]])
    data = {}
    fields = [("Open", 10.0), ("High", 11.0), ("Low", 9.0), ("Close", 10.5), ("Volume", 100.0)]
    for sym in symbols:
        for field, val in fields:
            data[(sym, field)] = [val] * len(idx)
    return pd.DataFrame(data, index=idx, columns=columns)


def test_fetch_universe_bars_includes_spy_and_requested_symbols(
    monkeypatch: Any, tmp_path: Any
) -> None:
    monkeypatch.setattr(data_module.yf, "download", _fake_download)

    result = fetch_universe_bars("sp500", ["AAPL", "MSFT"], cache_dir=tmp_path)

    assert set(result) == {"AAPL", "MSFT", "SPY"}
    assert list(result["AAPL"].columns) == ["open", "high", "low", "close", "volume"]
    assert result["AAPL"]["close"].iloc[0] == 10.5


def test_fetch_universe_bars_writes_and_reuses_cache(monkeypatch: Any, tmp_path: Any) -> None:
    calls = {"count": 0}

    def _counting_download(tickers: str, **kwargs: Any) -> pd.DataFrame:
        calls["count"] += 1
        return _fake_download(tickers, **kwargs)

    monkeypatch.setattr(data_module.yf, "download", _counting_download)

    fetch_universe_bars("sp500", ["AAPL"], cache_dir=tmp_path)
    first_call_count = calls["count"]
    fetch_universe_bars("sp500", ["AAPL"], cache_dir=tmp_path)

    assert calls["count"] == first_call_count  # second call hit the cache, no new network calls
    cached_files = list(tmp_path.glob("sp500_*.parquet"))
    assert len(cached_files) == 1
