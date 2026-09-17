import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from fixtures.synthetic import road, trajectories
from packages.cause_attribution.scoring import aggregate, rank_candidates, select_cause
from packages.plate_recognition.ocr import consensus
from packages.shared.config import thresholds
from packages.shared.schemas import CameraConfig, Plate, Report
from packages.tracking.motion import calculate_motion
from packages.traffic_analysis.congestion import detect_congestion
from packages.vision.quality import quality


def analyze_synthetic(scenario):
    cfg = thresholds()
    rows = calculate_motion(trajectories(scenario), road(), 720, 720, cfg)
    congestion, metrics = detect_congestion(rows, road(), 720, 720, cfg)
    candidates = rank_candidates(rows, congestion, road(), cfg)
    return rows, congestion, metrics, candidates, select_cause(candidates, cfg)


def test_motion_stationary_and_moving():
    rows, _, _, _, _ = analyze_synthetic("queue")
    lead = [o for o in rows if o.track_id == 1]
    assert lead[5].speed > 0.2
    assert lead[-1].stationary_duration > 10
    assert lead[-1].speed == 0


@pytest.mark.parametrize("scenario", ["flow", "no_congestion", "sparse"])
def test_no_false_congestion(scenario):
    _, event, _, candidates, cause = analyze_synthetic(scenario)
    assert not event.detected
    assert not candidates
    assert cause.type == "unknown"


def test_queue_and_causal_precedence():
    _, event, metrics, candidates, cause = analyze_synthetic("queue")
    assert event.detected
    assert 8 <= event.start_seconds <= 12
    assert event.peak_queue_size == 5
    assert candidates[0].candidate_track_id == 1
    assert candidates[0].evidence_scores["temporal_precedence"] == 1
    assert cause.suspected_track_id == 1
    assert len(metrics) > 20


def test_existing_queue_is_unknown():
    _, event, _, _, cause = analyze_synthetic("unknown")
    assert event.detected
    assert cause.type == "unknown"


def test_pedestrian_obstruction():
    _, event, _, candidates, cause = analyze_synthetic("pedestrian")
    assert event.detected
    assert candidates[0].object_type == "person"
    assert cause.type == "pedestrian_obstruction"


def test_whole_road_confidence_capped():
    cfg = thresholds()
    rows = calculate_motion(trajectories(), [], 720, 720, cfg)
    event, _ = detect_congestion(rows, [], 720, 720, cfg)
    candidates = rank_candidates(rows, event, [], cfg)
    assert all(c.cause_confidence <= 0.59 for c in candidates)
    assert select_cause(candidates, cfg).type == "unknown"


def test_single_factor_cannot_claim_cause():
    assert aggregate({"tracking_quality": 1}, thresholds()) < 0.5
    assert (
        aggregate(
            {k: 1 for k in thresholds()["weights"] if k != "temporal_precedence"}, thresholds()
        )
        <= 0.49
    )


def reading(text="KA01AB1234", t=1, conf=0.94, q=0.8):
    return {
        "raw_text": text,
        "timestamp": t,
        "confidence": conf,
        "quality": q,
        "detection_confidence": 0.9,
    }


@pytest.mark.parametrize("text", ["KA01AB1234", "DL8CAF5031", "TS09EX1234", "22BH1234AA"])
def test_indian_plate_consensus(text):
    p = consensus([reading(text, t=1), reading(text, t=2)], thresholds())
    assert p.status == "recognized" and p.text == text


@pytest.mark.parametrize(
    "readings",
    [
        [reading()],
        [reading(conf=0.6), reading(t=2, conf=0.6)],
        [reading(q=0.1), reading(t=2, q=0.1)],
        [reading("KAO1AB1234"), reading("KAO1AB1234", t=2)],
        [reading(t=1), reading(t=1)],
    ],
)
def test_ocr_rejects_weak_evidence(readings):
    result = consensus(readings, thresholds())
    assert result.text is None
    assert result.status == "unreadable"


def test_ocr_conflicting_frames():
    result = consensus(
        [reading(t=1), reading(t=2), reading("KA01AB1235", t=3), reading("KA01AB1235", t=4)],
        thresholds(),
    )
    assert result.text is None


def test_quality_prefers_sharp_exposed_subject():
    rng = np.random.default_rng(1)
    sharp = rng.integers(25, 220, (200, 200, 3), dtype=np.uint8)
    blur = cv2.GaussianBlur(sharp, (41, 41), 15)
    assert quality(sharp) > quality(blur)
    assert quality(sharp) > quality(np.zeros_like(sharp))


def test_report_schema_and_plate_invariants():
    assert "congestion" in Report.model_json_schema()["properties"]
    with pytest.raises(ValidationError):
        Plate(status="unreadable", text="KA01AB1234")
    with pytest.raises(ValidationError):
        Plate(status="recognized")


def test_polygon_validation():
    with pytest.raises(ValidationError):
        CameraConfig(
            regions=[
                {"id": "bad", "name": "bad", "polygon": [{"x": 0, "y": 0}] * 3, "direction": [0, 0]}
            ]
        )


def test_timeline_uses_measured_events_and_does_not_invent_clearance():
    from packages.workflows.timeline import build_timeline

    rows, event, metrics, _, cause = analyze_synthetic("queue")
    markers = build_timeline(rows, cause, event, metrics, road(), thresholds())
    labels = {m["label"] for m in markers}
    assert {
        "First follower slowdown",
        "Suspected causal event",
        "Congestion threshold reached",
        "Peak congestion",
    } <= labels
    assert "Congestion cleared" not in labels
    assert all(a["timestamp"] <= b["timestamp"] for a, b in zip(markers, markers[1:], strict=False))
