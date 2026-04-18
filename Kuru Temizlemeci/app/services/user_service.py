from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User, UserRole


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_phone(db: Session, phone_number: str) -> User | None:
    return db.query(User).filter(User.phone_number == phone_number).first()


def create_user(
    db: Session,
    phone_number: str,
    full_name: str,
    role: UserRole = UserRole.CUSTOMER,
    vendor_id: int | None = None,
) -> User:
    existing_user = get_user_by_phone(db, phone_number)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number already registered",
        )

    user = User(
        phone_number=phone_number,
        full_name=full_name,
        role=role,
        vendor_id=vendor_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_vendor_users(db: Session) -> list[User]:
    return (
        db.query(User)
        .filter(User.role == UserRole.VENDOR)
        .order_by(User.created_at.desc())
        .all()
    )
