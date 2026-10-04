"""Assemble the static showcase site from analysed 3D scenarios.

    uv run python scripts/build_site.py [--scenarios stalled_car ...]

Reads storage/sim3d/<scenario>/{showcase.mp4, ground_truth.json,
analysis/report.json, analysis/evaluation.json} and writes site/media/ and
site/data/showcase.json. The site itself (site/index.html) is static.
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = [
    "stalled_car",
    "stalled_autorickshaw",
    "pedestrian_obstruction",
    "red_light_queue",
    "free_flow",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", nargs="*", default=DEFAULT)
    ap.add_argument("--source", type=Path, default=ROOT / "storage" / "sim3d")
    ap.add_argument("--site", type=Path, default=ROOT / "site")
    args = ap.parse_args()
    media = args.site / "media"
    media.mkdir(parents=True, exist_ok=True)
    (args.site / "data").mkdir(exist_ok=True)

    scenarios = []
    totals = {"tp": 0, "fn": 0, "fp": 0, "switches": 0, "correct": 0, "n": 0}
    for name in args.scenarios:
        folder = args.source / name
        if not (folder / "showcase.mp4").exists():
            print(f"skipping {name}: not rendered/analysed")
            continue
        gt = json.loads((folder / "ground_truth.json").read_text())
        report = json.loads((folder / "analysis" / "report.json").read_text())
        ev = json.loads((folder / "analysis" / "evaluation.json").read_text())
        shutil.copy(folder / "showcase.mp4", media / f"{name}.mp4")
        poster = media / f"{name}.jpg"
        cause_t = report["cause"].get("first_relevant_timestamp")
        at = (cause_t + 6) if cause_t is not None else gt["frames"][-1]["t"] * 0.7
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{at:.1f}",
                "-i",
                str(media / f"{name}.mp4"),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(poster),
            ],
            check=True,
        )
        scenario = gt["scenario"]
        scenarios.append(
            {
                "name": name,
                "title": scenario["title"],
                "note": scenario["note"],
                "video": f"media/{name}.mp4",
                "poster": f"media/{name}.jpg",
                "duration": gt["frames"][-1]["t"],
                "truth": gt["truth"],
                "congestion": report["congestion"],
                "cause": {
                    k: report["cause"].get(k)
                    for k in (
                        "type",
                        "confidence",
                        "suspected_track_id",
                        "object_type",
                        "first_relevant_timestamp",
                        "explanation",
                        "evidence_scores",
                    )
                },
                "alternatives": [
                    {
                        "track": c["candidate_track_id"],
                        "object_type": c["object_type"],
                        "confidence": c["cause_confidence"],
                    }
                    for c in report.get("alternative_candidates", [])[:3]
                ],
                "plate": report.get("license_plate", {}),
                "evaluation": ev,
            }
        )
        det = ev["detection"]
        totals["tp"] += det["true_positives"]
        totals["fn"] += det["false_negatives"]
        totals["fp"] += det["false_positives"]
        totals["switches"] += ev["tracking"]["id_switches"]
        totals["correct"] += int(ev["cause"]["correct"])
        totals["n"] += 1

    summary = {
        "scenarios": totals["n"],
        "outcome_correct": totals["correct"],
        "detection_recall": round(totals["tp"] / max(1, totals["tp"] + totals["fn"]), 3),
        "detection_precision": round(totals["tp"] / max(1, totals["tp"] + totals["fp"]), 3),
        "id_switches": totals["switches"],
    }
    assets = json.loads((ROOT / "config" / "sim3d_assets.json").read_text())["assets"]
    credits = [{k: a[k] for k in ("kind", "name", "author", "license", "source")} for a in assets]
    out = {"summary": summary, "scenarios": scenarios, "credits": credits}
    (args.site / "data" / "showcase.json").write_text(json.dumps(out, indent=1))
    (ROOT / "docs" / "sim3d-evaluation.json").write_text(
        json.dumps(
            {
                "scope": "Rendered 3D simulation (Blender, Objaverse CC BY models). Real YOLO11n + "
                "ByteTrack detection and the unmodified investigation pipeline; ground truth "
                "from the scene geometry. Not real-world footage or an accuracy claim for "
                "real cameras.",
                "summary": summary,
                "scenarios": {s["name"]: s["evaluation"] for s in scenarios},
            },
            indent=2,
        )
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
