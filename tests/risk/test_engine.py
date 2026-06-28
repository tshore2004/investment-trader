from __future__ import annotations

import pytest

from src.broker.order import Order, OrderSide, OrderType
from src.risk.engine import RiskEngine


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    from src.utils.config import get_settings
    get_settings.cache_clear()


class TestRiskEngine:
    def test_approve_small_limit_order(self) -> None:
        engine = RiskEngine(peak_nav=100_000.0)
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=5,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        passed, reason = engine.approve(order)
        assert passed
        assert reason == ""

    def test_reject_oversized_limit_order(self) -> None:
        engine = RiskEngine(peak_nav=100_000.0)
        # 1000 * 200 = 200_000 > max_position_usd 50_000
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1000,
                      order_type=OrderType.LIMIT, limit_price=200.0)
        passed, _ = engine.approve(order)
        assert not passed

    def test_update_position_affects_checks(self) -> None:
        engine = RiskEngine(peak_nav=100_000.0)
        engine.update_position("AAPL", 45_000.0)
        # additional 10_000 = 55_000 > 50_000
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=100,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        passed, _ = engine.approve(order)
        assert not passed

    def test_drawdown_kills_any_order(self) -> None:
        engine = RiskEngine(peak_nav=100_000.0)
        engine.update_position("AAPL", 94_000.0)  # 6% drawdown > 5% limit
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1,
                      order_type=OrderType.LIMIT, limit_price=1.0)
        passed, reason = engine.approve(order)
        assert not passed
        assert "Drawdown" in reason
