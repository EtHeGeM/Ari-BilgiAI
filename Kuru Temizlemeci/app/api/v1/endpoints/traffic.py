from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.db.session import engine
from app.services import traffic_recognition_service

router = APIRouter()
settings = get_settings()


class TrafficJobStartRequest(BaseModel):
    video_path: str = Field(..., description="Dosya yolu veya URL (YouTube dahil)")
    max_frames: int | None = Field(default=None, ge=1)
    min_conf: float = Field(default=0.25, ge=0.0, le=1.0)
    device: str = Field(default="auto", description="auto|cpu|cuda|0|cuda:0 ...")

    vehicle_model: str | None = Field(default=None, description="YOLO ağırlıkları (varsayılan: TrafikTanıma/yolov8n.pt)")
    plate_model: str | None = Field(default=None)

    ocr_engine: str = Field(default="none", description="none|easyocr|tesseract")
    ocr_langs: list[str] = Field(default_factory=lambda: ["en"])
    ocr_gpu: str = Field(default="auto", description="auto|on|off (sadece easyocr)")

    save_plates_dir: str | None = Field(default=None)
    save_video_path: str | None = Field(default=None)


class TrafficJobStartResponse(BaseModel):
    job_id: str


class TrafficJobStatusResponse(BaseModel):
    id: str
    status: str
    created_at: str
    started_at: str | None
    ended_at: str | None
    error: str | None
    summary: dict[str, Any] | None
    progress: dict[str, Any] | None


def _default_vehicle_model_path() -> str | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "TrafikTanıma" / "yolov8n.pt"
        if candidate.is_file():
            return str(candidate)
    return None


@router.post("/jobs", response_model=TrafficJobStartResponse)
def start_traffic_job(payload: TrafficJobStartRequest) -> TrafficJobStartResponse:
    vehicle_model = payload.vehicle_model or _default_vehicle_model_path() or "yolov8n.pt"
    cfg_dict = {
        "video_path": payload.video_path,
        "db_path": settings.database_url,
        "vehicle_model": vehicle_model,
        "plate_model": payload.plate_model,
        "ocr_engine": payload.ocr_engine,
        "ocr_langs": payload.ocr_langs,
        "min_conf": payload.min_conf,
        "device": payload.device,
        "ocr_gpu": payload.ocr_gpu,
        "save_plates_dir": payload.save_plates_dir,
        "save_video_path": payload.save_video_path,
        "display": False,
        "max_frames": payload.max_frames,
    }
    job_id = traffic_recognition_service.start_job(engine=engine, cfg_dict=cfg_dict)
    return TrafficJobStartResponse(job_id=job_id)


@router.get("/jobs", response_model=list[TrafficJobStatusResponse])
def list_traffic_jobs() -> list[TrafficJobStatusResponse]:
    return [TrafficJobStatusResponse(**j.to_dict()) for j in traffic_recognition_service.list_jobs()]


@router.get("/jobs/{job_id}", response_model=TrafficJobStatusResponse)
def get_traffic_job(job_id: str) -> TrafficJobStatusResponse:
    job = traffic_recognition_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return TrafficJobStatusResponse(**job.to_dict())


@router.post("/jobs/{job_id}/stop")
def stop_traffic_job(job_id: str) -> dict[str, str]:
    ok = traffic_recognition_service.stop_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"message": "stop requested"}
