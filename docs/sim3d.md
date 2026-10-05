# Rendered 3D simulation

A showcase and end-to-end test bed that needs no real footage. Labelled traffic
scenarios are simulated, rendered as fixed-CCTV video in Blender, and analysed by the
**real** detector (YOLO11n + ByteTrack) and the **unmodified** investigation pipeline.
The simulation's ground truth is used only to score the result.

> Rendered scenes are cleaner than real cameras (no rain, night, glare, compression or
> shake). Results here show the system working end to end; they are not a real-world
> accuracy claim.

## What is simulated

`packages/simulation3d/traffic.py` is a world-space microsimulation of a two-way urban
street with footpaths. Traffic keeps left. Vehicles follow the Intelligent Driver Model
behind whatever is ahead in their lane (another vehicle, a stalled subject, a pedestrian
standing in the carriageway, or a red signal's stop line). Arrivals are an Indian urban
mix of cars, motorcycles/scooters, autorickshaws, buses and trucks, with pedestrians on
both footpaths.

| Scenario | Scripted event | Correct answer |
|---|---|---|
| `stalled_car` | A car breaks down in the near lane; oncoming traffic prevents passing | stalled vehicle, that car |
| `stalled_autorickshaw` | An autorickshaw stops in the near lane | stalled vehicle, that autorickshaw |
| `pedestrian_obstruction` | A pedestrian steps off the footpath and stays in the lane | pedestrian obstruction, that person |
| `red_light_queue` | A red signal holds the near lane | congestion, cause `unknown` |
| `free_flow` | Normal traffic | no sustained congestion |

Ground truth (cause subject, its stop time and the measured queue onset) is fixed by
construction and exported with the trajectories.

## Rendering

`scripts/sim3d/blender_scene.py` runs inside Blender 4.5 (headless, Cycles on CPU):

- A street with textured asphalt, pavers, black-and-yellow painted kerbs, a zebra
  crossing and signal, shopfronts with signage, jacaranda trees and street lamps, lit by
  an HDRI sky and sun.
- Road users are third-party CC BY 4.0 models (cars, autorickshaw, scooters and
  motorcycles with riders, buses, trucks, pedestrians, some with walk cycles), re-scaled,
  re-oriented and given Indian-format number plates. See [credits](sim3d-assets.md).
- A pole-mounted camera 6.5 m above the near footpath, 960×540 at 10 FPS.
- Per frame, every subject's 2D box is projected from its convex hull, with a ray-cast
  visibility fraction, into `ground_truth.json` along with the image-space lane regions.

**Asset selection.** About 170 candidate models were downloaded, rendered individually from
a CCTV-like angle and inspected. Models were chosen for realism, correct geometry and
licence (CC BY or CC0 only; ShareAlike and NonCommercial excluded). Detector scores on
those screening renders were one input to that choice, which favours recognisable
models; the detection numbers below should be read with that selection in mind.

## Analysis

`scripts/analyze_3d.py` uploads the rendered MP4 through the HTTP API (in process, with an
isolated SQLite database), stores the projected lane regions as the camera configuration,
and runs the same `Investigation` the Celery worker runs with the real model. No ground
truth is passed to the pipeline.

`packages/simulation3d/evaluate.py` then scores, on every frame the pipeline sampled:

- detection recall and precision at IoU ≥ 0.5 for subjects at least 50% visible and
  20 px tall (detections matching any ground-truth subject are never false positives);
- track ID switches for matched subjects;
- congestion detected vs truth and onset error;
- whether the suspected track is the scripted subject (or `unknown` when expected).

`scripts/render_showcase.py` draws the pipeline's tracks (green moving, amber
slowing/stationary, red suspected cause), the monitored lane, the congestion interval
and timeline markers. Boxes are inferred at 5 FPS and interpolated between samples for
display.

## Reproduce

```sh
uv sync --extra dev --extra vision
uv run python scripts/download_models.py
uv run python scripts/sim3d/fetch_assets.py          # ~1.7 GB of models and textures
export BLENDER=/path/to/blender-4.5/blender

uv run python scripts/render_3d.py stalled_car        # ~15 s per frame on 4 CPU cores
uv run python scripts/analyze_3d.py storage/sim3d/stalled_car
uv run python scripts/render_showcase.py storage/sim3d/stalled_car --gif
uv run python scripts/build_site.py                    # site/ and docs/sim3d-evaluation.json
```

Rendering is resumable; re-running `render_3d.py` keeps finished frames.

## Results

Machine-readable: [`docs/sim3d-evaluation.json`](sim3d-evaluation.json). One run per
scenario, no re-rolls; failures are reported as they occurred.

| Scenario | Congestion (truth → pipeline) | Cause | Outcome |
|---|---|---|---|
| `stalled_car` | yes → yes (onset 3.2 s early) | track #14, the scripted car, 0.93 | correct |
| `stalled_autorickshaw` | yes → yes (onset 0.1 s late) | track #26, the scripted autorickshaw, 0.93 | correct |
| `pedestrian_obstruction` | yes → **no** | none | missed |
| `red_light_queue` | yes → **no** | none (expected `unknown`) | right answer, wrong reason |
| `free_flow` | no → no | none | correct |

Detection recall on required subjects (≥ 50% visible, ≥ 20 px, IoU ≥ 0.5) across all
sampled frames, with sample counts:

| car | autorickshaw | person | bus | truck | motorcycle |
|---|---|---|---|---|---|
| 90% (1278) | 84% (797) | 77% (419) | 74% (313) | 47% (285) | **17%** (886) |

Overall recall 67%, precision 81%, 49 track ID switches over five clips.

**What failed and why.**

- *Pedestrian obstruction:* a dump truck queued directly beneath the camera (239 px
  tall, 81% visible) is not detected at that steep viewing angle and hides the vehicles
  behind it. The pipeline sees one queued vehicle in the lane, below the four needed to
  confirm congestion. The pedestrian is tracked.
- *Signal queue:* the queue is mostly scooters and motorcycles. Riders are detected as
  people, the two-wheelers almost never, so too few stopped vehicles are counted. The
  `unknown` answer is correct but not because the signal queue was recognised; it is
  scored as a failure.
- Two-wheeler detection is the clearest weakness of the generic COCO detector on Indian
  traffic. The simple rider figure used here may make it worse than real footage, but a
  domain-trained detector (two-wheelers, autorickshaws) remains the highest-value
  improvement.

**Pipeline fixes found with this test bed** (each with regression tests):

1. The tracking-quality gate is applied when selecting a cause, so a report never names a
   suspect below the selection threshold.
2. Tracking quality measures track continuity and box stability instead of mean
   detector confidence (which rejected most correctly tracked vehicles).
3. Congestion persistence tolerates brief occlusion dropouts.
4. Temporal precedence and follower response use each track's full history, so a subject
   that stopped well before the confirmed onset keeps its precedence.
