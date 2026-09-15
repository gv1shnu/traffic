from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment


def iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return intersection / max(1e-9, area_a + area_b - intersection)


def detection_counts(truth: list[dict], predictions: list[dict], threshold=0.5) -> dict:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    classes = {x["class"] for x in truth + predictions}
    for label in classes:
        gt = [x for x in truth if x["class"] == label]
        pred = [x for x in predictions if x["class"] == label]
        matches = 0
        if gt and pred:
            scores = np.array([[iou(a["bbox"], b["bbox"]) for b in pred] for a in gt])
            rows, cols = linear_sum_assignment(-scores)
            matches = sum(scores[r, c] >= threshold for r, c in zip(rows, cols, strict=True))
        counts[label] = {"tp": int(matches), "fp": len(pred) - matches, "fn": len(gt) - matches}
    return dict(counts)


def character_accuracy(expected: str, predicted: str) -> float:
    prev = list(range(len(predicted) + 1))
    for i, a in enumerate(expected, 1):
        current = [i]
        for j, b in enumerate(predicted, 1):
            current.append(min(current[-1] + 1, prev[j] + 1, prev[j - 1] + (a != b)))
        prev = current
    return max(0, 1 - prev[-1] / max(1, len(expected)))
