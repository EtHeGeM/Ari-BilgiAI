from __future__ import annotations

import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.engine import Engine


JobStatus = Literal["queued", "running", "completed", "failed", "stopped"]


@dataclass
class TrafficJob:
    id: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None
    summary: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None
    stop_event: threading.Event | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "error": self.error,
            "summary": self.summary,
            "progress": self.progress,
        }


_JOBS: dict[str, TrafficJob] = {}
_LOCK = threading.Lock()


def _ensure_trafiktanima_importable() -> None:
    try:
        import traffic_recognition  # noqa: F401

        return
    except Exception:
        pass

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "TrafikTanıma" / "src"
        if (candidate / "traffic_recognition").is_dir():
            sys.path.insert(0, str(candidate))
            return


def ensure_traffic_tables(engine: Engine) -> bool:
    _ensure_trafiktanima_importable()
    try:
        from traffic_recognition.db import Base  # type: ignore
    except Exception:
        return False

    Base.metadata.create_all(bind=engine)
    return True


def start_job(*, engine: Engine, cfg_dict: dict[str, Any]) -> str:
    job_id = uuid.uuid4().hex
    job = TrafficJob(id=job_id, status="queued", created_at=datetime.utcnow(), stop_event=threading.Event())

    with _LOCK:
        _JOBS[job_id] = job

    def _runner() -> None:
        with _LOCK:
            job.status = "running"
            job.started_at = datetime.utcnow()

        try:
            _ensure_trafiktanima_importable()
            from traffic_recognition.pipeline import PipelineConfig, run_video_pipeline  # type: ignore

            cfg = PipelineConfig(**cfg_dict)

            def _on_frame(frame_index: int, _frame_bgr, stats: dict) -> None:
                with _LOCK:
                    job.progress = {"frame_index": frame_index, **stats}

            summary = run_video_pipeline(
                cfg,
                db_engine=engine,
                on_frame=_on_frame,
                should_stop=lambda: bool(job.stop_event and job.stop_event.is_set()),
            )

            with _LOCK:
                job.status = "completed" if not (job.stop_event and job.stop_event.is_set()) else "stopped"
                job.summary = {
                    "session_id": summary.session_id,
                    "total_vehicles": summary.total_vehicles,
                    "vehicles_with_plate": summary.vehicles_with_plate,
                    "db_path": summary.db_path,
                    "save_plates_dir": summary.save_plates_dir,
                    "save_video_path": summary.save_video_path,
                }
        except Exception as e:
            with _LOCK:
                job.status = "failed"
                job.error = f"{type(e).__name__}: {e}"
        finally:
            with _LOCK:
                job.ended_at = datetime.utcnow()

    t = threading.Thread(target=_runner, name=f"traffic-job-{job_id}", daemon=True)
    t.start()
    return job_id


def get_job(job_id: str) -> TrafficJob | None:
    with _LOCK:
        return _JOBS.get(job_id)


def list_jobs() -> list[TrafficJob]:
    with _LOCK:
        return list(_JOBS.values())


def stop_job(job_id: str) -> bool:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job or not job.stop_event:
            return False
        job.stop_event.set()
        return True

