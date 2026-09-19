# Traffic Cause Investigator

An evidence-first browser workspace for understanding sustained traffic congestion. Upload fixed-camera footage, define the road, follow an asynchronous investigation, inspect tracked subjects and evidence, then record a human review.

Built with Indian mixed traffic in mind: configurable road regions and directions, relative movement rather than uncalibrated speed claims, Indian registration formats including BH-series, and a public Bengaluru CCTV detection evaluation. The default model remains a generic pretrained detector; this repository does **not** claim field-validated Indian causal or plate-recognition accuracy.

> This system produces probabilistic incident assessments for human review. It must not be used as the sole basis for enforcement, identification, or accusations.

![Investigation workspace](docs/screenshots/workspace.png)

## Live app walkthrough

Real captures of the running application (native Postgres/Redis/Celery + real YOLO11n /
ByteTrack inference). The demo clip is a **public Bengaluru still repeated and labelled
in-frame** as `NOT MOTION FOOTAGE`, so it exercises genuine detection but correctly
reports *no sustained congestion* (a still has no motion). It detects 19 real subjects
— cars, motorcycles, trucks, people.

| End-to-end workflow | Truthful stage progress |
|---|---|
| ![Upload, configure, process, results](docs/previews/app_workflow.gif) | ![Live processing stages](docs/previews/app_processing.gif) |

Results page — real track overlays, the `unknown` assessment, evidence, and the human-review controls:

![Results walkthrough](docs/previews/app_results.gif)

The generic COCO detector does not yet recognise autorickshaws (visible in the clip) as
a distinct class — one of the documented gaps under **Known limitations**.

## Reasoning-layer previews

Annotated illustrations of the congestion and cause-attribution logic on labelled
**simulated** scenarios (boxes coloured by motion state — green moving, amber slowing,
red stopped — with the configured incident region and the suspected subject). These
are synthetic kinematic examples of the reasoning, **not** real footage or an accuracy
benchmark. Regenerate with `make previews` (`scripts/render_previews.py`).

| Stalled autorickshaw → `stalled_vehicle` | Pedestrian in lane → `pedestrian_obstruction` |
|---|---|
| ![Stalled autorickshaw](docs/previews/stalled_autorickshaw.gif) | ![Pedestrian obstruction](docs/previews/pedestrian_obstruction.gif) |
| **Signal queue → `unknown` (no subject blamed)** | **Free flow → no congestion** |
| ![Signal queue](docs/previews/red_light_queue.gif) | ![Free flow](docs/previews/free_flow.gif) |

The signal-queue and free-flow previews show the system's conservative behaviour: it
detects the queue but refuses to blame a subject when there is no attributable cause,
and reports no congestion under free flow. See [docs/evaluation.md](docs/evaluation.md)
and the machine-readable [docs/simulation-evaluation.json](docs/simulation-evaluation.json).

## What works

- Validated MP4/MOV/MKV/AVI uploads; streamed storage, real upload progress, recent investigations.
- Reusable camera polygons and traffic directions, with an explicit whole-road fallback.
- PostgreSQL-backed jobs dispatched to Redis/Celery; real SSE progress, cancellation, retries and stage timings.
- Real YOLO11n detection and ByteTrack tracking; sampled inference and browser-synchronized boxes/IDs.
- Relative movement, occupancy, sustained congestion, candidate ranking, factor scores and conservative `unknown` outcomes.
- Candidate-only YOLO plate detection and EasyOCR; independent detector/OCR thresholds, multi-frame consensus, raw readings and null rejection.
- Original/annotated best subject frames, representative before/during/after frames and an MP4 evidence clip; optional bystander redaction.
- Click-to-seek evidence timeline, alternatives, review corrections and downloadable versioned JSON reports.
- Deletion, scheduled retention, basic local-workspace security, health/readiness/worker diagnostics, and tests.
- No paid API or LLM key; production analysis never substitutes synthetic detections.

