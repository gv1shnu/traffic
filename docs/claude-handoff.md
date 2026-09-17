# Continuation prompt for Claude

You are taking over an existing project: **Traffic Cause Investigator**. Continue the implementation in place, audit it critically, and bring it to the original acceptance criteria. Do not restart from scratch or stop at an architecture proposal.

## 1. User intent and working rules

The user wants a complete, portfolio-quality browser application for investigating why traffic congestion happened, with Indian traffic as the primary context. The original instructions are preserved in **`docs/project-brief.md`**. Read that file before deciding what “complete” means.

Additional user requirements:

- Use Git version control.
- Do not put your name, another assistant's name, or assistant attribution in commit messages.
- Work end to end and run the application; do not merely provide plans.
- Fetch necessary datasets from public sources yourself, respecting their terms and retaining attribution.
- Keep Indian mixed traffic central: motorcycles, scooters, autorickshaws, pedestrians, animals, heterogeneous vehicle sizes, occlusion and non-lane-disciplined movement.
- Do not invent detections, plates, incident timestamps, confidence values or evaluation metrics. Synthetic adapters belong only in tests. Never silently substitute them into production.
- Return `unknown` when cause evidence is insufficient. Use “suspected traffic-causing subject” or “likely cause,” never guilt or enforcement language.
- No paid LLM API key may be required. Numerical traffic analysis and attribution must work without an LLM.
- Preserve useful existing implementation, test it, fix failures, and make incremental commits with ordinary engineering descriptions.

## 2. Product vision

A reviewer uploads fixed-camera traffic footage. The backend processes it asynchronously and determines whether sustained congestion occurred, where and approximately when it originated, and which visible subject is a plausible cause. It ranks alternatives, exposes its evidence and uncertainty, and never forces a conclusion.

The reviewer should receive:

1. A playable browser-compatible video with tracked boxes and IDs.
2. Congestion timing, region, severity, queue metrics and clickable timeline markers.
3. A suspected subject and an explanation grounded in measured temporal/spatial evidence.
4. A readable plate only when independent detector/OCR/quality/consensus checks support it.
5. Otherwise, a clear `null` plate and the best original/annotated subject frame.
6. Before/during/after evidence, a short clip, alternative candidates and downloadable JSON.
7. Controls to confirm, reject or correct the cause, plate or selected track, preserving original computed evidence and recording review history for later labelling.

The application is decision support, not autonomous enforcement. Retain the visible disclaimer from the original brief.

## 3. Exact repository state at handoff

Working directory:

```text
/Users/skillmaxxing/Dev/traffic
```

Current branch:

```text
codex/traffic-investigator
```

There is one existing commit:

```text
e9e858b Build asynchronous traffic investigation application with evidence and review
```

**Important: substantial later work is present but uncommitted.** Do not discard it, reset to HEAD, or assume untracked files are disposable. At handoff, modified files include the Dockerfile, API, Nginx config, processing UI, worker tasks, evaluation metrics, settings, congestion/pipeline code and tests. Untracked work includes README, documentation, CI, Makefile, evaluation/download/smoke scripts, timeline module, additional tests, `uv.lock`, and this handoff.

Start with `git status --short`, `git diff`, and a read of relevant untracked files. Verify the entire working tree before making a continuation checkpoint commit. Do not commit `.env`, videos, public dataset images, weights, databases, caches or virtual environments.

## 4. Honest progress assessment

This is a **substantial working MVP and integration foundation**, not a completed or field-validated implementation of every requirement. Avoid a precise completion percentage: engineering coverage and real-world ML validity are very different here.

| Area | Current state |
|---|---|
| Browser upload/configuration/progress/results/review | Implemented; browser workflow exercised |
| FastAPI, SQL entities, Alembic, Celery, Redis | Implemented; native PostgreSQL/Redis/worker flow exercised |
| Real YOLO and ByteTrack adapters | Implemented; inference exercised |
| Motion and congestion rules | Implemented; deterministic fixtures tested |
| Explainable candidate scoring and unknown fallback | Implemented; synthetic causal cases tested |
| Plate detector, OCR and consensus | Implemented; model loading tested, acceptance paths tested with explicit test injection |
| Evidence frames, clips and report export | Implemented; integration exercised |
| Indian-domain validation | Only a four-image public still-image diagnostic; not sufficient |
| Specialist cause taxonomy | Schema/review support is broader than automatic detectors |
| Docker Compose | Files and CI exist; build/run was not locally verified |
| Authentication/public hosting security | Not implemented; local single-user workspace only |
| Full original acceptance criteria | Not yet demonstrated |

