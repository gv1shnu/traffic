from collections import defaultdict
from typing import Protocol

import numpy as np

from packages.shared.schemas import Candidate, Cause, CauseType, Congestion, Observation, Region
from packages.tracking.motion import center
from packages.vision.detector import VEHICLES


class CauseDetector(Protocol):
    def category(
        self, track: list[Observation], peers: list[Observation], cfg: dict
    ) -> CauseType | None: ...


class StationaryRoadUser:
    def category(
        self, track: list[Observation], peers: list[Observation], cfg: dict
    ) -> CauseType | None:
        if max(o.stationary_duration for o in track) < cfg["stationary_seconds"]:
            return None
        name = track[0].object_type
        if name in VEHICLES:
            return CauseType.stalled_vehicle
        if name == "person":
            return CauseType.pedestrian_obstruction
        if name in {"cow", "dog", "horse", "sheep", "elephant"}:
            return CauseType.animal_obstruction
        if name in {"debris", "barricade"}:
            return CauseType.road_debris if name == "debris" else CauseType.roadwork_or_barricade
        return None


DETECTORS: list[CauseDetector] = [StationaryRoadUser()]


def track_quality(rows: list[Observation]) -> float:
    """How reliably a subject was tracked: continuity times box stability.

    Continuity is the share of expected samples (at the track's own sampling
    interval) in which the track was present between its first and last sighting.
    Stability falls as the median frame-to-frame change in box area grows; a box
    that jumps in size usually means the track latched onto a different object.
    Detector confidence is deliberately excluded and reported separately.
    """
    ordered = sorted(rows, key=lambda o: o.timestamp)
    if len(ordered) < 2:
        return 0.0
    steps = np.diff([o.timestamp for o in ordered])
    step = float(np.median(steps[steps > 1e-6])) if np.any(steps > 1e-6) else 0.0
    if step <= 0:
        return 0.0
    span = ordered[-1].timestamp - ordered[0].timestamp
    continuity = min(1.0, len(ordered) / (round(span / step) + 1))
    areas = [max(1e-6, (o.bbox[2] - o.bbox[0]) * (o.bbox[3] - o.bbox[1])) for o in ordered]
    changes = [abs(b - a) / max(a, b) for a, b in zip(areas, areas[1:], strict=False)]
    stability = float(np.clip(1 - 2 * np.median(changes), 0, 1))
    return round(continuity * stability, 4)


def aggregate(scores: dict[str, float], cfg: dict) -> float:
    weights = cfg["weights"]
    value = sum(weights[k] * max(0, min(1, scores.get(k, 0))) for k in weights) / sum(
        weights.values()
    )
    # Corroboration gates prevent a good detector score from becoming a causal claim.
    if scores.get("temporal_precedence", 0) < 0.5 or scores.get("follower_response", 0) < 0.4:
        value = min(value, 0.49)
    return round(value, 4)


