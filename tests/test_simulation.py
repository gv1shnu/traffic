from packages.evaluation.scenarios import battery
from packages.evaluation.simulation import run
from scripts.simulate import evaluate_simulation


def test_battery_runs_and_measures_onset():
    scenarios = battery()
    assert len(scenarios) == 10
    for scenario in scenarios:
        rows, gt = run(scenario)
        assert rows, scenario.name
        # A congested scenario must have a kinematically-measured onset time.
        if gt.congestion and gt.cause_type is not None:
            assert gt.onset_seconds is not None, scenario.name


def test_reasoning_layer_invariants():
    report = evaluate_simulation()
    det = report["detection"]
    attr = report["attribution"]
    unknown = report["unknown_handling"]

    # Detection of sustained congestion is reliable on these labelled scenarios.
    assert det["precision"] == 1.0
    assert det["recall"] == 1.0

    # Safety: the system never blames a subject when there is no attributable cause,
    # and every cause it commits to is the correct one.
    assert unknown["false_blame_rate"] == 0.0
    assert attr["committed_precision"] == 1.0

    # The true subject is always present in the ranked top three (evidence is found),
    # even when the system conservatively defers the final commit to "unknown".
    assert attr["cause_top3_recall"] == 1.0
    assert 0.0 <= attr["cause_top1_accuracy"] <= 1.0
    assert attr["onset_mae_seconds"] is not None

    keys = {"scope", "detection", "attribution", "unknown_handling", "scenarios"}
    assert keys <= set(report)


def test_no_false_positive_on_signal_and_free_flow():
    report = evaluate_simulation()
    by_name = {d["scenario"]: d for d in report["scenarios"]}
    # A normal signal queue and an already-jammed clip must not blame a subject.
    for name in ("red_light_queue", "already_congested"):
        assert by_name[name]["predicted"]["suspect_track"] is None, name
    # Free flow and a lone stop below the vehicle floor are not congestion.
    for name in ("free_flow", "sparse_stalled"):
        assert by_name[name]["predicted"]["congestion"] is False, name


def test_immediate_follower_is_not_credited_as_the_cause():
    report = evaluate_simulation()
    by_name = {d["scenario"]: d for d in report["scenarios"]}
    # The lead subject stops one sample before its immediate follower; the follower
    # must be recognised as queued behind it rather than tie with it.
    for name in ("stalled_car", "animal_obstruction", "lane_blockage_horizontal"):
        assert by_name[name]["predicted"]["suspect_track"] == 1, name
    assert report["attribution"]["cause_top1_accuracy"] == 1.0


def test_vehicles_only_follow_leaders_in_their_own_lane():
    scenario = next(s for s in battery() if s.name == "adjacent_lane_flows")
    rows, _ = run(scenario)
    # Lane 1 is free-flowing until track 1 stalls at 3 s; its vehicles must hold
    # cruise speed (45 px/s, 9 px per sample) rather than brake for adjacent traffic.
    for tid in (1, 2, 3):
        track = [o for o in rows if o.track_id == tid and 2.0 <= o.timestamp <= 2.8]
        steps = [a.bbox[1] - b.bbox[1] for a, b in zip(track, track[1:], strict=False)]
        assert min(steps) > 8.0, (tid, steps)