The most important remaining work is **real-world reliability, missing detector capabilities, robust lifecycle handling, and deployment verification**, not another UI rewrite.

## 5. Existing architecture and file map

Backend: Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, Redis and Celery.

ML: OpenCV/FFmpeg, PyTorch/Ultralytics YOLO11n, ByteTrack, a separate YOLOv8 plate model, EasyOCR and an actual LangGraph `StateGraph`. scikit-learn is used in evaluation; it is not currently a learned causal model.

Frontend: React, TypeScript, Vite, Tailwind, TanStack Query, React Router, HTML5 video and SVG overlays/editor.

Read these first:

```text
README.md
docs/project-brief.md
docs/verification.md
docs/architecture.md
docs/cause-attribution.md
docs/plate-recognition.md
docs/privacy-and-security.md
docs/evaluation.md
docs/data-sources.md
```

Implementation map:

```text
apps/api/main.py                    REST, SSE, uploads, reports, reviews, API docs
apps/api/security.py                Pre-multipart request body limit
apps/api/lifecycle.py               Related-row and media deletion
apps/worker/tasks.py                Celery tasks, PostgreSQL job lock, retention
apps/web/src/UploadPage.tsx          File validation/upload and recent work
apps/web/src/ConfigurePage.tsx       Camera polygons and directions
apps/web/src/ProcessingPage.tsx      Real job state and skipped stages
apps/web/src/ResultsPage.tsx         Video, timeline, evidence and reviews
packages/shared/schemas.py          Validated observation/report/review contracts
packages/shared/db.py               SQLAlchemy entities
packages/shared/config.py           Environment settings and threshold loading
packages/shared/storage.py          Local storage boundary and safe path resolution
packages/vision/video.py            Header/probe/normalization/frame extraction
packages/vision/detector.py         Real YOLO + persistent ByteTrack adapter
packages/vision/quality.py          Image-quality heuristic
packages/tracking/motion.py         Relative movement and stationary duration
packages/traffic_analysis/congestion.py
packages/cause_attribution/scoring.py
packages/plate_recognition/ocr.py
packages/workflows/investigate.py   Conditional investigation pipeline
packages/workflows/timeline.py      Measured incident markers
packages/evaluation/metrics.py      IoU matching and character-distance metrics
config/analysis.json                Congestion thresholds, scoring weights, plate patterns
fixtures/synthetic.py               Explicit test fixtures, never production fallback
scripts/download_models.py
scripts/fetch_indian_sample.py
scripts/evaluate.py
scripts/generate_fixtures.py
scripts/smoke_http.py
```

The pipeline validates/normalizes, samples at 5 FPS by default, detects/tracks, estimates motion, detects persistent queues, generates/ranks candidates, conditionally attempts plate OCR, generates evidence, checks quality and persists a report. Conditional branches skip candidate/OCR stages when inapplicable.

Jobs snapshot thresholds and camera regions. Tracking output is atomically checkpointed and reused on retry. Other deterministic stages replay; this is **not a durable LangGraph checkpointer at every node**. Completed jobs are idempotent. PostgreSQL advisory locks prevent concurrent execution of the same job. Each analysis has its own normalized media URL, avoiding references to another attempt's video.

## 6. Implemented algorithm behavior

- Motion uses displacement over approximately one second, normalized by subject box size. It is not real km/h unless calibration exists. Calibration can be supplied through the API, but the browser does not edit it.
- Congestion combines minimum vehicle count, median movement, slow fraction, union occupancy, persistence and queue growth. Sparse stopped vehicles do not suffice.
- Pre-existing congestion may be detected after longer persistence, but often lacks causal precedence and returns unknown.
- Attribution combines precedence, downstream position, approximate blockage, stationary duration, follower response, upstream propagation, adjacent-region motion and track confidence.
- Missing precedence/follower corroboration caps scores. A subject stopped behind an earlier downstream stop is penalized as a follower.
- Whole-road fallback caps cause confidence below the selection threshold. Draw direction-configured regions to enable meaningful attribution.
- Similar leading candidates return unknown.
- Plate OCR uses a separate detector's measured confidence, image quality, EasyOCR confidence, format filtering and distinct-frame agreement. It does not fill uncertain characters.
- Standard Indian formats and BH-series patterns are configured. Raw readings remain separate from accepted text.
- Evidence quality combines sharpness, size, exposure, contrast, confidence and boundary clearance; it does not directly estimate true occlusion or viewing angle.
- Timeline includes measured causal/slowdown/threshold/peak events when available. It claims clearance only when later movement supports it; otherwise it says “Last observed congestion.”

