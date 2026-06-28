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
        current = portfolio.get(order.symbol, 0.0)
        projected = abs(current + order.quantity)
        if projected > self._settings.max_order_size:
            msg = (
                f"PositionLimit: {order.symbol} projected {projected} "
                f"> max {self._settings.max_order_size}"
            )
            log.warning("risk_check_failed", check="position_limit", reason=msg)
            return False, msg
        return True, ""


class DrawdownCheck:
    def __init__(self, peak_nav: float) -> None:
        self._peak_nav = peak_nav
        self._settings = get_settings()

    def check(self, order: Order, portfolio: dict[str, float]) -> tuple[bool, str]:
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
