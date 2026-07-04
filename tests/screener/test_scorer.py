from __future__ import annotations

import pandas as pd
import pytest

from src.screener.scorer import DEFAULT_WEIGHTS, score


def _sample_metrics() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "momentum_1m": [0.01, 0.05, -0.02],
            "momentum_3m": [0.02, 0.10, -0.03],
            "momentum_6m": [0.05, 0.20, -0.05],
            "momentum_12m": [0.10, 0.40, -0.10],
            "rel_strength_1m": [0.0, 0.03, -0.01],
            "rel_strength_3m": [0.0, 0.06, -0.02],
            "rel_strength_6m": [0.0, 0.12, -0.03],
            "rel_strength_12m": [0.0, 0.25, -0.05],
            "rsi14": [50.0, 70.0, 30.0],
            "rel_volume": [1.0, 2.0, 0.5],
            "volatility": [0.2, 0.3, 0.15],
        },
        index=["FLAT", "WINNER", "LOSER"],
    )


def test_default_weights_sum_to_one() -> None:
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_score_ranks_strong_momentum_symbol_first() -> None:
    result = score(_sample_metrics())

    assert result.index[0] == "WINNER"
    assert result["score"].is_monotonic_decreasing


def test_score_rejects_weights_not_summing_to_one() -> None:
    bad_weights = {**DEFAULT_WEIGHTS, "momentum": DEFAULT_WEIGHTS["momentum"] + 0.5}
    with pytest.raises(ValueError, match="must sum to 1.0"):
        score(_sample_metrics(), weights=bad_weights)


def test_low_weight_factor_does_not_dominate_ranking() -> None:
    # LOSER has the lowest volatility (best by our "lower is better" convention) but should not
    # overtake WINNER when volatility's weight is small relative to momentum/rel_strength.
    result = score(_sample_metrics())
    assert result.index[0] == "WINNER"
    assert result.loc["LOSER", "score"] < result.loc["WINNER", "score"]