## 7. Verification already performed

Last recorded checks:

- **36 backend tests passed**.
- **8 frontend tests passed**.
- Ruff lint and formatting passed.
- mypy passed for API, worker and packages.
- ESLint passed.
- TypeScript/Vite production build passed.
- Prettier check passed.
- `uv lock --check` passed.
- Native PostgreSQL + Redis + Celery + HTTP upload/report/review smoke passed.
- Browser upload, camera configuration entry, live processing, report access and persisted human review were exercised.
- Mobile layout/navigation was checked at 390×844 without horizontal overflow.
- The actual plate model and EasyOCR loaded; blank image yielded no reading.
- The self-contained `/docs` OpenAPI reference served correctly without CDN scripts.

One upstream Starlette/AnyIO deprecation warning appeared; no test failures remained in that run.

**Do not overstate what these prove:**

The confirmed real background-job smoke used an 18-second synthetic video. It completed in 6.07 seconds, with zero detected tracks, no congestion, a null plate, evidence retrieval and a saved review. This proves infrastructure integration, not positive vehicle recognition or causal accuracy.

Tests for known causes and recognized plate linking explicitly inject synthetic adapters/OCR in test code. They do not establish field accuracy.

A final positive-detection smoke was started using `storage/fixtures/uvh26_still_tracking_smoke.mp4`, created by repeating one public Indian image and visibly labelling it as a still-image smoke test. **Its final result was not confirmed before handoff.** Inspect its job/output if available or rerun it. Do not represent repeated stills as real motion footage or as a causal benchmark. Temporary `/tmp` outputs and old process/session IDs may no longer exist.

## 8. Data, models and measured limitations

Downloaded under ignored local directories:

- `models/yolo11n.pt`: actual public Ultralytics weights.
- `models/license_plate.pt`: public plate detector pinned to revision `83c98fbe7412fe8b3950adb5637cfd08b0f04809` of `Koushim/yolov8-license-plate-detection`.
- Expected plate weight SHA-256: `2d95861825bb4184404344c9cf809f40fd31dba785fe54e8ba5b9a3583789822`.
- `models/ocr/`: official EasyOCR model files.
- `storage/datasets/uvh26/`: a bounded public Indian CCTV sample, annotation subset and provenance manifest.

Dataset: `https://huggingface.co/datasets/iisc-aim/UVH-26`, AIM @ IISc, Bengaluru CCTV, CC BY 4.0. Attribution is in `docs/data-sources.md`; source URLs, revision and image hashes are in the local manifest. Do not commit those surveillance images.

Actual diagnostic result on **four** validation stills:

- Detection precision: **0.5625**.
- Detection recall: **0.50**.
- Matching IoU: **0.5**.
- Unsupported autorickshaws count as misses.
- Approximate measured throughput: 4.86 images/sec on that run, excluding model initialization; do not generalize it.

Read `docs/evaluation-results.json`. Fine vehicle classes were collapsed for comparison, and rider-inclusive two-wheeler boxes differ from COCO. This tiny lexicographic sample is not representative.

Synthetic rule fixtures achieved perfect event/top-k/unknown checks and roughly 0.6-second onset error, but these are designed logic tests. **No real Indian incident-cause accuracy, temporal ID-switch benchmark, plate exact-match accuracy, character accuracy or blinded evidence-quality study has been completed.** No neural model was trained in this project yet.

Respect model/package licensing independently of the dataset license. Inspect provenance before replacing weights; do not silently trust random model files.

## 9. Known gaps and audit priorities

Confirmed gaps:

