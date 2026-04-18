from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import asdict

import cv2
import streamlit as st

from traffic_recognition.pipeline import PipelineConfig, PipelineSummary, run_video_pipeline


# Tarayıcı sekmesi kapanınca Tornado websocket "closed" hataları loga düşebiliyor; gürültüyü azalt.
logging.getLogger("tornado").setLevel(logging.ERROR)


class PipelineRunner:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frames: "queue.Queue[tuple[bytes, dict]]" = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._running = False
        self._error: str | None = None
        self._summary: PipelineSummary | None = None

    def start(
        self,
        cfg: PipelineConfig,
        *,
        preview_max_width: int = 960,
        preview_fps: float = 8.0,
        jpeg_quality: int = 82,
    ) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._error = None
            self._summary = None
            self._stop.clear()

        last_push = 0.0

        def on_frame(_frame_index: int, frame_bgr, stats: dict) -> None:
            nonlocal last_push
            if self._stop.is_set():
                return
            now = time.monotonic()
            if preview_fps > 0 and (now - last_push) < (1.0 / preview_fps):
                return
            last_push = now

            if preview_max_width and preview_max_width > 0:
                h, w = frame_bgr.shape[:2]
                if w > preview_max_width:
                    scale = preview_max_width / float(w)
                    frame_bgr = cv2.resize(frame_bgr, (preview_max_width, int(h * scale)))

            ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
            if not ok:
                return
            item = (buf.tobytes(), stats)
            try:
                self._frames.put_nowait(item)
            except queue.Full:
                try:
                    _ = self._frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._frames.put_nowait(item)
                except queue.Full:
                    pass

        def should_stop() -> bool:
            return self._stop.is_set()

        def worker() -> None:
            try:
                summary = run_video_pipeline(cfg, on_frame=on_frame, should_stop=should_stop)
                with self._lock:
                    self._summary = summary
            except Exception as e:
                with self._lock:
                    self._error = str(e)
            finally:
                with self._lock:
                    self._running = False

        self._thread = threading.Thread(target=worker, name="pipeline-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poll_latest(self) -> tuple[bytes | None, dict | None]:
        frame_bytes = None
        stats = None
        while True:
            try:
                frame_bytes, stats = self._frames.get_nowait()
            except queue.Empty:
                break
        return frame_bytes, stats

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    @property
    def summary(self) -> PipelineSummary | None:
        with self._lock:
            return self._summary


@st.cache_resource
def get_runner(_version: str = "v2") -> PipelineRunner:
    return PipelineRunner()


def app() -> None:
    st.set_page_config(page_title="TrafikTanıma", layout="wide")
    st.title("TrafikTanıma – Canlı/Video Pipeline")

    runner = get_runner("v2")
    if "upload_path" not in st.session_state:
        st.session_state.upload_path = None
    if "last_frame_bytes" not in st.session_state:
        st.session_state.last_frame_bytes = None
    if "last_stats" not in st.session_state:
        st.session_state.last_stats = None

    with st.sidebar:
        st.header("Kaynak")
        source = st.text_input("Video / URL (YouTube dahil)", value="https://youtu.be/4X9dtsZmSw8")
        uploaded = st.file_uploader("Ya da dosya yükle (mp4)", type=["mp4", "mov", "mkv", "avi"])
        st.divider()

        st.header("Model / OCR")
        vehicle_model = st.text_input("Araç YOLO modeli", value="yolov8n.pt")
        plate_model_path = st.text_input("Plaka model yolu (ops.)", value="")
        ocr_engine = st.selectbox("OCR", options=["easyocr", "tesseract", "none"], index=0)
        ocr_langs = st.text_input("EasyOCR dilleri (virgülle)", value="en")
        ocr_gpu = st.selectbox("EasyOCR GPU", options=["auto", "on", "off"], index=0)
        st.divider()

        st.header("Performans")
        device = st.text_input("Cihaz (auto|cpu|0|cuda:0 ...)", value="auto")
        min_conf = st.slider("Min conf", min_value=0.05, max_value=0.90, value=0.25, step=0.05)
        max_frames = st.number_input("Max frames (ops.)", min_value=0, value=0, step=100)
        preview_max_width = st.select_slider("Önizleme genişliği", options=[480, 640, 960, 1280, 1920], value=960)
        preview_fps = st.slider("Önizleme FPS", min_value=1, max_value=20, value=8, step=1)
        st.divider()

        st.header("Çıktı")
        db_path = st.text_input("DB yolu", value="data/traffic.sqlite")
        save_video = st.checkbox("Annotated video kaydet", value=False)
        save_video_path = st.text_input("Video çıktı yolu", value="outputs/annotated.mp4", disabled=not save_video)
        save_plates = st.checkbox("Plaka kırpımlarını kaydet", value=False)
        save_plates_dir = st.text_input("Plates dir", value="outputs/plates", disabled=not save_plates)

        col1, col2 = st.columns(2)
        with col1:
            start = st.button("Başlat", type="primary", disabled=runner.running)
        with col2:
            stop = st.button("Durdur", disabled=not runner.running)

    if stop:
        runner.stop()
        st.warning("Durdurma istendi (birkaç saniye sürebilir).")

    effective_source = source
    if uploaded is not None:
        os.makedirs("outputs/uploads", exist_ok=True)
        temp_path = os.path.join("outputs/uploads", uploaded.name)
        if st.session_state.upload_path != temp_path or not os.path.exists(temp_path):
            with open(temp_path, "wb") as f:
                f.write(uploaded.getbuffer())
            st.session_state.upload_path = temp_path
        effective_source = st.session_state.upload_path

    if start:
        cfg = PipelineConfig(
            video_path=effective_source,
            db_path=db_path,
            vehicle_model=vehicle_model,
            plate_model=plate_model_path.strip() or None,
            ocr_engine=ocr_engine,
            ocr_langs=[x.strip() for x in ocr_langs.split(",") if x.strip()],
            ocr_gpu=ocr_gpu,
            min_conf=float(min_conf),
            device=device.strip() or "auto",
            save_video_path=(save_video_path if save_video else None),
            save_plates_dir=(save_plates_dir if save_plates else None),
            max_frames=(int(max_frames) if int(max_frames) > 0 else None),
            display=False,
        )
        runner.start(
            cfg,
            preview_max_width=int(preview_max_width),
            preview_fps=float(preview_fps),
        )

    left, right = st.columns([2, 1])
    with left:
        frame_slot = st.empty()
    with right:
        stats_slot = st.empty()
        summary_slot = st.empty()
        error_slot = st.empty()

    def render_once() -> None:
        poller = getattr(runner, "poll_latest", None)
        if callable(poller):
            frame_bytes, stats = poller()
        else:
            # Eski cache_resource instance'ları için geriye uyumluluk
            legacy = getattr(runner, "poll", None)
            if callable(legacy):
                frame_bytes, stats = legacy()
            else:  # pragma: no cover
                frame_bytes, stats = (None, None)
        if frame_bytes:
            st.session_state.last_frame_bytes = frame_bytes
        if stats:
            st.session_state.last_stats = stats

        if st.session_state.last_frame_bytes:
            # JPEG bytes doğrudan gösterilebilir (decode etmeyerek daha akıcı)
            frame_slot.image(st.session_state.last_frame_bytes, caption="Pipeline output")
        if st.session_state.last_stats:
            stats_slot.json(st.session_state.last_stats)
        if runner.error:
            error_slot.error(runner.error)
        if runner.summary:
            summary_slot.json(asdict(runner.summary))

    frag = getattr(st, "fragment", None)
    if frag:
        try:
            deco = frag(run_every=0.2)
        except TypeError:  # pragma: no cover
            deco = frag

        @deco
        def live_fragment() -> None:
            render_once()

        live_fragment()
    else:
        render_once()
        if runner.running:
            time.sleep(0.2)
            if hasattr(st, "rerun"):
                st.rerun()
            else:  # pragma: no cover
                st.experimental_rerun()


if __name__ == "__main__":
    app()
