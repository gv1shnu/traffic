from packages.simulation3d.evaluate import evaluate, iou, match_frame
from packages.simulation3d.scenarios import SCENARIOS
from packages.simulation3d.traffic import NEAR_X, run


def test_scenarios_produce_their_ground_truth():
    for name, scenario in SCENARIOS.items():
        frames, truth = run(scenario)
        assert len(frames) == int(round(scenario.duration * 10)), name
        assert truth.congestion == (name != "free_flow"), name
        if scenario.cause_type is None:
            assert truth.cause_agent is None, name
        else:
            # The scripted subject stops early in the clip and the queue forms after it.
            assert truth.cause_stop_time is not None and 0 < truth.cause_stop_time < 8, name
            assert truth.onset_seconds is not None and truth.onset_seconds > truth.cause_stop_time


def test_simulation_is_deterministic():
    a, ta = run(SCENARIOS["stalled_car"])
    b, tb = run(SCENARIOS["stalled_car"])
    assert ta == tb
    assert a[-1].agents == b[-1].agents


def test_stalled_subject_holds_position_and_followers_queue_behind_it():
    frames, truth = run(SCENARIOS["stalled_car"])
    end = frames[-1]
    cause = next(a for a in end.agents if a["id"] == truth.cause_agent)
    assert cause["speed"] == 0.0
    near = [a for a in end.agents if abs(a["x"] - NEAR_X) < 1.0 and a["kind"] != "person"]
    queued = [a for a in near if a["speed"] < 0.5 and a["y"] < cause["y"]]
    assert len(queued) >= 4
    # Nobody passes through the stalled subject in the near lane.
    assert all(a["y"] <= cause["y"] for a in near if a["id"] != cause["id"])


def test_iou_and_family_matching():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    subjects = [
        {"id": 1, "kind": "autorickshaw", "bbox": (0, 0, 10, 10)},
        {"id": 2, "kind": "person", "bbox": (50, 50, 60, 70)},
    ]
    detections = [
        {"object_type": "car", "bbox": (0, 0, 10, 11), "track_id": 7},
        {"object_type": "car", "bbox": (50, 50, 60, 70), "track_id": 8},
    ]
    # An autorickshaw detected as a car is a vehicle match; a person box is not.
    assert match_frame(subjects, detections) == [(0, 0, iou((0, 0, 10, 10), (0, 0, 10, 11)))]


def test_evaluate_scores_cause_through_track_matching():
    gt = {
        "truth": {
            "congestion": True,
            "cause_type": "stalled_vehicle",
            "cause_agent": 5,
            "onset_seconds": 1.0,
        },
        "frames": [
            {
                "t": 0.0,
                "subjects": [{"id": 5, "kind": "car", "bbox": [0, 0, 40, 30], "visible": 1.0}],
            },
            {
                "t": 0.2,
                "subjects": [{"id": 5, "kind": "car", "bbox": [0, 0, 40, 30], "visible": 1.0}],
            },
        ],
    }
    obs = [
        {"track_id": 3, "object_type": "car", "bbox": [1, 0, 40, 30], "timestamp": 0.0},
        {"track_id": 3, "object_type": "car", "bbox": [1, 0, 40, 30], "timestamp": 0.2},
    ]
    report = {
        "cause": {"suspected_track_id": 3, "type": "stalled_vehicle"},
        "congestion": {"detected": True, "start_seconds": 1.4},
    }
    result = evaluate(gt, obs, report)
    assert result["detection"]["recall"] == 1.0
    assert result["tracking"]["id_switches"] == 0
    assert result["cause"]["correct"] is True
    assert result["congestion"]["onset_error_seconds"] == 0.4
    report["cause"]["suspected_track_id"] = 9
    assert evaluate(gt, obs, report)["cause"]["correct"] is False
