"""Reasoning-layer evaluation on simulated scenarios with perfect ground truth.

Runs the labelled scenario battery through the real congestion and cause
attribution logic and reports detection, attribution, onset and unknown-handling
metrics against known answers. This measures the reasoning layer only: agents are
kinematic, so it says nothing about real detection recall or plate accuracy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.cause_attribution.scoring import rank_candidates, select_cause
from packages.evaluation.scenarios import battery
from packages.evaluation.simulation import run
from packages.shared.config import thresholds
from packages.tracking.motion import calculate_motion
from packages.traffic_analysis.congestion import detect_congestion


def evaluate_simulation() -> dict:
    cfg = thresholds()
    details = []
    for scenario in battery():
        rows, gt = run(scenario)
        obs = calculate_motion(rows, scenario.regions, 720, 720, cfg)
        congestion, _ = detect_congestion(obs, scenario.regions, 720, 720, cfg)
        candidates = rank_candidates(obs, congestion, scenario.regions, cfg, 720)
        cause = select_cause(candidates, cfg)
        details.append(
            {
                "scenario": scenario.name,
                "note": gt.note,
                "truth": {
                    "congestion": gt.congestion,
                    "cause_type": gt.cause_type,
                    "suspect_track": gt.suspect_track,
                    "onset_seconds": gt.onset_seconds,
                },
                "predicted": {
                    "congestion": congestion.detected,
                    "cause_type": str(cause.type),
                    "suspect_track": cause.suspected_track_id,
                    "start_seconds": congestion.start_seconds,
                    "top_three": [c.candidate_track_id for c in candidates[:3]],
                    "top_confidence": candidates[0].cause_confidence if candidates else 0.0,
                },
            }
        )

    caused = [d for d in details if d["truth"]["cause_type"] is not None]
    unknown_truth = [d for d in details if d["truth"]["cause_type"] is None]

    def rate(items, predicate):
        return round(sum(predicate(d) for d in items) / len(items), 4) if items else None

    det_tp = sum(d["truth"]["congestion"] and d["predicted"]["congestion"] for d in details)
    det_fp = sum(not d["truth"]["congestion"] and d["predicted"]["congestion"] for d in details)
    det_fn = sum(d["truth"]["congestion"] and not d["predicted"]["congestion"] for d in details)

    committed = [d for d in caused if d["predicted"]["suspect_track"] is not None]
    onset_pairs = [
        d
        for d in caused
        if d["predicted"]["start_seconds"] is not None and d["truth"]["onset_seconds"] is not None
    ]
    predicted_unknown = [d for d in details if d["predicted"]["suspect_track"] is None]

    report = {
        "scope": (
            "Simulated kinematic scenarios with perfect ground truth. Measures the "
            "congestion and cause-attribution logic only. Not real detection, tracking, "
            "occlusion or plate performance; those require real footage."
        ),
        "config_version": cfg["version"],
        "scenario_count": len(details),
        "detection": {
            "precision": round(det_tp / max(1, det_tp + det_fp), 4),
            "recall": round(det_tp / max(1, det_tp + det_fn), 4),
        },
        "attribution": {
            "caused_scenarios": len(caused),
            "cause_top1_accuracy": rate(
                caused,
                lambda d: (
                    d["predicted"]["cause_type"] == d["truth"]["cause_type"]
                    and d["predicted"]["suspect_track"] == d["truth"]["suspect_track"]
                ),
            ),
            "cause_top3_recall": rate(
                caused, lambda d: d["truth"]["suspect_track"] in d["predicted"]["top_three"]
            ),
            "committed_precision": rate(
                committed, lambda d: d["predicted"]["cause_type"] == d["truth"]["cause_type"]
            ),
            "onset_mae_seconds": round(
                sum(
                    abs(d["predicted"]["start_seconds"] - d["truth"]["onset_seconds"])
                    for d in onset_pairs
                )
                / len(onset_pairs),
                3,
            )
            if onset_pairs
            else None,
        },
        "unknown_handling": {
            # Of scenarios with no attributable subject, how many the system left unknown.
            "unknown_recall": rate(
                unknown_truth, lambda d: d["predicted"]["suspect_track"] is None
            ),
            # Of scenarios the system committed a cause to, how many truly had one.
            "commit_precision": rate(
                [d for d in details if d["predicted"]["suspect_track"] is not None],
                lambda d: d["truth"]["cause_type"] is not None,
            ),
            # Safety: fraction of no-cause scenarios the system wrongly blamed a subject.
            "false_blame_rate": rate(
                unknown_truth, lambda d: d["predicted"]["suspect_track"] is not None
            ),
            "deferred_true_causes": sum(d in predicted_unknown for d in caused),
        },
        "scenarios": details,
    }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("storage/simulation-evaluation.json"))
    args = parser.parse_args()
    report = evaluate_simulation()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    d, a, u = report["detection"], report["attribution"], report["unknown_handling"]
    print(f"Scenarios: {report['scenario_count']}")
    print(f"Detection    precision={d['precision']} recall={d['recall']}")
    print(
        f"Attribution  top1={a['cause_top1_accuracy']} top3={a['cause_top3_recall']} "
        f"committed_precision={a['committed_precision']} onset_mae={a['onset_mae_seconds']}s"
    )
    print(
        f"Unknown      false_blame_rate={u['false_blame_rate']} "
        f"deferred_true_causes={u['deferred_true_causes']}"
    )
    print(f"Saved to {args.output}")
