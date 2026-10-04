"""Compare pipeline output on a rendered scenario against its 3D ground truth.

Ground-truth boxes are projected from the scene geometry, with a ray-cast
visibility fraction. Only subjects that are at least ``min_visible`` visible and
``min_height`` pixels tall are required to be detected; detections that match any
ground-truth subject are never counted as false positives.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

VEHICLES = {"car", "bus", "truck", "motorcycle", "autorickshaw", "bicycle"}


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _family(kind: str) -> str:
    return "vehicle" if kind in VEHICLES else kind


def match_frame(subjects: list[dict], detections: list[dict], threshold: float = 0.5):
    """Greedy one-to-one matching by IoU within the same family (vehicle/person)."""
    pairs = sorted(
        (
            (iou(s["bbox"], d["bbox"]), si, di)
            for si, s in enumerate(subjects)
            for di, d in enumerate(detections)
            if _family(s["kind"]) == _family(d["object_type"])
        ),
        reverse=True,
    )
    used_s: set[int] = set()
    used_d: set[int] = set()
    matches = []
    for score, si, di in pairs:
        if score < threshold:
            break
        if si in used_s or di in used_d:
            continue
        used_s.add(si)
        used_d.add(di)
        matches.append((si, di, score))
    return matches


def evaluate(
    ground_truth: dict,
    observations: list[dict],
    report: dict,
    min_visible: float = 0.5,
    min_height: float = 20.0,
    sample_step: float = 0.2,
) -> dict[str, Any]:
    gt_by_time = {round(f["t"], 2): f for f in ground_truth["frames"]}
    times = sorted(gt_by_time)
    by_time: dict[float, list[dict]] = defaultdict(list)
    for o in observations:
        nearest = min(times, key=lambda t: abs(t - o["timestamp"]))
        if abs(nearest - o["timestamp"]) <= 0.051:
            by_time[nearest].append(o)
    # The pipeline samples on a fixed time grid; frames where it found nothing
    # still count against recall.
    sampled = [t for t in times if abs(t / sample_step - round(t / sample_step)) < 1e-3]

    tp = fp = fn = 0
    per_kind: dict[str, Counter] = defaultdict(Counter)
    confusion: dict[str, Counter] = defaultdict(Counter)
    track_of: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for t in sampled:
        subjects = gt_by_time[t]["subjects"]
        dets = by_time.get(t, [])
        matches = match_frame(subjects, dets)
        matched_s = {si for si, _, _ in matches}
        matched_d = {di for _, di, _ in matches}
        for si, di, _ in matches:
            s, d = subjects[si], dets[di]
            track_of[s["id"]].append((t, d["track_id"]))
            confusion[s["kind"]][d["object_type"]] += 1
        for si, s in enumerate(subjects):
            height = s["bbox"][3] - s["bbox"][1]
            required = s["visible"] >= min_visible and height >= min_height
            if not required:
                continue
            per_kind[s["kind"]]["total"] += 1
            if si in matched_s:
                tp += 1
                per_kind[s["kind"]]["detected"] += 1
            else:
                fn += 1
        fp += len(dets) - len(matched_d)

    switches = 0
    for history in track_of.values():
        ids = [tid for _, tid in sorted(history)]
        switches += sum(a != b for a, b in zip(ids, ids[1:], strict=False))

    truth = ground_truth["truth"]
    cause = report.get("cause", {})
    suspect = cause.get("suspected_track_id")
    cause_tracks = Counter(tid for _, tid in track_of.get(truth.get("cause_agent") or -1, []))
    expected_unknown = truth.get("cause_agent") is None
    if expected_unknown:
        cause_correct = suspect is None
    else:
        cause_correct = suspect is not None and suspect in cause_tracks
    congestion = report.get("congestion", {})
    onset = truth.get("onset_seconds")
    start = congestion.get("start_seconds")
    plate = report.get("license_plate", {})
    return {
        "sampled_frames": len(sampled),
        "detection": {
            "criteria": f"IoU>=0.5, visible>={min_visible}, height>={min_height}px",
            "true_positives": tp,
            "false_negatives": fn,
            "false_positives": fp,
            "recall": round(tp / max(1, tp + fn), 4),
            "precision": round(tp / max(1, tp + fp), 4),
            "per_kind_recall": {
                k: round(v["detected"] / max(1, v["total"]), 4) for k, v in sorted(per_kind.items())
            },
            "per_kind_required": {k: v["total"] for k, v in sorted(per_kind.items())},
            "class_confusion": {k: dict(v) for k, v in sorted(confusion.items())},
        },
        "tracking": {"id_switches": switches, "matched_subjects": len(track_of)},
        "congestion": {
            "truth": truth.get("congestion"),
            "detected": congestion.get("detected"),
            "truth_onset_seconds": onset,
            "detected_start_seconds": start,
            "onset_error_seconds": None
            if onset is None or start is None
            else round(start - onset, 2),
        },
        "cause": {
            "truth_type": truth.get("cause_type"),
            "truth_agent": truth.get("cause_agent"),
            "truth_agent_tracks": dict(cause_tracks),
            "predicted_type": cause.get("type"),
            "predicted_track": suspect,
            "confidence": cause.get("confidence"),
            "correct": cause_correct,
            "expected_unknown": expected_unknown,
        },
        "plate": {
            "status": plate.get("status"),
            "text": plate.get("text"),
        },
    }
