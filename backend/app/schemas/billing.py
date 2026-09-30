from datetime import date
from decimal import Decimal
from typing import List

from pydantic import BaseModel

from app.schemas.common import NamedRef


class SubscriptionOut(BaseModel):
    """A facility's SaaS subscription for the current billing month."""

    currency: str
    active: bool
    period_start: date
    period_end: date
    platform_fee: Decimal
    seat_fee: Decimal
    seats: int
    seat_guards: List[NamedRef]
    seats_total: Decimal
    monthly_total: Decimal
    active_contracts: int
    imported_contracts: int


class MonthValue(BaseModel):
    month: str
    value: Decimal


class SaasMetricsOut(BaseModel):
    currency: str
    platform_fee: Decimal
    seat_fee: Decimal
    subscribed_facilities: int
    tracked_guards: int
    platform_fees: Decimal
    seat_fees: Decimal
    mrr: Decimal
    arr: Decimal
    gmv: Decimal
    gmv_this_month: Decimal
    open_bid_volume: Decimal
    take_rate: float
    marketplace_revenue: Decimal
    marketplace_contracts: int
    imported_contracts: int
    gmv_by_month: List[MonthValue]
