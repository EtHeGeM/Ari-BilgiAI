#!/usr/bin/env python3

"""
Basit Plaka Tanima (ANPR) - OpenCV + (opsiyonel) Tesseract OCR.

Bu script:
1) Goruntude plaka olmasi muhtemel dikdortgen bolgeyi bulur (kontur tabanli).
2) Plakayi perspektif duzeltme ile kirpar.
3) OCR ile metni okumaya calisir (pytesseract kuruluysa).

Not: Gercek hayatta isik, aci, bulaniklik, farkli plaka fontlari vb. icin
ML tabanli plaka tespiti + daha guclu OCR gerekebilir. Bu dosya, hizli bir
baseline amaciyla yazilmistir.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


try:
    import pytesseract  # type: ignore

    _HAS_TESSERACT = True
except Exception:
    pytesseract = None
    _HAS_TESSERACT = False


TR_PLATE_RE = re.compile(r"^\d{2}[A-Z]{1,3}\d{2,4}$")


@dataclass(frozen=True)
class PlateResult:
    text: str
    score: float
    box: np.ndarray  # (4, 2) float32 points on original frame
    plate_warp: np.ndarray  # BGR crop after perspective transform


def _order_points(pts: np.ndarray) -> np.ndarray:
    # Order as: top-left, top-right, bottom-right, bottom-left.
    pts = np.asarray(pts, dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def _four_point_warp(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect

    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxW = int(max(widthA, widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxH = int(max(heightA, heightB))

    maxW = max(maxW, 1)
    maxH = max(maxH, 1)

    dst = np.array(
        [[0, 0], [maxW - 1, 0], [maxW - 1, maxH - 1], [0, maxH - 1]],
        dtype=np.float32,
    )
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (maxW, maxH))


def _preprocess_for_detection(frame_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    edges = cv2.Canny(gray, 30, 200)

    # Plaka kenarlarinin kapanmasi icin hafif morfoloji.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)
    return edges


def _plate_candidate_score(quad: np.ndarray, frame_shape: Tuple[int, int, int]) -> float:
    h, w = frame_shape[:2]
    area = cv2.contourArea(quad.astype(np.float32))
    if area <= 1:
        return 0.0

    x, y, bw, bh = cv2.boundingRect(quad.astype(np.int32))
    if bw <= 0 or bh <= 0:
        return 0.0

    aspect = bw / float(bh)
    # Tipik plaka en/boy araligi (genis tolerans).
    if aspect < 1.8 or aspect > 7.5:
        return 0.0

    # Ekran alani orani (cok kucukse gorme ihtimali dusuk).
    area_ratio = area / float(w * h)
    if area_ratio < 0.002:
        return 0.0

    # Skor: alan ve aspect uyumu.
    aspect_score = 1.0 - min(abs(aspect - 4.0) / 4.0, 1.0)
    return float(0.6 * aspect_score + 0.4 * min(area_ratio / 0.05, 1.0))


def detect_plate_region(frame_bgr: np.ndarray, max_candidates: int = 15) -> Optional[np.ndarray]:
    edges = _preprocess_for_detection(frame_bgr)

    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[: max_candidates * 5]

    best_quad = None
    best_score = 0.0

    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4:
            continue

        quad = approx.reshape(4, 2).astype(np.float32)
        score = _plate_candidate_score(quad, frame_bgr.shape)
        if score > best_score:
            best_score = score
            best_quad = quad

    return best_quad


def _preprocess_for_ocr(plate_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(plate_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    thr = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )

    # Kucuk gurultuleri azalt.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    thr = cv2.morphologyEx(thr, cv2.MORPH_OPEN, kernel, iterations=1)
    return thr


def ocr_plate_text(plate_bgr: np.ndarray, tesseract_cmd: Optional[str] = None) -> Tuple[str, float]:
    if not _HAS_TESSERACT:
        return ("", 0.0)

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    img = _preprocess_for_ocr(plate_bgr)
    config = (
        "--oem 3 --psm 7 "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    )
    raw = pytesseract.image_to_string(img, config=config)
    text = re.sub(r"[^A-Z0-9]", "", raw.upper())

    # Basit guven skoru: TR formatina uyum + uzunluk.
    score = 0.2
    if 5 <= len(text) <= 10:
        score += 0.3
    if TR_PLATE_RE.match(text):
        score += 0.5
    return (text, float(min(score, 1.0)))


def recognize_plate(frame_bgr: np.ndarray, tesseract_cmd: Optional[str] = None) -> Optional[PlateResult]:
    quad = detect_plate_region(frame_bgr)
    if quad is None:
        return None

    warp = _four_point_warp(frame_bgr, quad)
    text, score = ocr_plate_text(warp, tesseract_cmd=tesseract_cmd)
    return PlateResult(text=text, score=score, box=quad, plate_warp=warp)


def _draw_result(frame_bgr: np.ndarray, res: PlateResult) -> np.ndarray:
    out = frame_bgr.copy()
    box = _order_points(res.box).astype(np.int32)
    cv2.polylines(out, [box], True, (0, 255, 0), 2)

    label = res.text if res.text else "PLATE?"
    label = f"{label} ({res.score:.2f})"

    x, y, w, h = cv2.boundingRect(box)
    y_text = max(y - 10, 20)
    cv2.putText(out, label, (x, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    return out


def _is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except Exception:
        return False


def _open_capture(source: str) -> cv2.VideoCapture:
    if _is_int(source):
        return cv2.VideoCapture(int(source))
    return cv2.VideoCapture(source)


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenCV ile basit plaka tanima (ANPR).")
    ap.add_argument(
        "--source",
        default="0",
        help="Kamera index (0) veya dosya yolu (image/video). Varsayilan: 0",
    )
    ap.add_argument("--show", action="store_true", help="Pencere ac (imshow).")
    ap.add_argument(
        "--save-dir",
        default="outputs",
        help="Ciktilarin kaydedilecegi klasor (varsayilan: outputs).",
    )
    ap.add_argument(
        "--every",
        type=int,
        default=1,
        help="Videoda her N karede bir OCR dene (varsayilan: 1).",
    )
    ap.add_argument(
        "--tesseract-cmd",
        default=None,
        help="Tesseract binary yolu (or: /usr/bin/tesseract).",
    )
    args = ap.parse_args()

    os.makedirs(args.save_dir, exist_ok=True)

    source = args.source
    is_file = os.path.exists(source)

    if is_file:
        img = cv2.imread(source)
        if img is None:
            print(f"Hata: Goruntu okunamadi: {source}", file=sys.stderr)
            return 2

        res = recognize_plate(img, tesseract_cmd=args.tesseract_cmd)
        if res is None:
            print("Plaka bulunamadi.")
            return 0

        annotated = _draw_result(img, res)
        out_img = os.path.join(args.save_dir, "annotated.jpg")
        out_plate = os.path.join(args.save_dir, "plate.jpg")
        cv2.imwrite(out_img, annotated)
        cv2.imwrite(out_plate, res.plate_warp)

        print(f"Plaka: {res.text or '(OCR yok/okunamadi)'}  skor={res.score:.2f}")
        print(f"Kaydedildi: {out_img}")
        print(f"Kaydedildi: {out_plate}")

        if args.show:
            cv2.imshow("ANPR", annotated)
            cv2.imshow("Plate", res.plate_warp)
            cv2.waitKey(0)
        return 0

    cap = _open_capture(source)
    if not cap.isOpened():
        print(f"Hata: Kaynak acilamadi: {source}", file=sys.stderr)
        return 2

    last_text = ""
    frame_i = 0
    t0 = time.time()
    saved_count = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_i += 1
        res = None
        if frame_i % max(args.every, 1) == 0:
            res = recognize_plate(frame, tesseract_cmd=args.tesseract_cmd)

        annotated = frame
        if res is not None:
            annotated = _draw_result(frame, res)
            if res.text and res.text != last_text:
                last_text = res.text
                saved_count += 1
                fn = os.path.join(args.save_dir, f"plate_{saved_count:03d}_{res.text}.jpg")
                cv2.imwrite(fn, res.plate_warp)
                print(f"[{frame_i}] Plaka: {res.text} skor={res.score:.2f}  kayit={fn}")

        if args.show:
            # FPS gostergesi
            dt = max(time.time() - t0, 1e-6)
            fps = frame_i / dt
            cv2.putText(
                annotated,
                f"FPS {fps:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (255, 0, 0),
                2,
            )
            cv2.imshow("ANPR", annotated)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):  # ESC / q
                break

    cap.release()
    if args.show:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
