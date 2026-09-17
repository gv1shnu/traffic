You are a senior full-stack engineer, computer-vision engineer, ML engineer, and software architect. Build a complete, portfolio-quality browser application called **Traffic Cause Investigator**.

## 1. Product objective

Create a browser-based application where a user uploads traffic-surveillance footage. The system processes the video asynchronously and identifies:

1. Whether meaningful traffic congestion occurred.
2. The approximate timestamp and location where congestion began.
3. The vehicle, person, road obstruction, or infrastructure defect most likely responsible.
4. The suspected vehicle’s license plate, if a readable plate is visible.
5. If no reliable license plate can be extracted, the clearest evidentiary frame showing the suspected traffic-causing subject.
6. A concise explanation of why the system selected that subject.
7. Confidence scores, annotated evidence frames, and a short evidence clip.

This is an **incident-analysis and decision-support tool**, not an automatic enforcement system. In the UI and API, use terms such as **“suspected traffic-causing subject”** or **“likely cause”**, not definitive statements of guilt.

## 2. Required stack

Use:

### Backend and ML

* Python 3.12
* FastAPI
* Pydantic
* SQLAlchemy
* Alembic
* PostgreSQL
* Redis
* Celery or Dramatiq for background video-processing jobs
* OpenCV
* FFmpeg
* PyTorch
* A YOLO-family model for object detection
* ByteTrack or BoT-SORT for multi-object tracking
* PaddleOCR or an equivalent open-source OCR model for license-plate recognition
* scikit-learn for classical ML/anomaly scoring where appropriate
* LangGraph for the incident-investigation workflow
* Optional LLM integration through a provider-neutral interface

### Frontend

* React
* TypeScript
* Vite
* Tailwind CSS
* TanStack Query
* React Router
* A suitable HTML5 video player
* Canvas or SVG overlay for annotations

### Infrastructure

* Docker
* Docker Compose
* pytest
* Ruff
* mypy
* ESLint
* GitHub Actions

The application must run locally with Docker Compose. It should work without a paid LLM API key. An LLM may improve the final narrative, but all detection, tracking, congestion analysis, attribution, and confidence calculations must work deterministically without an LLM.

## 3. Core user flow

Implement this complete workflow:

1. User opens the web application.
2. User uploads an MP4, MOV, MKV, or AVI surveillance video.
3. Frontend validates type and file size.
4. Backend stores the original video and creates an analysis job.
5. Video processing runs asynchronously.
6. Frontend displays live progress:

   * Uploading
   * Validating
   * Extracting metadata
   * Detecting objects
   * Tracking objects
   * Measuring traffic movement
   * Detecting congestion
   * Evaluating possible causes
   * Reading license plate
   * Generating evidence
   * Completed or failed
7. Once complete, the browser displays:

   * Video with bounding boxes and track IDs
   * Incident start timestamp
   * Suspected cause category
   * Suspected subject
   * License plate, if confidently recognized
   * Plate confidence
   * Cause confidence
   * Clearest subject frame
   * Plate crop, when available
   * Evidence frames before, during, and after the incident
   * Explanation based on calculated evidence
   * Alternative candidates
   * Downloadable JSON report
8. User can approve the conclusion, reject it, or correct:

   * Cause category
   * License plate
   * Selected subject
9. Store reviewer corrections so they can become future labelled training data.

## 4. Scope and cause taxonomy

Support these cause categories:

* `stalled_vehicle`
* `collision`
* `vehicle_blocking_lane`
* `illegal_parking_or_stopping`
* `pedestrian_obstruction`
* `animal_obstruction`
* `road_debris`
* `roadwork_or_barricade`
* `pothole_or_road_damage`
* `flooded_road`
* `traffic_signal_failure`
* `unknown`

For the first working version, prioritize these high-feasibility categories:

1. Stalled vehicle
2. Vehicle blocking a lane
3. Collision
4. Pedestrian obstruction
5. Road debris or barricade
6. Unknown

Build the design so new cause detectors can be added through a common plugin/interface without changing the central pipeline.

Never force a cause. Return `unknown` when the available evidence is inadequate.

## 5. Video-processing pipeline

Build the pipeline as independent, testable stages.

### Stage A: Validation and normalization

* Validate MIME type, extension, file header, duration, resolution, and frame rate.
* Reject corrupted or unsupported files with useful error messages.
* Use FFmpeg to normalize uploaded videos to a browser-compatible MP4 when required.
* Extract:

  * Width
  * Height
  * FPS
  * Frame count
  * Duration
  * Codec
