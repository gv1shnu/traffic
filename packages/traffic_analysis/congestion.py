from collections import defaultdict

import cv2
import numpy as np

from packages.shared.schemas import Congestion, Observation, Region
from packages.vision.detector import VEHICLES


def detect_congestion(
    observations: list[Observation], regions: list[Region], width: int, height: int, cfg: dict
) -> tuple[Congestion, list[dict]]:
    grouped: dict[tuple[float, str], list[Observation]] = defaultdict(list)
    for o in observations:
        if o.object_type in VEHICLES and o.region != "outside":
            grouped[(o.timestamp, o.region)].append(o)
    metrics = []
    windows: dict[str, list[dict]] = defaultdict(list)
    events: list[Congestion] = []
    active: dict[str, Congestion] = {}
    for (timestamp, region_id), rows in sorted(grouped.items()):
        region = next((r for r in regions if r.id == region_id), None)
        # A small occupancy raster computes union area rather than double-counting overlaps.
        mask = np.zeros((90, 160), dtype=np.uint8)
        road = np.ones_like(mask)
        if region:
            road[:] = 0
            cv2.fillPoly(
                road, [np.array([[p.x * 159, p.y * 89] for p in region.polygon], np.int32)], 1
            )
        for row in rows:
            x1, y1, x2, y2 = row.bbox
            cv2.rectangle(
                mask,
                (int(x1 / width * 159), int(y1 / height * 89)),
                (int(x2 / width * 159), int(y2 / height * 89)),
                1,
                -1,
            )
        occupancy = float(np.sum(mask * road) / max(1, np.sum(road)))
        slow = sum(o.speed < cfg["slow_speed"] for o in rows)
        median = float(np.median([o.speed for o in rows]))
        metric = {
            "timestamp": timestamp,
            "region": region_id,
            "vehicle_count": len(rows),
            "queue_size": slow,
            "slow_fraction": slow / len(rows),
            "median_motion": median,
            "occupancy": occupancy,
        }
        metrics.append(metric)
        window = windows[region_id]
        if window and timestamp - window[-1]["timestamp"] > 1:
            window.clear()
            active.pop(region_id, None)
        window.append(metric)
        previous = [
            m for m in window if timestamp - m["timestamp"] <= cfg["persistence_seconds"] * 3
        ]
        windows[region_id] = previous
        baseline = min(m["queue_size"] for m in previous)
        qualifying = (
            len(rows) >= cfg["min_vehicles"]
            and median < cfg["slow_speed"]
            and metric["slow_fraction"] >= cfg["slow_fraction"]
            and occupancy >= cfg["min_occupancy"]
        )
        metric["qualifying"] = qualifying
        if not qualifying:
            active.pop(region_id, None)
            continue
        run = []
        for m in reversed(previous):
            if not m["qualifying"]:
                break
            run.append(m)
        persistence = timestamp - run[-1]["timestamp"]
        growth = slow - baseline >= cfg["queue_growth"]
        # An already congested clip can be detected, but attribution will lack precedence.
        dense_at_start = persistence >= cfg["persistence_seconds"] * 2
        if persistence >= cfg["persistence_seconds"] and (growth or dense_at_start):
            severity = min(
                1.0,
                0.45 * metric["slow_fraction"]
                + 0.3 * min(1, slow / 15)
                + 0.25 * min(1, occupancy / 0.4),
            )
            if region_id not in active:
                event = Congestion(
                    detected=True,
                    start_seconds=run[-1]["timestamp"],
                    end_seconds=timestamp,
                    region=region_id,
                    severity=severity,
                    peak_queue_size=slow,
                )
                events.append(event)
                active[region_id] = event
            else:
                event = active[region_id]
                event.end_seconds = timestamp
                event.peak_queue_size = max(event.peak_queue_size, slow)
                event.severity = max(event.severity, severity)
    return max(events, key=lambda e: e.severity, default=Congestion()), metrics
