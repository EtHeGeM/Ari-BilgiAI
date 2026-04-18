from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.address import AddressCreate, AddressResponse
from app.schemas.user import UserResponse
from app.services import address_service

router = APIRouter()


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/me/addresses", response_model=AddressResponse)
def create_my_address(
    payload: AddressCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return address_service.create_address(db, current_user, payload)


@router.get("/me/addresses", response_model=list[AddressResponse])
def list_my_addresses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return address_service.list_user_addresses(db, current_user.id)
