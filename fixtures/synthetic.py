"""Synthetic test observations only. Never used by the production detector."""

import cv2
import numpy as np

from packages.shared.schemas import Observation, Region


def road() -> list[Region]:
    return [
        Region(
            id="lane_1",
            name="Main road",
            polygon=[
                {"x": 0.2, "y": 0.02},
                {"x": 0.6, "y": 0.02},
                {"x": 0.6, "y": 0.98},
                {"x": 0.2, "y": 0.98},
            ],
            direction=(0, -1),
        ),
        Region(
            id="lane_2",
            name="Adjacent road",
            polygon=[
                {"x": 0.65, "y": 0.02},
                {"x": 0.98, "y": 0.02},
                {"x": 0.98, "y": 0.98},
                {"x": 0.65, "y": 0.98},
            ],
            direction=(0, -1),
        ),
    ]


def trajectories(scenario: str = "queue", duration: float = 18) -> list[Observation]:
    rows = []
    for tick in range(int(duration * 5)):
        t = tick / 5
        for i in range(5):
            stop = 4 + i * 1.6
            y = 85 + i * 85 + max(0, stop - t) * 18
            if scenario in {"flow", "no_congestion"}:
                y = 600 - ((t * 22 + i * 95) % 590)
            if scenario == "unknown":
                y = 120 + i * 85
            if scenario == "sparse" and i > 0:
                continue
            if scenario == "pedestrian" and i == 0:
                name, width = "person", 30
            else:
                name, width = "car", 65
            rows.append(
                Observation(
                    track_id=i + 1,
                    object_type=name,
                    bbox=(260 - width / 2, y, 260 + width / 2, y + 65),
                    confidence=0.96,
                    timestamp=t,
                    frame_index=tick * 2,
                )
            )
        if scenario != "sparse":
            y2 = 580 - (t * 24 % 570)
            rows.append(
                Observation(
                    track_id=99,
                    object_type="motorcycle",
                    bbox=(540, y2, 580, y2 + 60),
                    confidence=0.92,
                    timestamp=t,
                    frame_index=tick * 2,
                )
            )
    return rows


def make_video(path, duration=3, scenario="flow"):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (720, 720))
    rows = trajectories(scenario, duration)
    try:
        for i in range(int(duration * 10)):
            image = np.full((720, 720, 3), 80, dtype=np.uint8)
            for y in range(0, 720, 80):
                cv2.line(image, (460, y), (460, y + 40), (200, 200, 200), 2)
            cv2.putText(
                image,
                "SYNTHETIC TEST FIXTURE",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (220, 220, 220),
                1,
            )
            for o in rows:
                if o.frame_index == i - i % 2:
                    x1, y1, x2, y2 = map(int, o.bbox)
                    cv2.rectangle(image, (x1, y1), (x2, y2), (155, 185, 170), -1)
                    cv2.rectangle(image, (x1 + 5, y1 + 12), (x2 - 5, y1 + 25), (50, 60, 55), -1)
            writer.write(image)
    finally:
        writer.release()
