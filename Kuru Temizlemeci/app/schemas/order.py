from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.order import OrderStatus
from app.schemas.address import AddressResponse
from app.schemas.common import ORMModel
from app.schemas.user import UserResponse
from app.schemas.vendor import VendorResponse


class OrderItemCreate(BaseModel):
    item_type: str = Field(min_length=2, max_length=120)
    quantity: int = Field(gt=0, le=100)
    unit_price: Decimal = Field(gt=0)


class OrderCreate(BaseModel):
    address_id: int
    notes: str | None = Field(default=None, max_length=1000)
    items: list[OrderItemCreate]


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class OrderItemResponse(ORMModel):
    id: int
    item_type: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal


class OrderResponse(ORMModel):
    id: int
    user_id: int
    vendor_id: int | None
    address_id: int
    status: OrderStatus
    subtotal: Decimal
    delivery_fee: Decimal
    total_price: Decimal
    assigned_distance_km: float | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]


class OrderDetailResponse(OrderResponse):
    user: UserResponse
    vendor: VendorResponse | None
    address: AddressResponse


class OrderSummaryResponse(BaseModel):
    total_orders: int
    assigned_orders: int
    in_progress_orders: int
    delivered_orders: int
