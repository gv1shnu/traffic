from pathlib import Path

from fixtures.synthetic import make_video

folder = Path("storage/fixtures")
folder.mkdir(parents=True, exist_ok=True)
for scenario in ["flow", "queue", "sparse", "pedestrian", "unknown", "no_congestion"]:
    make_video(folder / f"{scenario}.mp4", duration=18, scenario=scenario)
(folder / "corrupted.mp4").write_bytes(b"not a video")
print(f"Synthetic fixtures written to {folder}; production inference does not use their labels.")
