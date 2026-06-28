from __future__ import annotations

from src.broker.order import Order
from src.risk.checks import DrawdownCheck, PositionLimitCheck, RiskCheck
from src.utils import get_logger

log = get_logger(__name__)


class RiskEngine:
    def __init__(self, peak_nav: float = 0.0) -> None:
        # DrawdownCheck runs first: it is a portfolio-level kill-switch that must
        # take priority over per-symbol position limits.
        self._checks: list[RiskCheck] = [
            DrawdownCheck(peak_nav),
            PositionLimitCheck(),
        ]
        self._portfolio: dict[str, float] = {}

    def update_position(self, symbol: str, usd_value: float) -> None:
        self._portfolio[symbol] = usd_value

    def approve(self, order: Order) -> tuple[bool, str]:
        for check in self._checks:
            passed, reason = check.check(order, self._portfolio)
            if not passed:
                log.warning("order_rejected", order_id=str(order.id), reason=reason)
                return False, reason
        return True, ""