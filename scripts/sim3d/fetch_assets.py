"""Download the 3D models and environment assets used by the 3D scenes.

    uv run python scripts/sim3d/fetch_assets.py

Road-user models listed in config/sim3d_assets.json come from the Objaverse
mirror on Hugging Face (CC BY 4.0; attribution in docs/sim3d-assets.md). The
environment (sky, road and wall textures, trees, street lamps) comes from Poly
Haven (CC0). Files are cached under storage/assets/.
"""

import argparse
import http.client
import json
import time
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co/datasets/allenai/objaverse/resolve/main/"
POLYHAVEN = "https://api.polyhaven.com/files/"
HDRIS = ["kloofendal_48d_partly_cloudy_puresky"]
TEXTURES = ["asphalt_02", "concrete_pavers_02", "clay_plaster", "concrete_wall_006"]
TEXTURE_MAPS = ["Diffuse", "nor_gl", "Rough"]
MODELS = ["jacaranda_tree", "street_lamp_02"]


def _get(url: str, attempts: int = 4) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "traffic-sim3d-asset-fetch/1.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except (OSError, http.client.IncompleteRead):
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def fetch_polyhaven(dest: Path) -> None:
    """Poly Haven environment assets (CC0)."""
    for name in HDRIS:
        target = dest / "hdri" / f"{name}.hdr"
        if not target.exists():
            files = json.loads(_get(POLYHAVEN + name))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_get(files["hdri"]["2k"]["hdr"]["url"]))
            print(f"fetched sky {name}")
    for name in TEXTURES:
        folder = dest / "textures" / name
        if (folder / "Rough.jpg").exists():
            continue
        files = json.loads(_get(POLYHAVEN + name))
        folder.mkdir(parents=True, exist_ok=True)
        for key in TEXTURE_MAPS:
            (folder / f"{key}.jpg").write_bytes(_get(files[key]["2k"]["jpg"]["url"]))
        print(f"fetched texture {name}")
    for name in MODELS:
        folder = dest / "models" / name
        if (folder / ".complete").exists():
            continue
        gltf = json.loads(_get(POLYHAVEN + name))["gltf"]["1k"]["gltf"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.gltf").write_bytes(_get(gltf["url"]))
        for rel, item in gltf["include"].items():
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_bytes(_get(item["url"]))
        (folder / ".complete").touch()
        print(f"fetched model {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=Path("config/sim3d_assets.json"))
    ap.add_argument("--dest", type=Path, default=Path("storage/assets/glbs"))
    ap.add_argument("--environment", type=Path, default=Path("storage/assets/polyhaven"))
    args = ap.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)
    for asset in json.loads(args.manifest.read_text())["assets"]:
        target = args.dest / f"{asset['uid']}.glb"
        if target.exists() and target.read_bytes()[:4] == b"glTF":
            continue
        print(f"fetching {asset['kind']}: {asset['name']}")
        data = _get(BASE + asset["objaverse_path"])
        if data[:4] != b"glTF":
            raise SystemExit(f"{asset['uid']} is not a binary glTF file")
        target.write_bytes(data)
    fetch_polyhaven(args.environment)
    print(f"assets ready in {args.dest} and {args.environment}")


if __name__ == "__main__":
    main()
