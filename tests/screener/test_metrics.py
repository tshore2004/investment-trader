from __future__ import annotations

import pandas as pd

from src.screener.metrics import compute_metrics


def _flat_series(n: int, close: float = 100.0, volume: float = 1_000_000) -> pd.DataFrame:
    return pd.DataFrame({"close": [close] * n, "volume": [volume] * n})


def _uptrend_series(n: int, start: float = 100.0, daily_return: float = 0.003) -> pd.DataFrame:
    closes = [start * (1 + daily_return) ** i for i in range(n)]
    return pd.DataFrame({"close": closes, "volume": [1_000_000] * n})


def test_flat_series_has_zero_momentum_and_neutral_rsi() -> None:
    bars = {"FLAT": _flat_series(300)}
    spy = _flat_series(300)

    metrics = compute_metrics(bars, spy)

    assert metrics.loc["FLAT", "momentum_1m"] == 0.0
    assert metrics.loc["FLAT", "momentum_12m"] == 0.0
    assert metrics.loc["FLAT", "rsi14"] == 100.0  # matches src/ml/features.py's _rsi convention


def test_uptrend_beats_flat_benchmark_on_momentum_and_relative_strength() -> None:
    bars = {"UP": _uptrend_series(300)}
    spy = _flat_series(300)

    metrics = compute_metrics(bars, spy)

    assert metrics.loc["UP", "momentum_12m"] > 0
    assert metrics.loc["UP", "rel_strength_12m"] > 0
    assert metrics.loc["UP", "trend_quality"] > 0.9


def test_volume_spike_raises_relative_volume() -> None:
    df = _flat_series(300)
    df.loc[df.index[-1], "volume"] = 10_000_000  # 10x the trailing 20-day average
    bars = {"SPIKE": df}
    spy = _flat_series(300)

    metrics = compute_metrics(bars, spy)

    assert metrics.loc["SPIKE", "rel_volume"] > 5.0


def test_symbol_with_insufficient_history_is_dropped() -> None:
    bars = {"NEWCO": _flat_series(10), "OLD": _flat_series(300)}
    spy = _flat_series(300)

    metrics = compute_metrics(bars, spy)

    assert "NEWCO" not in metrics.index
    assert "OLD" in metrics.index