* Protect against path traversal, malformed filenames, oversized uploads, and decompression/resource-exhaustion attacks.
* Make maximum upload size and maximum duration configurable through environment variables.

### Stage B: Adaptive frame sampling

Do not process every frame unnecessarily.

* Use a configurable inference FPS.
* Default to 5 inference frames per second.
* Permit full-FPS extraction around a suspected incident.
* Preserve the original timestamps.
* Batch frames during model inference where possible.
* Expose progress after each processing stage.

### Stage C: Object detection

Detect at minimum:

* Person
* Bicycle
* Motorcycle
* Car
* Bus
* Truck
* Animal, when supported
* Traffic light
* Stop sign
* Obstruction or debris, when supported

Return bounding box, class, detection confidence, frame index, and timestamp.

Design a model adapter so the detector can later be replaced without rewriting business logic.

### Stage D: Multi-object tracking

Track subjects consistently across frames.

For every track, maintain:

* Track ID
* Object type
* Bounding boxes
* Centroids
* First and last timestamp
* Detection-confidence history
* Estimated movement
* Stationary duration
* Lane or region
* Best-quality crop
* Best-quality full frame
* Whether other tracks queued behind it

Handle temporary occlusion and prevent unnecessary track-ID switching.

### Stage E: Scene and lane configuration

For the MVP:

* Allow the user to draw lane or road polygons on a representative frame.
* Allow the user to indicate approximate traffic direction for each lane.
* Store this camera configuration for reuse.
* If no regions are configured, provide a whole-road fallback mode and clearly label its lower reliability.

The region editor must support:

* Adding polygons
* Naming regions
* Setting direction arrows
* Deleting or resetting regions
* Saving configuration

### Stage F: Movement estimation

Estimate relative traffic movement without requiring exact real-world speed.

For each tracked road user:

* Calculate displacement over time.
* Smooth trajectories to reduce detector jitter.
* Normalize displacement using bounding-box scale or scene perspective where possible.
* Classify states:

  * Moving normally
  * Slowing
  * Nearly stationary
  * Stationary
  * Exited scene

If camera calibration is available, support approximate km/h. Otherwise clearly label measurements as relative or pixel-space movement.

### Stage G: Congestion detection

Detect congestion using a temporal combination of:

* Median vehicle movement
* Number of active vehicle tracks
* Region occupancy
* Queue length
* Percentage of nearly stationary vehicles
* Persistence over a configurable time window
* Upstream queue growth

A possible starting rule is:

* Sufficient vehicle density exists.
* Median motion falls below a configurable threshold.
* A configurable portion of vehicles remains slow or stationary.
* These conditions persist for several seconds.
* Queue length or occupied road area increases.

Do not classify naturally sparse footage as congestion merely because one vehicle is stationary.

Return:

* Congestion start and end time
* Affected region
* Peak queue size
* Severity score
* Supporting metrics over time

Keep thresholds in configuration files rather than scattering constants through the code.

### Stage H: Cause candidate generation

When congestion is detected, identify candidate causes around the time and location where it originated.

Generate candidates from:

* A vehicle that stopped before the queue formed
* A vehicle with an abrupt trajectory or collision-like overlap
* A vehicle positioned across a traffic lane
* A person remaining within the roadway
* A visible obstruction
* A detected road defect
* A failed or persistently unusual traffic-light state

For every candidate, capture structured evidence rather than asking an LLM to infer directly from raw frames.

### Stage I: Causal scoring

Implement an explainable candidate-scoring model.

Include factors such as:

* **Temporal precedence:** Did the candidate event occur before queue growth?
* **Spatial proximity:** Is the candidate near the downstream origin of the queue?
* **Lane blockage:** How much of the active lane does the candidate occupy?
* **Stationary duration:** Did the candidate remain stopped unusually long?
* **Follower response:** Did vehicles behind the candidate slow or stop afterward?
* **Queue propagation:** Did the queue expand upstream from the candidate?
* **Counterfactual evidence:** Did nearby lanes continue moving?
* **Detection quality:** Is the subject consistently detected and tracked?
* **Event-specific evidence:** Collision overlap, debris persistence, person-in-road duration, etc.

Make the weights configurable.

Produce a score between 0 and 1 and preserve individual factor scores. Do not report high confidence merely because one factor is high.

