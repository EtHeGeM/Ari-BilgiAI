from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()
static_dir = Path(__file__).resolve().parent / "static"


@router.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@router.get("/panel", include_in_schema=False)
def serve_panel() -> FileResponse:
    return FileResponse(static_dir / "index.html")
