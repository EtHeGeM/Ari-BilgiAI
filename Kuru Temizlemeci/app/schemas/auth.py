from pydantic import BaseModel, Field


class OTPRequest(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)


class OTPVerifyRequest(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)
    otp_code: str = Field(min_length=4, max_length=8)
    full_name: str | None = Field(default=None, max_length=120)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_new_user: bool
