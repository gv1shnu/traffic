import cv2
import numpy as np


def quality(frame: np.ndarray, bbox: tuple | None = None, detection_confidence: float = 1) -> float:
    h, w = frame.shape[:2]
    if bbox is not None:
        x1, y1, x2, y2 = [int(v) for v in bbox]
        crop = frame[max(0, y1) : min(h, y2), max(0, x1) : min(w, x2)]
        boundary = min(1.0, max(0, min(x1, y1, w - x2, h - y2)) / 15)
    else:
        crop, boundary = frame, 1.0
    if crop.size == 0:
        return 0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sharp = min(1, float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 250)
    exposure = 1 - abs(float(gray.mean()) - 128) / 128
    contrast = min(1, float(gray.std()) / 55)
    size = min(1, crop.shape[0] * crop.shape[1] / 15000)
    return round(
        float(
            0.3 * sharp
            + 0.15 * exposure
            + 0.1 * contrast
            + 0.2 * size
            + 0.15 * detection_confidence
            + 0.1 * boundary
        ),
        4,
    )
