import logging

from redis import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_memory_notifications: list[str] = []


def notify(event_type: str, payload: dict) -> None:
    settings = get_settings()
    if settings.redis_url.startswith("memory://"):
        _memory_notifications.append(f"{event_type}:{payload}")
        return
    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        client.lpush("notifications", f"{event_type}:{payload}")
    except Exception:
        _memory_notifications.append(f"{event_type}:{payload}")
        logger.info("Notification fallback", extra={"event_type": event_type, "payload": payload})
