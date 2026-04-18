from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AddressCreate(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    line_1: str = Field(min_length=5, max_length=255)
    line_2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=2, max_length=120)
    district: str = Field(min_length=2, max_length=120)
    latitude: float
    longitude: float


class AddressResponse(ORMModel):
    id: int
    user_id: int
    label: str
    line_1: str
    line_2: str | None
    city: str
    district: str
    latitude: float
    longitude: float
    created_at: datetime
