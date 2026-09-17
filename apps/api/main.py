import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import cv2
from fastapi import Depends, FastAPI, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from redis import Redis
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.lifecycle import delete_video
from apps.api.security import BodyLimitMiddleware
from apps.worker.tasks import analyze, celery
from packages.shared.config import settings, thresholds
from packages.shared.db import (
    AnalysisJob,
    Camera,
    EvidenceAsset,
    Incident,
    Review,
    Video,
    engine,
    get_session,
    now,
)
from packages.shared.db import Session as SessionFactory
from packages.shared.schemas import AnalyzeInput, CameraConfig, Report, ReviewInput
from packages.shared.storage import storage
from packages.vision.video import VideoError, probe, read_frame, validate_header

logger = logging.getLogger("traffic.api")


class APIError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    yield


app = FastAPI(
    title="Traffic Cause Investigator",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(APIError)
async def api_error(request: Request, exc: APIError):
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.message, "details": {}}}, status_code=exc.status
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        {
            "error": {
                "code": "UPLOAD_TOO_LARGE" if exc.status_code == 413 else "HTTP_ERROR",
                "message": str(exc.detail),
                "details": {},
            }
        },
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": {"fields": [".".join(str(p) for p in e["loc"]) for e in exc.errors()]},
            }
        },
        status_code=422,
    )


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error(json.dumps({"event": "request_failed", "error_code": type(exc).__name__}))
    return JSONResponse(
        {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Request failed. Check server health and retry.",
                "details": {},
            }
        },
        status_code=500,
    )


_requests: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def security(request: Request, call_next):
    origin = request.headers.get("origin")
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and origin
        and origin not in settings().cors_origins
    ):
        return JSONResponse(
            {"error": {"code": "ORIGIN_DENIED", "message": "Origin not allowed.", "details": {}}},
            status_code=403,
        )
    ip = request.client.host if request.client else "local"
    if len(_requests) > 10000:
        cutoff = time.monotonic() - 60
        for key in list(_requests):
            if not _requests[key] or _requests[key][-1] < cutoff:
                del _requests[key]
    recent = _requests[ip]
    moment = time.monotonic()
    while recent and recent[0] < moment - 60:
        recent.popleft()
    if len(recent) >= settings().rate_limit_per_minute:
        return JSONResponse(
            {
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many requests. Retry in one minute.",
                    "details": {},
                }
            },
            status_code=429,
            headers={"Retry-After": "60"},
        )
    recent.append(moment)
    content_length = request.headers.get("content-length")
    if content_length and (
        not content_length.isdigit()
        or int(content_length) > (settings().max_upload_mb + 1) * 1024 * 1024
    ):
        return JSONResponse(
            {
                "error": {
                    "code": "UPLOAD_TOO_LARGE",
                    "message": "Upload exceeds configured size limit.",
                    "details": {},
                }
            },
            status_code=413,
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    )
    if request.method != "GET":
        logger.info(
            json.dumps(
                {
                    "event": "mutation",
                    "method": request.method,
                    "status": response.status_code,
                    "route": getattr(request.scope.get("route"), "path", "unknown")
                    if request.scope.get("route")
                    else "unknown",
                }
            )
        )
    return response


def require(db: Session, entity, ident: str):
    if entity != Camera:
        try:
            UUID(ident)
        except ValueError as exc:
            raise APIError("NOT_FOUND", "Resource not found.", 404) from exc
    result = db.get(entity, ident)
    if result is None:
        raise APIError("NOT_FOUND", "Resource not found.", 404)
    return result


def job_json(job: AnalysisJob, db: Session) -> dict:
    incident = db.scalar(select(Incident).where(Incident.analysis_id == job.id))
    return {
        "id": job.id,
        "video_id": job.video_id,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error_code": job.error_code,
        "error_details": job.error_details,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "incident_id": incident.id if incident else None,
        "timings": job.timings,
        "mode": settings().device,
    }