Example output:

```json
{
  "candidate_track_id": 42,
  "cause_type": "stalled_vehicle",
  "cause_confidence": 0.84,
  "evidence_scores": {
    "temporal_precedence": 0.92,
    "spatial_proximity": 0.88,
    "lane_blockage": 0.79,
    "stationary_duration": 0.91,
    "follower_response": 0.83,
    "queue_propagation": 0.81,
    "tracking_quality": 0.86
  }
}
```

The explanation displayed to the user must be derived from these metrics.

Example:

> A car in Lane 2 became stationary at 00:42.6. Vehicles immediately behind it slowed within 4.1 seconds, and the queue expanded upstream from 2 to 13 vehicles. Adjacent Lane 1 continued moving. The vehicle is therefore the highest-ranked suspected cause.

## 6. License-plate pipeline

Attempt license-plate extraction only for the selected vehicle candidate and optionally the top alternative candidates.

### Plate processing

1. Gather frames in which the candidate vehicle is visible.
2. Detect the license-plate region.
3. Rank plate crops using:

   * Resolution
   * Bounding-box size
   * Sharpness
   * Brightness
   * Contrast
   * Viewing angle
   * Occlusion
4. Select several high-quality crops.
5. Apply conservative preprocessing:

   * Perspective correction
   * Denoising
   * Contrast enhancement
   * Upscaling
   * Sharpening
6. Run OCR on multiple frames.
7. Normalize characters without silently changing uncertain characters.
8. Combine readings through multi-frame consensus.
9. Validate against configurable license-plate patterns.
10. Preserve raw OCR readings and confidence.

For Indian plates, support patterns such as:

```text
KA01AB1234
DL8CAF5031
TS09EX1234
```

Do not require every plate to match an Indian format. The application should remain region-configurable.

### Plate acceptance rule

Only show a plate as the primary result when:

* Plate detection confidence exceeds a configurable threshold.
* OCR confidence exceeds a configurable threshold.
* Multiple frames agree, or one frame is exceptionally clear.
* The crop has adequate visual quality.

Otherwise return:

```json
{
  "license_plate": null,
  "plate_status": "unreadable",
  "plate_confidence": 0.31
}
```

Never fabricate missing characters. Display partially recognized text separately and label it as uncertain.

## 7. Fallback evidence-frame behavior

If no reliable license plate is available:

* Return the clearest full frame containing the suspected subject.
* Draw a visible bounding box around that subject.
* Include its track ID and object type.
* Include the frame timestamp.
* Include the cause-confidence score.
* Provide the original unannotated frame as well as the annotated version.

Select the clearest frame using:

* Image sharpness
* Subject size
* Detection confidence
* Occlusion percentage
* Exposure quality
* Distance from image boundaries
* Visibility of the full subject

If the suspected cause is a person, animal, road defect, debris, or barricade, return its clearest evidence frame regardless of plate status.

If no subject can be identified reliably, return representative frames showing where congestion originated and mark the cause as `unknown`.

## 8. LangGraph workflow

Use LangGraph to coordinate high-level incident investigation—not to replace computer vision.

Suggested graph nodes:

1. `validate_video`
2. `extract_metadata`
3. `detect_and_track`
4. `calculate_motion`
5. `detect_congestion`
6. `generate_candidates`
7. `score_candidates`
8. `extract_plate`
9. `select_evidence`
10. `generate_explanation`
11. `quality_check`
12. `persist_results`

Required branches:

* If no congestion exists, generate a “No congestion detected” result.
* If congestion exists but no cause is reliable, return `unknown`.
* If a vehicle is selected, attempt plate recognition.
* If plate recognition fails, select the best perpetrator/subject frame.
* If quality validation fails, lower confidence and flag the incident for manual review.
* Persist intermediate state so interrupted jobs can be resumed.

## 9. LLM and RAG constraints

The application must function without an LLM.

If an LLM provider is configured:

* Feed it only structured incident evidence.
* Use it to produce a concise natural-language report.
* Require schema-validated structured output.
* Do not send the complete video.
* Do not allow the LLM to invent a plate, timestamp, person, vehicle, or cause.
* Verify every generated factual statement against computed evidence.

Optional RAG functionality may retrieve:

* Cause definitions
* Incident-handling procedures
* Local traffic policies
* Model limitations
* Previous reviewed incidents

RAG content must be cited separately and must not override video evidence.

## 10. API requirements

