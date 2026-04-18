from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.utils.bootstrap import ensure_default_admin, ensure_demo_data
from app.web.routes import router as web_router
from app import models  # noqa: F401

settings = get_settings()
static_dir = Path(__file__).resolve().parent / "web" / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_default_admin(db)
        ensure_demo_data(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")
app.include_router(web_router)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
def healthcheck() -> dict:
    return {"status": "ok"}
