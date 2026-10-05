"""Simulate, render and encode a labelled 3D traffic scenario.

    uv run python scripts/render_3d.py stalled_car [--samples 10] [--chunk 80]

Writes storage/sim3d/<scenario>/{trajectories.json, frames/, ground_truth.json,
video.mp4}. Rendering runs Blender headless in resumable chunks; frames that
already exist are kept. Requires Blender 4.5 (BLENDER env var or --blender) and
the assets from scripts/sim3d/fetch_assets.py.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from packages.simulation3d.scenarios import SCENARIOS
from packages.simulation3d.traffic import run, to_json

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--samples", type=int, default=10)
    ap.add_argument("--chunk", type=int, default=80)
    ap.add_argument("--blender", default=os.environ.get("BLENDER", "blender"))
    args = ap.parse_args()
    out = args.out or ROOT / "storage" / "sim3d" / args.scenario
    out.mkdir(parents=True, exist_ok=True)

    scenario = SCENARIOS[args.scenario]
    frames, truth = run(scenario, fps=args.fps)
    trajectories = out / "trajectories.json"
    trajectories.write_text(json.dumps(to_json(scenario, frames, truth, args.fps)))
    print(f"simulated {len(frames)} frames; truth: {truth}")

    script = ROOT / "scripts" / "sim3d" / "blender_scene.py"
    parts = []
    for start in range(0, len(frames), args.chunk):
        end = min(len(frames), start + args.chunk)
        part = out / f"ground_truth_{start}_{end}.json"
        frames_done = all((out / "frames" / f"{i:06d}.jpg").exists() for i in range(start, end))
        if not (part.exists() and frames_done):
            subprocess.run(
                [
                    args.blender,
                    "--background",
                    "--factory-startup",
                    "--python",
                    str(script),
                    "--",
                    "--trajectories",
                    str(trajectories),
                    "--out",
                    str(out),
                    "--frames",
                    f"{start}:{end}",
                    "--samples",
                    str(args.samples),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        parts.append(json.loads(part.read_text()))
        print(f"frames {start}-{end} done")

    merged = {k: v for k, v in parts[0].items() if k not in {"frames", "assets"}}
    merged["frames"] = [f for p in parts for f in p["frames"]]
    merged["assets"] = {k: v for p in parts for k, v in p.get("assets", {}).items()}
    (out / "ground_truth.json").write_text(json.dumps(merged))

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(args.fps),
            "-i",
            str(out / "frames" / "%06d.jpg"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(out / "video.mp4"),
        ],
        check=True,
    )
    print(f"wrote {out / 'video.mp4'}")


if __name__ == "__main__":
    main()