Create versioned REST endpoints similar to:

```text
POST   /api/v1/videos
GET    /api/v1/videos/{video_id}
POST   /api/v1/videos/{video_id}/analyze
GET    /api/v1/jobs/{job_id}
GET    /api/v1/jobs/{job_id}/events
GET    /api/v1/incidents/{incident_id}
GET    /api/v1/incidents/{incident_id}/timeline
GET    /api/v1/incidents/{incident_id}/evidence
GET    /api/v1/incidents/{incident_id}/report.json
PATCH  /api/v1/incidents/{incident_id}/review
GET    /api/v1/cameras/{camera_id}/regions
PUT    /api/v1/cameras/{camera_id}/regions
DELETE /api/v1/videos/{video_id}
```

Use WebSocket or Server-Sent Events for progress updates.

Return consistent errors using a structure such as:

```json
{
  "error": {
    "code": "UNSUPPORTED_VIDEO",
    "message": "The uploaded codec is not supported.",
    "details": {}
  }
}
```

Generate OpenAPI documentation automatically.

## 11. Data model

Include entities such as:

### Video

* ID
* Original filename
* Storage path
* Normalized path
* File hash
* MIME type
* Duration
* FPS
* Width
* Height
* Upload timestamp
* Processing status

### AnalysisJob

* ID
* Video ID
* Status
* Progress percentage
* Current stage
* Error code
* Error details
* Created/started/completed timestamps

### Track

* ID
* Analysis ID
* Tracker ID
* Object class
* First timestamp
* Last timestamp
* Region
* Movement summary
* Best-frame path
* Tracking confidence

### Incident

* ID
* Video ID
* Cause type
* Start and end timestamp
* Region
* Selected track ID
* Cause confidence
* Congestion severity
* Explanation
* Review status
* Model and configuration versions

### PlateReading

* ID
* Incident ID
* Track ID
* Normalized text
* Raw OCR text
* Confidence
* Crop path
* Frame timestamp
* Acceptance status

### EvidenceAsset

* ID
* Incident ID
* Asset type
* Storage path
* Timestamp
* Track ID
* Quality score
* Metadata

### Review

* ID
* Incident ID
* Reviewer action
* Corrected cause
* Corrected plate
* Corrected track
* Notes
* Timestamp

## 12. Frontend requirements

Build a polished, responsive interface.

### Upload page

* Drag-and-drop upload
* File picker
* File type and size guidance
* Upload progress
* Helpful validation errors
* Recent analyses list

### Configuration page

* Display a representative video frame
* Let the user draw road/lane polygons
* Let the user assign direction
* Provide a simple whole-road fallback
* Save configuration before analysis

### Processing page

* Stage-by-stage progress
* Percentage completion
* Elapsed processing time
* Cancel button
* Error details and retry action
* Do not display fake progress

### Results page

Include:

* Video player
* Toggleable bounding boxes and track IDs
* Timeline markers for congestion and suspected cause
* Cause category
* Confidence badge
* License plate result or “No reliable plate detected”
* Best subject frame
* Plate crop
* Before/during/after evidence
* Evidence-score breakdown
* Congestion metrics
* Alternative candidates
* Human-review controls
* JSON-report download

Use confidence labels:

* High: `>= 0.80`
* Medium: `0.60–0.79`
* Low: `< 0.60`

Do not use alarming red styling merely because a person or vehicle is selected. Reserve red for errors or severe warnings.

### Review interaction

Allow the reviewer to:

* Confirm result
* Mark result incorrect
* Select another tracked subject
* Correct plate text
* Select another cause category
* Add notes

## 13. Evidence timeline

Create a synchronized incident timeline containing:

* First abnormal behaviour
* Suspected causal event
* First follower slowdown
* Congestion threshold reached
* Peak congestion
* Congestion cleared

Clicking a marker should seek the video to that timestamp.

## 14. Output contract

The final report must follow a stable schema:

