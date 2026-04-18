from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class VendorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone_number: str = Field(min_length=10, max_length=20)
    address_line: str = Field(min_length=5, max_length=255)
    latitude: float
    longitude: float


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone_number: str | None = Field(default=None, min_length=10, max_length=20)
    address_line: str | None = Field(default=None, min_length=5, max_length=255)
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool | None = None


class VendorResponse(ORMModel):
    id: int
    tenant_id: str
    name: str
    phone_number: str
    address_line: str
    latitude: float
    longitude: float
    is_active: bool
    created_at: datetime


class VendorSummaryResponse(BaseModel):
    total_vendors: int
    active_vendors: int
