from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

import cv2
import numpy as np
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from traffic_recognition.db import (
    Base,
    RunSession,
    TrackUpsert,
    insert_plate_read,
    open_db,
    update_best_plate,
    upsert_vehicle_track,
)
from traffic_recognition.ocr import build_ocr_engine, looks_like_tr_plate, normalize_plate
from traffic_recognition.plates import (
    BBox,
    HeuristicPlateDetector,
    PlateDetector,
    UltralyticsPlateDetector,
    preprocess_for_ocr,
)
from traffic_recognition.source import resolve_video_source


_COCO_VEHICLE_NAMES = {"car", "motorcycle", "bus", "truck"}


@dataclass(frozen=True)
class PipelineConfig:
    video_path: str
    db_path: str = "data/traffic.sqlite"
    vehicle_model: str = "yolov8n.pt"
    plate_model: str | None = None
    ocr_engine: str = "easyocr"
    ocr_langs: list[str] = None  # type: ignore[assignment]
    min_conf: float = 0.25
    device: str = "auto"  # auto|cpu|cuda|0|cuda:0 ...
    ocr_gpu: str = "auto"  # auto|on|off (sadece easyocr)
    save_plates_dir: str | None = None
    save_video_path: str | None = None
    display: bool = False
    max_frames: int | None = None


@dataclass(frozen=True)
class PipelineSummary:
    session_id: int
    total_vehicles: int
    vehicles_with_plate: int
    db_path: str
    save_plates_dir: str | None
    save_video_path: str | None


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _build_plate_detector(plate_model: str | None) -> PlateDetector:
    if plate_model:
        return UltralyticsPlateDetector(plate_model, device="auto")
    return HeuristicPlateDetector()


def _safe_int(x) -> int:
    try:
        return int(x)
    except Exception:
        return 0


def _resolve_ultralytics_device(requested: str, *, torch) -> str | int:
    req = (requested or "auto").strip().lower()
    cuda_ok = bool(torch.cuda.is_available())
    if req == "auto":
        return 0 if cuda_ok else "cpu"
    if req in ("cpu",):
        return "cpu"
    if req in ("cuda", "cuda:0"):
        if not cuda_ok:
            raise RuntimeError("CUDA isteniyor ama torch.cuda.is_available() = False (CUDA'lı PyTorch kurulu değil).")
        return 0
    if req.isdigit():
        if not cuda_ok:
            raise RuntimeError("GPU device isteniyor ama CUDA yok (CUDA'lı PyTorch kurulu değil).")
        return int(req)
    if req.startswith("cuda:"):
        if not cuda_ok:
            raise RuntimeError("CUDA device isteniyor ama CUDA yok (CUDA'lı PyTorch kurulu değil).")
        # ultralytics hem "cuda:0" hem 0 kabul edebiliyor; string olarak geç
        return requested
    return requested


