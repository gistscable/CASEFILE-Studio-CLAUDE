"""Effects and transitions (v0.4.26): transitions blend INTO a scene without
moving any boundary, looks/grain/vignette/letterbox change the picture, and the
lower-third name card is drawn by libass."""
import subprocess

import numpy as np
from PIL import Image

import effects
import renderer
import storage

FPS = renderer.FPS


def still(folder, name, colour):
    path = folder / name
    Image.new("RGB", (640, 360), colour).save(path)
    return {"id": name, "kind": "image", "path": str(path), "name": name, "width": 640, "height": 360}


def frame_at(video, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(480, 854, 3).astype(int)


def length(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def make(tmp_path, scenes, **project):
    folder = storage.ROOT / "qa" / ("fx-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    assets = [still(folder, "red.png", "#c03020"), still(folder, "blue.png", "#2040c0"), still(folder, "green.png", "#20a040")]
    base = {"id": "fx", "title": "FX", "look": "natural", "captions": False, "assets": assets, "scenes": scenes, "music_volume": 0}
    base.update(project)
    out = tmp_path / "out.mp4"
    try:
        renderer.render(base, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    finally:
        __import__("shutil").rmtree(folder, ignore_errors=True)
    return out


def scene(asset, seconds, **kw):
    return {"id": asset, "title": "", "narration": "", "duration": seconds, "asset_id": asset, "motion": "none", "show_title": False, **kw}


def test_transitions_blend_without_moving_any_boundary(tmp_path):
    out = make(tmp_path, [
        scene("red.png", 2.0),
        scene("blue.png", 2.0, transition="dissolve", transition_duration=1.0),
        scene("green.png", 2.0, transition="slide-left", transition_duration=1.0),
    ])
    assert length(out) == 6 * FPS  # exactly the sum of the scenes
    mid = frame_at(out, 2.5)[240, 427]  # half-way through the dissolve: red and blue mixed
    assert 60 < mid[0] < 170 and 40 < mid[2] < 170, mid
    assert frame_at(out, 3.5)[240, 427][2] > 150  # blue fully in, on time
    slide = frame_at(out, 4.5)
    left, right = slide[240, 100], slide[240, 750]
    assert left[2] > 150 and right[1] > 120 and right[2] < 120, (left, right)  # green slides in over blue
    assert frame_at(out, 1.9)[240, 427][0] > 150  # the first scene is untouched


def test_legacy_names_still_work():
    assert effects.transition_id("cross-dissolve") == "dissolve"
    assert effects.transition_id("cut") == "none"
    assert effects.transition_id("spin") == "none"
    assert effects.transition_length({"transition": "dissolve"}, 3) == 0.5  # a sensible default
    assert effects.transition_length({"transition": "dissolve", "transition_duration": 9}, 3) == 1.5  # at most half the scene


def test_look_letterbox_and_lower_third(tmp_path):
    out = make(
        tmp_path,
        [scene("red.png", 3.0, lower_third={"name": "Dedrick Hilton", "role": "Father"})],
        look="bw",
        effects={"letterbox": True, "vignette": 0.0, "grain": 0},
    )
    img = frame_at(out, 1.5)
    centre = img[240, 600]
    assert abs(centre[0] - centre[1]) < 6 and abs(centre[1] - centre[2]) < 6  # black and white
    assert img[5, 427].max() < 20 and img[475, 427].max() < 20  # letterbox bars
    card = img[300:380, 40:330]
    assert (card.min(axis=2) > 225).sum() > 400  # white name text on the card
    early = frame_at(out, 0.05)  # the card comes in after 0.3 s[300:380, 40:330]
    assert (early.min(axis=2) > 225).sum() < 50


def test_effects_are_clamped():
    assert effects.normalise_effects({"grain": 7, "vignette": -1, "letterbox": "yes"}) == {"grain": 1.0, "vignette": 0.0, "letterbox": False}
    assert effects.normalise_lower_third({"name": "  A  B ", "role": ""}) == {"name": "A B", "role": ""}
    assert effects.normalise_lower_third({"name": "", "role": ""}) is None
    assert "noise" in "".join(effects.picture_filters("natural", {"grain": 0.5}, 854, 480))


def test_moving_photos_with_transitions_keep_every_frame(tmp_path):
    # Odd lengths and zoompan stills: the case that once lost a frame.
    out = make(tmp_path, [
        scene("red.png", 2.37, motion="slow-zoom"),
        scene("blue.png", 1.96, motion="ken-burns", transition="circle", transition_duration=0.8),
        scene("green.png", 2.21, motion="pan-up", transition="zoom"),
    ])
    assert length(out) == round(2.37 * FPS) + round(1.96 * FPS) + round(2.21 * FPS)
