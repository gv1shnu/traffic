"""Microscopic traffic simulation in world coordinates for 3D rendered scenes.

The road is a two-way, two-lane urban street with footpaths, aligned with the
world Y axis. Traffic keeps left (Indian convention): the near lane at negative
X travels away from the camera (+Y); the far lane at positive X carries oncoming
traffic (-Y). Vehicles follow the Intelligent Driver Model (IDM) behind whatever
is ahead of them in their lane: another vehicle, a stalled subject, a pedestrian
standing in the carriageway or a red signal's stop line.

Ground truth (the scripted cause subject, its stop time and the measured queue
onset) is known by construction and exported alongside the trajectories.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any

LANE_WIDTH = 3.5
NEAR_X = -LANE_WIDTH / 2  # travels +Y, away from the camera
FAR_X = LANE_WIDTH / 2  # oncoming, travels -Y
FOOTPATH_X = 4.9  # footpath centre line, both sides
SPAWN_Y = -45.0
END_Y = 190.0
VISIBLE_Y = (0.0, 75.0)  # approximate range the CCTV camera sees well

SIM_DT = 0.05


@dataclass(frozen=True)
class Kind:
    length: float
    width: float
    height: float
    v_desired: float  # m/s
    accel: float  # m/s^2


KINDS: dict[str, Kind] = {
    "car": Kind(4.2, 1.75, 1.5, 11.0, 1.6),
    "autorickshaw": Kind(2.9, 1.35, 1.75, 8.5, 1.2),
    "motorcycle": Kind(2.0, 0.75, 1.45, 11.5, 2.0),
    "bus": Kind(11.0, 2.55, 3.2, 9.0, 0.9),
    "truck": Kind(7.5, 2.4, 3.1, 8.5, 0.9),
    "person": Kind(0.5, 0.5, 1.7, 1.3, 1.0),
}

# Indian urban mix by approximate share of arrivals.
DEFAULT_MIX = {"car": 0.38, "motorcycle": 0.3, "autorickshaw": 0.2, "bus": 0.06, "truck": 0.06}

IDM_S0 = 1.6  # jam gap, metres (dense Indian queues)
IDM_T = 1.0  # time headway, seconds
IDM_B = 2.6  # comfortable deceleration


@dataclass
class Agent:
    id: int
    kind: str
    lane: str  # "near", "far", "footpath_left", "footpath_right", "crossing"
    s: float  # travel-direction coordinate; world Y for near lane
    lateral: float  # world X
    color: int  # palette index chosen by the renderer
    spawn_time: float
    v: float = 0.0
    odometer: float = 0.0
    active: bool = False
    done: bool = False
    stop_at_y: float | None = None  # scripted stall: brake to a stop here
    stop_after: float | None = None  # ... once this time has passed
    stalled: bool = False
    stalled_since: float | None = None
    plate: str = ""
    # pedestrian crossing script
    walk_to_x: float | None = None
    walk_after: float | None = None

    @property
    def spec(self) -> Kind:
        return KINDS[self.kind]

    def world(self) -> tuple[float, float, float]:
        """World (x, y, heading) of the agent's footprint centre."""
        if self.lane == "far":
            return self.lateral, END_Y + SPAWN_Y - self.s, math.pi
        if self.lane == "crossing":
            return self.lateral, self.s, -math.pi / 2
        if self.lane == "footpath_right":
            return self.lateral, END_Y + SPAWN_Y - self.s, math.pi
        return self.lateral, self.s, 0.0


@dataclass
class Signal:
    stop_line_y: float
    red_from: float
    red_until: float


@dataclass
class Scenario3D:
    name: str
    title: str
    duration: float
    seed: int
    near_rate: float  # arrivals per second, near lane
    far_rate: float
    footpath_rate: float
    cause_kind: str | None  # scripted cause subject kind, None for no cause
    cause_type: str | None  # taxonomy label expected from attribution
    cause_spawn: float = 0.0
    cause_stop_y: float = 40.0
    cause_stop_after: float = 0.0
    signal: Signal | None = None
    crossing_pedestrian: bool = False
    mix: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_MIX))
    note: str = ""
    preroll: float = 15.0  # warm-up so the clip opens on established traffic


@dataclass
class Truth:
    congestion: bool
    cause_type: str | None
    cause_agent: int | None
    cause_stop_time: float | None
    onset_seconds: float | None
    note: str


@dataclass
class Frame:
    t: float
    agents: list[dict[str, Any]]
    signal_red: bool | None


def _plate(rng: random.Random) -> str:
    states = ["KA", "MH", "TN", "DL", "TS", "KL"]
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return (
        f"{rng.choice(states)} {rng.randint(1, 60):02d} "
        f"{rng.choice(letters)}{rng.choice(letters)} {rng.randint(1000, 9999)}"
    )


