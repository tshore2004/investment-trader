from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import ib_insync as ibi

from src.broker.order import Order, OrderStatus, OrderType
from src.utils import get_logger, get_settings

log = get_logger(__name__)


class IBBroker:
    def __init__(self, ib: ibi.IB | None = None) -> None:
        self._settings = get_settings()
        self._owns_ib = ib is None
        if ib is not None:
            self._ib: Any = ib
        else:
            import ib_insync as _ibi  # lazy: eventkit fails at module level on Py 3.14+
            self._ib = _ibi.IB()  # type: ignore[no-untyped-call]

    async def connect(self) -> None:
        if not self._owns_ib:
            return
        await self._ib.connectAsync(
            host=self._settings.ib_host,
            port=self._settings.ib_port,
            clientId=self._settings.ib_client_id + 10,
        )
        log.info("broker_connected")

    async def disconnect(self) -> None:
        if not self._owns_ib:
            return
        self._ib.disconnect()

    async def submit(self, order: Order) -> Order:
        import ib_insync as _ibi  # lazy: eventkit fails at module level on Py 3.14+
        contract = _ibi.Stock(order.symbol, "SMART", "USD")

        ib_order: Any
        if order.order_type == OrderType.MARKET:
            ib_order = _ibi.MarketOrder(order.side.value, order.quantity)
        elif order.order_type == OrderType.LIMIT:
            assert order.limit_price is not None
            ib_order = _ibi.LimitOrder(order.side.value, order.quantity, order.limit_price)
        else:
            raise ValueError(f"Unsupported order type: {order.order_type}")

        self._ib.placeOrder(contract, ib_order)
        order.submitted_at = datetime.now(UTC)
        order.status = OrderStatus.SUBMITTED

        log.info(
            "order_submitted",
            order_id=str(order.id),
            symbol=order.symbol,
            side=order.side,
            qty=order.quantity,
        )
        return order

    async def cancel(self, order: Order) -> None:
        log.warning("cancel_not_implemented", order_id=str(order.id))

    def portfolio_snapshot(self) -> list[dict[str, Any]]:
        """Read current IB positions via ib_insync's PortfolioItem list."""
        rows: list[dict[str, Any]] = []
        for item in self._ib.portfolio():
            qty = item.position
            avg_cost = item.averageCost
            price = item.marketPrice
            pnl = item.unrealizedPNL
            cost_basis = avg_cost * qty
            pnl_pct = (pnl / abs(cost_basis) * 100.0) if cost_basis else 0.0
            rows.append(
                {
                    "symbol": item.contract.symbol,
                    "qty": qty,
                    "avg_cost": avg_cost,
                    "price": price,
                    "unrealized_pnl": pnl,
                    "unrealized_pnl_pct": pnl_pct,
                }
            )
        return rows

    @property
    def is_connected(self) -> bool:
        return bool(self._ib.isConnected())