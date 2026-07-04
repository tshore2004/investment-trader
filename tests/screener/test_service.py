from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.screener import service as service_module
from src.screener.service import run_screen


def _fake_load_universe(name: str) -> list[str]:
    return ["AAPL", "MSFT"]


def _fake_fetch_universe_bars(
    universe_name: str, symbols: list[str], cache_dir: Any = None
) -> dict[str, pd.DataFrame]:
    n = 300
    closes = [100.0 + i * 0.1 for i in range(n)]
    df = pd.DataFrame({"close": closes, "volume": [1_000_000] * n})
    return {sym: df for sym in [*symbols, "SPY"]}


def test_run_screen_reports_all_four_stages_in_order(monkeypatch: Any) -> None:
    monkeypatch.setattr(service_module, "load_universe", _fake_load_universe)
    monkeypatch.setattr(service_module, "fetch_universe_bars", _fake_fetch_universe_bars)

    stages: list[str] = []
    result = run_screen("sp500", on_progress=lambda p: stages.append(p.stage))

    assert stages == ["universe_loaded", "data_fetched", "metrics_computed", "done"]
    assert isinstance(result, pd.DataFrame)
    assert "score" in result.columns
    assert set(result.index) == {"AAPL", "MSFT"}


def test_run_screen_works_without_progress_callback(monkeypatch: Any) -> None:
    monkeypatch.setattr(service_module, "load_universe", _fake_load_universe)
    monkeypatch.setattr(service_module, "fetch_universe_bars", _fake_fetch_universe_bars)

    result = run_screen("sp500")

    assert not result.empty


def test_run_screen_accepts_custom_weights(monkeypatch: Any) -> None:
    monkeypatch.setattr(service_module, "load_universe", _fake_load_universe)
    monkeypatch.setattr(service_module, "fetch_universe_bars", _fake_fetch_universe_bars)
    custom = {
        "momentum": 1.0,
        "rel_strength": 0.0,
        "rsi": 0.0,
        "rel_volume": 0.0,
        "volatility": 0.0,
    }

    result = run_screen("sp500", weights=custom)

    assert "score" in result.columns


def test_run_screen_raises_clear_error_when_spy_benchmark_missing(monkeypatch: Any) -> None:
    monkeypatch.setattr(service_module, "load_universe", _fake_load_universe)

    def _fetch_without_spy(
        universe_name: str, symbols: list[str], cache_dir: Any = None
    ) -> dict[str, pd.DataFrame]:
        n = 300
        df = pd.DataFrame({"close": [100.0] * n, "volume": [1_000_000] * n})
        return {sym: df for sym in symbols}  # no SPY

    monkeypatch.setattr(service_module, "fetch_universe_bars", _fetch_without_spy)

    with pytest.raises(RuntimeError, match="SPY benchmark data unavailable"):
        run_screen("sp500")


def test_run_screen_raises_clear_error_when_no_symbols_have_sufficient_history(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(service_module, "load_universe", _fake_load_universe)

    def _fetch_only_spy(
        universe_name: str, symbols: list[str], cache_dir: Any = None
    ) -> dict[str, pd.DataFrame]:
        n = 300
        closes = [100.0 + i * 0.1 for i in range(n)]
        df = pd.DataFrame({"close": closes, "volume": [1_000_000] * n})
        return {"SPY": df}

    monkeypatch.setattr(service_module, "fetch_universe_bars", _fetch_only_spy)

    with pytest.raises(RuntimeError, match="no symbols had sufficient history"):
        run_screen("sp500")
