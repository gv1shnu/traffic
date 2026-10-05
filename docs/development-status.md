# Development status

Short, current development status. The original mandate and product vision are in
[`docs/project-brief.md`](project-brief.md); the first-handoff audit is in
[`docs/development-handoff.md`](development-handoff.md). This file is the up-to-date entry point.

## Working rules (unchanged, important)

- Git version control with ordinary engineering commit messages.
- Run things end to end; do not stop at plans. Prefer measurable progress and honest
  evidence over features that merely look complete.
- Do not invent detections, plates, timestamps, confidence values or metrics. Synthetic
  adapters and the simulator are for tests/evaluation only and must never be substituted
  into the production pipeline.
- Return `unknown` when evidence is insufficient. Use "suspected"/"likely cause", never
  enforcement or guilt language. No paid LLM key; core analysis must work without an LLM.
- Project use is **non-commercial / research** — CC BY-NC-ND datasets (e.g. DriveIndia)
  are usable for detector fine-tuning with attribution.

## Current branch and state

- Branch: **`master`**, remote `origin`
  (github.com/gv1shnu/traffic). This is the repository's default branch.
- Baseline verified and committed; two substantive changes landed this cycle:
  1. **VFR timestamp fix** — `detect_and_track` now reads each frame's real presentation
     time (`CAP_PROP_POS_MSEC`) instead of a uniform `index/fps` grid, so
     variable-frame-rate footage stays aligned with presentation-time evidence seeking.
     Regression test: `tests/test_integration.py::test_detect_and_track_uses_real_frame_timestamps`.
  2. **Simulated reasoning-layer evaluation harness** — `packages/evaluation/simulation.py`
     (car-following simulator), `packages/evaluation/scenarios.py` (10 labelled scenarios),
     `scripts/simulate.py` (metrics), `tests/test_simulation.py`, and
     `scripts/render_previews.py` (README GIFs). Report: `docs/simulation-evaluation.json`.

## Rendered 3D simulation (this cycle)

`packages/simulation3d`, `scripts/sim3d/`, `scripts/{render_3d,analyze_3d,render_showcase,build_site}.py`
render labelled scenarios in Blender and run the real pipeline on them; see
[`docs/sim3d.md`](sim3d.md). Result: 3/5 scenarios correct; two-wheeler detection (17%
recall) and large vehicles seen from above are the main failures. Four pipeline fixes
came out of it (cause gate placement, tracking-quality definition, occlusion-tolerant
persistence, full-history precedence).

## How to verify (no services needed — tests use SQLite)

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy apps/api apps/worker packages
uv run pytest -q                     # 51 backend tests
npm --prefix apps/web run lint && npm --prefix apps/web test && npm --prefix apps/web run build
make simulate                        # reasoning-layer metrics
make previews                        # regenerate docs/previews/*.gif
```

## Environment blockers (as of this cycle)

- **Docker Compose verified end to end on 2026-10-05** (Colima on Apple Silicon): build,
  model download, `up`, `/health` + `/ready` via port 8080, and the HTTP smoke test with real
  worker inference. Acceptance criterion #16 is closed; the CI `compose` job also passes.
  Fixes from that run: one shared backend image instead of four identical builds, CPU
  PyTorch wheels by default (site-packages 6.2 GB → 1.8 GB), and `/ready` proxied by nginx.
- Native Postgres/Redis were not started in the last session, so the live end-to-end
  smoke is pending. Commands are in `docs/development-handoff.md` §10.

## Iteration closed (2026-10-05)

Merged to `master` in gv1shnu/traffic#1: rendered 3D showcase (3/5 scenarios correct, two
failures reported), four attribution fixes, and the static site, published at
https://www.vishnugandarapu.in/traffic/ by the "Showcase site" workflow. Docker Compose was
verified end to end (see above); the 2D signal-queue preview was regenerated after the
lane-following fix; the workspace screenshot was recaptured.

## Next iteration (in order)

1. **Indian-traffic detector.** Train/fine-tune for two-wheelers (17% recall now), an
   autorickshaw class, and large vehicles seen from above. Use the 3D simulator to generate
   labelled training images alongside UVH-26 / BMD-45.
2. **Re-run the 3D scenarios** with the new detector and compare against
   `docs/sim3d-evaluation.json`.
3. **More scenes:** night, rain, junction, animal, and realistic riders.
4. **Fewer track ID switches** (49 over five clips).

Still open from earlier: multiple-incident reporting, and automatic detectors for collision,
lane blockage, debris, flooding and signal failure.

## Data landscape (verified 2026-09)

- Images (detector fine-tuning): **UVH-26** CC BY 4.0 (in use), **BMD-45** (Bengaluru CCTV).
- Video w/ tracks: **TrafficMOT** (fixed-cam, 8 Indian cities, has auto/e-rickshaw) but
  30-frame clips and no cause labels; license unposted — report the boundary, don't scrape.
- **DriveIndia** dashcam images, CC BY-NC-ND (wrong viewpoint, non-commercial). **IDD** dashcam.
- Simulation strategy: "sim validates the brain, real data validates the eyes." CARLA+SUMO
  can give perfect ground-truth fixed-camera video but lacks autorickshaw assets / Indian
  non-lane behaviour (sim2real gap), so photoreal perception sim is limited-payoff.
