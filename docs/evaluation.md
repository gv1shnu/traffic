# Evaluation

Run:

```sh
python scripts/evaluate.py --output storage/evaluation.json
python scripts/fetch_indian_sample.py --count 4
python scripts/evaluate.py --indian-sample storage/datasets/uvh26 --output storage/indian-evaluation.json
```

The evaluation separates algorithm fixtures from actual model inference. Synthetic trajectories test congestion-event precision/recall, onset error, cause top-1/top-3 accuracy and unknown assignment. They do not test object detection. The onset reference is the designed physical stop of the third follower; movement smoothing creates some expected latency.

The public-data path runs the actual YOLO/ByteTrack adapter on UVH-26 validation stills and matches predicted and reference boxes by Hungarian assignment at IoU ≥ 0.5. Fine car classes are mapped to `car`, mini-bus/tempo-traveller to `bus`, light goods vehicles to `truck`, and two/three-wheelers to motorcycle/autorickshaw. Missing unsupported categories count against recall. Person precision/recall cannot be measured because UVH-26 provides vehicle labels only.

Downloads are a bounded lexicographic sample, **not a representative benchmark**. The dataset has rider-inclusive two-wheeler boxes while COCO often separates riders, so IoU mismatch is a meaningful limitation. Throughput excludes model initialization but includes decoding and detector/tracker calls. It is hardware- and inference-size-specific.

`docs/evaluation-results.json` records the run performed during development, including per-image totals, class counts and scope. No real causal accuracy is claimed. The report explicitly marks tracking ID switches, real cause ranking, plate exact/character accuracy and human evidence-quality ratings as unmeasured until suitable ground truth exists.

For a serious evaluation, hold out entire Indian cameras, day/night periods and junctions; label temporal identities, event onset/clearance, candidate causes, plate transcription (including unreadable), and evidentiary quality. Separate difficult negatives such as red-light queues, parked roadside vehicles and moving cameras. Report per-class and scene-stratified precision/recall, ID switches, event timing error, unknown precision/recall and calibration curves. Reviewer corrections form a useful exportable labelling seed, not unquestionable ground truth.