def run_video_pipeline(
    cfg: PipelineConfig,
    *,
    db_engine: Engine | None = None,
    on_frame: "callable[[int, np.ndarray, dict], None] | None" = None,
    should_stop: "callable[[], bool] | None" = None,
) -> PipelineSummary:
    source = resolve_video_source(cfg.video_path)
    if not (source.startswith("http://") or source.startswith("https://")) and not os.path.exists(source):
        raise FileNotFoundError(source)

    from ultralytics import YOLO  # type: ignore
    import torch  # type: ignore

    engine = db_engine or open_db(cfg.db_path)
    if db_engine is not None:
        # Dışarıdan engine verildiyse tabloları burada garanti altına al.
        Base.metadata.create_all(engine)
    ocr = build_ocr_engine(cfg.ocr_engine, cfg.ocr_langs or ["en"], ocr_gpu=cfg.ocr_gpu)
    # cihaz seçimi
    ultra_device = _resolve_ultralytics_device(cfg.device, torch=torch)
    plate_detector = (
        UltralyticsPlateDetector(cfg.plate_model, device=ultra_device) if cfg.plate_model else HeuristicPlateDetector()
    )

    vehicle_model = YOLO(cfg.vehicle_model)

    session_id: int
    with Session(engine) as db:
        rs = RunSession(video_path=cfg.video_path, started_at=dt.datetime.utcnow())
        db.add(rs)
        db.commit()
        session_id = rs.id

    plates_out_dir = None
    if cfg.save_plates_dir:
        plates_out_dir = os.path.join(cfg.save_plates_dir, str(session_id))
        _ensure_dir(plates_out_dir)

    writer = None
    window = "TrafikTanima"

    total_seen_tracks: set[int] = set()
    tracks_with_plate: set[int] = set()

    # Ultralytics tracking stream
    stream = vehicle_model.track(
        source=source,
        stream=True,
        persist=True,
        conf=cfg.min_conf,
        verbose=False,
        tracker="bytetrack.yaml",
        device=ultra_device,
    )

    for frame_index, result in enumerate(stream):
        if should_stop and should_stop():
            break
        if cfg.max_frames is not None and frame_index >= cfg.max_frames:
            break

        frame_bgr = result.orig_img
        if frame_bgr is None:
            continue

        if writer is None and cfg.save_video_path:
            h, w = frame_bgr.shape[:2]
            fps = float(result.speed.get("fps", 0.0) or 0.0)
            if fps <= 0:
                # fallback (stream URL'lerde VideoCapture FPS güvenilir olmayabilir)
                if source.startswith("http://") or source.startswith("https://"):
                    fps = 25.0
                else:
                    cap = cv2.VideoCapture(source)
                    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    cap.release()
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(cfg.save_video_path, fourcc, fps, (w, h))

        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            if cfg.display:
                cv2.imshow(window, frame_bgr)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
            if writer:
                writer.write(frame_bgr)
            continue

        names = result.names or {}

        frame_annot = frame_bgr.copy() if (cfg.display or writer) else frame_bgr

        with Session(engine) as db:
            for b in boxes:
                cls_id = _safe_int(b.cls.item() if b.cls is not None else 0)
                label = str(names.get(cls_id, cls_id))
                if label not in _COCO_VEHICLE_NAMES:
                    continue

                track_id = None
                if b.id is not None:
                    track_id = _safe_int(b.id.item())
                if track_id is None:
                    # takip id yoksa benzersiz araç sayımı güvenilir olmaz
                    continue

                total_seen_tracks.add(track_id)

                xyxy = b.xyxy[0].tolist()
                x1, y1, x2, y2 = [int(v) for v in xyxy]
                vehicle_bbox = BBox(x1, y1, x2, y2)

                vt = upsert_vehicle_track(
                    db,
                    TrackUpsert(
                        session_id=session_id,
                        track_id=track_id,
                        vehicle_type=label,
                        frame_index=frame_index,
                    ),
                )

                # Plaka tespiti + OCR
                plate_candidates = plate_detector.detect(frame_bgr, vehicle_bbox)[:3]
                best_plate_text = None
                best_plate_conf = -1.0
                best_plate_img_path = None

                for i, cand in enumerate(plate_candidates):
                    bb = cand.bbox
                    h, w = frame_bgr.shape[:2]
                    bb = bb.clamp(w, h)
                    plate_img = frame_bgr[bb.y1 : bb.y2, bb.x1 : bb.x2]
                    if plate_img.size == 0:
                        continue

                    ocr_img = preprocess_for_ocr(plate_img)
                    reads = ocr.read(ocr_img)
                    if not reads:
                        continue

                    top = reads[0]
                    plate_text = normalize_plate(top.text)
                    conf = float(top.conf) * float(max(cand.conf, 0.1))

                    # basit filtre: TR formatına benzemiyorsa düşür
                    if looks_like_tr_plate(plate_text):
                        conf *= 1.1
                    else:
                        conf *= 0.8

                    img_path = None
                    if plates_out_dir:
                        img_path = os.path.join(plates_out_dir, f"track{track_id}_f{frame_index}_c{i}.jpg")
                        cv2.imwrite(img_path, plate_img)

                    insert_plate_read(
                        db,
                        session_id=session_id,
                        vehicle_track_id=vt.id,
                        frame_index=frame_index,
                        plate_text=plate_text,
                        conf=conf,
                        image_path=img_path,
                    )

                    if conf > best_plate_conf:
                        best_plate_conf = conf
                        best_plate_text = plate_text
                        best_plate_img_path = img_path

                if best_plate_text is not None:
                    update_best_plate(db, vt, best_plate_text, best_plate_conf)
                    tracks_with_plate.add(track_id)

                if cfg.display or writer:
                    # çizim
                    cv2.rectangle(frame_annot, (x1, y1), (x2, y2), (0, 200, 0), 2)
                    caption = f"{label} id={track_id}"
                    if best_plate_text:
                        caption += f" plate={best_plate_text}"
                    cv2.putText(
                        frame_annot,
                        caption,
                        (x1, max(0, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 200, 0),
                        2,
                        cv2.LINE_AA,
                    )
                    if best_plate_img_path:
                        # küçük işaret
                        cv2.circle(frame_annot, (x2 - 6, y1 + 6), 4, (0, 255, 255), -1)

            db.commit()

        if cfg.display:
            cv2.imshow(window, frame_annot)
            if cv2.waitKey(1) & 0xFF == 27:
                break
        if writer:
            writer.write(frame_annot)
        if on_frame:
            on_frame(
                frame_index,
                frame_annot,
                {
                    "session_id": session_id,
                    "total_vehicles": len(total_seen_tracks),
                    "vehicles_with_plate": len(tracks_with_plate),
                },
            )

    if writer:
        writer.release()
    if cfg.display:
        cv2.destroyAllWindows()

    # session end
    with Session(engine) as db:
        rs = db.get(RunSession, session_id)
        if rs is not None:
            rs.ended_at = dt.datetime.utcnow()
            db.commit()

    return PipelineSummary(
        session_id=session_id,
        total_vehicles=len(total_seen_tracks),
        vehicles_with_plate=len(tracks_with_plate),
        db_path=cfg.db_path,
        save_plates_dir=plates_out_dir,
        save_video_path=cfg.save_video_path,
    )


def run_video_pipeline_blocking(cfg: PipelineConfig) -> PipelineSummary:
    # Geriye dönük uyumluluk: eski çağrıların tek parametre ile çalışması için
    return run_video_pipeline(cfg)
