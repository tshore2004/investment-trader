from __future__ import annotations

from datetime import datetime, timezone

import ib_insync as ibi

from src.broker.order import Order, OrderSide, OrderStatus, OrderType
from src.utils import get_logger, get_settings

log = get_logger(__name__)


class IBBroker:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._ib = ibi.IB()

    async def connect(self) -> None:
        await self._ib.connectAsync(
            host=self._settings.ib_host,
            port=self._settings.ib_port,
            clientId=self._settings.ib_client_id + 10,  # separate client ID from feed
        )
        log.info("broker_connected")

    async def disconnect(self) -> None:
        self._ib.disconnect()

    async def submit(self, order: Order) -> Order:
        contract = ibi.Stock(order.symbol, "SMART", "USD")

        if order.order_type == OrderType.MARKET:
            ib_order = ibi.MarketOrder(order.side.value, order.quantity)
        elif order.order_type == OrderType.LIMIT:
            assert order.limit_price is not None
            ib_order = ibi.LimitOrder(order.side.value, order.quantity, order.limit_price)
        else:
            raise ValueError(f"Unsupported order type: {order.order_type}")

        self._ib.placeOrder(contract, ib_order)
        order.submitted_at = datetime.now(timezone.utc)
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

    @property
    def is_connected(self) -> bool:
        return self._ib.isConnected()
