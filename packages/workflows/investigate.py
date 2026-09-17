import json
import logging
import time
from typing import Any, TypedDict
from uuid import uuid4

import cv2
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from packages.cause_attribution.scoring import rank_candidates, select_cause
from packages.plate_recognition.ocr import consensus, ocr_engine
from packages.shared.config import settings, thresholds
from packages.shared.db import (
    AnalysisJob,
    EvidenceAsset,
    Incident,
    PlateReading,
    Session,
    Track,
    Video,
    now,
)
from packages.shared.schemas import (
    Asset,
    Candidate,
    Cause,
    Congestion,
    Observation,
    Plate,
    Region,
    Report,
)
from packages.shared.storage import storage
from packages.tracking.motion import calculate_motion, summarize_tracks
from packages.traffic_analysis.congestion import detect_congestion
from packages.vision.detector import VEHICLES, DetectorTracker, detector
from packages.vision.quality import quality
from packages.vision.video import normalize, probe, read_frame, validate_header
from packages.workflows.timeline import build_timeline

logger = logging.getLogger("traffic.pipeline")
STAGES = [
    "validate_video",
    "extract_metadata",
    "detect_and_track",
    "calculate_motion",
    "detect_congestion",
    "generate_candidates",
    "score_candidates",
    "extract_plate",
    "select_evidence",
    "generate_explanation",
    "quality_check",
    "persist_results",
]


class Cancelled(Exception):
    pass


class State(TypedDict):
    job_id: str


