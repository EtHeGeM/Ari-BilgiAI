from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User, UserRole
from app.schemas.order import OrderCreate
from app.services import address_service, notification_service, pricing_service, vendor_service

ALLOWED_VENDOR_TRANSITIONS = {
    OrderStatus.ASSIGNED: {OrderStatus.PICKED_UP, OrderStatus.REJECTED},
    OrderStatus.PICKED_UP: {OrderStatus.CLEANING},
    OrderStatus.CLEANING: {OrderStatus.READY},
    OrderStatus.READY: {OrderStatus.OUT_FOR_DELIVERY},
    OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.DELIVERED},
}


def create_order(db: Session, user: User, payload: OrderCreate) -> Order:
    address = address_service.get_user_address(db, user.id, payload.address_id)
    assigned_vendor, distance_km = vendor_service.assign_nearest_vendor(
        db, address.latitude, address.longitude
    )

    item_payloads = [item.model_dump() for item in payload.items]
    subtotal, delivery_fee, total = pricing_service.calculate_pricing(item_payloads)

    order = Order(
        user_id=user.id,
        vendor_id=assigned_vendor.id,
        address_id=address.id,
        status=OrderStatus.ASSIGNED,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total_price=total,
        assigned_distance_km=distance_km,
        notes=payload.notes,
    )
    db.add(order)
    db.flush()

    for item in item_payloads:
        total_price = Decimal(str(item["unit_price"])) * item["quantity"]
        db.add(
            OrderItem(
                order_id=order.id,
                item_type=item["item_type"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                total_price=total_price,
            )
        )

    db.commit()
    db.refresh(order)
    notification_service.notify(
        "order_assigned",
        {"order_id": order.id, "vendor_id": assigned_vendor.id, "user_id": user.id},
    )
    return get_order_for_user(db, user, order.id)


def get_order(db: Session, order_id: int) -> Order:
    order = (
        db.query(Order)
        .options(
            joinedload(Order.items),
            joinedload(Order.user),
            joinedload(Order.vendor),
            joinedload(Order.address),
        )
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    return order


def get_order_for_user(db: Session, user: User, order_id: int) -> Order:
    order = get_order(db, order_id)
    if user.role == UserRole.CUSTOMER and order.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Order access denied"
        )
    if user.role == UserRole.VENDOR and order.vendor_id != user.vendor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Order access denied"
        )
    return order


def list_orders_for_user(db: Session, user: User) -> list[Order]:
    query = (
        db.query(Order)
        .options(
            joinedload(Order.items),
            joinedload(Order.user),
            joinedload(Order.vendor),
            joinedload(Order.address),
        )
        .order_by(Order.created_at.desc())
    )
    if user.role == UserRole.CUSTOMER:
        query = query.filter(Order.user_id == user.id)
    elif user.role == UserRole.VENDOR:
        query = query.filter(Order.vendor_id == user.vendor_id)
    return query.all()


def accept_order_by_vendor(db: Session, vendor_user: User, order_id: int) -> Order:
    if vendor_user.role != UserRole.VENDOR or not vendor_user.vendor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor permissions required",
        )

    order = get_order(db, order_id)
    if order.vendor_id != vendor_user.vendor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Order access denied"
        )
    if order.status != OrderStatus.ASSIGNED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only assigned orders can be accepted",
        )

    notification_service.notify(
        "order_accepted",
        {"order_id": order.id, "vendor_id": vendor_user.vendor_id},
    )
    return order


def update_order_status_by_vendor(db: Session, vendor_user: User, order_id: int, new_status: OrderStatus) -> Order:
    if vendor_user.role != UserRole.VENDOR or not vendor_user.vendor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor permissions required",
        )

    order = get_order(db, order_id)
    if order.vendor_id != vendor_user.vendor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Order access denied"
        )

    allowed = ALLOWED_VENDOR_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status transition from {order.status} to {new_status}",
        )

    if new_status == OrderStatus.REJECTED:
        new_vendor, distance_km = vendor_service.assign_nearest_vendor(
            db, order.address.latitude, order.address.longitude
        )
        if new_vendor.id == order.vendor_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No alternative vendor available",
            )
        order.vendor_id = new_vendor.id
        order.assigned_distance_km = distance_km
        order.status = OrderStatus.ASSIGNED
        notification_service.notify(
            "order_reassigned", {"order_id": order.id, "vendor_id": new_vendor.id}
        )
    else:
        order.status = new_status
        notification_service.notify(
            "order_status_changed",
            {"order_id": order.id, "status": new_status.value},
        )

    db.commit()
    db.refresh(order)
    return get_order(db, order.id)


def admin_list_orders(db: Session) -> list[Order]:
    return (
        db.query(Order)
        .options(
            joinedload(Order.items),
            joinedload(Order.user),
            joinedload(Order.vendor),
            joinedload(Order.address),
        )
        .order_by(Order.created_at.desc())
        .all()
    )


def admin_order_summary(db: Session) -> dict:
    orders = db.query(Order).all()
    return {
        "total_orders": len(orders),
        "assigned_orders": len([o for o in orders if o.status == OrderStatus.ASSIGNED]),
        "in_progress_orders": len(
            [
                o
                for o in orders
                if o.status
                in {
                    OrderStatus.PICKED_UP,
                    OrderStatus.CLEANING,
                    OrderStatus.READY,
                    OrderStatus.OUT_FOR_DELIVERY,
                }
            ]
        ),
        "delivered_orders": len([o for o in orders if o.status == OrderStatus.DELIVERED]),
    }
