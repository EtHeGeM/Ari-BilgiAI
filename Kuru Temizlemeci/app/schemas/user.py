from datetime import datetime

from pydantic import BaseModel, Field

from app.models.user import UserRole
from app.schemas.common import ORMModel


class UserResponse(ORMModel):
    id: int
    phone_number: str
    full_name: str
    role: UserRole
    vendor_id: int | None
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)
    full_name: str = Field(min_length=2, max_length=120)
    role: UserRole = UserRole.CUSTOMER
    vendor_id: int | None = None


class VendorUserCreate(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)
    full_name: str = Field(min_length=2, max_length=120)
    vendor_id: int
