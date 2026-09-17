"""Kinematic traffic simulator for reasoning-layer evaluation only.

This module generates labelled synthetic scenarios with perfect ground truth
(true cause, onset time, suspect track) by running a lightweight car-following
model. It is used exclusively by evaluation scripts and tests to measure the
congestion/attribution logic against known answers. It is never imported by the
investigation pipeline and never substitutes for real detection.

It does not model real appearance, lighting, occlusion or plate imagery, so it
validates the reasoning layer, not perception. Real detection precision/recall
and plate accuracy still require real footage.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.shared.schemas import Observation, Region

FPS = 5.0
DT = 1.0 / FPS
IMAGE = 720
MIN_VEHICLES = 4  # matches config/analysis.json; used only to time the onset label


@dataclass
class Agent:
    track_id: int
    object_type: str
    axis: str  # "y" = vertical lane (moves up), "x" = horizontal lane (moves left)
    pos: float  # position along the travel axis, in pixels (vehicles move toward 0)
    cross: float  # fixed lane-centre position on the cross axis, in pixels
    length: float  # extent along the travel axis
    width: float  # extent across the travel axis
    v_desired: float  # free-flow speed in px/s (0 keeps it parked from t=0)
    v: float = 0.0
    stop_at: float | None = None  # time at which this agent stalls
    release_at: float | None = None  # time a temporarily stopped agent resumes
    stalled: bool = False

    def bbox(self) -> tuple[float, float, float, float]:
        if self.axis == "y":
            return (
                self.cross - self.width / 2,
                self.pos,
                self.cross + self.width / 2,
                self.pos + self.length,
            )
        return (
            self.pos,
            self.cross - self.width / 2,
            self.pos + self.length,
            self.cross + self.width / 2,
        )


@dataclass
class GroundTruth:
    congestion: bool
    cause_type: str | None  # None => no attributable subject (expected "unknown")
    suspect_track: int | None
    note: str
    onset_seconds: float | None = None  # measured from kinematics during the run


@dataclass
class Scenario:
    name: str
    agents: list[Agent]
    regions: list[Region]
    duration: float
    incident_region: str
    truth: GroundTruth


def _region_of(agent: Agent, regions: list[Region], incident_region: str) -> bool:
    region = next((r for r in regions if r.id == incident_region), None)
    if region is None:
        return True
    x1, y1, x2, y2 = agent.bbox()
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    xs = [p.x * IMAGE for p in region.polygon]
    ys = [p.y * IMAGE for p in region.polygon]
    return min(xs) <= cx <= max(xs) and min(ys) <= cy <= max(ys)


def _advance(agents: list[Agent], t: float) -> None:
    # The lane front is the smallest travel-axis position; agents move toward 0
    # and hold a safe gap behind their leader (a simple car-following rule).
    ordered = sorted(agents, key=lambda a: a.pos)
    safe_gap = 22.0
    for i, a in enumerate(ordered):
        if a.stop_at is not None and t >= a.stop_at:
            a.stalled = a.release_at is None or t < a.release_at
        if a.stalled:
            a.v = 0.0
            continue
        target = a.v_desired
        if i > 0:
            leader = ordered[i - 1]
            gap = a.pos - (leader.pos + leader.length)
            if gap < safe_gap:
                target = 0.0
            elif gap < 2 * safe_gap:
                target = a.v_desired * (gap - safe_gap) / safe_gap
        a.v += max(-140.0 * DT, min(28.0 * DT, target - a.v))
        a.v = max(0.0, a.v)
        a.pos -= a.v * DT


def run(scenario: Scenario) -> tuple[list[Observation], GroundTruth]:
    """Simulate a scenario, returning observations and ground truth with a
    kinematically-measured congestion onset time."""
    agents = [Agent(**a.__dict__) for a in scenario.agents]
    rows: list[Observation] = []
    stationary_since: dict[int, float | None] = {a.track_id: None for a in agents}
    onset: float | None = None
    steps = int(round(scenario.duration * FPS))
    for step in range(steps):
        t = round(step * DT, 3)
        _advance(agents, t)
        stationary = 0
        for a in agents:
            rows.append(
                Observation(
                    track_id=a.track_id,
                    object_type=a.object_type,
                    bbox=a.bbox(),
                    confidence=0.95,
                    timestamp=t,
                    frame_index=step,
                )
            )
            in_region = _region_of(a, scenario.regions, scenario.incident_region)
            if a.v < 3.0 and in_region:
                since = stationary_since[a.track_id]
                if since is None:
                    since = t
                    stationary_since[a.track_id] = t
                if t - since >= 1.0:
                    stationary += 1
            else:
                stationary_since[a.track_id] = None
        if onset is None and stationary >= MIN_VEHICLES:
            onset = t
    truth = GroundTruth(**{**scenario.truth.__dict__, "onset_seconds": onset})
    return rows, truth
