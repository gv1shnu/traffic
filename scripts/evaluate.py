"""Evaluate deterministic fixtures and optionally actual detections on UVH-26."""

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import cv2
from sklearn.metrics import precision_score, recall_score

from fixtures.synthetic import road, trajectories
from packages.cause_attribution.scoring import rank_candidates, select_cause
from packages.evaluation.metrics import detection_counts
from packages.shared.config import thresholds
from packages.tracking.motion import calculate_motion
from packages.traffic_analysis.congestion import detect_congestion


def evaluate(sample: Path | None = None) -> dict:
    cfg = thresholds()
    scenarios = {
        "flow": False,
        "queue": True,
        "pedestrian": True,
        "unknown": True,
        "sparse": False,
        "no_congestion": False,
    }
    truth = []
    predicted = []
    details = []
    for name, expected in scenarios.items():
        observations = calculate_motion(trajectories(name), road(), 720, 720, cfg)
        congestion, _ = detect_congestion(observations, road(), 720, 720, cfg)
        candidates = rank_candidates(observations, congestion, road(), cfg)
        cause = select_cause(candidates, cfg)
        truth.append(expected)
        predicted.append(congestion.detected)
        details.append(
            {
                "scenario": name,
                "congestion": congestion.model_dump(),
                "selected_track": cause.suspected_track_id,
                "cause": cause.type,
                "top_three": [c.candidate_track_id for c in candidates[:3]],
            }
        )
    causal = [d for d in details if d["scenario"] in {"queue", "pedestrian"}]
    report = {
        "scope": "Synthetic trajectories evaluate rules only. Public stills evaluate detection only. Neither measures real incident attribution accuracy.",
        "config_version": cfg["version"],
        "synthetic": {
            "event_precision": float(precision_score(truth, predicted, zero_division=0)),
            "event_recall": float(recall_score(truth, predicted, zero_division=0)),
            "cause_top1_accuracy": sum(d["selected_track"] == 1 for d in causal) / len(causal),
            "cause_top3_accuracy": sum(1 in d["top_three"] for d in causal) / len(causal),
            "unknown_assignment_accuracy": float(
                next(d for d in details if d["scenario"] == "unknown")["cause"] == "unknown"
            ),
            "event_onset_mae_seconds": sum(
                abs(d["congestion"]["start_seconds"] - 8.8) for d in causal
            )
            / len(causal),
            "onset_reference": "3 or more followers have physically stopped by 8.8s; detector includes its motion smoothing latency.",
            "scenarios": details,
        },
        "unmeasured": {
            "tracking_id_switches": "Requires ground-truth identities in real sequences.",
            "plate_exact_match_accuracy": "Requires labelled plate images and full plate pipeline predictions.",
            "plate_character_accuracy": "Requires labelled plate predictions.",
            "evidence_quality": "Requires blinded human ratings; Laplacian sharpness alone is not accuracy.",
            "real_cause_accuracy": "No annotated causal traffic-video benchmark supplied or evaluated.",
        },
    }
    if sample:
        from packages.vision.detector import detector

        data = json.loads((sample / "annotations.json").read_text())
        mapping = {
            1: "car",
            2: "car",
            3: "car",
            4: "car",
            5: "bus",
            6: "truck",
            7: "autorickshaw",
            8: "motorcycle",
            9: "truck",
            10: "bus",
            11: "bus",
            12: "bicycle",
            13: "car",
            14: "other",
        }
        counts = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
        model = detector()
        started = time.monotonic()
        per_image = []
        for img in data["images"]:
            frame = cv2.imread(str(sample / img["file_name"]))
            if frame is None:
                raise RuntimeError(f"Missing image {img['file_name']}; run fetch_indian_sample.py")
            model.reset()
            found = model.infer(frame, 0, 0)
            predictions = [
                {"class": o.object_type, "bbox": o.bbox}
                for o in found
                if o.object_type in set(mapping.values())
            ]
            truth = []
            for a in data["annotations"]:
                if a["image_id"] == img["id"]:
                    x, y, w, h = a["bbox"]
                    truth.append({"class": mapping[a["category_id"]], "bbox": (x, y, x + w, y + h)})
            for label, values in detection_counts(truth, predictions).items():
                for key, value in values.items():
                    counts[label][key] += value
            per_image.append(
                {
                    "filename": img["file_name"],
                    "ground_truth": len(truth),
                    "predictions": len(predictions),
                }
            )
        elapsed = time.monotonic() - started
        totals = {k: sum(c[k] for c in counts.values()) for k in ["tp", "fp", "fn"]}
        report["public_indian_detection"] = {
            "dataset": "UVH-26 validation subset, CC-BY-4.0, Sharma et al. (IISc)",
            "images": len(data["images"]),
            "iou_threshold": 0.5,
            "precision": totals["tp"] / max(1, totals["tp"] + totals["fp"]),
            "recall": totals["tp"] / max(1, totals["tp"] + totals["fn"]),
            "per_class_counts": dict(counts),
            "per_image": per_image,
            "inference_seconds": elapsed,
            "images_per_second": len(data["images"]) / elapsed,
            "model": model.version,
            "limitations": "Tiny lexicographic sample. Fine vehicle classes collapsed; rider-inclusive two-wheeler boxes differ from COCO. Persons have no ground truth here. Autorickshaw and other classes remain unsupported and count as misses.",
        }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--indian-sample", type=Path)
    parser.add_argument("--output", type=Path, default=Path("storage/evaluation.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evaluate(args.indian_sample), indent=2))
    print(f"Evaluation saved to {args.output}")
