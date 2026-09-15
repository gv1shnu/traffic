import pytest

from fixtures.synthetic import make_video
from packages.shared.storage import storage
from packages.vision.video import VideoError, normalize, probe, validate_header


def test_real_video_probe_and_normalization(tmp_path):
    source = tmp_path / "fixture.mp4"
    target = tmp_path / "normalized.mp4"
    make_video(source)
    validate_header(source, "fixture.mp4", "video/mp4")
    metadata = probe(source)
    assert metadata["width"] == 720
    assert metadata["duration_seconds"] == 3
    normalize(source, target)
    assert probe(target)["codec"] == "h264"


def test_corruption_and_unsupported_type(tmp_path):
    source = tmp_path / "bad.mp4"
    source.write_bytes(b"not video")
    with pytest.raises(VideoError):
        validate_header(source, "bad.mp4", "video/mp4")
    with pytest.raises(VideoError):
        validate_header(source, "bad.exe", "video/mp4")
    with pytest.raises(VideoError):
        probe(source)


def test_path_traversal():
    with pytest.raises(ValueError):
        storage.resolve("../../etc/passwd")
    with pytest.raises(ValueError):
        storage.remove_tree(".")
