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

See [`docs/sim3d-evaluation.json`](sim3d-evaluation.json) and the showcase site.