def video_json(video: Video, db: Session) -> dict:
    job = db.scalar(
        select(AnalysisJob)
        .where(AnalysisJob.video_id == video.id)
        .order_by(AnalysisJob.created_at.desc())
    )
    return {
        "id": video.id,
        "filename": video.filename,
        "status": video.status,
        "created_at": video.created_at.isoformat(),
        "metadata": video.metadata_json,
        "thumbnail_url": f"/api/v1/videos/{video.id}/thumbnail",
        "job": job_json(job, db) if job else None,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        Redis.from_url(settings().redis_url, socket_connect_timeout=2).ping()
    except Exception as exc:
        raise APIError("NOT_READY", "Database or Redis unavailable.", 503) from exc
    return {"status": "ready"}


@app.get("/api/v1/worker-health")
def worker_health():
    try:
        replies = celery.control.ping(timeout=1)
    except Exception:
        replies = []
    return {
        "status": "ready" if replies else "unavailable",
        "workers": len(replies),
        "mode": settings().device,
    }


@app.get("/api/v1/metrics")
def counters(db: Session = Depends(get_session)):
    return {
        "jobs": {
            status: count
            for status, count in db.execute(
                select(AnalysisJob.status, func.count()).group_by(AnalysisJob.status)
            )
        }
    }


@app.get("/api/v1/config")
def public_config():
    return {
        "max_upload_mb": settings().max_upload_mb,
        "max_duration_seconds": settings().max_duration_seconds,
        "mode": settings().device,
    }


@app.post("/api/v1/videos", status_code=201)
def upload(file: UploadFile, db: Session = Depends(get_session)):
    ident = str(uuid4())
    folder = storage.resolve(ident)
    folder.mkdir(parents=True)
    source = folder / "original"
    digest = hashlib.sha256()
    size = 0
    filename = Path((file.filename or "video").replace("\\", "/")).name[:200]
    try:
        with source.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings().max_upload_mb * 1024 * 1024:
                    raise APIError("UPLOAD_TOO_LARGE", "Video exceeds upload size limit.", 413)
                digest.update(chunk)
                out.write(chunk)
        validate_header(source, filename, file.content_type or "application/octet-stream")
        metadata = probe(source)
        frame = read_frame(source, 0)
        cv2.imwrite(str(folder / "thumbnail.jpg"), frame)
        video = Video(
            id=ident,
            filename=filename,
            path=f"{ident}/original",
            normalized_path=None,
            file_hash=digest.hexdigest(),
            mime_type=file.content_type or "application/octet-stream",
            metadata_json=metadata,
        )
        db.add(video)
        db.commit()
        return video_json(video, db)
    except VideoError as exc:
        storage.remove_tree(ident)
        raise APIError("INVALID_VIDEO", str(exc), 422) from exc
    except Exception:
        storage.remove_tree(ident)
        raise
    finally:
        file.file.close()


@app.get("/api/v1/videos")
def videos(db: Session = Depends(get_session)):
    return [
        video_json(v, db)
        for v in db.scalars(select(Video).order_by(Video.created_at.desc()).limit(50))
    ]


@app.get("/api/v1/videos/{video_id}")
def get_video(video_id: str, db: Session = Depends(get_session)):
    return video_json(require(db, Video, video_id), db)


@app.get("/api/v1/videos/{video_id}/thumbnail")
def thumbnail(video_id: str, db: Session = Depends(get_session)):
    require(db, Video, video_id)
    return FileResponse(storage.resolve(f"{video_id}/thumbnail.jpg"), media_type="image/jpeg")


@app.get("/api/v1/videos/{video_id}/media")
def media(video_id: str, db: Session = Depends(get_session)):
    video = require(db, Video, video_id)
    if not video.normalized_path or not storage.resolve(video.normalized_path).exists():
        raise APIError("NOT_READY", "Browser video is available after normalization.", 409)
    return FileResponse(storage.resolve(video.normalized_path), media_type="video/mp4")


@app.post("/api/v1/videos/{video_id}/analyze", status_code=202)
def start_analysis(video_id: str, options: AnalyzeInput, db: Session = Depends(get_session)):
    video = require(db, Video, video_id)
    # Serialize submissions for this video in PostgreSQL.
    db.execute(select(Video).where(Video.id == video_id).with_for_update())
    busy = db.scalar(
        select(AnalysisJob).where(
            AnalysisJob.video_id == video_id, AnalysisJob.status.in_(["queued", "processing"])
        )
    )
    if busy:
        return job_json(busy, db)
    camera = require(db, Camera, options.camera_id) if options.camera_id else None
    job = AnalysisJob(
        video_id=video_id,
        config={
            "regions": camera.config["regions"] if camera else [],
            "redact": options.redact,
            "thresholds": thresholds(),
        },
    )
    db.add(job)
    video.status = "queued"
    db.commit()
    try:
        analyze.apply_async(args=[job.id], task_id=job.id, retry=False)
    except Exception as exc:
        job.status, job.error_code, job.error_details = (
            "failed",
            "QUEUE_UNAVAILABLE",
            "Redis or the worker queue is unavailable. Start services, then retry.",
        )
        db.commit()
        raise APIError("QUEUE_UNAVAILABLE", job.error_details, 503) from exc
    return job_json(job, db)


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_session)):
    return job_json(require(db, AnalysisJob, job_id), db)


