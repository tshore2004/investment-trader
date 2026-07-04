from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from src.screener.data import fetch_universe_bars
from src.screener.metrics import compute_metrics
from src.screener.scorer import score
from src.screener.universe import load_universe

ProgressCallback = Callable[["ScreenProgress"], None]


@dataclass
class ScreenProgress:
    stage: str
    detail: str = ""


def run_screen(
    universe: str,
    weights: dict[str, float] | None = None,
    on_progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    def _report(stage: str, detail: str = "") -> None:
        if on_progress is not None:
            on_progress(ScreenProgress(stage=stage, detail=detail))

    symbols = load_universe(universe)
    _report("universe_loaded", f"{len(symbols)} symbols")

    bars_by_symbol = fetch_universe_bars(universe, symbols)
    _report("data_fetched", f"{len(bars_by_symbol)} symbols with data")

    if "SPY" not in bars_by_symbol:
        raise RuntimeError("SPY benchmark data unavailable — cannot compute relative strength")
    spy_df = bars_by_symbol["SPY"]
    scannable = {sym: df for sym, df in bars_by_symbol.items() if sym != "SPY"}
    metrics_df = compute_metrics(scannable, spy_df)
    _report("metrics_computed", f"{len(metrics_df)} symbols scored")

    result = score(metrics_df, weights=weights)
    _report("done")
    return result
