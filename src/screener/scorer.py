from __future__ import annotations

import pandas as pd

DEFAULT_WEIGHTS: dict[str, float] = {
    "momentum": 0.30,
    "rel_strength": 0.30,
    "rsi": 0.15,
    "rel_volume": 0.10,
    "volatility": 0.15,
}

# Multi-window factors are averaged across their _1m.._12m columns before percentile-ranking.
# volatility is inverted (lower realized vol ranks higher) — it's a risk penalty, not a reward.
_MULTI_WINDOW_FACTORS = {
    "momentum": ["momentum_1m", "momentum_3m", "momentum_6m", "momentum_12m"],
    "rel_strength": ["rel_strength_1m", "rel_strength_3m", "rel_strength_6m", "rel_strength_12m"],
}
_SINGLE_COLUMN_FACTORS = {"rsi": "rsi14", "rel_volume": "rel_volume"}
_INVERTED_FACTORS = {"volatility": "volatility"}


def score(metrics_df: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Percentile-rank each factor and combine into a weighted composite score (0-100).

    weights, if given, must specify all five factor keys (momentum, rel_strength, rsi,
    rel_volume, volatility) — it replaces DEFAULT_WEIGHTS entirely rather than merging into it.
    A weights dict that omits one of the five keys will silently exclude that factor from the
    weighted sum rather than raising or falling back to its default weight.
    """
    weights = weights if weights is not None else DEFAULT_WEIGHTS
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1.0, got {total}")

    percentiles = pd.DataFrame(index=metrics_df.index)
    for factor, cols in _MULTI_WINDOW_FACTORS.items():
        raw = metrics_df[cols].mean(axis=1)
        percentiles[factor] = raw.rank(pct=True) * 100

    for factor, col in _SINGLE_COLUMN_FACTORS.items():
        percentiles[factor] = metrics_df[col].rank(pct=True) * 100

    for factor, col in _INVERTED_FACTORS.items():
        percentiles[factor] = (1 - metrics_df[col].rank(pct=True)) * 100

    composite = sum(percentiles[factor] * weight for factor, weight in weights.items())

    result = metrics_df.copy()
    result["score"] = composite
    return result.sort_values("score", ascending=False)
