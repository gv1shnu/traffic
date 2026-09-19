# Resume guide for Claude

Short, current continuation notes. The original mandate and product vision are in
[`docs/project-brief.md`](project-brief.md); the first-handoff audit is in
[`docs/claude-handoff.md`](claude-handoff.md). This file is the up-to-date entry point.

## Working rules (unchanged, important)

- Git version control. **No assistant/AI name or attribution in commit messages or PRs.**
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

- Branch: **`master`** (renamed from `codex/traffic-investigator`), remote `origin`
  (github.com/gv1shnu/traffic). Repo default branch is `main`.
- Baseline verified and committed; two substantive changes landed this cycle:
  1. **VFR timestamp fix** — `detect_and_track` now reads each frame's real presentation
     time (`CAP_PROP_POS_MSEC`) instead of a uniform `index/fps` grid, so
     variable-frame-rate footage stays aligned with presentation-time evidence seeking.
     Regression test: `tests/test_integration.py::test_detect_and_track_uses_real_frame_timestamps`.
  2. **Simulated reasoning-layer evaluation harness** — `packages/evaluation/simulation.py`
     (car-following simulator), `packages/evaluation/scenarios.py` (10 labelled scenarios),
     `scripts/simulate.py` (metrics), `tests/test_simulation.py`, and
     `scripts/render_previews.py` (README GIFs). Report: `docs/simulation-evaluation.json`.

## How to verify (no services needed — tests use SQLite)

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy apps/api apps/worker packages
uv run pytest -q                     # 40 backend tests
npm --prefix apps/web run lint && npm --prefix apps/web test && npm --prefix apps/web run build
make simulate                        # reasoning-layer metrics
make previews                        # regenerate docs/previews/*.gif
```

## Environment blockers (as of this cycle)

- **Docker is not installed** on the dev host → acceptance criterion #16 (Compose
  end-to-end) is unverified here. Install Docker or run the native stack to close it.
- Native Postgres/Redis were not started in the last session, so the live end-to-end
  smoke is pending. Commands are in `docs/claude-handoff.md` §10.

## Highest-value next steps (in order)

1. **Attribution: lead/follower separation.** The simulator shows detection 1.0/1.0 and
   zero false blame, but cause **top-1 ≈ 0.33**: in dense queues the immediate follower
   scores close to the true lead subject, so the `cause_margin` gate defers clear stalls
   to `unknown` (true subject is always in the top-3). Root cause: the `prior_downstream`
   follower-precedence penalty in `packages/cause_attribution/scoring.py` is applied
   inconsistently to the immediate follower. Fix it, then re-run `make simulate` and the
   existing `tests/test_analysis.py` precedence tests to confirm gains without regressions.
2. **Detection on real Indian data.** Fine-tune / evaluate on UVH-26 (CC BY 4.0, already
   fetched) and BMD-45 images; add an explicit label→taxonomy map incl. autorickshaw.
   No public Indian dataset has fixed-camera video with cause/timing labels, so real data
   validates perception only — the reasoning layer stays on the simulator.
3. **Deployment**: verify Docker Compose end to end once Docker is available.
4. Multiple-incident reporting, and missing automatic cause detectors (collision, lane
   blockage, debris, flooding, signal failure) with corroboration beyond box overlap.

## Data landscape (verified 2026-09)

- Images (detector fine-tuning): **UVH-26** CC BY 4.0 (in use), **BMD-45** (Bengaluru CCTV).
- Video w/ tracks: **TrafficMOT** (fixed-cam, 8 Indian cities, has auto/e-rickshaw) but
  30-frame clips and no cause labels; license unposted — report the boundary, don't scrape.
- **DriveIndia** dashcam images, CC BY-NC-ND (wrong viewpoint, non-commercial). **IDD** dashcam.
- Simulation strategy: "sim validates the brain, real data validates the eyes." CARLA+SUMO
  can give perfect ground-truth fixed-camera video but lacks autorickshaw assets / Indian
  non-lane behaviour (sim2real gap), so photoreal perception sim is limited-payoff.