def rank_candidates(
    observations: list[Observation],
    incident: Congestion,
    regions: list[Region],
    cfg: dict,
    image_width: int = 720,
) -> list[Candidate]:
    if not incident.detected:
        return []
    start = incident.start_seconds or 0
    end = (incident.end_seconds or start) + 2
    grouped: dict[int, list[Observation]] = defaultdict(list)
    # Full track histories up to the end of the incident: when a subject stopped,
    # whether it was moving beforehand and how followers responded can predate
    # the confirmed onset by more than the candidate window.
    history: dict[int, list[Observation]] = defaultdict(list)
    for o in observations:
        if o.timestamp <= end:
            history[o.track_id].append(o)
        if start - 8 <= o.timestamp <= end:
            grouped[o.track_id].append(o)
    region = next((r for r in regions if r.id == incident.region), None)
    direction = np.array(region.direction if region else [0, -1], dtype=float)
    direction /= np.linalg.norm(direction)
    candidates = []
    for tid, rows in grouped.items():
        lane_rows = [o for o in rows if o.region == incident.region]
        if len(lane_rows) < 3:
            continue
        categories = [d.category(lane_rows, observations, cfg) for d in DETECTORS]
        category = next((c for c in categories if c is not None), None)
        if not category:
            continue
        stationary_rows = [
            o for o in lane_rows if o.stationary_duration >= cfg["stationary_seconds"]
        ]
        if not stationary_rows:
            continue
        first = stationary_rows[0]
        stopped_at = first.timestamp - first.stationary_duration
        had_motion = any(
            o.speed >= cfg["slow_speed"]
            and o.movement != "unmeasured"
            and o.timestamp < first.timestamp
            for o in history[tid]
        )
        precedence = float(had_motion and stopped_at < start - 0.3)
        # A subject already queued behind an earlier downstream stop is a follower,
        # even when it precedes the aggregate congestion threshold.
        prior_downstream = any(
            other_id != tid
            and any(
                p.region == incident.region
                and p.stationary_duration >= cfg["stationary_seconds"]
                and p.timestamp - p.stationary_duration < stopped_at - 0.1
                and abs(p.timestamp - first.timestamp) < 0.25
                and np.dot(center(p) - center(first), direction) > 0
                for p in other_rows
            )
            for other_id, other_rows in history.items()
        )
        if prior_downstream:
            precedence *= 0.25
        followers = 0
        upstream_stops = []
        for other_id, other_rows in history.items():
            if other_id == tid or other_rows[0].object_type not in VEHICLES:
                continue
            same_lane = [o for o in other_rows if o.region == incident.region]
            stopped = next(
                (
                    o
                    for o in same_lane
                    if o.stationary_duration >= 0.6
                    and o.timestamp > stopped_at + 0.3
                    and np.dot(center(o) - center(first), direction) < 0
                ),
                None,
            )
            was_moving = stopped and any(
                o.timestamp < stopped.timestamp
                and o.timestamp >= stopped_at - 2
                and o.speed >= cfg["slow_speed"]
                and o.movement != "unmeasured"
                for o in same_lane
            )
            if stopped is not None and was_moving:
                followers += 1
                upstream_stops.append(
                    (stopped.timestamp, -float(np.dot(center(stopped) - center(first), direction)))
                )
        propagation = 0.0
        if len(upstream_stops) >= 2:
            ordered = sorted(upstream_stops)
            propagation = sum(b[1] > a[1] for a, b in zip(ordered, ordered[1:], strict=False)) / (
                len(ordered) - 1
            )
        peers = [
            o
            for o in observations
            if abs(o.timestamp - first.timestamp) < 0.11
            and o.region == incident.region
            and o.object_type in VEHICLES
        ]
        downstream = sum(np.dot(center(o) - center(first), direction) <= 0 for o in peers) / max(
            1, len(peers)
        )
        adjacent = [
            o
            for o in observations
            if o.region not in {incident.region, "outside"}
            and start <= o.timestamp <= start + 3
            and o.object_type in VEHICLES
        ]
        scores = {
            "temporal_precedence": precedence,
            "spatial_proximity": float(downstream) if region else 0.3,
            "lane_blockage": min(
                1,
                (first.bbox[2] - first.bbox[0])
                / max(
                    1,
                    (max(p.x for p in region.polygon) - min(p.x for p in region.polygon))
                    * image_width,
                ),
            )
            if region
            else 0.2,
            "stationary_duration": min(1, max(o.stationary_duration for o in rows) / 8),
            "follower_response": min(1, followers / 3),
            "queue_propagation": propagation if region else min(0.3, propagation),
            "counterfactual": sum(o.speed >= cfg["slow_speed"] for o in adjacent)
            / max(1, len(adjacent)),
            "tracking_quality": track_quality(rows),
            "detection_confidence": float(np.mean([o.confidence for o in rows])),
        }
        confidence = aggregate(scores, cfg)
        if not region:
            confidence = min(confidence, 0.59)
        explanation = f"Track {tid} ({first.object_type}) was stationary from {stopped_at:.1f}s; {followers} upstream vehicle tracks subsequently slowed or stopped. Maximum stationary duration was {max(o.stationary_duration for o in rows):.1f}s. Congestion began at {start:.1f}s. This is a suspected cause; mechanical failure cannot be verified from motion alone."
        # Counter-evidence: when the adjacent lanes are also halted, a shared
        # control (such as a signal) explains the queue better than this subject.
        if len(adjacent) >= 3 and scores["counterfactual"] < 0.2:
            confidence = min(confidence, 0.49)
            explanation += " Adjacent lanes were also halted at the same time, which suggests a shared control such as a signal rather than this subject."
        candidates.append(
            Candidate(
                candidate_track_id=tid,
                cause_type=category,
                object_type=first.object_type,
                cause_confidence=confidence,
                first_relevant_timestamp=stopped_at,
                evidence_scores=scores,
                explanation=explanation,
            )
        )
    return sorted(candidates, key=lambda c: c.cause_confidence, reverse=True)[:10]


def select_cause(candidates: list[Candidate], cfg: dict) -> Cause:
    if not candidates or candidates[0].cause_confidence < cfg["cause_threshold"]:
        return Cause()
    top = candidates[0]
    quality = top.evidence_scores.get("tracking_quality", 1.0)
    min_quality = cfg.get("min_tracking_quality", 0.65)
    if quality < min_quality:
        # A reported suspect must clear every gate; weak tracking defers to review.
        return Cause(
            explanation=f"Track {top.candidate_track_id} ({top.object_type}) was the leading candidate, but its tracking quality ({quality:.2f}) is below the {min_quality:.2f} required for attribution; manual review is required."
        )
    if (
        len(candidates) > 1
        and top.cause_confidence - candidates[1].cause_confidence < cfg["cause_margin"]
    ):
        return Cause(
            explanation="The leading candidates have similar evidence scores; manual review is required."
        )
    return Cause(
        type=top.cause_type,
        confidence=top.cause_confidence,
        suspected_track_id=top.candidate_track_id,
        object_type=top.object_type,
        first_relevant_timestamp=top.first_relevant_timestamp,
        explanation=top.explanation,
        evidence_scores=top.evidence_scores,
    )
