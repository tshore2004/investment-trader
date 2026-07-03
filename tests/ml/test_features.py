from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from src.ml.features import FEATURE_COLUMNS, build_windows, compute_indicators


def _make_bars(n: int, close: float = 100.0) -> list[dict[str, Any]]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {
            "symbol": "TEST",
            "timestamp": base + timedelta(minutes=i),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000 + i,
        }
        for i in range(n)
    ]


def test_compute_indicators_constant_series() -> None:
    bars = _make_bars(20, close=100.0)
    df = compute_indicators(bars)

    assert df["sma10"].iloc[-1] == 100.0
    assert df["ema10"].iloc[-1] == 100.0
    assert df["rsi14"].iloc[-1] == 100.0
    assert df["vwap"].iloc[-1] == 100.0


def test_compute_indicators_warmup_rows_are_nan() -> None:
    bars = _make_bars(20, close=100.0)
    df = compute_indicators(bars)

    assert df["sma10"].iloc[0:9].isna().all()
    assert df["rsi14"].iloc[0:14].isna().all()


def test_build_windows_shapes_and_no_nan() -> None:
    bars = _make_bars(60)
    for i, bar in enumerate(bars):
        bar["close"] = 100.0 + (i % 5) * 0.1
    df = compute_indicators(bars)

    X, y, timestamps = build_windows(df, window=10)

    assert X.shape[1] == 10 * len(FEATURE_COLUMNS)
    assert X.shape[0] == y.shape[0] == len(timestamps)
    assert X.shape[0] > 0
    assert not np.isnan(X).any()
    assert not np.isnan(y).any()


def test_build_windows_target_matches_next_return() -> None:
    bars = _make_bars(40)
    bars[30]["close"] = 101.0  # isolated jump: bar 30 vs bar 29 (both 100.0 before this line)
    df = compute_indicators(bars)

    X, y, timestamps = build_windows(df, window=10)

    idx = timestamps.index(bars[30]["timestamp"])
    expected_return = (101.0 - 100.0) / 100.0
    assert abs(y[idx] - expected_return) < 1e-6
