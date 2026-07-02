from __future__ import annotations

from typing import Protocol

from src.broker.order import Order
from src.utils import get_logger, get_settings

log = get_logger(__name__)


class RiskCheck(Protocol):
    def check(
        self,
        order: Order,
        portfolio: dict[str, float],
        last_prices: dict[str, float],
    ) -> tuple[bool, str]:
        ...


class PositionLimitCheck:
    def __init__(self) -> None:
        self._settings = get_settings()

    def _check_usd_exposure(
        self, order: Order, portfolio: dict[str, float], price: float
    ) -> tuple[bool, str]:
        current_usd = portfolio.get(order.symbol, 0.0)
        order_usd = order.quantity * price
        projected_usd = abs(current_usd + order_usd)
        if projected_usd > self._settings.max_position_usd:
            msg = (
                f"PositionLimit: {order.symbol} projected ${projected_usd:,.0f} "
                f"> max ${self._settings.max_position_usd:,.0f}"
            )
            log.warning("risk_check_failed", check="position_limit", reason=msg)
            return False, msg
        return True, ""

    def check(
        self,
        order: Order,
        portfolio: dict[str, float],
        last_prices: dict[str, float],
    ) -> tuple[bool, str]:
        if order.limit_price is not None:
            return self._check_usd_exposure(order, portfolio, order.limit_price)

        last_price = last_prices.get(order.symbol)
        if last_price is not None:
            # Market order, but we have a recent traded price for this symbol
            # (fed by the strategy via RiskEngine.update_price on every bar), so
            # we can evaluate real USD exposure just like a limit order.
            return self._check_usd_exposure(order, portfolio, last_price)

        # True last resort: no limit_price AND no last-price observation exists
        # yet for this symbol (e.g. the very first bar before any price has been
        # recorded). Fall back to a raw share-count cap so we never submit an
        # order with zero risk evaluation.
        if abs(order.quantity) > self._settings.max_order_size:
            msg = (
                f"PositionLimit: {order.symbol} market order {order.quantity} shares "
                f"> max {self._settings.max_order_size} (share-count fallback, no price known)"
            )
            log.warning("risk_check_failed", check="position_limit", reason=msg)
            return False, msg

        return True, ""


class DrawdownCheck:
    def __init__(self, peak_nav: float) -> None:
        self._peak_nav = peak_nav
        self._settings = get_settings()

    def check(
        self,
        order: Order,
        portfolio: dict[str, float],
        last_prices: dict[str, float],
    ) -> tuple[bool, str]:
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