def _arrivals(
    rng: random.Random, rate: float, start: float, duration: float, mix: dict[str, float]
):
    t = start + (rng.uniform(0.0, 1.0 / rate) if rate > 0 else duration - start)
    kinds, weights = zip(*mix.items(), strict=True)
    out = []
    while t < duration:
        out.append((t, rng.choices(kinds, weights)[0]))
        t += max(0.6, rng.expovariate(rate))
    return out


class Simulation:
    def __init__(self, scenario: Scenario3D):
        self.sc = scenario
        self.rng = random.Random(scenario.seed)
        # The clock reads zero at the first recorded frame; warm-up is negative.
        self.t = -scenario.preroll
        self.agents: list[Agent] = []
        self.pending: list[Agent] = []
        self.cause_id: int | None = None
        self._next_id = 1
        self._schedule()

    def _new(self, kind: str, lane: str, spawn: float, lateral: float) -> Agent:
        agent = Agent(
            id=self._next_id,
            kind=kind,
            lane=lane,
            s=SPAWN_Y,
            lateral=lateral,
            color=self.rng.randrange(1_000_000),
            spawn_time=spawn,
            plate=_plate(self.rng) if kind not in {"person"} else "",
        )
        self._next_id += 1
        return agent

    def _jitter(self, kind: str) -> float:
        spread = {"motorcycle": 0.75, "autorickshaw": 0.45, "car": 0.25}.get(kind, 0.1)
        return self.rng.uniform(-spread, spread)

    def _schedule(self) -> None:
        sc = self.sc
        for lane, rate, x in (("near", sc.near_rate, NEAR_X), ("far", sc.far_rate, FAR_X)):
            for spawn, kind in _arrivals(self.rng, rate, -sc.preroll, sc.duration, sc.mix):
                self.pending.append(self._new(kind, lane, spawn, x + self._jitter(kind)))
        for lane, x in (("footpath_left", -FOOTPATH_X), ("footpath_right", FOOTPATH_X)):
            for spawn, _ in _arrivals(
                self.rng, sc.footpath_rate, -sc.preroll, sc.duration, {"person": 1}
            ):
                p = self._new("person", lane, spawn, x + self.rng.uniform(-0.6, 0.6))
                p.s = SPAWN_Y + 25
                self.pending.append(p)
        if sc.cause_kind is not None and sc.cause_kind != "person":
            cause = self._new(sc.cause_kind, "near", sc.cause_spawn, NEAR_X)
            cause.stop_at_y = sc.cause_stop_y
            cause.stop_after = sc.cause_stop_after
            self.pending.append(cause)
            self.cause_id = cause.id
        if sc.crossing_pedestrian:
            ped = self._new("person", "crossing", sc.cause_spawn, -FOOTPATH_X)
            ped.s = sc.cause_stop_y
            ped.walk_to_x = NEAR_X + 0.2
            ped.walk_after = sc.cause_stop_after
            self.pending.append(ped)
            self.cause_id = ped.id
        self.pending.sort(key=lambda a: a.spawn_time)

    # -- dynamics ---------------------------------------------------------
    def _lane_queue(self, lane: str) -> list[Agent]:
        return sorted((a for a in self.agents if a.active and a.lane == lane), key=lambda a: -a.s)

    def _obstacles_near(self) -> list[tuple[float, float]]:
        """Static obstacles in the near lane as (rear_s, speed) pairs."""
        out = []
        for a in self.agents:
            if a.active and a.lane == "crossing" and a.lateral > -3.4:
                out.append((a.s - 0.4, 0.0))
        sig = self.sc.signal
        if sig is not None and sig.red_from <= self.t < sig.red_until:
            out.append((sig.stop_line_y, 0.0))
        return out

    def _spawn(self) -> None:
        still = []
        for a in self.pending:
            if a.spawn_time > self.t:
                still.append(a)
                continue
            if a.lane in ("near", "far"):
                queue = self._lane_queue(a.lane)
                last = queue[-1] if queue else None
                if last is not None and last.s - last.spec.length - a.spec.length - 2.0 < SPAWN_Y:
                    still.append(a)  # entry blocked by spillback; wait
                    continue
                a.v = a.spec.v_desired * 0.8
            a.active = True
            self.agents.append(a)
        self.pending = still

    def _idm(self, a: Agent, gap: float, lead_v: float) -> float:
        k = a.spec
        dv = a.v - lead_v
        s_star = IDM_S0 + max(0.0, a.v * IDM_T + a.v * dv / (2 * math.sqrt(k.accel * IDM_B)))
        gap = max(gap, 0.05)
        return k.accel * (1 - (a.v / k.v_desired) ** 4 - (s_star / gap) ** 2)

    def step(self) -> None:
        dt = SIM_DT
        self._spawn()
        for lane in ("near", "far"):
            queue = self._lane_queue(lane)
            obstacles = self._obstacles_near() if lane == "near" else []
            for i, a in enumerate(queue):
                if a.stop_at_y is not None and self.t >= (a.stop_after or 0.0) and not a.stalled:
                    remaining = a.stop_at_y - a.s
                    if remaining <= 0.3 or (remaining < 30 and a.v < 0.3):
                        a.stalled, a.v = True, 0.0
                        a.stalled_since = self.t
                if a.stalled:
                    continue
                gap, lead_v = 1e9, a.spec.v_desired
                if i > 0:
                    lead = queue[i - 1]
                    gap = (lead.s - lead.spec.length / 2) - (a.s + a.spec.length / 2)
                    lead_v = lead.v
                front = a.s + a.spec.length / 2
                for rear, v in obstacles:
                    # Commit through a signal if already too close to stop comfortably.
                    braking = a.v * a.v / (2 * IDM_B * 1.6)
                    if rear >= front and rear - front < gap and rear - front > braking * 0.4:
                        gap, lead_v = rear - front, v
                if a.stop_at_y is not None and self.t >= (a.stop_after or 0.0):
                    target = a.stop_at_y - a.s
                    if 0 < target < gap:
                        gap, lead_v = target + IDM_S0, 0.0
                acc = max(-8.0, min(a.spec.accel, self._idm(a, gap, lead_v)))
                a.v = max(0.0, a.v + acc * dt)
                a.s += a.v * dt
                a.odometer += a.v * dt
                if a.s > END_Y:
                    a.active, a.done = False, True
        for a in self.agents:
            if not a.active:
                continue
            if a.lane.startswith("footpath"):
                a.v = a.spec.v_desired
                a.s += a.v * dt
                a.odometer += a.v * dt
                if a.s > END_Y:
                    a.active, a.done = False, True
            elif a.lane == "crossing" and a.walk_to_x is not None:
                if self.t >= (a.walk_after or 0.0) and a.lateral < a.walk_to_x:
                    a.v = a.spec.v_desired
                    a.lateral = min(a.walk_to_x, a.lateral + a.v * dt)
                    a.odometer += a.v * dt
                else:
                    if a.v > 0 and a.stalled_since is None:
                        a.stalled_since = self.t
                    a.v = 0.0
        self.t += dt

    def snapshot(self) -> Frame:
        sig = self.sc.signal
        rows = []
        for a in self.agents:
            if not a.active:
                continue
            x, y, heading = a.world()
            rows.append(
                {
                    "id": a.id,
                    "kind": a.kind,
                    "x": round(x, 4),
                    "y": round(y, 4),
                    "heading": round(heading, 5),
                    "speed": round(a.v, 4),
                    "odometer": round(a.odometer, 4),
                    "color": a.color,
                    "plate": a.plate,
                    "walking": a.kind == "person" and a.v > 0.05,
                }
            )
        red = None if sig is None else bool(sig.red_from <= self.t < sig.red_until)
        return Frame(t=round(self.t, 4), agents=rows, signal_red=red)


