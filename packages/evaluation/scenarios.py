"""Labelled scenario battery for reasoning-layer evaluation.

Each builder returns a Scenario whose ground truth is known by construction.
Only the congestion onset time is measured from the kinematics at run time.
See packages/evaluation/simulation.py for the disclaimer on scope.
"""

from __future__ import annotations

from packages.evaluation.simulation import Agent, GroundTruth, Scenario
from packages.shared.schemas import Point, Region


def _poly(*points: tuple[float, float]) -> list[Point]:
    return [Point(x=x, y=y) for x, y in points]


CAR = ("car", 65.0, 65.0)
PERSON = ("person", 30.0, 30.0)
COW = ("cow", 55.0, 45.0)

LANE1_X = 288.0  # centre of the 0.2-0.6 vertical region
LANE2_X = 590.0  # centre of the 0.65-0.98 vertical region
HLANE_Y = 324.0  # centre of the 0.3-0.6 horizontal region


def vertical_lanes() -> list[Region]:
    return [
        Region(
            id="lane_1",
            name="Main road",
            polygon=_poly((0.2, 0.02), (0.6, 0.02), (0.6, 0.98), (0.2, 0.98)),
            direction=(0, -1),
        ),
        Region(
            id="lane_2",
            name="Adjacent road",
            polygon=_poly((0.65, 0.02), (0.98, 0.02), (0.98, 0.98), (0.65, 0.98)),
            direction=(0, -1),
        ),
    ]


def horizontal_lane() -> list[Region]:
    return [
        Region(
            id="lane_h",
            name="Cross road",
            polygon=_poly((0.02, 0.3), (0.98, 0.3), (0.98, 0.6), (0.02, 0.6)),
            direction=(-1, 0),
        )
    ]


def _column(
    kind,
    first_id,
    count,
    axis,
    cross,
    start,
    spacing,
    v,
    stall_id=None,
    stop_at=None,
    release_at=None,
    parked=False,
):
    name, length, width = kind
    agents = []
    for k in range(count):
        tid = first_id + k
        agents.append(
            Agent(
                track_id=tid,
                object_type=name,
                axis=axis,
                pos=start + k * spacing,
                cross=cross,
                length=length,
                width=width,
                v_desired=0.0 if parked else v,
                stop_at=stop_at if (stall_id is not None and tid == stall_id) else None,
                release_at=release_at if (stall_id is not None and tid == stall_id) else None,
                stalled=parked,
            )
        )
    return agents


def stalled_car() -> Scenario:
    agents = _column(CAR, 1, 6, "y", LANE1_X, 380, 95, 45, stall_id=1, stop_at=3.0)
    return Scenario(
        "stalled_car",
        agents,
        vertical_lanes(),
        22,
        "lane_1",
        GroundTruth(True, "stalled_vehicle", 1, "Lead car stalls; queue builds behind"),
    )


def stalled_autorickshaw() -> Scenario:
    agents = _column(CAR, 1, 6, "y", LANE1_X, 380, 95, 45, stall_id=1, stop_at=3.0)
    agents[0].object_type = "autorickshaw"
    agents[0].length, agents[0].width = 55.0, 55.0
    return Scenario(
        "stalled_autorickshaw",
        agents,
        vertical_lanes(),
        22,
        "lane_1",
        GroundTruth(True, "stalled_vehicle", 1, "Lead autorickshaw stalls"),
    )


def pedestrian_obstruction() -> Scenario:
    ped = _column(PERSON, 1, 1, "y", LANE1_X, 300, 0, 16, stall_id=1, stop_at=3.0)
    cars = _column(CAR, 2, 5, "y", LANE1_X, 430, 95, 45)
    return Scenario(
        "pedestrian_obstruction",
        ped + cars,
        vertical_lanes(),
        22,
        "lane_1",
        GroundTruth(True, "pedestrian_obstruction", 1, "Person walks in and stops"),
    )


def animal_obstruction() -> Scenario:
    cow = _column(COW, 1, 1, "y", LANE1_X, 300, 0, 16, stall_id=1, stop_at=3.0)
    cars = _column(CAR, 2, 5, "y", LANE1_X, 430, 95, 45)
    return Scenario(
        "animal_obstruction",
        cow + cars,
        vertical_lanes(),
        22,
        "lane_1",
        GroundTruth(True, "animal_obstruction", 1, "Cow walks in and stops"),
    )


def adjacent_lane_flows() -> Scenario:
    stalled = _column(CAR, 1, 6, "y", LANE1_X, 380, 95, 45, stall_id=1, stop_at=3.0)
    flowing = _column(CAR, 10, 5, "y", LANE2_X, 200, 150, 55)
    return Scenario(
        "adjacent_lane_flows",
        stalled + flowing,
        vertical_lanes(),
        22,
        "lane_1",
        GroundTruth(True, "stalled_vehicle", 1, "Lane 1 stalls while lane 2 flows"),
    )


def lane_blockage_horizontal() -> Scenario:
    agents = _column(CAR, 1, 6, "x", HLANE_Y, 380, 95, 45, stall_id=1, stop_at=3.0)
    return Scenario(
        "lane_blockage_horizontal",
        agents,
        horizontal_lane(),
        22,
        "lane_h",
        GroundTruth(True, "stalled_vehicle", 1, "Blocker on a horizontal lane"),
    )


def red_light_queue() -> Scenario:
    # Both approaches stop at the line and release together: normal signal
    # operation, not an attributable incident subject.
    lane1 = _column(CAR, 1, 6, "y", LANE1_X, 300, 95, 45)
    lane2 = _column(CAR, 10, 5, "y", LANE2_X, 300, 95, 45)
    for k, a in enumerate(lane1):
        a.stop_at, a.release_at = 2.0 + k * 0.4, 14.0
    for k, a in enumerate(lane2):
        a.stop_at, a.release_at = 2.0 + k * 0.4, 14.0
    return Scenario(
        "red_light_queue",
        lane1 + lane2,
        vertical_lanes(),
        22,
        "lane_1",
        GroundTruth(True, None, None, "Signal queue: no attributable subject"),
    )


def already_congested() -> Scenario:
    agents = _column(CAR, 1, 6, "y", LANE1_X, 120, 80, 0, parked=True)
    return Scenario(
        "already_congested",
        agents,
        vertical_lanes(),
        22,
        "lane_1",
        GroundTruth(True, None, None, "Jam present from the first frame; no precedence"),
    )


def free_flow() -> Scenario:
    agents = _column(CAR, 1, 6, "y", LANE1_X, 200, 110, 55)
    return Scenario(
        "free_flow",
        agents,
        vertical_lanes(),
        22,
        "lane_1",
        GroundTruth(False, None, None, "Smooth flow; no congestion"),
    )


def sparse_stalled() -> Scenario:
    agents = _column(CAR, 1, 2, "y", LANE1_X, 380, 120, 45, stall_id=1, stop_at=3.0)
    return Scenario(
        "sparse_stalled",
        agents,
        vertical_lanes(),
        22,
        "lane_1",
        GroundTruth(False, None, None, "One stop, too few vehicles for a queue"),
    )


def battery() -> list[Scenario]:
    return [
        stalled_car(),
        stalled_autorickshaw(),
        pedestrian_obstruction(),
        animal_obstruction(),
        adjacent_lane_flows(),
        lane_blockage_horizontal(),
        red_light_queue(),
        already_congested(),
        free_flow(),
        sparse_stalled(),
    ]
