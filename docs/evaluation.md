# Evaluation

Run:

```sh
python scripts/evaluate.py --output storage/evaluation.json
python scripts/simulate.py --output storage/simulation-evaluation.json
python scripts/fetch_indian_sample.py --count 4
python scripts/evaluate.py --indian-sample storage/datasets/uvh26 --output storage/indian-evaluation.json
```

The evaluation separates algorithm fixtures from actual model inference. Synthetic trajectories test congestion-event precision/recall, onset error, cause top-1/top-3 accuracy and unknown assignment. They do not test object detection. The onset reference is the designed physical stop of the third follower; movement smoothing creates some expected latency.

## Simulated reasoning-layer battery

`scripts/simulate.py` runs a larger labelled battery (`packages/evaluation/scenarios.py`)
through the real congestion and attribution logic. A lightweight car-following model
generates ten scenarios — lead-vehicle stall, stalled autorickshaw, pedestrian and
animal obstruction, a stall beside a free-flowing lane, a horizontal-lane blockage, a
signal (red-light) queue, an already-jammed clip, free flow and a below-threshold lone
stop — each carrying ground truth by construction, with the congestion onset time
measured from the kinematics. It reports detection precision/recall, cause top-1
accuracy, top-3 recall, committed-cause precision, onset MAE, and the safety metrics
`false_blame_rate` (no-cause scenarios wrongly assigned a subject) and
`deferred_true_causes`.

This measures the **reasoning layer only**. Agents are kinematic boxes, so it says
nothing about real detection recall, occlusion, tracking ID switches or plate accuracy;
those still require real footage.

The first harness runs showed reliable detection and zero false blame, but cause top-1 of
only 0.33: the immediate follower scored close to the true lead subject, so the margin
gate deferred clear stalls to `unknown`. Two defects were behind this and are now fixed.
The follower-precedence check required a downstream stop more than 0.5 s earlier, which
missed a follower stopping one 5 FPS sample (0.2–0.4 s) behind the leader; it now uses a
0.1 s margin. Separately, the simulator's car-following ignored lanes, so in
`adjacent_lane_flows` lane-1 cars braked for faster lane-2 traffic and the scenario's
ground truth did not hold. With lane-correct kinematics, the red-light leader looked like
a stall, so attribution also gained a counter-evidence gate: when the adjacent lanes are
halted at the same time, a shared control such as a signal is the likelier explanation
and confidence is capped below the selection threshold. Current results are in
`docs/simulation-evaluation.json` (top-1 1.0, top-3 1.0, zero false blame, zero deferred
true causes on the ten scenarios). These scenarios are small and were used to find the
defects, so treat them as regression checks rather than an accuracy estimate.

The public-data path runs the actual YOLO/ByteTrack adapter on UVH-26 validation stills and matches predicted and reference boxes by Hungarian assignment at IoU ≥ 0.5. Fine car classes are mapped to `car`, mini-bus/tempo-traveller to `bus`, light goods vehicles to `truck`, and two/three-wheelers to motorcycle/autorickshaw. Missing unsupported categories count against recall. Person precision/recall cannot be measured because UVH-26 provides vehicle labels only.

Downloads are a bounded lexicographic sample, **not a representative benchmark**. The dataset has rider-inclusive two-wheeler boxes while COCO often separates riders, so IoU mismatch is a meaningful limitation. Throughput excludes model initialization but includes decoding and detector/tracker calls. It is hardware- and inference-size-specific.

`docs/evaluation-results.json` records the run performed during development, including per-image totals, class counts and scope. No real causal accuracy is claimed. The report explicitly marks tracking ID switches, real cause ranking, plate exact/character accuracy and human evidence-quality ratings as unmeasured until suitable ground truth exists.

For a serious evaluation, hold out entire Indian cameras, day/night periods and junctions; label temporal identities, event onset/clearance, candidate causes, plate transcription (including unreadable), and evidentiary quality. Separate difficult negatives such as red-light queues, parked roadside vehicles and moving cameras. Report per-class and scene-stratified precision/recall, ID switches, event timing error, unknown precision/recall and calibration curves. Reviewer corrections form a useful exportable labelling seed, not unquestionable ground truth.
