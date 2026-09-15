from sqlalchemy import select

from apps.worker.tasks import analyze
from fixtures.synthetic import make_video, trajectories
from packages.shared.config import settings
from packages.shared.db import AnalysisJob, EvidenceAsset, Incident, Review, Session, Track
from packages.workflows.investigate import Investigation


class SyntheticAdapter:
    """Test dependency injection only; no production mode switches to this adapter."""

    version = "synthetic-test-only"

    def reset(self):
        pass

    def infer(self, frame, timestamp, index):
        return [o for o in trajectories("queue", 18) if abs(o.timestamp - timestamp) < 0.05]


def upload(client, tmp_path, duration=3):
    source = tmp_path / "video.mp4"
    make_video(source, duration)
    with source.open("rb") as f:
        response = client.post("/api/v1/videos", files={"file": ("road.mp4", f, "video/mp4")})
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_to_report_review_delete(client, tmp_path, monkeypatch):
    from fixtures.synthetic import road

    video = upload(client, tmp_path, 18)
    assert (
        client.put(
            "/api/v1/cameras/test/regions", json={"regions": [r.model_dump() for r in road()]}
        ).status_code
        == 200
    )
    queued = []
    monkeypatch.setattr(analyze, "apply_async", lambda **kwargs: queued.append(kwargs))
    response = client.post(
        f"/api/v1/videos/{video['id']}/analyze", json={"camera_id": "test", "redact": True}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    assert queued[0]["args"] == [job_id]
    assert client.delete(f"/api/v1/videos/{video['id']}").status_code == 409
    Investigation(job_id, adapter=SyntheticAdapter()).run()
    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "completed"
    incident_id = status["incident_id"]
    report = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert report["congestion"]["detected"]
    assert report["cause"]["suspected_track_id"] == 1
    assert report["license_plate"]["text"] is None
    assert report["fallback_subject_frame"]["required"]
    assert len(report["evidence"]) >= 6
    assert client.get(report["evidence"][0]["url"]).headers["content-type"] == "image/jpeg"
    media = client.get(report["video"]["url"], headers={"Range": "bytes=0-99"})
    assert media.status_code == 206
    assert len(media.content) == 100
    assert client.get(f"/api/v1/jobs/{job_id}/events").text.startswith("data: ")
    assert (
        client.patch(
            f"/api/v1/incidents/{incident_id}/review",
            json={"action": "corrected", "corrected_track": 9999},
        ).status_code
        == 422
    )
    response = client.patch(
        f"/api/v1/incidents/{incident_id}/review",
        json={
            "action": "corrected",
            "corrected_cause": "vehicle_blocking_lane",
            "corrected_track": 2,
            "notes": "Human review",
        },
    )
    assert response.status_code == 200
    exported = client.get(f"/api/v1/incidents/{incident_id}/report.json").json()
    assert exported["reviews"][0]["corrected_track"] == 2
    assert exported["cause"]["suspected_track_id"] == 1
    with Session() as db:
        assert len(list(db.scalars(select(Track)))) >= 5
        assert len(list(db.scalars(select(Review)))) == 1
    assert client.delete(f"/api/v1/videos/{video['id']}").status_code == 204
    assert not (settings().storage_root / video["id"]).exists()
    with Session() as db:
        for entity in (Incident, Track, Review, EvidenceAsset, AnalysisJob):
            assert db.scalar(select(entity)) is None


def test_invalid_upload_cleans_storage(client):
    before = set(settings().storage_root.iterdir())
    result = client.post(
        "/api/v1/videos", files={"file": ("../../bad.mp4", b"garbage", "video/mp4")}
    )
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "INVALID_VIDEO"
    assert set(settings().storage_root.iterdir()) == before


def test_queue_failure_and_cancel(client, tmp_path, monkeypatch):
    video = upload(client, tmp_path)

    def fail(**kwargs):
        raise ConnectionError()

    monkeypatch.setattr(analyze, "apply_async", fail)
    response = client.post(f"/api/v1/videos/{video['id']}/analyze", json={})
    assert response.status_code == 503
    with Session() as db:
        job = db.scalar(select(AnalysisJob))
        assert job.status == "failed"
        job_id = job.id
    monkeypatch.setattr(analyze, "apply_async", lambda **kwargs: None)
    assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 202
    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert client.delete(f"/api/v1/videos/{video['id']}").status_code == 204


def test_worker_failure_is_persisted(client, tmp_path, monkeypatch):
    video = upload(client, tmp_path)
    monkeypatch.setattr(analyze, "apply_async", lambda **kwargs: None)
    job_id = client.post(f"/api/v1/videos/{video['id']}/analyze", json={}).json()["id"]

    def fail(self):
        raise RuntimeError("MODEL_MISSING")

    monkeypatch.setattr(Investigation, "run", fail)
    analyze.run(job_id)
    result = client.get(f"/api/v1/jobs/{job_id}").json()
    assert result["status"] == "failed"
    assert "download_models" in result["error_details"]


def test_security_headers_and_origin(client):
    assert client.get("/health").headers["x-content-type-options"] == "nosniff"
    result = client.post(
        "/api/v1/videos/no/analyze", json={}, headers={"Origin": "https://evil.example"}
    )
    assert result.status_code == 403
    assert client.get("/api/v1/videos/not-a-uuid").status_code == 404