Automatic cause detection currently covers suspected stopped vehicles, persistent people in the roadway and supported animals. Other taxonomy categories can be selected by reviewers and extended through a detector interface; see **Known limitations** below.

## Docker Compose

Requires Docker Engine/Desktop with Compose v2, at least 8 GB available memory, and several GB of disk for PyTorch, image layers and models. First build/download needs internet; ordinary analysis uses local weights.

```sh
cp .env.example .env.docker
export APP_ENV_FILE=.env.docker

docker compose build
docker compose run --rm worker python scripts/download_models.py --ocr
docker compose up -d
```

Open **[http://localhost:8080](http://localhost:8080)**. The frontend is loopback-bound; PostgreSQL, Redis and the API are internal to the Compose network.

```sh
docker compose logs -f worker
docker compose exec api python scripts/generate_fixtures.py
docker compose exec api python scripts/smoke_http.py \
  --base http://api:8000 --video storage/fixtures/no_congestion.mp4
docker compose down              # keep media and database volumes
# docker compose down -v         # DESTRUCTIVE: remove all persisted volumes
```

The `migrate` service applies Alembic migrations before API/worker startup. The scheduler runs retention hourly. `MAX_UPLOAD_MB` must remain within Nginx's `client_max_body_size` (251 MB including multipart overhead by default); update both for a larger upload ceiling. `.env.docker` is ignored by Git.

**Validation boundary:** Docker was not available on the development host, so Compose execution was not tested there. The same API, PostgreSQL, Redis, Celery, FFmpeg and actual inference path was exercised natively. A dedicated GitHub Actions job builds Compose and runs a real upload-to-report smoke test; its remote result is not claimed until that workflow runs.

## Native development

Requires Python **3.12**, Node 22+, FFmpeg/FFprobe, PostgreSQL and Redis. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) or use a Python 3.12 virtual environment with `pip install -e '.[dev,vision]'`.

```sh
uv sync --extra dev --extra vision
npm --prefix apps/web ci
uv run python scripts/download_models.py --ocr
```

Create an ignored `.env` for your local services:

```dotenv
DATABASE_URL=postgresql+psycopg://traffic:traffic@127.0.0.1:5432/traffic
REDIS_URL=redis://127.0.0.1:6379/0
STORAGE_ROOT=storage/media
MODEL_PATH=models/yolo11n.pt
PLATE_MODEL_PATH=models/license_plate.pt
DEVICE=cpu
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
OCR_ENABLED=true
MODEL_DOWNLOAD_ALLOWED=false
```

Create the `traffic` PostgreSQL database/user, then run these in separate terminals:

```sh
uv run alembic upgrade head
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
uv run celery -A apps.worker.tasks.celery worker --pool=solo --concurrency=1 --loglevel=INFO
uv run celery -A apps.worker.tasks.celery beat --loglevel=INFO --schedule=storage/celerybeat-schedule
npm --prefix apps/web run dev
```

