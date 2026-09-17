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
