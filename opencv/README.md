# OpenCV ile Basit Plaka Tanima (ANPR)

Bu klasor, OpenCV ile kontur tabanli plaka bolgesi bulma + (opsiyonel) Tesseract OCR ile metin okuma yapan basit bir baseline icerir.

## Kurulum

Python paketleri:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Tesseract (Ubuntu/Debian):

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr
```

Not: `pytesseract` bir Python sarmalayicisidir; ayrica `tesseract` binary sistemde kurulu olmali.

## Calistirma

### Kamera (varsayilan 0)

```bash
python anpr.py --source 0 --show
```

### Video dosyasi

```bash
python anpr.py --source path/to/video.mp4 --show --every 2
```

### Goruntu dosyasi

```bash
python anpr.py --source path/to/image.jpg --show
```

Ciktilar varsayilan olarak `outputs/` klasorune yazilir:
- `outputs/annotated.jpg`: plaka kutusu + OCR metni
- `outputs/plate.jpg`: perspektif duzeltilmis plaka kirpimi
- Video/kamera modunda yeni plaka goruldukce `outputs/plate_*.jpg`

## Nasil Gelistirilir?

Bu yaklasim (kontur + Canny) zor kosullarda (gece, yansima, egik aci, dusuk cozunurluk) zorlanir. Daha guclu bir sistem icin tipik yol:
- Plaka tespiti icin YOLO/SSD gibi bir model (egitilmis plaka dataset'i ile)
- OCR icin CRNN/Transformer tabanli bir model veya iyilestirilmis Tesseract ayarlari
- Ulkeye ozel format kurallariyla metin duzeltme (regex + dil modeli)
