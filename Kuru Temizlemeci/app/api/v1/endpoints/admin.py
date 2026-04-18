from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.order import OrderDetailResponse, OrderSummaryResponse
from app.schemas.user import UserResponse, VendorUserCreate
from app.schemas.vendor import VendorResponse, VendorSummaryResponse
from app.services import order_service
from app.services import user_service
from app.services import vendor_service

router = APIRouter()


@router.get("/orders", response_model=list[OrderDetailResponse])
def list_all_orders(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    return order_service.admin_list_orders(db)


@router.get("/summary", response_model=OrderSummaryResponse)
def get_admin_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    return order_service.admin_order_summary(db)


@router.get("/vendor-users", response_model=list[UserResponse])
def list_vendor_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    return user_service.list_vendor_users(db)


@router.post("/vendor-users", response_model=UserResponse)
def create_vendor_user(
    payload: VendorUserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    vendor_service.get_vendor(db, payload.vendor_id)
    return user_service.create_user(
        db,
        phone_number=payload.phone_number,
        full_name=payload.full_name,
        role=UserRole.VENDOR,
        vendor_id=payload.vendor_id,
    )


@router.get("/vendors", response_model=list[VendorResponse])
def list_admin_vendors(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    return vendor_service.list_vendors(db)


@router.get("/vendors/summary", response_model=VendorSummaryResponse)
def get_vendor_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    vendors = vendor_service.list_vendors(db)
    return VendorSummaryResponse(
        total_vendors=len(vendors),
        active_vendors=len([vendor for vendor in vendors if vendor.is_active]),
    )
