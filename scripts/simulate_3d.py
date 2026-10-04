"""Simulate a labelled 3D traffic scenario and write its trajectories as JSON.

uv run python scripts/simulate_3d.py stalled_car --out storage/sim3d/stalled_car
"""

import argparse
import json
from pathlib import Path

from packages.simulation3d.scenarios import SCENARIOS
from packages.simulation3d.traffic import run, to_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fps", type=float, default=10.0)
    args = ap.parse_args()
    scenario = SCENARIOS[args.scenario]
    frames, truth = run(scenario, fps=args.fps)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "trajectories.json"
    path.write_text(json.dumps(to_json(scenario, frames, truth, args.fps)))
    print(f"{path}: {len(frames)} frames, truth={truth}")


if __name__ == "__main__":
    main()