def run(scenario: Scenario3D, fps: float = 10.0) -> tuple[list[Frame], Truth]:
    """Simulate the scenario and sample frames at ``fps``."""
    sim = Simulation(scenario)
    frames: list[Frame] = []
    every = max(1, round(1.0 / (fps * SIM_DT)))
    stationary_since: dict[int, float] = {}
    onset: float | None = None
    pre = int(round(scenario.preroll / SIM_DT))
    steps = pre + int(round(scenario.duration / SIM_DT))
    for step in range(steps):
        if step >= pre and (step - pre) % every == 0:
            frames.append(sim.snapshot())
        sim.step()
        # Queue onset label: >= 4 visible near-lane vehicles (excluding the
        # cause) held below walking pace for at least a second.
        count = 0
        for a in sim.agents:
            if not a.active or a.lane != "near" or a.id == sim.cause_id:
                continue
            if a.v < 0.5 and VISIBLE_Y[0] <= a.s <= VISIBLE_Y[1]:
                since = stationary_since.setdefault(a.id, sim.t)
                if sim.t - since >= 1.0:
                    count += 1
            else:
                stationary_since.pop(a.id, None)
        if onset is None and count >= 4 and sim.t > 0:
            onset = round(sim.t, 2)
    cause = next((a for a in sim.agents if a.id == sim.cause_id), None)
    truth = Truth(
        congestion=onset is not None,
        cause_type=scenario.cause_type,
        cause_agent=sim.cause_id if scenario.cause_type else None,
        cause_stop_time=None
        if cause is None or cause.stalled_since is None
        else round(cause.stalled_since, 2),
        onset_seconds=onset,
        note=scenario.note,
    )
    return frames, truth


def to_json(scenario: Scenario3D, frames: list[Frame], truth: Truth, fps: float) -> dict:
    return {
        "scenario": asdict(scenario),
        "fps": fps,
        "lane_width": LANE_WIDTH,
        "near_x": NEAR_X,
        "far_x": FAR_X,
        "footpath_x": FOOTPATH_X,
        "visible_y": VISIBLE_Y,
        "truth": asdict(truth),
        "frames": [asdict(f) for f in frames],
    }
