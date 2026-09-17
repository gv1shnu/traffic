import numpy as np

from packages.shared.schemas import Cause, Congestion, Observation, Region
from packages.tracking.motion import center
from packages.vision.detector import VEHICLES


def build_timeline(
    observations: list[Observation],
    cause: Cause,
    congestion: Congestion,
    metrics: list[dict],
    regions: list[Region],
    cfg: dict,
) -> list[dict]:
    if not congestion.detected:
        return []
    markers: list[dict] = []
    selected = [o for o in observations if o.track_id == cause.suspected_track_id]
    onset = cause.first_relevant_timestamp
    if selected and onset is not None:
        abnormal = next(
            (o.timestamp for o in selected if o.movement == "slowing"),
            cause.first_relevant_timestamp,
        )
        markers.append({"label": "First abnormal movement", "timestamp": abnormal})
        markers.append({"label": "Suspected causal event", "timestamp": onset})
        origin = min(selected, key=lambda o: abs(o.timestamp - onset))
        region = next((r for r in regions if r.id == congestion.region), None)
        if region:
            direction = np.array(region.direction)
            first_moving: dict[int, float] = {}
            for previous in observations:
                if (
                    previous.timestamp >= onset - 2
                    and previous.speed >= cfg["slow_speed"]
                    and previous.movement != "unmeasured"
                ):
                    first_moving.setdefault(previous.track_id, previous.timestamp)
            slow_followers = [
                o.timestamp
                for o in observations
                if o.track_id != cause.suspected_track_id
                and o.object_type in VEHICLES
                and o.region == congestion.region
                and o.timestamp > onset
                and o.speed < cfg["slow_speed"]
                and o.movement != "unmeasured"
                and np.dot(center(o) - center(origin), direction) < 0
                and first_moving.get(o.track_id, float("inf")) < o.timestamp
            ]
            if slow_followers:
                markers.append(
                    {"label": "First follower slowdown", "timestamp": min(slow_followers)}
                )
    markers.append({"label": "Congestion began", "timestamp": congestion.start_seconds})
    region_metrics = [
        m
        for m in metrics
        if m["region"] == congestion.region
        and (congestion.start_seconds or 0) <= m["timestamp"] <= (congestion.end_seconds or 0)
    ]
    if region_metrics:
        reached = next((m for m in region_metrics if m.get("event_confirmed")), None)
        if reached:
            markers.append(
                {"label": "Congestion threshold reached", "timestamp": reached["timestamp"]}
            )
        peak = max(region_metrics, key=lambda m: m["queue_size"])
        markers.append({"label": "Peak congestion", "timestamp": peak["timestamp"]})
    # Only claim clearance if a later observed window actually shows flowing traffic.
    cleared = next(
        (
            m
            for m in metrics
            if m["region"] == congestion.region
            and m["timestamp"] > (congestion.end_seconds or 0)
            and m["median_motion"] >= cfg["slow_speed"]
            and m["slow_fraction"] < cfg["slow_fraction"]
        ),
        None,
    )
    markers.append(
        {
            "label": "Congestion cleared" if cleared else "Last observed congestion",
            "timestamp": cleared["timestamp"] if cleared else congestion.end_seconds,
        }
    )
    return sorted(markers, key=lambda m: m["timestamp"])