Open **[http://127.0.0.1:5173](http://127.0.0.1:5173)**. Vite proxies API requests to port 8000. The `solo` pool is recommended for native macOS/PyTorch; Linux Compose uses a single prefork worker. SQLite is available for isolated tests but is not the production database.

### This checkout's local services

The development `.env` was configured for PostgreSQL on `127.0.0.1:54329` and Redis on `127.0.0.1:6389`, avoiding standard-port services. Model files and a small attributed Indian dataset sample were downloaded under ignored `models/` and `storage/`. If these services have stopped, restart them with:

```sh
pg_ctl -D storage/postgres -l /tmp/traffic-postgres.log -o '-p 54329 -h 127.0.0.1' start
redis-server --bind 127.0.0.1 --port 6389 --dir "$PWD/storage" --appendonly yes
```

Then run the API, worker and frontend commands above. These native service commands are specific to this prepared checkout, not prerequisites for Compose.

### CPU / GPU

CPU is the default and was exercised. Set `DEVICE=auto` for automatic PyTorch device selection, or `DEVICE=cuda:0` for a CUDA installation. On Linux with NVIDIA Container Toolkit, add `gpus: all` to the worker in a Compose override and install a CUDA-compatible PyTorch build. GPU execution and memory behavior were not tested here; use concurrency 1 until measured. Models load once per worker. There is no fabricated completion-time estimate.

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `MAX_UPLOAD_MB` | 250 | Per-file upload ceiling |
| `MAX_DURATION_SECONDS` | 600 | Maximum clip duration |
| `INFERENCE_FPS` | 5 | Time-based model sampling |
| `MAX_PIXELS` | 8294400 | Maximum decoded frame area |
| `MAX_SAMPLES` | 6000 | Inference sample budget |
| `RETENTION_DAYS` | 7 | Video/evidence expiry, via Celery beat |
| `DEVICE` | cpu | cpu, cuda:0 or auto |
| `OCR_ENABLED` | true | Candidate plate OCR |
| `MODEL_DOWNLOAD_ALLOWED` | false | Fail clearly if weights are missing |
| `CORS_ORIGINS` | local origins | JSON list of permitted browser origins |
| `ANALYSIS_CONFIG` | config/analysis.json | Thresholds, weights and plate formats |

`config/analysis.json` contains congestion thresholds and causal weights. Each job snapshots this configuration and reports its version. Camera configuration is similarly snapshotted.

## Architecture

```mermaid
flowchart LR
  UI[React + TypeScript] --> API[FastAPI]
  API --> PG[(PostgreSQL)]
  API --> Redis[(Redis)]
  Redis --> Worker[Celery / LangGraph]
  Worker --> Models[YOLO + ByteTrack + EasyOCR]
  Worker --> Store[(Media and checkpoints)]
  Worker --> PG
  API -->|SSE progress and reports| UI
```

```mermaid
flowchart TD
  Upload[Validate and normalize] --> Track[Sample / detect / track]
  Track --> Motion[Calculate relative movement]
  Motion --> Congestion{Sustained congestion?}
  Congestion -->|No| Evidence[Generate representative evidence]
  Congestion -->|Yes| Rank[Generate and score candidates]
  Rank --> Reliable{Reliable vehicle cause?}
  Reliable -->|Yes| OCR[Plate detector / OCR consensus]
  Reliable -->|No| Evidence
  OCR --> Evidence
  Evidence --> Quality[Explain / quality check / persist]
  Quality --> Review[Human review and JSON export]
```

```
apps/api                 REST, SSE, review, retention deletion
apps/worker              Celery orchestration and retention scheduler
apps/web                 React routes, player, region editor, reviews
packages/vision          Video, model adapter, frame quality
packages/tracking        Motion and track summaries
packages/traffic_analysis Congestion metrics and temporal rules
packages/cause_attribution Candidate plugin and explainable scoring
packages/plate_recognition Plate localization and multi-frame OCR
packages/workflows       Conditional LangGraph investigation
packages/evaluation      Box matching and character metrics
packages/shared          Schemas, configuration, SQL models, storage
migrations               Alembic schema
fixtures / tests         Generated fixtures and verification
scripts / docs           Setup, evaluation, smoke tests and design notes
```

## API examples

Use the Vite/Compose origin, or port 8000 directly in native development:

```sh
curl -F 'file=@traffic.mp4' http://localhost:8000/api/v1/videos
curl -H 'Content-Type: application/json' -d '{"redact":true}' \
  http://localhost:8000/api/v1/videos/VIDEO_ID/analyze
curl -N http://localhost:8000/api/v1/jobs/JOB_ID/events
curl http://localhost:8000/api/v1/incidents/INCIDENT_ID/report.json -o report.json
curl -X PATCH -H 'Content-Type: application/json' \
  -d '{"action":"corrected","corrected_cause":"vehicle_blocking_lane","notes":"Reviewed manually"}' \
  http://localhost:8000/api/v1/incidents/INCIDENT_ID/review
```

OpenAPI JSON is generated at `http://localhost:8000/openapi.json`, with a self-contained API reference at `/docs`. The reference needs no third-party scripts. The stable report contract is in `packages/shared/schemas.py`.

Other endpoints include video listing/metadata, camera region GET/PUT, cancel/retry, timeline/evidence, immutable analysis media, review history, deletion, `/health`, `/ready`, `/api/v1/worker-health`, and `/api/v1/metrics`. Errors use `{ "error": { "code", "message", "details" } }`. Reports preserve computed findings; corrections are exported separately rather than silently rewriting model evidence.

## Tests and evaluation

```sh
make lint
make test
make build
uv run python scripts/generate_fixtures.py
uv run python scripts/evaluate.py
uv run python scripts/fetch_indian_sample.py --count 4
uv run python scripts/evaluate.py --indian-sample storage/datasets/uvh26 \
  --output storage/indian-evaluation.json
```

The committed [evaluation report](docs/evaluation-results.json) contains deterministic rule results and actual YOLO inference on four public UVH-26 Indian CCTV stills. The generic model achieved **56.25% detection precision and 50% recall at IoU 0.5** on that tiny, nonrepresentative sample. Unsupported autorickshaws are counted as misses. This is diagnostic evidence for fine-tuning, not a production benchmark. Source attribution and retrieval details are in [data sources](docs/data-sources.md).

Final local verification: **36 backend tests and 8 frontend tests passed**, together with Ruff, mypy, ESLint, TypeScript and the production build. See [verification details](docs/verification.md).

Tests inject explicit synthetic adapters only inside test code. Production has no mock inference or hard-coded incident path. Frontend tests cover validation, upload progress, job state, accepted/unreadable plates and manual corrections. Backend tests cover motion, congestion, scoring, OCR consensus, quality, schema validation, media normalization, upload/report/review/delete, failures, retries and checkpoints. Native smoke testing uses real Celery, PostgreSQL, Redis and model inference.

## Known limitations and next improvements

- Only the most severe congestion interval is reported. Camera motion, signal queues, shadow/occlusion, perspective and Indian mixed traffic can distort results.
- The generic detector does not have an autorickshaw class. Fine-tune/evaluate an Indian-road detector before trusting dense mixed traffic results. Public still-image samples cannot validate incident causality.
- Collision, transverse lane blocking, roadwork, debris, potholes, flooding and signal failure require additional detectors/event evidence. Their schema/review categories exist; unsupported evidence returns unknown rather than fabricated detection.
- Motion and causal scores are heuristics, not calibrated probabilities. Camera regions are required for reliable directional attribution. Real enforcement or identification is outside scope.
- Plate localization/OCR is implemented, but real Indian plate exact-match/character accuracy is unmeasured. No inferred characters are filled in.
- Redaction covers detected non-selected boxes and may miss subjects. Source media stays unredacted. Local storage is encryption-ready through an abstraction, not encrypted by this code.
- The app is single-user and localhost-only by default. Add authentication, tenant isolation, TLS, encrypted storage and distributed quotas before hosting it for others.
- Long normalization stages use bounded subprocess timeouts; cancellation is cooperative. Tracking checkpoints are reusable, while later deterministic stages replay. Individual sampled inference is sequential, not batched.
- Full automatic training, a paid/optional LLM narrative provider and RAG are not included. The entire analysis works without them.

Highest-value next work: an Indian camera holdout dataset with temporal cause labels; a domain detector including autorickshaws and obstructions; plate-model validation; multi-incident reporting; calibrated uncertainty; and authenticated deployment hardening.

## Further documentation

[Architecture](docs/architecture.md) · [Cause attribution](docs/cause-attribution.md) · [Plate recognition](docs/plate-recognition.md) · [Privacy/security](docs/privacy-and-security.md) · [Evaluation](docs/evaluation.md) · [Demo walkthrough](docs/demo-script.md) · [Data/model provenance](docs/data-sources.md)
