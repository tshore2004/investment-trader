from __future__ import annotations

import pytest

from src.broker.order import Order, OrderSide, OrderType
from src.risk.checks import DrawdownCheck, PositionLimitCheck


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    from src.utils.config import get_settings
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# PositionLimitCheck
# ---------------------------------------------------------------------------

class TestPositionLimitCheck:
    def test_limit_order_within_bounds_passes(self) -> None:
        check = PositionLimitCheck()
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=10,
                      order_type=OrderType.LIMIT, limit_price=100.0)
        passed, reason = check.check(order, {}, {})
        assert passed
        assert reason == ""

    def test_limit_order_exceeds_max_position_usd(self) -> None:
        check = PositionLimitCheck()
        # quantity * price = 1000 * 200 = 200_000 > default 50_000
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1000,
                      order_type=OrderType.LIMIT, limit_price=200.0)
        passed, reason = check.check(order, {}, {})
        assert not passed
        assert "PositionLimit" in reason

    def test_limit_order_adds_to_existing_usd_position(self) -> None:
        check = PositionLimitCheck()
        # existing 40_000 + new 20_000 = 60_000 > 50_000
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=100,
                      order_type=OrderType.LIMIT, limit_price=200.0)
        passed, _ = check.check(order, {"AAPL": 40_000.0}, {})
        assert not passed

    def test_market_order_within_max_order_size_no_price_known(self) -> None:
        check = PositionLimitCheck()
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=10,
                      order_type=OrderType.MARKET)
        passed, _ = check.check(order, {}, {})
        assert passed

    def test_market_order_exceeds_max_order_size_no_price_known(self) -> None:
        check = PositionLimitCheck()
        # default max_order_size = 100, no last price recorded for AAPL
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=500,
                      order_type=OrderType.MARKET)
        passed, reason = check.check(order, {}, {})
        assert not passed
        assert "share-count fallback" in reason

    def test_market_order_with_known_price_uses_usd_exposure_small_qty_expensive(self) -> None:
        # 50 shares of a $500 stock = $25,000 < $50,000 cap — passes on USD exposure,
        # even though the old share-count-only fallback (max_order_size=100) would
        # have also passed here, this demonstrates the price-based math is used.
        check = PositionLimitCheck()
        order = Order(symbol="EXP", side=OrderSide.BUY, quantity=50,
                      order_type=OrderType.MARKET)
        passed, _ = check.check(order, {}, {"EXP": 500.0})
        assert passed

    def test_market_order_with_known_price_rejects_over_cap_despite_small_share_count(self) -> None:
        # 90 shares (under max_order_size=100, so the OLD share-count fallback would
        # have wrongly passed this) of a $600 stock = $54,000 > $50,000 cap — rejected
        # once real price-based USD exposure is used.
        check = PositionLimitCheck()
        order = Order(symbol="EXP", side=OrderSide.BUY, quantity=90,
                      order_type=OrderType.MARKET)
        passed, reason = check.check(order, {}, {"EXP": 600.0})
        assert not passed
        assert "PositionLimit" in reason

    def test_market_order_with_known_price_passes_large_share_count_cheap_stock(self) -> None:
        # 400 shares (over max_order_size=100, so the OLD share-count fallback would
        # have wrongly rejected this) of a $5 stock = $2,000 << $50,000 cap — passes
        # once real price-based USD exposure is used.
        check = PositionLimitCheck()
        order = Order(symbol="CHEAP", side=OrderSide.BUY, quantity=400,
                      order_type=OrderType.MARKET)
        passed, _ = check.check(order, {}, {"CHEAP": 5.0})
        assert passed


# ---------------------------------------------------------------------------
# DrawdownCheck
# ---------------------------------------------------------------------------

class TestDrawdownCheck:
    def test_no_drawdown_passes(self) -> None:
        check = DrawdownCheck(peak_nav=100_000.0)
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1)
        passed, _ = check.check(order, {"AAPL": 100_000.0}, {})
        assert passed

    def test_drawdown_below_limit_passes(self) -> None:
        check = DrawdownCheck(peak_nav=100_000.0)
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1)
        passed, _ = check.check(order, {"AAPL": 96_000.0}, {})  # 4% < 5%
        assert passed

    def test_drawdown_at_limit_blocked(self) -> None:
        check = DrawdownCheck(peak_nav=100_000.0)
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1)
        passed, reason = check.check(order, {"AAPL": 95_000.0}, {})  # 5% >= 5%
        assert not passed
        assert "Drawdown" in reason

    def test_zero_peak_nav_always_passes(self) -> None:
        check = DrawdownCheck(peak_nav=0.0)
        order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=1)
        passed, _ = check.check(order, {"AAPL": 0.0}, {})
        assert passed
