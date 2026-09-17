"""Fetch a bounded, attributed UVH-26 validation sample; never commit its images."""

import argparse
import hashlib
import json
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = "iisc-aim/UVH-26"


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--output", type=Path, default=Path("storage/datasets/uvh26"))
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        parser.error("Sample count must be between 1 and 100")
    args.output.mkdir(parents=True, exist_ok=True)
    revision = get_json(f"https://huggingface.co/api/datasets/{REPO}")["sha"]
    root = f"https://huggingface.co/datasets/{REPO}/resolve/{revision}/"
    listing = get_json(
        f"https://huggingface.co/api/datasets/{REPO}/tree/{revision}/UVH-26-Val/data/000"
    )
    files = [entry for entry in listing if entry["type"] == "file"][: args.count]
    annotations_path = args.output / "annotations.json"
    urllib.request.urlretrieve(root + "UVH-26-Val/UVH-26-MV-Val.json", annotations_path)
    annotation_data = json.loads(annotations_path.read_text())
    names = {Path(f["path"]).name for f in files}
    annotation_data["images"] = [i for i in annotation_data["images"] if i["file_name"] in names]
    ids = {i["id"] for i in annotation_data["images"]}
    annotation_data["annotations"] = [
        a for a in annotation_data["annotations"] if a["image_id"] in ids
    ]
    annotations_path.write_text(json.dumps(annotation_data))

    def download(entry):
        target = args.output / Path(entry["path"]).name
        if not target.exists() or target.stat().st_size != entry["size"]:
            temporary = target.with_suffix(".part")
            subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "3",
                    "--retry-all-errors",
                    "--max-time",
                    "90",
                    root + entry["path"],
                    "-o",
                    str(temporary),
                ],
                check=True,
            )
            if temporary.stat().st_size != entry["size"]:
                raise RuntimeError(f"Incomplete download: {target.name}")
            temporary.replace(target)
        return {
            "filename": target.name,
            "source": root + entry["path"],
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        downloaded = list(pool.map(download, files))
    manifest = {
        "dataset": REPO,
        "revision": revision,
        "license": "CC-BY-4.0",
        "attribution": "Sharma et al., AIM @ IISc, UVH-26-v1.0, arXiv:2511.02563 (2025)",
        "sampling": "First N lexicographic image files in validation data/000; not a representative benchmark.",
        "files": downloaded,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Downloaded {len(downloaded)} Indian CCTV validation images to {args.output}.")


if __name__ == "__main__":
    main()
