from fastapi import APIRouter
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status

from app.core.security import create_access_token
from app.db.session import get_db
from app.schemas.auth import OTPRequest, OTPVerifyRequest, TokenResponse
from app.schemas.common import MessageResponse
from app.services import auth_service, user_service

router = APIRouter()


@router.post("/otp/request", response_model=MessageResponse)
def request_otp(payload: OTPRequest) -> MessageResponse:
    code = auth_service.generate_and_store_otp(payload.phone_number)
    return MessageResponse(message=f"OTP generated for testing: {code}")


@router.post("/otp/verify", response_model=TokenResponse)
def verify_otp(payload: OTPVerifyRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if not auth_service.verify_otp(payload.phone_number, payload.otp_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OTP code",
        )

    user = user_service.get_user_by_phone(db, payload.phone_number)
    is_new_user = False
    if not user:
        if not payload.full_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="full_name is required for first login",
            )
        user = user_service.create_user(
            db,
            phone_number=payload.phone_number,
            full_name=payload.full_name,
        )
        is_new_user = True

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token, is_new_user=is_new_user)