```json
{
  "analysis_id": "uuid",
  "video": {
    "filename": "traffic.mp4",
    "duration_seconds": 182.4,
    "fps": 30
  },
  "congestion": {
    "detected": true,
    "start_seconds": 42.6,
    "end_seconds": 131.8,
    "region": "lane_2",
    "severity": 0.76,
    "peak_queue_size": 13
  },
  "cause": {
    "type": "stalled_vehicle",
    "confidence": 0.84,
    "suspected_track_id": 42,
    "object_type": "car",
    "first_relevant_timestamp": 38.5,
    "explanation": "A car stopped before the queue formed..."
  },
  "license_plate": {
    "status": "recognized",
    "text": "KA01AB1234",
    "confidence": 0.87,
    "evidence_asset_id": "uuid"
  },
  "fallback_subject_frame": {
    "required": false,
    "asset_id": "uuid",
    "timestamp": 39.2
  },
  "evidence": [],
  "alternative_candidates": [],
  "limitations": [],
  "model_versions": {},
  "review_status": "pending"
}
```

If the plate is not reliable:

```json
{
  "license_plate": {
    "status": "unreadable",
    "text": null,
    "confidence": 0.28,
    "evidence_asset_id": null
  },
  "fallback_subject_frame": {
    "required": true,
    "asset_id": "uuid",
    "timestamp": 39.2
  }
}
```

## 15. Security, privacy, and retention

Implement:

* Random storage identifiers instead of raw filenames
* MIME and file-signature validation
* Configurable upload limits
* No execution of uploaded content
* Protection against path traversal
* Content Security Policy
* Restricted CORS
* Rate limiting
* Structured audit logging
* Configurable video and evidence retention
* Deletion endpoint that removes associated assets
* Redaction option for non-relevant plates and faces
* Encryption-ready storage abstraction
* No external LLM or analytics upload by default

Add a visible disclaimer:

> This system produces probabilistic incident assessments for human review. It must not be used as the sole basis for enforcement, identification, or accusations.

## 16. Performance requirements

* Keep API requests non-blocking.
* Process videos using background workers.
* Batch model inference where possible.
* Avoid loading the same model for every frame.
* Load models once per worker.
* Stream files rather than loading entire videos into memory.
* Save only necessary intermediate artifacts.
* Allow CPU mode, CUDA mode, and automatic device selection.
* Display an estimated processing mode, not an inaccurate completion time.
* Support cancellation and cleanup of partially completed jobs.
* Cache reusable camera configuration.
* Record stage timings for profiling.

## 17. Observability

Implement structured logs containing:

* Analysis ID
* Video ID
* Job ID
* Pipeline stage
* Duration
* Model version
* Error code

Expose:

* Health endpoint
* Readiness endpoint
* Worker-health endpoint
* Processing-stage timings
* Successful/failed job counters

Do not log license plates or image contents in plaintext application logs.

## 18. Testing

Create meaningful tests, not placeholder tests.

### Unit tests

Test:

* Video validation
* Motion calculations
* Congestion rules
* Candidate scoring
* Confidence aggregation
* Frame-quality scoring
* Multi-frame OCR consensus
* Plate acceptance/rejection
* JSON schema generation
* Unknown-cause fallback

### Integration tests

Test:

* Upload-to-report workflow
* Background-job execution
* Progress updates
* Database persistence
* Evidence retrieval
* Review corrections
* Video deletion and cleanup

### Frontend tests

Test:

* File validation
* Upload progress
* Job-status rendering
* Result rendering with a recognized plate
* Result rendering with no plate
* Unknown-cause state
* Manual correction workflow

### Synthetic test fixtures

Create small synthetic or generated fixtures representing:

1. Normal flowing traffic
2. A vehicle stopping and causing a queue
3. A stopped vehicle without a readable plate
4. A pedestrian obstruction
5. Congestion with no identifiable cause
6. A video with no congestion
7. Corrupted video input

Do not commit copyrighted surveillance footage or personally identifying real-world footage.

## 19. Evaluation metrics

Calculate and document:

* Vehicle/person detection precision and recall
* Tracking ID-switch count
* Congestion-event precision, recall, and timing error
* Cause top-1 and top-3 accuracy
* Plate exact-match accuracy
* Character-level plate accuracy
* Percentage of incidents correctly assigned `unknown`
* Evidence-frame quality
* CPU/GPU processing throughput

Create an evaluation command that produces a machine-readable report.

## 20. Repository structure

Use a clean structure similar to:

```text
traffic-cause-investigator/
├── apps/
│   ├── api/
│   ├── worker/
│   └── web/
├── packages/
│   ├── vision/
│   ├── tracking/
│   ├── traffic_analysis/
│   ├── cause_attribution/
│   ├── plate_recognition/
│   ├── workflows/
│   └── shared/
├── migrations/
├── tests/
├── fixtures/
├── docs/
├── scripts/
├── docker-compose.yml
├── .env.example
├── Makefile
└── README.md
```

