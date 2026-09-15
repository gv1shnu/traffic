import json
import subprocess
from pathlib import Path
from typing import Any

import cv2

from packages.shared.config import settings

EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
MIMES = {
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
    "video/x-msvideo",
    "video/avi",
    "application/octet-stream",
}


class VideoError(ValueError):
    pass


def validate_header(path: Path, filename: str, mime: str) -> None:
    if Path(filename).suffix.lower() not in EXTENSIONS or mime not in MIMES:
        raise VideoError("Choose MP4, MOV, MKV or AVI video.")
    with path.open("rb") as stream:
        header = stream.read(32)
    valid = len(header) >= 12 and (
        header[4:8] == b"ftyp"
        or header[:4] == b"\x1aE\xdf\xa3"
        or (header[:4] == b"RIFF" and header[8:12] == b"AVI ")
    )
    if not valid:
        raise VideoError("File signature does not match a supported video container.")


def probe(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(result.stdout)
        stream = next(s for s in data["streams"] if s["codec_type"] == "video")
        num, den = stream["avg_frame_rate"].split("/")
        fps = float(num) / float(den)
        duration = float(data["format"].get("duration", stream.get("duration", 0)))
        width, height = int(stream["width"]), int(stream["height"])
        if not (0 < fps <= 120 and 0 < duration <= settings().max_duration_seconds):
            raise VideoError(f"Video must be ≤ {settings().max_duration_seconds}s and 1–120 FPS.")
        if width < 32 or height < 32 or width * height > settings().max_pixels:
            raise VideoError("Resolution must be between 32×32 and 3840×2160 pixels.")
        if duration * min(fps, settings().inference_fps) > settings().max_samples:
            raise VideoError("Video exceeds the configured inference sample budget.")
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "duration_seconds": duration,
            "frame_count": int(stream.get("nb_frames", 0) or 0)
            if str(stream.get("nb_frames", "0")).isdigit()
            else int(duration * fps),
            "codec": stream["codec_name"],
        }
    except (
        subprocess.SubprocessError,
        KeyError,
        StopIteration,
        ValueError,
        ZeroDivisionError,
    ) as exc:
        if isinstance(exc, VideoError):
            raise
        raise VideoError(
            "Video is corrupted or has invalid metadata. Re-export as H.264 MP4."
        ) from exc


def normalize(source: Path, target: Path) -> None:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-threads",
                "2",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-movflags",
                "+faststart",
                "-y",
                str(target),
            ],
            capture_output=True,
            timeout=max(90, settings().max_duration_seconds * 3),
            check=True,
        )
    except subprocess.SubprocessError as exc:
        raise VideoError("Video normalization failed. Re-export the file as H.264 MP4.") from exc


def read_frame(path: Path, timestamp: float):
    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0, timestamp) * 1000)
        ok, frame = cap.read()
        if not ok:
            raise VideoError("Cannot decode requested evidence frame.")
        return frame
    finally:
        cap.release()
