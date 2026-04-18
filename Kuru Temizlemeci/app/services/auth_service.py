import random

from fastapi import HTTPException, status
from redis import Redis

from app.core.config import get_settings

_memory_otp_store: dict[str, str] = {}


def _redis_client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def generate_and_store_otp(phone_number: str) -> str:
    code = f"{random.randint(100000, 999999)}"
    settings = get_settings()
    if settings.redis_url.startswith("memory://"):
        _memory_otp_store[phone_number] = code
        return code
    try:
        client = _redis_client()
        client.setex(f"otp:{phone_number}", settings.otp_ttl_seconds, code)
    except Exception:
        _memory_otp_store[phone_number] = code
    return code


def verify_otp(phone_number: str, otp_code: str) -> bool:
    settings = get_settings()
    if settings.redis_url.startswith("memory://"):
        stored = _memory_otp_store.get(phone_number)
        if stored != otp_code:
            return False
        _memory_otp_store.pop(phone_number, None)
        return True

    try:
        client = _redis_client()
        stored = client.get(f"otp:{phone_number}")
    except Exception:
        stored = _memory_otp_store.get(phone_number)
        if stored != otp_code:
            return False
        _memory_otp_store.pop(phone_number, None)
        return True

    if stored != otp_code:
        return False

    client.delete(f"otp:{phone_number}")
    return True