1. Generic COCO detection lacks autorickshaws and robust Indian mixed-traffic coverage.
2. Automatic categories currently cover stopped vehicles, persistent pedestrians and supported animals. Collision, transverse lane blockage, illegal stopping, roadwork/debris, potholes, flooding and signal failure are not fully implemented automatic detectors. Schema/review categories do not count as detector support.
3. Only the most severe congestion interval is reported.
4. Causal scores are heuristic, not calibrated probabilities. A stationary vehicle does not prove mechanical failure.
5. Full-FPS event-window re-inference, batch inference, explicit occlusion scoring and perspective-aware plate rectification are incomplete or absent.
6. Cancellation is cooperative; normalization subprocesses may delay it until completion/timeout.
7. Retry durability is partial: tracking is reused, later stages replay.
8. Redaction blurs detected non-selected boxes, may miss subjects, and leaves source video unredacted.
9. Storage is not encrypted by the application. Authentication, tenant authorization, distributed rate limiting and hosted deployment controls are absent.
10. Docker Compose build/run, CUDA execution and remote GitHub Actions results are not verified.
11. Optional LLM/RAG is absent, intentionally unnecessary for core functionality.

Audit these potential correctness risks rather than assuming they are proven defects:

- Variable-frame-rate timestamps and normalization: preserve source-to-normalized timing accurately; frame index divided by nominal FPS may be insufficient.
- Tracking behavior at sampled FPS and under occlusion; stationary jitter and camera-motion effects.
- Lane-blockage geometry for horizontal/diagonal regions and perspective.
- Whether congestion onset/end and temporal windows handle gaps, clearance, repeated episodes and already-congested footage correctly.
- Candidate follower/propagation logic and its behavior at signalized intersections or queues unrelated to the selected object.
- Consistency of quality-gated cause selection, plate acceptance, fallback evidence and report fields.
- Race conditions around enqueue failure, cancellation, retry, deletion, retention and worker death.
- Chunked body limits, multipart cleanup, decode resource exhaustion and malformed inputs.
- Evidence-player alignment, stale SSE/poll snapshots, failed-upload/retry UX and accessibility of the polygon editor.
- Whether Compose installation copies/installs all fixture/script/package dependencies correctly and uses the intended model volumes.
- Reproducibility of runtime dependencies versus lockfiles and documentation.

## 10. Local execution and commands

Check what is running; prior sessions have restarted during development. Do not assume services or browser handles survive.

This prepared checkout's ignored `.env` uses:

```text
PostgreSQL: 127.0.0.1:54329, database/user traffic
Redis:      127.0.0.1:6389
API:        127.0.0.1:8000
Frontend:   127.0.0.1:5173
Storage:    storage/media
```

Python 3.12 virtual environment, Node, FFmpeg, PostgreSQL, Redis and uv were installed/used. Inspect rather than overwrite `.env`.

If the local services are stopped:

```sh
pg_ctl -D storage/postgres -l /tmp/traffic-postgres.log -o '-p 54329 -h 127.0.0.1' start
redis-server --bind 127.0.0.1 --port 6389 --dir "$PWD/storage" --appendonly yes
```

Use separate terminals/processes:

```sh
uv sync --extra dev --extra vision
npm --prefix apps/web ci
uv run alembic upgrade head
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
uv run celery -A apps.worker.tasks.celery worker --pool=solo --concurrency=1 --loglevel=INFO
npm --prefix apps/web run dev
```

Optional native retention scheduler:

```sh
uv run celery -A apps.worker.tasks.celery beat --loglevel=INFO --schedule=storage/celerybeat-schedule
```

Quality checks:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api apps/worker packages
uv run pytest -q
npm --prefix apps/web run lint
npm --prefix apps/web test
npm --prefix apps/web run build
uv lock --check
```

Data/model/evaluation commands:

```sh
uv run python scripts/download_models.py --ocr
uv run python scripts/generate_fixtures.py
uv run python scripts/evaluate.py
uv run python scripts/fetch_indian_sample.py --count 4
uv run python scripts/evaluate.py --indian-sample storage/datasets/uvh26 --output storage/indian-evaluation.json
uv run python scripts/smoke_http.py --video storage/fixtures/no_congestion.mp4
```

Compose, once a working Docker daemon is available:

```sh
cp .env.example .env.docker
export APP_ENV_FILE=.env.docker
docker compose config --quiet
docker compose build
docker compose run --rm worker python scripts/download_models.py --ocr
docker compose up -d
```

Open `http://localhost:8080`. Do not overwrite native `.env` just to configure Compose. Do not run `docker compose down -v` unless intentionally deleting those volumes.

