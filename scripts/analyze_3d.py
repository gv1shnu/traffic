"""Run the real investigation pipeline on a rendered 3D scenario.

    uv run python scripts/analyze_3d.py storage/sim3d/stalled_car

The scenario folder must contain ``video.mp4`` and ``ground_truth.json`` (written
by ``scripts/render_3d.py``). The clip is uploaded through the HTTP API (in
process), the camera regions are taken from the projected lane geometry, and the
same ``Investigation`` the Celery worker runs is executed with the real
YOLO/ByteTrack adapter. The report, timeline and evidence files are copied to
``<scenario>/analysis/``. Ground truth is never passed to the pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario_dir", type=Path)
    ap.add_argument("--ocr", action="store_true", help="enable plate OCR (needs OCR weights)")
    args = ap.parse_args()
    folder = args.scenario_dir.resolve()
    work = folder / "app"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    # Isolated database and storage, configured before application imports.
    os.environ["STORAGE_ROOT"] = str(work / "media")
    os.environ["DATABASE_URL"] = f"sqlite:///{work}/app.db"
    os.environ["OCR_ENABLED"] = "true" if args.ocr else "false"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from fastapi.testclient import TestClient

    from apps.api.main import app
    from apps.worker.tasks import analyze
    from packages.shared.db import Base, engine
    from packages.workflows.investigate import Investigation

    Base.metadata.create_all(engine)
    gt = json.loads((folder / "ground_truth.json").read_text())
    regions = [{k: r[k] for k in ("id", "name", "polygon", "direction")} for r in gt["regions"]]
    analyze.apply_async = lambda **kwargs: None  # run in-process below instead of via Celery

    with TestClient(app) as client:
        with (folder / "video.mp4").open("rb") as handle:
            response = client.post(
                "/api/v1/videos", files={"file": (f"{folder.name}.mp4", handle, "video/mp4")}
            )
        response.raise_for_status()
        video = response.json()
        client.put("/api/v1/cameras/sim3d/regions", json={"regions": regions}).raise_for_status()
        response = client.post(
            f"/api/v1/videos/{video['id']}/analyze", json={"camera_id": "sim3d", "redact": False}
        )
        response.raise_for_status()
        job_id = response.json()["id"]
        Investigation(job_id).run()
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] != "completed":
            raise SystemExit(f"analysis failed: {job}")
        incident = job["incident_id"]
        out = folder / "analysis"
        shutil.rmtree(out, ignore_errors=True)
        (out / "evidence").mkdir(parents=True)
        report = client.get(f"/api/v1/incidents/{incident}/report.json").json()
        timeline = client.get(f"/api/v1/incidents/{incident}/timeline").json()
        for item in report.get("evidence", []):
            url = item.get("url")
            if not url:
                continue
            data = client.get(url)
            if data.status_code == 200:
                suffix = ".mp4" if "video" in data.headers.get("content-type", "") else ".jpg"
                name = f"{item['asset_type']}_{item['id']}{suffix}"
                (out / "evidence" / name).write_bytes(data.content)
                item["local_file"] = f"evidence/{name}"
        (out / "report.json").write_text(json.dumps(report, indent=2))
        (out / "timeline.json").write_text(json.dumps(timeline, indent=2))
        tracks = Path(os.environ["STORAGE_ROOT"]) / video["id"] / job_id / "detect_and_track.json"
        if tracks.exists():
            shutil.copy(tracks, out / "tracks.json")
        cause = report.get("cause", {})
        print(
            f"{folder.name}: congestion={report['congestion']['detected']} "
            f"cause={cause.get('type')} track={cause.get('suspected_track_id')} "
            f"confidence={cause.get('confidence')}"
        )


if __name__ == "__main__":
    main()
