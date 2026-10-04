"""Labelled 3D scenarios. Ground truth is fixed by construction; only the queue
onset time is measured from the simulated kinematics."""

from __future__ import annotations

from packages.simulation3d.traffic import Scenario3D, Signal

SCENARIOS: dict[str, Scenario3D] = {
    s.name: s
    for s in [
        Scenario3D(
            name="stalled_car",
            title="Stalled car blocks the near lane",
            duration=28.0,
            seed=11,
            near_rate=0.55,
            far_rate=0.4,
            footpath_rate=0.12,
            cause_kind="car",
            cause_type="stalled_vehicle",
            cause_spawn=-8.0,
            cause_stop_y=30.0,
            note="A car breaks down mid-lane; oncoming traffic keeps flowing so it cannot be passed.",
        ),
        Scenario3D(
            name="stalled_autorickshaw",
            title="Stalled autorickshaw blocks the near lane",
            duration=26.0,
            seed=23,
            near_rate=0.55,
            far_rate=0.4,
            footpath_rate=0.12,
            cause_kind="autorickshaw",
            cause_type="stalled_vehicle",
            cause_spawn=-7.0,
            cause_stop_y=30.0,
            note="An autorickshaw stops mid-lane. The generic COCO detector has no autorickshaw class.",
        ),
        Scenario3D(
            name="pedestrian_obstruction",
            title="Pedestrian standing in the carriageway",
            duration=28.0,
            seed=37,
            near_rate=0.55,
            far_rate=0.4,
            footpath_rate=0.08,
            cause_kind="person",
            cause_type="pedestrian_obstruction",
            cause_spawn=-1.0,
            cause_stop_y=28.0,
            cause_stop_after=3.0,
            crossing_pedestrian=True,
            note="A pedestrian steps off the footpath and stays in the near lane.",
        ),
        Scenario3D(
            name="red_light_queue",
            title="Signal queue (no subject to blame)",
            duration=26.0,
            seed=41,
            near_rate=0.6,
            far_rate=0.4,
            footpath_rate=0.12,
            cause_kind=None,
            cause_type=None,
            signal=Signal(stop_line_y=34.0, red_from=2.0, red_until=24.0),
            note="A red signal queues the near lane. The correct answer is 'unknown'.",
        ),
        Scenario3D(
            name="free_flow",
            title="Free-flowing traffic",
            duration=18.0,
            seed=53,
            near_rate=0.45,
            far_rate=0.4,
            footpath_rate=0.12,
            cause_kind=None,
            cause_type=None,
            note="Normal flow; the correct answer is 'no sustained congestion'.",
        ),
    ]
}
