"""Logo watermark (v0.4.36): placement (YouTube default bottom right, 150 px
at 1080p), the nine spots, and a real export with the logo in it."""
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image, ImageDraw

import renderer
import storage
import watermark


def test_normalise_and_default():
    w = watermark.normalise({"enabled": True, "asset_id": "x", "position": "nowhere", "size": 5, "opacity": 0}, images={"x"})
    assert (w["enabled"], w["asset_id"], w["position"], w["size"], w["opacity"]) == (True, "x", "bottom-right", 0.4, 0.2)
    assert watermark.normalise({"asset_id": "gone"}, images=set())["asset_id"] is None
    d = watermark.normalise({})
    assert watermark.box(1920, 1080, 500, 500, d["position"], d["size"]) == (1731, 891, 151, 151)


@pytest.mark.parametrize("pos,where", [
    ("top-left", (38, 38)), ("top-center", (884, 38)), ("top-right", (1731, 38)),
    ("middle-left", (38, 464)), ("center", (884, 464)), ("middle-right", (1731, 464)),
    ("bottom-left", (38, 891)), ("bottom-center", (884, 891)), ("bottom-right", (1731, 891)),
])
def test_nine_spots(pos, where):
    assert watermark.box(1920, 1080, 300, 300, pos, 0.14)[:2] == where


def test_vertical_keeps_the_same_size():
    assert watermark.box(1080, 1920, 300, 300, "bottom-right", 0.14)[2] == 151


def test_export_has_the_logo(tmp_path):
    folder = storage.ROOT / "qa" / ("wm-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        Image.new("RGB", (640, 360), "#2050a0").save(folder / "bg.png")
        logo = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        ImageDraw.Draw(logo).ellipse((0, 0, 199, 199), fill=(255, 220, 0, 255))
        logo.save(folder / "logo.png")
        assets = [{"id": "bg", "kind": "image", "path": str(folder / "bg.png"), "name": "bg.png"},
                  {"id": "lg", "kind": "image", "path": str(folder / "logo.png"), "name": "logo.png", "width": 200, "height": 200}]
        scenes = [{"id": "a", "title": "", "narration": "", "duration": 2.0, "asset_id": "bg", "motion": "none", "show_title": False},
                  {"id": "b", "title": "", "narration": "", "duration": 2.0, "asset_id": "bg", "motion": "slow-zoom", "show_title": False}]
        p = {"id": "w", "title": "W", "look": "natural", "captions": False, "music_volume": 0, "assets": assets, "scenes": scenes,
             "watermark": {"enabled": True, "asset_id": "lg", "position": "top-left", "size": 0.14, "opacity": 1}}
        out = tmp_path / "o.mp4"
        renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    for t in (0.5, 3.0):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        f = np.frombuffer(raw, dtype=np.uint8).reshape(480, 854, 3).astype(int)
        x, y, w, h = watermark.box(854, 480, 200, 200, "top-left", 0.14)
        r, g, b = f[y + h // 2, x + w // 2]
        assert r > 200 and g > 180 and b < 90, (t, f[y + h // 2, x + w // 2])  # yellow logo
        assert f[y + h // 2, 854 - 40][2] > 120  # the rest is the blue picture