Avoid giant files and circular dependencies. Use interfaces for detectors, trackers, OCR engines, storage, and optional LLM providers.

## 21. Documentation

Write a strong README containing:

* Product description
* Screenshots or placeholders
* Architecture diagram
* Processing-flow diagram
* Local installation
* Docker Compose commands
* CPU and GPU instructions
* Environment variables
* API examples
* Model-download instructions
* Testing commands
* Evaluation procedure
* Known limitations
* Privacy considerations
* Future improvements

Also create:

* `docs/architecture.md`
* `docs/cause-attribution.md`
* `docs/plate-recognition.md`
* `docs/privacy-and-security.md`
* `docs/evaluation.md`
* `docs/demo-script.md`

## 22. Development strategy

Work in vertical slices.

### Milestone 1: Functional browser application

* Upload video
* Create background job
* Show real progress
* Store and retrieve results
* Display extracted frames

### Milestone 2: Detection and tracking

* Detect road users
* Track them through the video
* Render annotated evidence

### Milestone 3: Congestion detection

* Calculate movement and occupancy
* Detect persistent queue formation
* Display timeline and metrics

### Milestone 4: Cause attribution

* Generate and rank candidates
* Produce evidence-based explanations
* Support unknown results

### Milestone 5: Plate recognition and fallback

* Read plates from the selected vehicle
* Aggregate multi-frame OCR
* Reject unreliable readings
* Return the clearest subject frame when OCR fails

### Milestone 6: Review, tests, and polish

* Add human correction
* Expand automated tests
* Improve accessibility and error handling
* Complete documentation and demo

After each milestone, run the relevant tests and repair failures before proceeding.

## 23. Mandatory engineering rules

* Inspect the existing repository before changing anything.
* Preserve useful existing code and conventions.
* If the repository is empty, initialize the structure described above.
* Do not stop after producing an architecture plan.
* Implement a genuinely working end-to-end vertical slice.
* Do not generate fake detections, fake plates, or hard-coded incidents.
* Do not silently substitute mock analysis in production mode.
* A clearly labelled demo mode is acceptable only for frontend development.
* Keep expensive dependencies behind adapters.
* Use typed interfaces and validated schemas.
* Keep thresholds configurable.
* Record model and configuration versions with every analysis.
* Handle failure states explicitly.
* Never infer a license-plate character when OCR confidence is inadequate.
* Prefer an honest `unknown` result over a confident but unsupported attribution.
* Do not make an LLM responsible for numerical traffic analysis.
* Do not expose secrets to the frontend.
* Add comments only where the reasoning is not obvious from the code.
* Run formatting, linting, type checking, backend tests, frontend tests, and a production build before declaring completion.

## 24. Acceptance criteria

The project is complete only when:

1. A user can upload a video from a browser.
2. Processing occurs asynchronously.
3. The UI displays truthful stage progress.
4. Vehicles and people are tracked across frames.
5. The system can detect sustained congestion.
6. It ranks plausible cause candidates.
7. It displays the selected suspected subject and reasoning.
8. It attempts plate recognition only for relevant candidate vehicles.
9. A reliable plate is displayed with confidence and supporting crop.
10. An unreliable or absent plate produces a clear `null` result.
11. When no plate is available, the clearest annotated subject frame is returned.
12. An unknown cause is supported as a valid outcome.
13. The video timeline contains clickable evidence markers.
14. The user can correct the cause, subject, or plate.
15. A JSON report can be downloaded.
16. The application runs through Docker Compose.
17. The core pipeline works without an LLM API key.
18. Automated tests cover the main success and failure paths.
19. The README explains setup, architecture, limitations, and evaluation.
20. No fake or hard-coded analysis appears in normal operation.

## 25. Start now

Begin by:

1. Inspecting the repository.
2. Summarizing what already exists.
3. Writing a concise implementation plan.
4. Identifying the smallest end-to-end vertical slice.
5. Implementing that slice immediately.
6. Running it and fixing errors.
7. Continuing through the milestones while keeping the application runnable.

When a model weight or external dependency cannot be bundled, implement the real adapter, document the exact installation or download command, and fail with a clear actionable message. Do not pretend that inference succeeded.

At the end, report:

* Files created or changed
* Architecture implemented
* Features completed
* Tests executed and their results
* Exact local run commands
* Known limitations
* Highest-value next improvements
