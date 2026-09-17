"""Run a real API -> queue -> worker -> report smoke test (no mock inference)."""

import argparse
import json
import time
import urllib.request
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--video", type=Path, required=True)
    args = parser.parse_args()
    boundary = uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{args.video.name}"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
        + args.video.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )

    def request(path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            args.base + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response) if response.status != 204 else None

    req = urllib.request.Request(
        args.base + "/api/v1/videos",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        video = json.load(response)
    job = request(f"/api/v1/videos/{video['id']}/analyze", "POST", {})
    started = time.monotonic()
    seen = []
    while time.monotonic() - started < 600:
        job = request(f"/api/v1/jobs/{job['id']}")
        if job["stage"] not in seen:
            seen.append(job["stage"])
        if job["status"] in {"failed", "cancelled"}:
            raise RuntimeError(job["error_details"] or job["status"])
        if job["status"] == "completed":
            break
        time.sleep(1)
    else:
        raise TimeoutError("Worker did not complete within 10 minutes")
    report = request(f"/api/v1/incidents/{job['incident_id']}")
    assert report["evidence"] and report["license_plate"]["text"] is None
    with urllib.request.urlopen(args.base + report["evidence"][0]["url"]) as response:
        assert response.status == 200
    request(
        f"/api/v1/incidents/{job['incident_id']}/review",
        "PATCH",
        {
            "action": "confirmed",
            "notes": "Automated infrastructure smoke test; not an accuracy assessment.",
        },
    )
    print(
        json.dumps(
            {
                "job_id": job["id"],
                "incident_id": job["incident_id"],
                "stages_observed": seen,
                "tracks": len(report["tracks"]),
                "congestion": report["congestion"]["detected"],
                "elapsed_seconds": round(time.monotonic() - started, 2),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
