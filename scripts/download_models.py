"""Download pinned public detector weights and official EasyOCR models."""

import argparse
import hashlib
import urllib.request
from pathlib import Path

PLATE_URL = "https://huggingface.co/Koushim/yolov8-license-plate-detection/resolve/83c98fbe7412fe8b3950adb5637cfd08b0f04809/best.pt"
PLATE_SHA256 = "2d95861825bb4184404344c9cf809f40fd31dba785fe54e8ba5b9a3583789822"
parser = argparse.ArgumentParser()
parser.add_argument("--ocr", action="store_true")
args = parser.parse_args()
Path("models").mkdir(exist_ok=True)
from ultralytics import YOLO  # noqa: E402

model = YOLO("models/yolo11n.pt")
print(f"Detector ready: {model.ckpt_path}")
if args.ocr:
    path = Path("models/license_plate.pt")
    if not path.exists():
        urllib.request.urlretrieve(PLATE_URL, path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != PLATE_SHA256:
        path.unlink()
        raise RuntimeError("Plate model checksum mismatch; download removed.")
    import easyocr

    easyocr.Reader(
        ["en"],
        gpu=False,
        model_storage_directory="models/ocr",
        download_enabled=True,
        verbose=False,
    )
    print("Plate detector and OCR models ready")
