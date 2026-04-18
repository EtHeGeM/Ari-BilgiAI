from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.vendor import VendorCreate, VendorResponse, VendorUpdate
from app.services import vendor_service

router = APIRouter()


@router.get("", response_model=list[VendorResponse])
def list_vendors(db: Session = Depends(get_db)):
    return vendor_service.list_vendors(db)


@router.post("", response_model=VendorResponse)
def create_vendor(
    payload: VendorCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    return vendor_service.create_vendor(db, payload)


@router.patch("/{vendor_id}", response_model=VendorResponse)
def update_vendor(
    vendor_id: int,
    payload: VendorUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    return vendor_service.update_vendor(db, vendor_id, payload)
