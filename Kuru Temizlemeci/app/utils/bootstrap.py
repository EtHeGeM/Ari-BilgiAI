from sqlalchemy.orm import Session

from app.models.address import Address
from app.models.order import Order, OrderItem, OrderStatus
from app.core.config import get_settings
from app.models.user import UserRole
from app.models.vendor import Vendor
from app.services import user_service


def ensure_default_admin(db: Session) -> None:
    settings = get_settings()
    admin = user_service.get_user_by_phone(db, settings.default_admin_phone)
    if admin:
        return

    user_service.create_user(
        db,
        phone_number=settings.default_admin_phone,
        full_name=settings.default_admin_name,
        role=UserRole.ADMIN,
    )


def ensure_demo_data(db: Session) -> None:
    vendor_count = db.query(Vendor).count()
    if vendor_count:
        return

    alpha_vendor = Vendor(
        name="FreshDrop Sisli",
        phone_number="+905550000001",
        address_line="Sisli, Istanbul",
        latitude=41.0602,
        longitude=28.9877,
        is_active=True,
    )
    beta_vendor = Vendor(
        name="BluePress Kadikoy",
        phone_number="+905550000002",
        address_line="Kadikoy, Istanbul",
        latitude=40.9909,
        longitude=29.0280,
        is_active=True,
    )
    db.add_all([alpha_vendor, beta_vendor])
    db.flush()

    vendor_user = user_service.create_user(
        db,
        phone_number="+905550000101",
        full_name="Vendor Operator",
        role=UserRole.VENDOR,
        vendor_id=alpha_vendor.id,
    )
    customer = user_service.create_user(
        db,
        phone_number="+905550000201",
        full_name="Demo Customer",
        role=UserRole.CUSTOMER,
    )

    address = Address(
        user_id=customer.id,
        label="Ev",
        line_1="Halaskargazi Cd. No: 10",
        line_2=None,
        city="Istanbul",
        district="Sisli",
        latitude=41.0521,
        longitude=28.9870,
    )
    db.add(address)
    db.flush()

    order = Order(
        user_id=customer.id,
        vendor_id=alpha_vendor.id,
        address_id=address.id,
        status=OrderStatus.ASSIGNED,
        subtotal=220.00,
        delivery_fee=39.90,
        total_price=259.90,
        assigned_distance_km=1.1,
        notes="Kiyafetler hassas yikansin",
    )
    db.add(order)
    db.flush()

    db.add_all(
        [
            OrderItem(
                order_id=order.id,
                item_type="Gomlek",
                quantity=4,
                unit_price=30.00,
                total_price=120.00,
            ),
            OrderItem(
                order_id=order.id,
                item_type="Pantolon",
                quantity=2,
                unit_price=50.00,
                total_price=100.00,
            ),
        ]
    )
    db.commit()