class Investigation:
    def __init__(self, job_id: str, adapter: DetectorTracker | None = None):
        self.job_id = job_id
        self.adapter = adapter
        with Session() as db:
            job = db.get(AnalysisJob, job_id)
            if job is None:
                raise ValueError("Job not found")
            video = db.get(Video, job.video_id)
            if video is None:
                raise ValueError("Video not found")
            self.video_id = video.id
            self.filename = video.filename
            self.mime = video.mime_type
            self.source = storage.resolve(video.path)
            self.options = job.config
        self.folder = storage.resolve(f"{self.video_id}/{job_id}")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.normalized = self.folder / "normalized.mp4"
        self.cfg = self.options.get("thresholds", thresholds())
        self.regions = [Region.model_validate(r) for r in self.options.get("regions", [])]
        self.incident_id = str(uuid4())
        self.observations: list[Observation] = []
        self.meta: dict[str, Any] = {}
        self.congestion = Congestion()
        self.metrics: list[dict] = []
        self.candidates: list[Candidate] = []
        self.cause = Cause()
        self.plate = Plate()
        self.assets: list[Asset] = []
        self.limitations = [
            "Scores are heuristic evidence strength, not calibrated probabilities.",
            "Mixed Indian traffic, autorickshaws, occlusion, night scenes and camera motion can reduce accuracy.",
            "Collision, lane blocking, road damage, flooding and signal failure need specialist detectors; they are not inferred from generic object boxes.",
            "Only the most severe congestion interval is reported.",
        ]
        if not self.regions:
            self.limitations.append(
                "Whole-road fallback: direction is uncalibrated and cause confidence is capped below the selection threshold. Draw road regions for attribution."
            )

    def progress(self, stage: str, fraction: float = 0) -> None:
        with Session() as db:
            job = db.get(AnalysisJob, self.job_id)
            if job is None or job.cancelled:
                raise Cancelled()
            job.stage = stage
            job.progress = round((STAGES.index(stage) + min(fraction, 0.99)) / len(STAGES) * 100, 1)
            job.status = "processing"
            if job.started_at is None:
                job.started_at = now()
            db.commit()

    def checkpoint(self, stage: str, payload: dict) -> None:
        target = self.folder / f"{stage}.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(payload))
        temp.replace(target)
        with Session() as db:
            job = db.get(AnalysisJob, self.job_id)
            if job:
                job.checkpoint = {**job.checkpoint, stage: target.name}
                db.commit()

    def validate_video(self) -> None:
        validate_header(self.source, self.filename, self.mime)

    def extract_metadata(self) -> None:
        self.meta = probe(self.source)
        if not self.normalized.exists():
            target = self.folder / "normalizing.mp4"
            normalize(self.source, target)
            target.replace(self.normalized)
        self.meta = probe(self.normalized)
        with Session() as db:
            video = db.get(Video, self.video_id)
            if video:
                video.normalized_path = str(
                    self.normalized.relative_to(settings().storage_root.resolve())
                )
                video.metadata_json = self.meta
                db.commit()

    def detect_and_track(self) -> None:
        cached = self.folder / "detect_and_track.json"
        if cached.exists():
            data = json.loads(cached.read_text())
            self.observations = [Observation.model_validate(o) for o in data["observations"]]
            self.model_version = data["model_version"]
            return
        adapter = self.adapter or detector()
        adapter.reset()
        self.model_version = adapter.version
        cap = cv2.VideoCapture(str(self.normalized))
        index = 0
        fps = self.meta["fps"]
        next_sample = 0.0
        last_timestamp = -1.0
        try:
            while True:
                ok = cap.grab()
                if not ok:
                    break
                # Use the frame's real presentation time so variable-frame-rate footage
                # keeps observation timestamps aligned with evidence seeking, which also
                # uses presentation time. Fall back to the nominal index/fps grid only
                # when the container exposes no usable timestamp.
                pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                timestamp = pos if pos > last_timestamp else index / fps
                last_timestamp = timestamp
                if timestamp + 1e-6 >= next_sample:
                    ok, frame = cap.retrieve()
                    if not ok:
                        raise ValueError("Frame decoding failed during tracking")
                    self.observations.extend(adapter.infer(frame, timestamp, index))
                    if len(self.observations) > settings().max_observations:
                        raise RuntimeError(
                            "Observation budget exceeded. Use a shorter clip or lower inference FPS."
                        )
                    next_sample += 1 / min(fps, settings().inference_fps)
                    self.progress(
                        "detect_and_track", min(0.99, timestamp / self.meta["duration_seconds"])
                    )
                index += 1
            if index < self.meta["duration_seconds"] * fps * 0.8:
                raise ValueError("Video ended prematurely during decoding")
        finally:
            cap.release()
        self.checkpoint(
            "detect_and_track",
            {
                "observations": [o.model_dump() for o in self.observations],
                "model_version": self.model_version,
            },
        )

    def calculate_motion(self) -> None:
        self.observations = calculate_motion(
            self.observations, self.regions, self.meta["width"], self.meta["height"], self.cfg
        )

    def detect_congestion(self) -> None:
        self.congestion, self.metrics = detect_congestion(
            self.observations, self.regions, self.meta["width"], self.meta["height"], self.cfg
        )

    def generate_candidates(self) -> None:
        self.candidates = rank_candidates(
            self.observations, self.congestion, self.regions, self.cfg, self.meta["width"]
        )

    def score_candidates(self) -> None:
        self.cause = select_cause(self.candidates, self.cfg)

    def add_image(
        self, frame, kind: str, timestamp: float, track_id: int | None = None, score: float = 0
    ) -> Asset:
        asset_id = str(uuid4())
        path = self.folder / f"{asset_id}.jpg"
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError("Evidence image could not be written")
        asset = Asset(
            id=asset_id,
            asset_type=kind,
            url=f"/api/v1/assets/{asset_id}",
            timestamp=timestamp,
            track_id=track_id,
            quality_score=score,
            metadata={"filename": path.name, "redacted": bool(self.options.get("redact"))},
        )
        self.assets.append(asset)
        return asset

    def extract_plate(self) -> None:
        if self.cause.object_type not in VEHICLES:
            self.plate = Plate(status="not_applicable")
            return
        if not settings().ocr_enabled:
            self.limitations.append("OCR was disabled; no plate recognition was performed.")
            return
        try:
            engine = ocr_engine()
        except (ImportError, FileNotFoundError, RuntimeError) as exc:
            self.limitations.append(
                f"OCR unavailable ({type(exc).__name__}); run python scripts/download_models.py --ocr."
            )
            return
        self.limitations.append(
            "The plate detector is pretrained on public data and has not been validated on an Indian surveillance benchmark."
        )
        self.ocr_version = engine.version
        rows = [o for o in self.observations if o.track_id == self.cause.suspected_track_id]
        ranked = []
        for o in rows[:: max(1, len(rows) // 40)]:
            frame = read_frame(self.normalized, o.timestamp)
            ranked.append((quality(frame, o.bbox, o.confidence), o))
        readings = []
        crops = {}
        for _, o in sorted(ranked, key=lambda item: item[0], reverse=True)[:8]:
            self.progress("extract_plate")
            frame = read_frame(self.normalized, o.timestamp)
            x1, y1, x2, y2 = [max(0, int(v)) for v in o.bbox]
            vehicle = frame[y1:y2, x1:x2]
            if vehicle.size == 0:
                continue
            for row in engine.read(vehicle):
                row["timestamp"] = o.timestamp
                readings.append(row)
                a, b, c, d = row["bbox"]
                crops[(o.timestamp, row["raw_text"])] = vehicle[b:d, a:c]
        self.plate = consensus(readings, self.cfg)
        if self.plate.status == "recognized":
            row = max(
                (r for r in readings if r["normalized_text"] == self.plate.text),
                key=lambda r: r["quality"],
            )
            asset = self.add_image(
                crops[(row["timestamp"], row["raw_text"])],
                "plate_crop",
                row["timestamp"],
                self.cause.suspected_track_id,
                row["quality"],
            )
            self.plate.evidence_asset_id = asset.id

    def redacted(self, frame, timestamp: float):
        if not self.options.get("redact"):
            return frame.copy()
        image = frame.copy()
        for o in self.observations:
            if abs(o.timestamp - timestamp) > 0.25 or o.track_id == self.cause.suspected_track_id:
                continue
            x1, y1, x2, y2 = [max(0, int(v)) for v in o.bbox]
            crop = image[y1:y2, x1:x2]
            if crop.size:
                crop[:] = cv2.GaussianBlur(crop, (51, 51), 0)
        return image

    def select_evidence(self) -> None:
        duration = self.meta["duration_seconds"]
        start = self.congestion.start_seconds if self.congestion.detected else duration / 2
        start = start or 0
        times = [
            ("before", max(0, start - 2)),
            ("during", min(duration - 0.1, start + 1)),
            ("after", min(duration - 0.1, (self.congestion.end_seconds or start) + 2)),
        ]
        for kind, timestamp in times:
            frame = read_frame(self.normalized, timestamp)
            self.add_image(self.redacted(frame, timestamp), kind, timestamp)
        rows = [o for o in self.observations if o.track_id == self.cause.suspected_track_id]
        if rows:
            best = None
            for o in rows[:: max(1, len(rows) // 50)]:
                frame = read_frame(self.normalized, o.timestamp)
                score = quality(frame, o.bbox, o.confidence)
                if best is None or score > best[0]:
                    best = (score, o, frame)
            if best:
                score, o, frame = best
                self.add_image(
                    self.redacted(frame, o.timestamp),
                    "subject_original",
                    o.timestamp,
                    o.track_id,
                    score,
                )
                annotated = self.redacted(frame, o.timestamp)
                x1, y1, x2, y2 = [int(v) for v in o.bbox]
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (50, 205, 190), 3)
                label = f"Suspected {o.object_type} #{o.track_id} | {o.timestamp:.1f}s | {self.cause.confidence:.0%}"
                cv2.putText(
                    annotated,
                    label,
                    (max(4, x1), max(24, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (50, 205, 190),
                    2,
                )
                self.add_image(annotated, "subject_annotated", o.timestamp, o.track_id, score)
        # Re-encode a short clip at original FPS; optionally redact tracked bystanders.
        clip_id = str(uuid4())
        raw_clip = self.folder / "clip_raw.avi"
        clip_start, clip_end = max(0, start - 3), min(duration - 0.05, start + 7)
        cap = cv2.VideoCapture(str(self.normalized))
        cap.set(cv2.CAP_PROP_POS_MSEC, clip_start * 1000)
        writer = cv2.VideoWriter(
            str(raw_clip),
            cv2.VideoWriter.fourcc(*"MJPG"),
            self.meta["fps"],
            (self.meta["width"], self.meta["height"]),
        )
        try:
            for i in range(int((clip_end - clip_start) * self.meta["fps"])):
                if i % 30 == 0:
                    self.progress("select_evidence")
                ok, frame = cap.read()
                if not ok:
                    break
                writer.write(self.redacted(frame, clip_start + i / self.meta["fps"]))
        finally:
            writer.release()
            cap.release()
        normalize(raw_clip, self.folder / f"{clip_id}.mp4")
        raw_clip.unlink(missing_ok=True)
        self.assets.append(
            Asset(
                id=clip_id,
                asset_type="clip",
                url=f"/api/v1/assets/{clip_id}",
                timestamp=clip_start,
                metadata={
                    "filename": f"{clip_id}.mp4",
                    "redacted": bool(self.options.get("redact")),
                },
            )
        )

    def generate_explanation(self) -> None:
        if not self.congestion.detected:
            self.cause = Cause(
                explanation="No sustained congestion met the configured density, movement and persistence thresholds."
            )
        if self.options.get("redact"):
            self.limitations.append(
                "Evidence redaction blurs detected non-selected subjects only and may miss undetected faces or plates. Source video remains unredacted."
            )

    def quality_check(self) -> None:
        if self.cause.confidence and self.cause.evidence_scores.get("tracking_quality", 0) < 0.65:
            self.cause.confidence = min(self.cause.confidence, 0.59)
            self.limitations.append("Low tracking quality requires manual review.")
        if not self.observations:
            self.limitations.append(
                "No supported road users were detected. This does not prove the road was clear."
            )

    def persist_results(self) -> None:
        tracks = summarize_tracks(self.observations)
        timeline = build_timeline(
            self.observations, self.cause, self.congestion, self.metrics, self.regions, self.cfg
        )
        best = next(
            (a for a in self.assets if a.asset_type == "subject_annotated"),
            next((a for a in self.assets if a.asset_type == "during"), None),
        )
        with Session() as db:
            job = db.get(AnalysisJob, self.job_id)
            if job is None or job.cancelled:
                raise Cancelled()
            existing = db.scalar(select(Incident).where(Incident.analysis_id == self.job_id))
            if existing:
                return
            report = Report(
                analysis_id=self.job_id,
                incident_id=self.incident_id,
                video={
                    "id": self.video_id,
                    "filename": self.filename,
                    **self.meta,
                    "url": f"/api/v1/jobs/{self.job_id}/media",
                },
                congestion=self.congestion,
                cause=self.cause,
                license_plate=self.plate,
                fallback_subject_frame={
                    "required": self.plate.status != "recognized",
                    "asset_id": best.id if best else None,
                    "timestamp": best.timestamp if best else None,
                },
                evidence=self.assets,
                alternative_candidates=[
                    c
                    for c in self.candidates
                    if c.candidate_track_id != self.cause.suspected_track_id
                ],
                limitations=self.limitations,
                model_versions={
                    "detector": self.model_version,
                    "tracker": "ByteTrack",
                    "config": self.cfg["version"],
                    "ocr": getattr(self, "ocr_version", "not run"),
                    "pipeline": "0.1.0",
                },
                timeline=sorted(timeline, key=lambda m: m["timestamp"]),
                metrics=self.metrics,
                tracks=tracks,
                stage_timings=job.timings,
            )
            db.add(
                Incident(
                    id=self.incident_id,
                    video_id=self.video_id,
                    analysis_id=self.job_id,
                    report=report.model_dump(mode="json"),
                )
            )
            db.flush()
            for track in tracks:
                db.add(Track(analysis_id=self.job_id, tracker_id=track["track_id"], data=track))
            for asset in self.assets:
                db.add(
                    EvidenceAsset(
                        id=asset.id,
                        incident_id=self.incident_id,
                        path=str(
                            (self.folder / asset.metadata["filename"]).relative_to(
                                settings().storage_root.resolve()
                            )
                        ),
                        data=asset.model_dump(),
                    )
                )
            for reading in self.plate.raw_readings:
                db.add(PlateReading(incident_id=self.incident_id, data=reading))
            job.status, job.stage, job.progress, job.completed_at = (
                "completed",
                "completed",
                100,
                now(),
            )
            video = db.get(Video, self.video_id)
            if video:
                video.status = "completed"
            db.commit()

    def run(self) -> None:
        with Session() as db:
            job = db.get(AnalysisJob, self.job_id)
            if job and job.status == "completed":
                return
        # Failed attempts may leave unreferenced images. The tracking checkpoint and
        # normalized source are reusable; generated evidence is replaced on replay.
        for path in self.folder.iterdir():
            if path.suffix in {".jpg", ".avi", ".mp4"} and path.name != "normalized.mp4":
                path.unlink()
        graph = StateGraph(State)
        for stage in STAGES:

            def node(state: State, name=stage):
                self.progress(name)
                started = time.monotonic()
                getattr(self, name)()
                elapsed = time.monotonic() - started
                with Session() as db:
                    job = db.get(AnalysisJob, self.job_id)
                    if job:
                        job.timings = {**job.timings, name: round(elapsed, 3)}
                        if name == "persist_results":
                            incident = db.scalar(
                                select(Incident).where(Incident.analysis_id == self.job_id)
                            )
                            if incident:
                                incident.report = {**incident.report, "stage_timings": job.timings}
                        db.commit()
                logger.info(
                    json.dumps(
                        {
                            "analysis_id": self.job_id,
                            "video_id": self.video_id,
                            "job_id": self.job_id,
                            "stage": name,
                            "duration": elapsed,
                            "model_version": getattr(self, "model_version", "pending"),
                        }
                    )
                )
                return state

            graph.add_node(stage, node)
        graph.add_edge(START, STAGES[0])
        for a, b in zip(STAGES, STAGES[1:], strict=False):
            if a not in {"detect_congestion", "score_candidates"}:
                graph.add_edge(a, b)
        graph.add_conditional_edges(
            "detect_congestion",
            lambda _: "generate_candidates" if self.congestion.detected else "select_evidence",
        )
        graph.add_conditional_edges(
            "score_candidates",
            lambda _: "extract_plate" if self.cause.object_type in VEHICLES else "select_evidence",
        )
        graph.add_edge(STAGES[-1], END)
        graph.compile().invoke({"job_id": self.job_id})
