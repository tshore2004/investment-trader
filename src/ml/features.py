from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

FEATURE_COLUMNS = ["open", "high", "low", "close", "volume", "sma10", "ema10", "rsi14", "vwap"]


def compute_indicators(bars: list[dict[str, Any]]) -> pd.DataFrame:
    """Turn raw bar dicts (as returned by TimeseriesStore.get_bars) into a DataFrame with
    SMA(10)/EMA(10)/RSI(14)/VWAP columns appended. The first ~14 rows have NaN indicators
    (warm-up period) — callers must drop or mask those before training."""
    df = pd.DataFrame(bars).sort_values("timestamp").reset_index(drop=True)
    df["sma10"] = df["close"].rolling(window=10).mean()
    df["ema10"] = df["close"].ewm(span=10, adjust=False).mean()
    df["rsi14"] = _rsi(df["close"], period=14)
    df["vwap"] = _vwap(df)
    return df


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.where(avg_loss != 0, 100.0)


def _vwap(df: pd.DataFrame) -> pd.Series:
    date = pd.to_datetime(df["timestamp"]).dt.date
    pv = df["close"] * df["volume"]
    cum_pv = pv.groupby(date).cumsum()
    cum_vol = df["volume"].groupby(date).cumsum()
    return cum_pv / cum_vol.replace(0, np.nan)


def build_windows(
    df: pd.DataFrame, window: int = 30
) -> tuple[np.ndarray, np.ndarray, list[Any]]:
    """For each bar i (i >= window), build a sample from the window of bars [i-window, i)
    (NOT including bar i itself, to avoid leaking bar i's own OHLCV into its own prediction)
    and a target equal to bar i's percent return vs bar i-1. Rows touching any NaN indicator
    (warm-up period) are dropped."""
    feat = df[FEATURE_COLUMNS].to_numpy(dtype=float)
    target = df["close"].pct_change().to_numpy(dtype=float)
    timestamps = df["timestamp"].tolist()
    feat_valid = ~np.isnan(feat).any(axis=1)

    X_list: list[np.ndarray] = []
    y_list: list[float] = []
    ts_list: list[Any] = []
    for i in range(window, len(df)):
        if np.isnan(target[i]) or not feat_valid[i - window:i].all():
            continue
        X_list.append(feat[i - window : i].flatten())
        y_list.append(target[i])
        ts_list.append(timestamps[i])

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)
    return X, y, ts_list
