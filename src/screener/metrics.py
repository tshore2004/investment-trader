from __future__ import annotations

import numpy as np
import pandas as pd

# Trading-day approximations for the four momentum/relative-strength windows.
_WINDOWS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
# Minimum trailing history required for a symbol to be scored (12-month window + warm-up).
_MIN_HISTORY = 260


def compute_metrics(bars_by_symbol: dict[str, pd.DataFrame], spy_df: pd.DataFrame) -> pd.DataFrame:
    rows: dict[str, dict[str, float]] = {}
    for symbol, df in bars_by_symbol.items():
        if len(df) < _MIN_HISTORY:
            continue
        rows[symbol] = _metrics_for_symbol(df, spy_df)

    return pd.DataFrame.from_dict(rows, orient="index")


def _metrics_for_symbol(df: pd.DataFrame, spy_df: pd.DataFrame) -> dict[str, float]:
    close = df["close"]
    row: dict[str, float] = {}

    for label, window in _WINDOWS.items():
        sym_return = _trailing_return(close, window)
        spy_return = _trailing_return(spy_df["close"], window)
        row[f"momentum_{label}"] = sym_return
        row[f"rel_strength_{label}"] = sym_return - spy_return

    row["rsi14"] = float(_rsi(close, period=14).iloc[-1])
    row["rel_volume"] = _relative_volume(df["volume"])
    row["volatility"] = _realized_volatility(close)
    row["trend_quality"] = _trend_quality(close)
    return row


def _trailing_return(close: pd.Series, window: int) -> float:
    if len(close) <= window:
        return 0.0
    start, end = close.iloc[-window - 1], close.iloc[-1]
    if start == 0:
        return 0.0
    return float((end - start) / start)


# Same rolling-gain/loss formula as src/ml/features.py's _rsi — duplicated rather than shared
# (see plan's Global Constraints for why).
def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.where(avg_loss != 0, 100.0)


def _relative_volume(volume: pd.Series) -> float:
    avg20 = volume.rolling(window=20).mean().iloc[-1]
    if avg20 == 0 or np.isnan(avg20):
        return 1.0
    return float(volume.iloc[-1] / avg20)


def _realized_volatility(close: pd.Series) -> float:
    daily_returns = close.pct_change().dropna().iloc[-20:]
    return float(daily_returns.std() * np.sqrt(252))


def _trend_quality(close: pd.Series) -> float:
    sma50 = close.rolling(window=50).mean()
    tail_close = close.iloc[-50:]
    tail_sma = sma50.iloc[-50:]
    return float((tail_close > tail_sma).mean())
