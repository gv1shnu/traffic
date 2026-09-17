import logging
from contextlib import contextmanager
from datetime import timedelta

from celery import Celery
from sqlalchemy import select, text

from packages.shared.config import settings
from packages.shared.db import AnalysisJob, Session, Video, engine, now
from packages.shared.storage import storage
from packages.workflows.investigate import Cancelled, Investigation

celery = Celery("traffic", broker=settings().redis_url, backend=settings().redis_url)
celery.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_time_limit=7200,
    broker_transport_options={"visibility_timeout": 7500},
    beat_schedule={"retention": {"task": "traffic.retention", "schedule": 3600}},
)


@contextmanager
def exclusive_job(job_id: str):
    # PostgreSQL session locks release automatically if a worker process dies.
    if engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as connection:
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_id}
        )
        try:
            yield bool(acquired)
        finally:
            if acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:job))"), {"job": job_id}
                )


@celery.task(name="traffic.analyze", bind=True)
def analyze(self, job_id: str):
    with Session() as db:
        job = db.get(AnalysisJob, job_id)
        if job is None or job.status in {"completed", "cancelled"}:
            return
    try:
        with exclusive_job(job_id) as acquired:
            if acquired:
                Investigation(job_id).run()
    except Cancelled:
        with Session() as db:
            job = db.get(AnalysisJob, job_id)
            if job:
                job.status, job.stage, job.completed_at = "cancelled", "cancelled", now()
                storage.remove_tree(f"{job.video_id}/{job.id}")
                job.checkpoint = {}
                db.commit()
    except Exception as exc:
        # Exception strings may contain OCR text; logs only contain safe identifiers.
        logging.getLogger("traffic.worker").error(
            "analysis_failed job_id=%s error_type=%s", job_id, type(exc).__name__
        )
        with Session() as db:
            job = db.get(AnalysisJob, job_id)
            if job:
                job.status, job.error_code, job.completed_at = "failed", type(exc).__name__, now()
                job.error_details = (
                    "Model setup is incomplete. Run scripts/download_models.py."
                    if "MODEL_MISSING" in str(exc)
                    else f"Stage {job.stage} failed ({type(exc).__name__}). Check media validity and worker/model setup, then retry."
                )
                db.commit()


@celery.task(name="traffic.retention")
def retention():
    from apps.api.lifecycle import delete_video

    with Session() as db:
        old = list(
            db.scalars(
                select(Video).where(
                    Video.created_at < now() - timedelta(days=settings().retention_days)
                )
            )
        )
        for video in old:
            busy = db.scalar(
                select(AnalysisJob).where(
                    AnalysisJob.video_id == video.id,
                    AnalysisJob.status.in_(["queued", "processing"]),
                )
            )
            if not busy:
                delete_video(db, video)
