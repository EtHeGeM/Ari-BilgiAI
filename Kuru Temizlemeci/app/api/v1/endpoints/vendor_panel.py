from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.order import OrderDetailResponse, OrderStatusUpdate
from app.services import order_service

router = APIRouter()


@router.get("/orders", response_model=list[OrderDetailResponse])
def list_vendor_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.VENDOR)),
):
    return order_service.list_orders_for_user(db, current_user)


@router.post("/orders/{order_id}/accept", response_model=OrderDetailResponse)
def accept_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.VENDOR)),
):
    return order_service.accept_order_by_vendor(db, current_user, order_id)


@router.post("/orders/{order_id}/status", response_model=OrderDetailResponse)
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.VENDOR)),
):
    return order_service.update_order_status_by_vendor(
        db, current_user, order_id, payload.status
    )
