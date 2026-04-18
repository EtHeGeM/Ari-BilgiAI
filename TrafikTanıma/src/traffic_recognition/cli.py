from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from traffic_recognition.pipeline import PipelineConfig, run_video_pipeline


@dataclass(frozen=True)
class CliArgs:
    video: str
    db: str
    yolo_model: str
    plate_model: str | None
    ocr: str
    ocr_langs: list[str]
    ocr_gpu: str
    min_conf: float
    device: str
    save_plates: str | None
    save_video: str | None
    display: bool
    max_frames: int | None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trafiktanima")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Videoyu işle ve DB'ye kaydet")
    run.add_argument("--video", required=True, help="Girdi video yolu")
    run.add_argument("--db", default="data/traffic.sqlite", help="SQLite db yolu")
    run.add_argument("--yolo-model", default="yolov8n.pt", help="Araç tespiti modeli (Ultralytics)")
    run.add_argument(
        "--plate-model",
        default=None,
        help="Plaka tespiti YOLO modeli yolu (verilmezse heuristik crop kullanılır)",
    )
    run.add_argument("--ocr", choices=["easyocr", "tesseract", "none"], default="easyocr")
    run.add_argument(
        "--ocr-langs",
        default="en",
        help="EasyOCR dil listesi (virgülle). Örn: en,tr",
    )
    run.add_argument("--ocr-gpu", choices=["auto", "on", "off"], default="auto", help="EasyOCR GPU kullanımı")
    run.add_argument("--min-conf", type=float, default=0.25, help="Tespit minimum güven")
    run.add_argument("--device", default="auto", help="Ultralytics cihazı: auto|cpu|cuda|0|cuda:0 ...")
    run.add_argument("--save-plates", default=None, help="Plaka kırpımlarını kaydet klasörü")
    run.add_argument("--save-video", default=None, help="Annotate edilmiş videoyu kaydet")
    run.add_argument("--display", action="store_true", help="Pencere açıp göster")
    run.add_argument("--max-frames", type=int, default=None, help="Debug için maksimum frame")

    live = sub.add_parser("live", help="Canlı yayın/URL kaynağını işle (YouTube dahil)")
    live.add_argument("--source", required=True, help="YouTube URL veya doğrudan stream URL (m3u8/http)")
    live.add_argument("--db", default="data/traffic.sqlite", help="SQLite db yolu")
    live.add_argument("--yolo-model", default="yolov8n.pt", help="Araç tespiti modeli (Ultralytics)")
    live.add_argument("--plate-model", default=None, help="Plaka tespiti YOLO modeli yolu")
    live.add_argument("--ocr", choices=["easyocr", "tesseract", "none"], default="easyocr")
    live.add_argument("--ocr-langs", default="en", help="EasyOCR dil listesi (virgülle). Örn: en,tr")
    live.add_argument("--ocr-gpu", choices=["auto", "on", "off"], default="auto", help="EasyOCR GPU kullanımı")
    live.add_argument("--min-conf", type=float, default=0.25, help="Tespit minimum güven")
    live.add_argument("--device", default="auto", help="Ultralytics cihazı: auto|cpu|cuda|0|cuda:0 ...")
    live.add_argument("--save-plates", default=None, help="Plaka kırpımlarını kaydet klasörü")
    live.add_argument("--save-video", default=None, help="Annotate edilmiş videoyu kaydet")
    live.add_argument("--display", action="store_true", help="Pencere açıp göster (ESC ile durdur)")
    live.add_argument("--max-frames", type=int, default=None, help="Debug için maksimum frame")

    ui = sub.add_parser("ui", help="Streamlit web arayüzünü başlat")
    ui.add_argument("--host", default="localhost", help="Streamlit host")
    ui.add_argument("--port", type=int, default=8501, help="Streamlit port")
    ui.add_argument("--headless", action="store_true", help="Headless çalıştır")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)

    if ns.cmd == "ui":
        import subprocess
        import sys

        import traffic_recognition.ui_app as ui_app

        app_path = ui_app.__file__
        if not app_path:
            raise RuntimeError("ui_app dosyası bulunamadı")
        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            app_path,
            "--server.address",
            str(ns.host),
            "--server.port",
            str(int(ns.port)),
        ]
        if ns.headless:
            cmd += ["--server.headless", "true"]
        raise SystemExit(subprocess.call(cmd))

    if ns.cmd == "run":
        args = CliArgs(
            video=ns.video,
            db=ns.db,
            yolo_model=ns.yolo_model,
            plate_model=ns.plate_model,
            ocr=ns.ocr,
            ocr_langs=[x.strip() for x in str(ns.ocr_langs).split(",") if x.strip()],
            ocr_gpu=ns.ocr_gpu,
            min_conf=float(ns.min_conf),
            device=str(ns.device),
            save_plates=ns.save_plates,
            save_video=ns.save_video,
            display=bool(ns.display),
            max_frames=ns.max_frames,
        )
    elif ns.cmd == "live":
        args = CliArgs(
            video=ns.source,
            db=ns.db,
            yolo_model=ns.yolo_model,
            plate_model=ns.plate_model,
            ocr=ns.ocr,
            ocr_langs=[x.strip() for x in str(ns.ocr_langs).split(",") if x.strip()],
            ocr_gpu=ns.ocr_gpu,
            min_conf=float(ns.min_conf),
            device=str(ns.device),
            save_plates=ns.save_plates,
            save_video=ns.save_video,
            display=bool(ns.display),
            max_frames=ns.max_frames,
        )
    else:
        parser.error("Bilinmeyen komut")

    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    if args.save_plates:
        os.makedirs(args.save_plates, exist_ok=True)
    if args.save_video:
        os.makedirs(os.path.dirname(args.save_video) or ".", exist_ok=True)

    config = PipelineConfig(
        video_path=args.video,
        db_path=args.db,
        vehicle_model=args.yolo_model,
        plate_model=args.plate_model,
        ocr_engine=args.ocr,
        ocr_langs=args.ocr_langs,
        ocr_gpu=args.ocr_gpu,
        min_conf=args.min_conf,
        device=args.device,
        save_plates_dir=args.save_plates,
        save_video_path=args.save_video,
        display=args.display,
        max_frames=args.max_frames,
    )
    summary = run_video_pipeline(config)

    print(f"Session: {summary.session_id}")
    print(f"Total vehicles (unique tracks): {summary.total_vehicles}")
    print(f"Vehicles with a plate: {summary.vehicles_with_plate}")
    print(f"DB: {summary.db_path}")
    if summary.save_video_path:
        print(f"Video: {summary.save_video_path}")
    if summary.save_plates_dir:
        print(f"Plates dir: {summary.save_plates_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
