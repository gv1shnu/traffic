"""Render annotated preview GIFs of the reasoning layer on simulated scenarios.

Each GIF shows the labelled kinematic scenario with per-frame motion state,
the configured incident region, the suspected subject (when the system commits)
and the system's verdict. These are simulated illustrations of the congestion
and attribution logic, not real footage or a performance benchmark.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import imageio.v2 as imageio
import numpy as np

from packages.cause_attribution.scoring import rank_candidates, select_cause
from packages.evaluation import scenarios as sc
from packages.evaluation.simulation import run
from packages.shared.config import thresholds
from packages.tracking.motion import calculate_motion
from packages.traffic_analysis.congestion import detect_congestion

SIZE = 420
STATE_COLOR = {
    "moving_normally": (70, 200, 110),
    "slowing": (240, 160, 55),
    "nearly_stationary": (240, 200, 70),
    "stationary": (230, 80, 70),
    "unmeasured": (150, 150, 150),
}
CYAN = (60, 205, 190)
INK = (30, 40, 38)

# Scenarios chosen to show the honest spread: a positive Indian-vehicle attribution,
# a vulnerable-road-user attribution, a correctly-unattributed signal queue, and a
# true negative.
PREVIEWS = [
    ("stalled_autorickshaw", "Stalled autorickshaw blocks a lane"),
    ("pedestrian_obstruction", "Pedestrian stops in the carriageway"),
    ("red_light_queue", "Signal queue - no subject blamed"),
    ("free_flow", "Free flow - no congestion"),
]


def _draw(frame, obs_at, region, cause, congestion, t, title):
    img = np.full((SIZE, SIZE, 3), 245, dtype=np.uint8)
    # Incident region outline.
    poly = np.array([[int(p.x * SIZE), int(p.y * SIZE)] for p in region.polygon], np.int32)
    cv2.polylines(img, [poly], True, CYAN, 1)
    suspect = cause.suspected_track_id
    for o in obs_at:
        x1, y1, x2, y2 = (int(v * SIZE / 720) for v in o.bbox)
        color = STATE_COLOR.get(o.movement, (150, 150, 150))
        thick = 3 if o.track_id == suspect else 1
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thick)
        if o.track_id == suspect:
            cv2.rectangle(img, (x1 - 3, y1 - 3), (x2 + 3, y2 + 3), (225, 70, 60), 2)
            cv2.putText(
                img,
                f"suspect #{o.track_id}",
                (x1, max(12, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (225, 70, 60),
                1,
                cv2.LINE_AA,
            )
    # Caption bar.
    cv2.rectangle(img, (0, 0), (SIZE, 46), (248, 249, 246), -1)
    cv2.putText(img, title, (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, INK, 1, cv2.LINE_AA)
    detected = (
        congestion.detected
        and congestion.start_seconds is not None
        and (t >= congestion.start_seconds)
    )
    if detected:
        verdict = f"Congestion  |  cause: {cause.type}"
        vcol = (200, 90, 60) if str(cause.type) != "unknown" else (150, 120, 40)
    elif congestion.detected:
        verdict = "monitoring queue build-up"
        vcol = (120, 120, 120)
    else:
        verdict = "no sustained congestion"
        vcol = (90, 160, 110)
    cv2.putText(img, verdict, (10, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.42, vcol, 1, cv2.LINE_AA)
    cv2.putText(
        img,
        f"t={t:04.1f}s  (simulated)",
        (SIZE - 150, 38),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (140, 140, 140),
        1,
        cv2.LINE_AA,
    )
    return img


def render(scenario_name: str, title: str, out: Path) -> Path:
    cfg = thresholds()
    scenario = getattr(sc, scenario_name)()
    rows, _ = run(scenario)
    obs = calculate_motion(rows, scenario.regions, 720, 720, cfg)
    congestion, _ = detect_congestion(obs, scenario.regions, 720, 720, cfg)
    candidates = rank_candidates(obs, congestion, scenario.regions, cfg, 720)
    cause = select_cause(candidates, cfg)
    region = next(r for r in scenario.regions if r.id == scenario.incident_region)
    by_t: dict[float, list] = {}
    for o in obs:
        by_t.setdefault(round(o.timestamp, 1), []).append(o)
    times = sorted(by_t)[::2][:40]  # ~2 fps, cap length for a compact GIF
    frames = [_draw(None, by_t[t], region, cause, congestion, t, title) for t in times]
    out.parent.mkdir(parents=True, exist_ok=True)
    imageio.mimsave(out, frames, format="GIF", duration=0.2, loop=0)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("docs/previews"))
    args = parser.parse_args()
    for name, title in PREVIEWS:
        path = render(name, title, args.out_dir / f"{name}.gif")
        print(f"{name:26} -> {path}  ({path.stat().st_size // 1024} KB)")
