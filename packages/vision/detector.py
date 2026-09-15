from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from packages.shared.config import settings
from packages.shared.schemas import Observation

ROAD_USERS = {
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "traffic light",
    "stop sign",
}
VEHICLES = {"bicycle", "car", "motorcycle", "bus", "truck", "autorickshaw"}


class DetectorTracker(Protocol):
    version: str

    def reset(self) -> None: ...
    def infer(self, frame: np.ndarray, timestamp: float, index: int) -> list[Observation]: ...


class YoloByteTrack:
    def __init__(self) -> None:
        from ultralytics import YOLO

        path = settings().model_path
        if not Path(path).is_file() and not settings().model_download_allowed:
            raise RuntimeError(
                "MODEL_MISSING: Run python scripts/download_models.py before starting the worker."
            )
        self.model = YOLO(path)
        import hashlib

        self.version = (
            f"{Path(path).name}:sha256:{hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]}"
        )
        self.reset()

    def reset(self) -> None:
        if getattr(self.model, "predictor", None) is not None:
            self.model.predictor = None

    def infer(self, frame: np.ndarray, timestamp: float, index: int) -> list[Observation]:
        device = settings().device
        result = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            verbose=False,
            conf=0.15,
            imgsz=960,
            device=None if device == "auto" else device,
        )[0]
        boxes: Any = result.boxes
        if boxes is None or boxes.id is None:
            return []
        observations = []
        for bbox, cls, confidence, track_id in zip(
            boxes.xyxy.cpu().tolist(),
            boxes.cls.cpu().tolist(),
            boxes.conf.cpu().tolist(),
            boxes.id.cpu().tolist(),
            strict=True,
        ):
            name = result.names[int(cls)]
            if name in ROAD_USERS:
                observations.append(
                    Observation(
                        track_id=int(track_id),
                        object_type=name,
                        bbox=tuple(bbox),
                        confidence=confidence,
                        timestamp=timestamp,
                        frame_index=index,
                    )
                )
        return observations


@lru_cache(maxsize=1)
def detector() -> YoloByteTrack:
    return YoloByteTrack()
