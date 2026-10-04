"""Render the annotated showcase video for an analysed 3D scenario.

    uv run python scripts/render_showcase.py storage/sim3d/stalled_car [--gif]

Everything drawn on the frames comes from the pipeline's own output: tracked
boxes and IDs from the YOLO/ByteTrack checkpoint, movement state from the
pipeline's motion calculation, and the congestion interval, timeline markers and
suspected subject from the report. Ground truth is used only for the final check
line ("matches the scripted cause"), which is labelled as such.

Boxes are inferred at 5 FPS; between inference samples a track's box is linearly
interpolated for display.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from packages.shared.config import thresholds
from packages.shared.schemas import Observation, Region
from packages.simulation3d.evaluate import evaluate
from packages.tracking.motion import calculate_motion

GREEN = (90, 200, 90)
AMBER = (40, 180, 250)
RED = (60, 60, 235)
CYAN = (220, 200, 60)
WHITE = (245, 245, 245)
PANEL = (28, 26, 24)
FONT = cv2.FONT_HERSHEY_SIMPLEX
CAUSE_LABEL = {
    "stalled_vehicle": "stalled vehicle",
    "pedestrian_obstruction": "pedestrian in carriageway",
    "animal_obstruction": "animal in carriageway",
}


def text(img, s, org, scale=0.5, colour=WHITE, thick=1, bg=None):
    (w, h), base = cv2.getTextSize(s, FONT, scale, thick)
    if bg is not None:
        x, y = org
        cv2.rectangle(img, (x - 3, y - h - 4), (x + w + 3, y + base + 1), bg, -1)
    cv2.putText(img, s, org, FONT, scale, colour, thick, cv2.LINE_AA)


def interpolated(track: list[Observation], t: float) -> Observation | None:
    """Box at time t, interpolated between consecutive inference samples."""
    if not track or t < track[0].timestamp - 0.11 or t > track[-1].timestamp + 0.11:
        return None
    for a, b in zip(track, track[1:], strict=False):
        if a.timestamp <= t <= b.timestamp:
            if b.timestamp - a.timestamp > 0.45:  # do not bridge long gaps
                return a if t - a.timestamp < 0.11 else None
            w = (t - a.timestamp) / (b.timestamp - a.timestamp)
            box = tuple((1 - w) * p + w * q for p, q in zip(a.bbox, b.bbox, strict=True))
            return a.model_copy(update={"bbox": box})
    return min(track, key=lambda o: abs(o.timestamp - t))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario_dir", type=Path)
    ap.add_argument("--gif", action="store_true", help="also write a small looping GIF")
    args = ap.parse_args()
    folder = args.scenario_dir
    gt = json.loads((folder / "ground_truth.json").read_text())
    report = json.loads((folder / "analysis" / "report.json").read_text())
    timeline = json.loads((folder / "analysis" / "timeline.json").read_text())
    raw = json.loads((folder / "analysis" / "tracks.json").read_text())["observations"]

    cfg = thresholds()
    regions = [Region.model_validate(r) for r in gt["regions"]]
    width, height = gt["width"], gt["height"]
    obs = calculate_motion(
        [Observation.model_validate(o) for o in raw], regions, width, height, cfg
    )
    tracks: dict[int, list[Observation]] = defaultdict(list)
    for o in sorted(obs, key=lambda o: o.timestamp):
        tracks[o.track_id].append(o)

    result = evaluate(gt, raw, report)
    (folder / "analysis" / "evaluation.json").write_text(json.dumps(result, indent=2))

    congestion = report["congestion"]
    cause = report["cause"]
    suspect = cause.get("suspected_track_id")
    cause_from = cause.get("first_relevant_timestamp")
    incident_region = next((r for r in regions if r.id == congestion.get("region")), None)
    markers = timeline if isinstance(timeline, list) else timeline.get("markers", [])
    duration = gt["frames"][-1]["t"]
    fps = gt["fps"]
    panel_h = 120
    out_frames = folder / "showcase_frames"
    shutil.rmtree(out_frames, ignore_errors=True)
    out_frames.mkdir()
    x0, x1 = 20, width - 20

    def xt(s: float) -> int:
        return int(x0 + (x1 - x0) * min(1.0, max(0.0, s / duration)))

    for f in gt["frames"]:
        t = f["t"]
        img = cv2.imread(str(folder / "frames" / f"{f['index']:06d}.jpg"))
        overlay = img.copy()
        if incident_region is not None:
            poly = np.array(
                [(p.x * width, p.y * height) for p in incident_region.polygon], dtype=np.int32
            )
            cv2.fillPoly(overlay, [poly], CYAN)
            img = cv2.addWeighted(overlay, 0.12, img, 0.88, 0)
            cv2.polylines(img, [poly], True, CYAN, 1, cv2.LINE_AA)
        for tid, track in tracks.items():
            o = interpolated(track, t)
            if o is None:
                continue
            x1, y1, x2, y2 = (int(v) for v in o.bbox)
            is_cause = tid == suspect and cause_from is not None and t >= cause_from
            if is_cause:
                colour, thick = RED, 3
            elif o.movement in {"stationary", "slowing"}:
                colour, thick = AMBER, 2
            else:
                colour, thick = GREEN, 1
            cv2.rectangle(img, (x1, y1), (x2, y2), colour, thick, cv2.LINE_AA)
            label = f"#{tid} {o.object_type}"
            text(img, label, (x1 + 2, max(12, y1 - 4)), 0.38, (20, 20, 20), 1, bg=colour)
            if is_cause:
                kind = CAUSE_LABEL.get(cause.get("type"), cause.get("type"))
                text(
                    img,
                    f"SUSPECTED CAUSE: {kind} ({cause.get('confidence', 0):.2f})",
                    (x1, max(30, y1 - 22)),
                    0.5,
                    WHITE,
                    1,
                    bg=RED,
                )
        text(img, "RENDERED SIMULATION", (10, 22), 0.5, WHITE, 1, bg=(0, 0, 0))
        text(
            img,
            "detections: YOLO11n + ByteTrack | reasoning: investigation pipeline",
            (10, 44),
            0.42,
            WHITE,
            1,
            bg=(0, 0, 0),
        )
        text(img, f"t = {t:5.1f} s", (width - 105, 22), 0.5, WHITE, 1, bg=(0, 0, 0))

        canvas = np.full((height + panel_h, width, 3), PANEL, np.uint8)
        canvas[:height] = img
        bar_y = height + 26
        cv2.rectangle(canvas, (x0, bar_y - 5), (x1, bar_y + 5), (70, 70, 70), -1)
        if congestion.get("detected") and congestion.get("start_seconds") is not None:
            end = congestion.get("end_seconds") or duration
            cv2.rectangle(
                canvas,
                (xt(congestion["start_seconds"]), bar_y - 5),
                (xt(end), bar_y + 5),
                AMBER,
                -1,
            )
        for m in markers:
            if m.get("timestamp") is None:
                continue
            mx = xt(m["timestamp"])
            reached = t >= m["timestamp"]
            cv2.line(
                canvas, (mx, bar_y - 10), (mx, bar_y + 10), WHITE if reached else (120, 120, 120), 1
            )
        cv2.line(canvas, (xt(t), bar_y - 12), (xt(t), bar_y + 12), RED, 2)

        lines = []
        passed = [m for m in markers if m.get("timestamp") is not None and t >= m["timestamp"]]
        if passed:
            last = passed[-1]
            lines.append(f"{last['timestamp']:.1f} s  {last['label']}")
        if not congestion.get("detected"):
            lines.append("No sustained congestion detected in this clip.")
        elif t >= congestion["start_seconds"]:
            lines.append(
                f"Sustained congestion from {congestion['start_seconds']:.1f} s "
                f"(peak queue {congestion.get('peak_queue_size', 0)})"
            )
        if suspect is not None and cause_from is not None and t >= cause_from:
            lines.append(
                f"Suspected cause: track #{suspect} ({cause.get('object_type')}), "
                f"stopped at {cause_from:.1f} s"
            )
        elif congestion.get("detected") and suspect is None and t >= congestion["start_seconds"]:
            lines.append("Cause: unknown (no subject meets the evidence threshold)")
        if t >= duration - 3:
            ok = result["cause"]["correct"]
            lines.append(
                "Ground-truth check: "
                + (
                    "matches the scripted scenario"
                    if ok
                    else "does NOT match the scripted scenario"
                )
            )
        for i, line in enumerate(lines[:4]):
            text(canvas, line, (x0, bar_y + 30 + i * 20), 0.45, WHITE)
        cv2.imwrite(
            str(out_frames / f"{f['index']:06d}.jpg"), canvas, [cv2.IMWRITE_JPEG_QUALITY, 92]
        )

    video = folder / "showcase.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(out_frames / "%06d.jpg"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=True,
    )
    if args.gif:
        palette = folder / "palette.png"
        gif = folder / "showcase.gif"
        filters = "fps=6,scale=640:-1:flags=lanczos"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(video),
                "-vf",
                f"{filters},palettegen",
                str(palette),
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(video),
                "-i",
                str(palette),
                "-lavfi",
                f"{filters}[x];[x][1:v]paletteuse",
                str(gif),
            ],
            check=True,
        )
        palette.unlink()
    print(json.dumps(result["cause"]), "->", video)


if __name__ == "__main__":
    main()
