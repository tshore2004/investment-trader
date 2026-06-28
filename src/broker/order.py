from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    strategy_id: str = ""
    id: UUID = field(default_factory=uuid4)
    status: OrderStatus = OrderStatus.PENDING
    filled_price: float | None = None
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
