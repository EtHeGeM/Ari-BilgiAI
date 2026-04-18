from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.address import Address
from app.models.user import User
from app.schemas.address import AddressCreate


def create_address(db: Session, user: User, payload: AddressCreate) -> Address:
    address = Address(user_id=user.id, **payload.model_dump())
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


def list_user_addresses(db: Session, user_id: int) -> list[Address]:
    return (
        db.query(Address)
        .filter(Address.user_id == user_id)
        .order_by(Address.created_at.desc())
        .all()
    )


def get_user_address(db: Session, user_id: int, address_id: int) -> Address:
    address = (
        db.query(Address)
        .filter(Address.id == address_id, Address.user_id == user_id)
        .first()
    )
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found",
        )
    return address
