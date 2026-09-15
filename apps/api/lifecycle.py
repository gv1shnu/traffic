from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from packages.shared.db import (
    AnalysisJob,
    EvidenceAsset,
    Incident,
    PlateReading,
    Review,
    Track,
    Video,
)
from packages.shared.storage import storage


def delete_video(db: Session, video: Video) -> None:
    jobs = select(AnalysisJob.id).where(AnalysisJob.video_id == video.id)
    incidents = select(Incident.id).where(Incident.video_id == video.id)
    for entity in (EvidenceAsset, PlateReading, Review):
        db.execute(delete(entity).where(entity.incident_id.in_(incidents)))
    db.execute(delete(Track).where(Track.analysis_id.in_(jobs)))
    db.execute(delete(Incident).where(Incident.video_id == video.id))
    db.execute(delete(AnalysisJob).where(AnalysisJob.video_id == video.id))
    db.delete(video)
    db.commit()
    storage.remove_tree(video.id)
