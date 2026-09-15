from collections import defaultdict

import cv2
import numpy as np

from packages.shared.schemas import Observation, Region


def center(o: Observation) -> np.ndarray:
    x1, y1, x2, y2 = o.bbox
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2])


def calculate_motion(
    observations: list[Observation], regions: list[Region], width: int, height: int, cfg: dict
) -> list[Observation]:
    history: dict[int, list[Observation]] = defaultdict(list)
    stationary: dict[int, float] = {}
    for o in sorted(observations, key=lambda x: (x.timestamp, x.track_id)):
        pt = center(o)
        region = next(
            (
                r
                for r in regions
                if cv2.pointPolygonTest(
                    np.array([[p.x * width, p.y * height] for p in r.polygon], np.float32),
                    tuple(pt),
                    False,
                )
                >= 0
            ),
            None,
        )
        o.region = region.id if region else ("outside" if regions else "whole_road")
        past = history[o.track_id]
        # A one-second baseline limits box jitter without assuming calibrated road speeds.
        window = [p for p in past if 0 < o.timestamp - p.timestamp <= 1.2]
        if window:
            prev = window[0]
            dt = o.timestamp - prev.timestamp
            scale = max(10.0, (o.bbox[3] - o.bbox[1] + o.bbox[2] - o.bbox[0]) / 2)
            velocity = float(np.linalg.norm(pt - center(prev)) / dt)
            o.speed = velocity / scale
            if region and region.meters_per_pixel:
                o.kmh = velocity * region.meters_per_pixel * 3.6
            if o.speed <= cfg["stationary_speed"]:
                stationary.setdefault(o.track_id, prev.timestamp)
                o.stationary_duration = o.timestamp - stationary[o.track_id]
                o.movement = "stationary"
            else:
                stationary.pop(o.track_id, None)
                o.movement = (
                    "nearly_stationary" if o.speed < cfg["slow_speed"] else "moving_normally"
                )
                if (
                    len(past) > 1
                    and past[-1].speed > o.speed * 1.6
                    and o.speed >= cfg["slow_speed"]
                ):
                    o.movement = "slowing"
        else:
            # No movement evidence exists for a first detection or a long occlusion.
            o.speed = cfg["slow_speed"] * 2
            o.movement = "unmeasured"
            stationary.pop(o.track_id, None)
        past.append(o)
    return observations


def summarize_tracks(observations: list[Observation]) -> list[dict]:
    grouped: dict[int, list[Observation]] = defaultdict(list)
    for o in observations:
        grouped[o.track_id].append(o)
    return [
        {
            "track_id": tid,
            "object_type": rows[0].object_type,
            "first_timestamp": rows[0].timestamp,
            "last_timestamp": rows[-1].timestamp,
            "region": rows[-1].region,
            "tracking_confidence": float(np.mean([o.confidence for o in rows])),
            "stationary_duration": max(o.stationary_duration for o in rows),
            "movement_summary": {
                "median_relative_speed": float(np.median([o.speed for o in rows])),
                "unit": "box_lengths/second",
            },
            "observations": [o.model_dump() for o in rows],
        }
        for tid, rows in grouped.items()
    ]