## 11. Step-by-step continuation plan

### Step 1 — Establish and preserve the baseline

Read the original brief and current docs, inspect Git/untracked work, rerun the existing checks and inspect the live services. Produce a concise acceptance-criteria gap checklist. Fix baseline failures before feature expansion. Commit the verified inherited working tree without assistant attribution.

### Step 2 — Verify actual deployment

Build and start Compose. Exercise real HTTP upload → worker → evidence → review → download → deletion with PostgreSQL/Redis and actual model weights. Verify model setup failures, health endpoints, worker restart, bounded cancellation and retention. Fix Docker/package/volume/proxy issues and capture reproducible results. Do not claim CI passed unless it actually ran.

### Step 3 — Establish a meaningful Indian evaluation set

Find legally reusable fixed-camera Indian video, not only unrelated stills or dashcam footage. Preserve licences/provenance and keep raw media out of Git. Build camera-separated train/validation/test partitions. Label normal flow, sustained congestion, stationary vehicles without queues, genuine obstructions, red-light queues, people/animals, heavy occlusion and unknown causes. Add temporal IDs, event timing, plate readability and independently reviewed cause labels. If a dataset requires an account or agreement, report that boundary rather than bypassing it.

### Step 4 — Improve detection and tracking

Evaluate an India-specific pretrained YOLO-family model or fine-tune on appropriately licensed data. Include autorickshaws and relevant obstructions while preserving person/animal coverage. Explicitly map model labels into the shared taxonomy. Measure held-out precision/recall, missed classes, ID switches and throughput. Verify tracker reset, occlusion recovery, timestamps and device selection. Retain the replaceable adapter boundary.

### Step 5 — Harden congestion and cause attribution

Use the real labelled videos to tune persistence, density, motion, occupancy and queue-growth thresholds. Address perspective and traffic direction, red-light negatives and camera motion. Support multiple incidents. Add the high-feasibility missing cause plugins, especially lane blockage and collision-like events, with corroboration beyond box overlap. Explain alternatives and counter-evidence; preserve unknown outcomes. Measure top-1/top-3 accuracy, event timing and unknown precision/recall; calibrate scores before treating them as probabilities.

### Step 6 — Validate plate recognition and fallback evidence

Evaluate actual Indian plate detector/OCR behavior on readable and unreadable held-out examples, including two-line plates, motorcycles, glare and commercial plates. Improve localization/rectification/preprocessing if measured evidence warrants it. Measure exact-match and character accuracy plus false acceptances. Require supporting crops and genuine distinct-frame agreement. Ensure no plate or poor quality always yields null plus useful evidence.

### Step 7 — Finish lifecycle, privacy and performance

Make cancellation terminate bounded subprocess work promptly. Test worker crashes and resume semantics. Address concurrency and retention/delete races, orphan cleanup and quotas. Improve memory usage and profiling. Complete evidence redaction or accurately expose its limits. If hosting beyond localhost is requested, add actual authentication/authorization/TLS/storage protection; do not mistake UUIDs or CORS for access control.

### Step 8 — Validate the complete browser workflow

Automate real browser tests covering success, no congestion, unknown, readable/unreadable plate, region editing, SSE reconnect, retry, cancellation, review corrections, timeline seeking, export and deletion. Inspect desktop/mobile layouts, keyboard access and error states. Preserve the existing restrained visual design unless a concrete usability issue requires change.

### Step 9 — Close the acceptance checklist

Re-run every required check, execute Compose end to end, update screenshots and documentation, and produce a machine-readable evaluation report separating synthetic logic checks from real data results. Commit in coherent increments. Report completed criteria, remaining blockers, exact run commands, test evidence and limitations. Do not declare full completion while unsupported automatic categories or unverified operational claims are presented as done.

## 12. Your first response and immediate action

Briefly summarize the inherited state and your next concrete steps, then inspect the repository and execute the baseline checks. Do not ask the user to re-explain the project, find datasets for you, or approve routine reversible implementation work. Ask only for genuinely missing information or authorization for consequential external actions.

Continue from the existing code. Prioritize measurable progress and honest evidence over adding features that merely look complete.
