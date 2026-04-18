# TrafikTanıma

High Definition bir trafik videosunda:
- Kaç araç geçtiğini (benzersiz takip id sayısı)
- Bu araçların plakalarını (OCR) okuyup
- Sonuçları bir veritabanına (varsayılan: SQLite) kaydeden örnek proje.

## Kurulum

Python 3.10+ (önerilen 3.12) gerekir.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[ocr_easyocr]
```

Alternatif (tek komut):

```bash
bash scripts/bootstrap_venv.sh
source .venv/bin/activate
```

Notlar:
- `easyocr` kullanmak istemezseniz `pip install -e .` ile sadece tespit/takip + DB çalışır.
- `tesseract` ile OCR için: `pip install -e .[ocr_tesseract]` ve sistemde `tesseract-ocr` kurulu olmalı.

## Çalıştırma

```bash
trafiktanima run \
  --video /path/to/video.mp4 \
  --db data/traffic.sqlite \
  --save-plates outputs/plates \
  --save-video outputs/annotated.mp4
```

`trafiktanima` komutu bulunamazsa:
- Virtualenv’in aktif olduğundan emin olun: `source .venv/bin/activate`
- Kurulum yapın: `pip install -e .`
- Alternatif olarak kurulumdan bağımsız çalıştırın: `python3 -m traffic_recognition run --video ...`
- Veya venv’i otomatik seçen wrapper’ı kullanın: `bash scripts/trafiktanima run --video ...`

## Canlı yayın (YouTube)

YouTube canlı yayınını pipeline’dan geçirmek için `yt-dlp` gerekir:

```bash
pip install -e .[youtube,ocr_easyocr]
```

Sonra:

```bash
trafiktanima live \
  --source "https://youtu.be/4X9dtsZmSw8" \
  --db data/traffic.sqlite \
  --display
```

İpucu: `--display` ile ESC’ye basarak durdurabilirsiniz. UI olmadan arka planda çalıştıracaksanız `--max-frames` ile sınırlamak iyi olur.

## NVIDIA / CUDA ile çalıştırma

GPU kullanımı için Python ortamınızda CUDA destekli PyTorch kurulu olmalı. Kontrol:

```bash
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')"
```

Ultralytics’in GPU kullandığını doğrulamak için (kısa test):

```bash
python -c "from ultralytics import YOLO; import torch; print('cuda', torch.cuda.is_available()); YOLO('yolov8n.pt').predict(source='https://ultralytics.com/images/bus.jpg', device=0 if torch.cuda.is_available() else 'cpu', verbose=False); print('ok')"
```

Pipeline tarafında cihaz seçimi:
- Otomatik (varsayılan): `--device auto`
- Zorla GPU: `--device 0` (veya `--device cuda:0`)
- CPU: `--device cpu`

EasyOCR GPU kullanımı (sadece `--ocr easyocr` için):
- Otomatik: `--ocr-gpu auto`
- Zorla aç: `--ocr-gpu on`
- Kapat: `--ocr-gpu off`

## Streamlit Web Arayüzü

Kurulum:

```bash
pip install -e .[ui,youtube,ocr_easyocr]
```

Çalıştırma:

```bash
trafiktanima ui --host 0.0.0.0 --port 8501
```

Alternatif:

```bash
streamlit run src/traffic_recognition/ui_app.py
```

Plaka tespiti için (önerilir) ayrı bir plaka-detector YOLO modeli vermek isteyebilirsiniz:

```bash
trafiktanima run \
  --video /path/to/video.mp4 \
  --plate-model /path/to/license_plate_yolo.pt
```

Model verilmezse sistem, araç kutusunun alt bandını plaka adayı olarak alıp OCR dener (daha düşük doğruluk).

## Çıktılar

- Veritabanı: `data/traffic.sqlite` (varsayılan)
- Plaka kırpımları (opsiyonel): `outputs/plates/<session_id>/...jpg`
- Annotated video (opsiyonel): `outputs/annotated.mp4`

## Şema (özet)

- `run_sessions`: çalıştırma bilgileri
- `vehicle_tracks`: benzersiz araçlar (track_id)
- `plate_reads`: her OCR denemesi ve güven skoru
