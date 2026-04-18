from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class BBox:
    x1: int
    y1: int
    x2: int
    y2: int

    def clamp(self, w: int, h: int) -> "BBox":
        x1 = max(0, min(self.x1, w - 1))
        y1 = max(0, min(self.y1, h - 1))
        x2 = max(0, min(self.x2, w))
        y2 = max(0, min(self.y2, h))
        if x2 <= x1:
            x2 = min(w, x1 + 1)
        if y2 <= y1:
            y2 = min(h, y1 + 1)
        return BBox(x1, y1, x2, y2)


@dataclass(frozen=True)
class PlateCandidate:
    bbox: BBox
    conf: float


class PlateDetector:
    def detect(self, frame_bgr: np.ndarray, vehicle_bbox: BBox) -> list[PlateCandidate]:
        raise NotImplementedError


class HeuristicPlateDetector(PlateDetector):
    """
    Plaka-detector modeli yoksa:
    - Araç bbox'ın alt bandını plaka adayı kabul et.
    """

    def detect(self, frame_bgr: np.ndarray, vehicle_bbox: BBox) -> list[PlateCandidate]:
        h, w = frame_bgr.shape[:2]
        vb = vehicle_bbox.clamp(w, h)
        vh = vb.y2 - vb.y1
        vw = vb.x2 - vb.x1
        # Alt %40 ve orta %80
        y1 = vb.y1 + int(vh * 0.55)
        y2 = vb.y2 - int(vh * 0.05)
        x1 = vb.x1 + int(vw * 0.10)
        x2 = vb.x2 - int(vw * 0.10)
        b = BBox(x1, y1, x2, y2).clamp(w, h)
        return [PlateCandidate(bbox=b, conf=0.2)]


class UltralyticsPlateDetector(PlateDetector):
    def __init__(self, model_path: str, device="auto"):
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("ultralytics import edilemedi") from e
        self._model = YOLO(model_path)
        self._device = device

    def detect(self, frame_bgr: np.ndarray, vehicle_bbox: BBox) -> list[PlateCandidate]:
        h, w = frame_bgr.shape[:2]
        vb = vehicle_bbox.clamp(w, h)
        crop = frame_bgr[vb.y1 : vb.y2, vb.x1 : vb.x2]
        if crop.size == 0:
            return []
        # model RGB kullanabiliyor; ultralytics BGR ile de çalışıyor
        res = self._model.predict(source=crop, verbose=False, device=self._device)
        if not res:
            return []
        r0 = res[0]
        if r0.boxes is None or len(r0.boxes) == 0:
            return []
        out: list[PlateCandidate] = []
        for box in r0.boxes:
            conf = float(box.conf.item()) if box.conf is not None else 0.0
            xyxy = box.xyxy[0].tolist()
            x1, y1, x2, y2 = [int(v) for v in xyxy]
            bb = BBox(vb.x1 + x1, vb.y1 + y1, vb.x1 + x2, vb.y1 + y2).clamp(w, h)
            out.append(PlateCandidate(bbox=bb, conf=conf))
        out.sort(key=lambda c: c.conf, reverse=True)
        return out


def preprocess_for_ocr(plate_bgr: np.ndarray) -> np.ndarray:
    if plate_bgr.size == 0:
        return plate_bgr
    gray = cv2.cvtColor(plate_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    gray = cv2.equalizeHist(gray)
    thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5)
    return cv2.cvtColor(thr, cv2.COLOR_GRAY2BGR)
