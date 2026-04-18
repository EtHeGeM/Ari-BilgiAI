from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np


_ALNUM = re.compile(r"[^A-Z0-9]+")


def normalize_plate(text: str) -> str:
    text = (text or "").upper()
    text = _ALNUM.sub("", text)
    return text


def looks_like_tr_plate(text: str) -> bool:
    # Basit TR format kontrolü: 2 rakam + 1-3 harf + 2-4 rakam
    return bool(re.fullmatch(r"\d{2}[A-Z]{1,3}\d{2,4}", text))


@dataclass(frozen=True)
class OcrResult:
    text: str
    conf: float


class OcrEngine:
    def read(self, image_bgr: np.ndarray) -> list[OcrResult]:
        raise NotImplementedError


class NoOcr(OcrEngine):
    def read(self, image_bgr: np.ndarray) -> list[OcrResult]:
        return []


class EasyOcrEngine(OcrEngine):
    def __init__(self, langs: list[str], *, gpu: bool = False):
        try:
            import easyocr  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("easyocr yüklü değil. `pip install -e .[ocr_easyocr]`") from e

        self._reader = easyocr.Reader(langs, gpu=bool(gpu))

    def read(self, image_bgr: np.ndarray) -> list[OcrResult]:
        # easyocr RGB bekliyor
        image_rgb = image_bgr[:, :, ::-1]
        results = self._reader.readtext(image_rgb, detail=1, paragraph=False)
        out: list[OcrResult] = []
        for _bbox, text, conf in results:
            t = normalize_plate(text)
            if not t:
                continue
            out.append(OcrResult(text=t, conf=float(conf)))
        out.sort(key=lambda r: r.conf, reverse=True)
        return out


class TesseractOcrEngine(OcrEngine):
    def __init__(self):
        try:
            import pytesseract  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("pytesseract yüklü değil. `pip install -e .[ocr_tesseract]`") from e
        self._pytesseract = pytesseract

    def read(self, image_bgr: np.ndarray) -> list[OcrResult]:
        # Basit bir tesseract çağrısı
        config = "--oem 1 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        text = self._pytesseract.image_to_string(image_bgr, config=config)
        t = normalize_plate(text)
        if not t:
            return []
        return [OcrResult(text=t, conf=0.5)]


def _cuda_available() -> bool:
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def build_ocr_engine(engine: str, langs: list[str], *, ocr_gpu: str = "auto") -> OcrEngine:
    if engine == "none":
        return NoOcr()
    if engine == "easyocr":
        if ocr_gpu == "auto":
            use_gpu = _cuda_available()
        elif ocr_gpu == "on":
            if not _cuda_available():
                raise RuntimeError(
                    "EasyOCR GPU istendi ama torch.cuda.is_available() = False (CUDA'lı PyTorch kurulu değil)."
                )
            use_gpu = True
        elif ocr_gpu == "off":
            use_gpu = False
        else:
            raise ValueError(f"Unknown ocr_gpu: {ocr_gpu}")
        return EasyOcrEngine(langs or ["en"], gpu=use_gpu)
    if engine == "tesseract":
        return TesseractOcrEngine()
    raise ValueError(f"Unknown ocr engine: {engine}")
