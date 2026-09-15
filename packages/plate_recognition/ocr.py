import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from packages.shared.config import settings
from packages.shared.schemas import Plate
from packages.vision.quality import quality


class OCR(Protocol):
    def read(self, image: np.ndarray) -> list[dict]: ...


class EasyOCREngine:
    def __init__(self):
        import easyocr
        from ultralytics import YOLO

        path = Path(settings().plate_model_path)
        if not path.is_file():
            raise FileNotFoundError("Plate model missing. Run scripts/download_models.py --ocr.")
        self.plate_detector = YOLO(str(path))
        self.reader = easyocr.Reader(
            ["en"],
            gpu=settings().device.startswith("cuda"),
            model_storage_directory="models/ocr",
            download_enabled=settings().model_download_allowed,
        )
        import hashlib

        self.version = (
            f"YOLOv8 plate:{hashlib.sha256(path.read_bytes()).hexdigest()[:16]} / EasyOCR"
        )

    def read(self, image: np.ndarray) -> list[dict]:
        device = settings().device
        predictions: Any = self.plate_detector.predict(
            image,
            verbose=False,
            conf=0.25,
            device=None if device == "auto" else device,
        )
        boxes: Any = predictions[0].boxes
        results: list[dict] = []
        if boxes is None:
            return results
        for bbox, confidence in zip(
            boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(), strict=True
        ):
            x1, y1, x2, y2 = [max(0, int(v)) for v in bbox]
            crop = image[y1:y2, x1:x2]
            if crop.size == 0 or crop.shape[1] < 48 or crop.shape[0] < 12:
                continue
            score = quality(image, (x1, y1, x2, y2), float(confidence))
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4)).apply(gray)
            enlarged = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            words = self.reader.readtext(
                enlarged,
                detail=1,
                paragraph=False,
                allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                min_size=8,
            )
            if not words:
                continue
            # Preserve spatial reading order, including two-line Indian plates.
            words = sorted(
                words,
                key=lambda item: (
                    round(min(p[1] for p in item[0]) / max(1, enlarged.shape[0] / 2)),
                    min(p[0] for p in item[0]),
                ),
            )
            results.append(
                {
                    "raw_text": "".join(word[1] for word in words),
                    "confidence": min(float(word[2]) for word in words),
                    "bbox": [x1, y1, x2, y2],
                    "detection_confidence": float(confidence),
                    "quality": score,
                }
            )
        return results


@lru_cache(maxsize=1)
def ocr_engine() -> EasyOCREngine:
    return EasyOCREngine()


def consensus(readings: list[dict], cfg: dict) -> Plate:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in readings:
        normalized = re.sub(r"[^A-Z0-9]", "", r["raw_text"].upper())
        r["normalized_text"] = normalized
        if any(re.fullmatch(p, normalized) for p in cfg["plate_patterns"]):
            grouped[normalized].append(r)
    if not grouped:
        return Plate(raw_readings=readings)
    text, group = max(grouped.items(), key=lambda kv: len({r["timestamp"] for r in kv[1]}))
    accepted = [
        r
        for r in group
        if r["confidence"] >= cfg["plate_ocr_threshold"]
        and r["detection_confidence"] >= cfg["plate_detection_threshold"]
        and r["quality"] >= cfg["plate_quality_threshold"]
    ]
    distinct_frames = len({r["timestamp"] for r in accepted})
    agreement = len({r["timestamp"] for r in group}) / max(
        1, len({r["timestamp"] for r in readings})
    )
    conf = float(np.mean([r["confidence"] for r in group])) * agreement
    exceptional = any(
        r["confidence"] >= 0.98 and r["quality"] >= 0.9 and r["detection_confidence"] >= 0.95
        for r in accepted
    )
    if (distinct_frames >= 2 or exceptional) and agreement >= 0.7:
        return Plate(status="recognized", text=text, confidence=conf, raw_readings=readings)
    return Plate(confidence=min(conf, 0.59), raw_readings=readings)
