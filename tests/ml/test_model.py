from __future__ import annotations

import torch

from src.ml.model import PricePredictorMLP


def test_price_predictor_mlp_forward_shape() -> None:
    model = PricePredictorMLP(input_size=12, hidden_size=8)
    x = torch.randn(5, 12)

    out = model(x)

    assert out.shape == (5, 1)


def test_price_predictor_mlp_default_hidden_size() -> None:
    model = PricePredictorMLP(input_size=270)
    x = torch.randn(2, 270)

    out = model(x)

    assert out.shape == (2, 1)
