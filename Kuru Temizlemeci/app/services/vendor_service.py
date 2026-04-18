from math import radians, sin, cos, sqrt, atan2

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.vendor import Vendor
from app.schemas.vendor import VendorCreate, VendorUpdate


def list_vendors(db: Session, active_only: bool = False) -> list[Vendor]:
    query = db.query(Vendor)
    if active_only:
        query = query.filter(Vendor.is_active.is_(True))
    return query.order_by(Vendor.created_at.desc()).all()


def get_vendor(db: Session, vendor_id: int) -> Vendor:
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found"
        )
    return vendor


def create_vendor(db: Session, payload: VendorCreate) -> Vendor:
    existing_vendor = (
        db.query(Vendor).filter(Vendor.phone_number == payload.phone_number).first()
    )
    if existing_vendor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vendor phone number already exists",
        )
    vendor = Vendor(**payload.model_dump())
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return vendor


def update_vendor(db: Session, vendor_id: int, payload: VendorUpdate) -> Vendor:
    vendor = get_vendor(db, vendor_id)
    if payload.phone_number and payload.phone_number != vendor.phone_number:
        existing_vendor = (
            db.query(Vendor).filter(Vendor.phone_number == payload.phone_number).first()
        )
        if existing_vendor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vendor phone number already exists",
            )
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(vendor, key, value)
    db.commit()
    db.refresh(vendor)
    return vendor


def assign_nearest_vendor(db: Session, latitude: float, longitude: float) -> tuple[Vendor, float]:
    vendors = list_vendors(db, active_only=True)
    if not vendors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active vendor available",
        )

    best_vendor = None
    best_distance = None
    for vendor in vendors:
        distance = haversine_km(latitude, longitude, vendor.latitude, vendor.longitude)
        if best_distance is None or distance < best_distance:
            best_vendor = vendor
            best_distance = distance

    return best_vendor, round(best_distance or 0, 2)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return earth_radius * c