@app.get("/api/v1/jobs/{job_id}/media")
def analysis_media(job_id: str, db: Session = Depends(get_session)):
    job = require(db, AnalysisJob, job_id)
    path = storage.resolve(f"{job.video_id}/{job.id}/normalized.mp4")
    if not path.exists():
        raise APIError("NOT_READY", "Normalized video is not available.", 409)
    return FileResponse(path, media_type="video/mp4")


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel(job_id: str, db: Session = Depends(get_session)):
    job = require(db, AnalysisJob, job_id)
    if job.status in {"completed", "failed", "cancelled"}:
        return job_json(job, db)
    job.cancelled = True
    if job.status == "queued":
        job.status, job.stage, job.completed_at = "cancelled", "cancelled", now()
    db.commit()
    return job_json(job, db)


@app.post("/api/v1/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str, db: Session = Depends(get_session)):
    job = require(db, AnalysisJob, job_id)
    if job.status not in {"failed", "cancelled"}:
        raise APIError("JOB_ACTIVE", "Only failed or cancelled jobs can be retried.", 409)
    other = db.scalar(
        select(AnalysisJob).where(
            AnalysisJob.video_id == job.video_id, AnalysisJob.status.in_(["queued", "processing"])
        )
    )
    if other:
        raise APIError("JOB_ACTIVE", "Another analysis is running for this video.", 409)
    job.status, job.stage, job.cancelled = "queued", "queued", False
    job.error_code, job.error_details, job.completed_at = None, None, None
    db.commit()
    try:
        analyze.apply_async(args=[job.id], task_id=job.id, retry=False)
    except Exception as exc:
        job.status, job.error_code, job.error_details = (
            "failed",
            "QUEUE_UNAVAILABLE",
            "Queue unavailable. Start Redis and retry.",
        )
        db.commit()
        raise APIError("QUEUE_UNAVAILABLE", job.error_details, 503) from exc
    return job_json(job, db)


@app.get("/api/v1/jobs/{job_id}/events")
async def events(job_id: str):
    def snapshot():
        with SessionFactory() as db:
            return job_json(require(db, AnalysisJob, job_id), db)

    await run_in_threadpool(snapshot)

    async def stream():
        previous = None
        for _ in range(7200):
            data = await run_in_threadpool(snapshot)
            encoded = json.dumps(data)
            if encoded != previous:
                yield f"data: {encoded}\n\n"
                previous = encoded
            else:
                yield ": heartbeat\n\n"
            if data["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/api/v1/incidents/{incident_id}", response_model=Report)
def incident(incident_id: str, db: Session = Depends(get_session)):
    row = require(db, Incident, incident_id)
    return {**row.report, "review_status": row.review_status}


@app.get("/api/v1/incidents/{incident_id}/timeline")
def timeline(incident_id: str, db: Session = Depends(get_session)):
    return require(db, Incident, incident_id).report["timeline"]


@app.get("/api/v1/incidents/{incident_id}/evidence")
def evidence(incident_id: str, db: Session = Depends(get_session)):
    return require(db, Incident, incident_id).report["evidence"]


@app.get("/api/v1/incidents/{incident_id}/report.json")
def report(incident_id: str, db: Session = Depends(get_session)):
    row = require(db, Incident, incident_id)
    reviews = [
        {"id": r.id, "created_at": r.created_at.isoformat(), **r.data}
        for r in db.scalars(select(Review).where(Review.incident_id == incident_id))
    ]
    return JSONResponse(
        {**row.report, "review_status": row.review_status, "reviews": reviews},
        headers={"Content-Disposition": 'attachment; filename="traffic-report.json"'},
    )


@app.patch("/api/v1/incidents/{incident_id}/review")
def review(incident_id: str, correction: ReviewInput, db: Session = Depends(get_session)):
    row = require(db, Incident, incident_id)
    if correction.corrected_track is not None and correction.corrected_track not in {
        t["track_id"] for t in row.report["tracks"]
    }:
        raise APIError(
            "INVALID_TRACK", "Corrected subject must be a track from this analysis.", 422
        )
    db.add(Review(incident_id=incident_id, data=correction.model_dump(mode="json")))
    row.review_status = correction.action
    db.commit()
    return {
        "review_status": row.review_status,
        "message": "Review saved. Computed evidence is preserved; corrections are recorded separately.",
    }


@app.get("/api/v1/incidents/{incident_id}/reviews")
def reviews(incident_id: str, db: Session = Depends(get_session)):
    require(db, Incident, incident_id)
    return [
        {"id": r.id, "created_at": r.created_at.isoformat(), **r.data}
        for r in db.scalars(
            select(Review)
            .where(Review.incident_id == incident_id)
            .order_by(Review.created_at.desc())
        )
    ]


@app.get("/api/v1/assets/{asset_id}")
def asset(asset_id: str, db: Session = Depends(get_session)):
    row = require(db, EvidenceAsset, asset_id)
    path = storage.resolve(row.path)
    if not path.exists():
        raise APIError("ASSET_MISSING", "Evidence asset no longer exists.", 404)
    return FileResponse(path, media_type="video/mp4" if path.suffix == ".mp4" else "image/jpeg")


@app.get("/api/v1/cameras/{camera_id}/regions")
def regions(camera_id: str, db: Session = Depends(get_session)):
    row = db.get(Camera, camera_id)
    return row.config if row else {"regions": []}


@app.put("/api/v1/cameras/{camera_id}/regions")
def save_regions(camera_id: str, config: CameraConfig, db: Session = Depends(get_session)):
    import re

    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", camera_id):
        raise APIError("INVALID_CAMERA", "Invalid camera identifier.", 422)
    row = db.get(Camera, camera_id)
    if row:
        row.config = config.model_dump()
    else:
        db.add(Camera(id=camera_id, config=config.model_dump()))
    db.commit()
    return config


@app.delete("/api/v1/videos/{video_id}", status_code=204)
def remove(video_id: str, db: Session = Depends(get_session)):
    video = require(db, Video, video_id)
    busy = db.scalar(
        select(AnalysisJob).where(
            AnalysisJob.video_id == video_id, AnalysisJob.status.in_(["queued", "processing"])
        )
    )
    if busy:
        raise APIError(
            "JOB_ACTIVE", "Cancel processing and wait for cancellation before deleting.", 409
        )
    delete_video(db, video)


@app.get("/docs", include_in_schema=False)
def api_reference():
    from html import escape

    from fastapi.responses import HTMLResponse

    schema = app.openapi()
    sections = []
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            sections.append(
                f"<details><summary><b>{escape(method.upper())}</b> <code>{escape(path)}</code> — {escape(operation.get('summary', ''))}</summary>"
                f"<pre>{escape(json.dumps(operation, indent=2))}</pre></details>"
            )
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Traffic API reference</title><style>body{font:15px system-ui;color:#263b37;background:#f7f8f5;max-width:1100px;margin:40px auto;padding:20px}h1{font-weight:500}details{padding:15px;margin:12px 0;background:white;border:1px solid #dce4d8;border-radius:6px}summary{cursor:pointer}b{display:inline-block;min-width:65px;color:#2e7056}pre{overflow:auto;font-size:12px}a{color:#2e7056}</style></head><body><h1>Traffic Cause Investigator API</h1><p>Generated from the current OpenAPI schema. <a href='/openapi.json'>Download OpenAPI JSON</a></p>"
        + "".join(sections)
        + "<details><summary>Shared schemas</summary><pre>"
        + escape(json.dumps(schema.get("components", {}), indent=2))
        + "</pre></details></body></html>"
    )
