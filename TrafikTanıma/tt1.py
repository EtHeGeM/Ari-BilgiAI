import streamlit as st
import cv2
import time
from ultralytics import YOLO
from vidgear.gears import CamGear

st.set_page_config(page_title="Pro Trafik Analizi", layout="wide")
st.title("🚀 Profesyonel Trafik Akış Analiz Sistemi")

# UI Bileşenleri
col1, col2 = st.columns([4, 1])
with col1:
    st_frame = st.empty()
with col2:
    st.markdown("### 📊 İstatistikler")
    count_text = st.empty()
    fps_text = st.empty()


# Modeli Yükle (Takip için persist=True kullanacağız)
@st.cache_resource
def load_model():
    return YOLO('yolov8n.pt')


model = load_model()
video_url = "https://youtu.be/4X9dtsZmSw8"
options = {"STREAM_RESOLUTION": "720p",}
stream = CamGear(source=video_url, stream_mode=True,**options).start()

# Değişkenler
frame_count = 0
skip_frames = 2  # Her 3 kareden 1'ini işle (Hız kazandırır)

while True:
    frame = stream.read()
    if frame is None: break

    frame_count += 1
    if frame_count % (skip_frames + 1) != 0:
        continue  # Bu kareyi analiz etmeden atla

    prev_time = time.time()

    # YOLO Tracking (Persist=True nesnelerin ID almasını sağlar)
    # Sadece araçları (classes=[2,3,5,7]) takip et
    results = model.track(frame, persist=True, conf=0.3, classes=[2, 3, 5, 7], verbose=False)

    if results[0].boxes.id is not None:
        # Görselleştirme
        annotated_frame = results[0].plot()

        # İstatistikleri Güncelle
        car_count = len(results[0].boxes)
        curr_time = time.time()
        fps = 1 / (curr_time - prev_time)

        # UI Güncelleme
        st_frame.image(annotated_frame, channels="BGR", width="stretch")
        count_text.metric("Tespit Edilen Araç", car_count)
        fps_text.metric("İşleme Hızı (FPS)", f"{fps:.1f}")

stream.stop()
