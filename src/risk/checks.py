from __future__ import annotations

from typing import Protocol

from src.broker.order import Order
from src.utils import get_logger, get_settings

log = get_logger(__name__)


class RiskCheck(Protocol):
    def check(self, order: Order, portfolio: dict[str, float]) -> tuple[bool, str]:
        ...


class PositionLimitCheck:
    def __init__(self) -> None:
        self._settings = get_settings()

    def check(self, order: Order, portfolio: dict[str, float]) -> tuple[bool, str]:
        current_usd = portfolio.get(order.symbol, 0.0)

        if order.limit_price is not None:
            order_usd = order.quantity * order.limit_price
            projected_usd = abs(current_usd + order_usd)
            if projected_usd > self._settings.max_position_usd:
                msg = (
                    f"PositionLimit: {order.symbol} projected ${projected_usd:,.0f} "
                    f"> max ${self._settings.max_position_usd:,.0f}"
                )
                log.warning("risk_check_failed", check="position_limit", reason=msg)
                return False, msg
        else:
            # FIXME: market orders carry no limit_price, so USD exposure cannot be computed
            # without a last-price feed.  Falling back to raw share count vs max_order_size
            # until a price provider is injected into RiskCheck.
            if abs(order.quantity) > self._settings.max_order_size:
                msg = (
                    f"PositionLimit: {order.symbol} market order {order.quantity} shares "
                    f"> max {self._settings.max_order_size} (share-count fallback)"
                )
                log.warning("risk_check_failed", check="position_limit", reason=msg)
                return False, msg

        return True, ""


class DrawdownCheck:
    def __init__(self, peak_nav: float) -> None:
        self._peak_nav = peak_nav
        self._settings = get_settings()

    def check(self, order: Order, portfolio: dict[str, float]) -> tuple[bool, str]:
        # An empty portfolio means no positions have been recorded yet; treat
        # this as NAV == peak (no drawdown) rather than NAV == 0 (total loss).
        if not portfolio:
            return True, ""
        current_nav = sum(portfolio.values())
        if self._peak_nav > 0:
            drawdown = (self._peak_nav - current_nav) / self._peak_nav
            if drawdown >= self._settings.max_portfolio_drawdown_pct:
                msg = (
                    f"Drawdown {drawdown:.2%} >= limit "
                    f"{self._settings.max_portfolio_drawdown_pct:.2%}"
                )
                log.warning("risk_check_failed", check="drawdown", reason=msg)
                return False, msg
        return True, ""
