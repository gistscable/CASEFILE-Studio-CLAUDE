"""9:16 vertical (v0.4.28): tall frames, blurred-background or crop fill,
text sized for a phone and kept above the app buttons. 16:9 is unchanged."""
import shutil
import subprocess

import numpy as np
from PIL import Image

import captionstyle
import effects
import renderer
import storage


def frame(video, t, w, h):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).astype(int)


def render(tmp_path, **project):
    folder = storage.ROOT / "qa" / ("vert-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1280, 720), "#2040c0")
    img.paste(Image.new("RGB", (200, 720), "#e0e020"), (0, 0))  # a yellow strip at the far left
    path = folder / "wide.png"
    img.save(path)
    base = {"id": "v", "title": "V", "look": "natural", "captions": False, "music_volume": 0,
            "assets": [{"id": "a", "kind": "image", "path": str(path), "name": "wide.png", "width": 1280, "height": 720}],
            "scenes": [{"id": "s", "title": "", "narration": "", "duration": 1.0, "asset_id": "a", "motion": "none", "show_title": False}]}
    base.update(project)
    out = tmp_path / "v.mp4"
    try:
        renderer.render(base, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return out


def size(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return tuple(int(x) for x in out.split(","))


def test_blurred_background_keeps_the_whole_picture(tmp_path):
    out = render(tmp_path, aspect="9:16", vertical_fit="blur")
    assert size(out) == (480, 854)
    f = frame(out, 0.5, 480, 854)
    mid = 427
    assert f[mid, 5][0] > 150 and f[mid, 5][1] > 150  # the yellow strip is still there, at the left edge
    assert f[mid, 240][2] > 150  # blue in the middle, sharp
    top = f[60, 240]
    assert top.max() > 40 and top.max() < 230  # blurred, darker copy above, not black bars


def test_crop_fills_and_cuts_the_sides(tmp_path):
    out = render(tmp_path, aspect="9:16", vertical_fit="crop")
    f = frame(out, 0.5, 480, 854)
    assert f[427, 5][2] > 150 and f[427, 5][0] < 100  # the yellow strip was cut off
    assert f[30, 240][2] > 150  # the picture fills top to bottom


def test_sixteen_nine_is_unchanged(tmp_path):
    out = render(tmp_path)
    assert size(out) == (854, 480)
    assert effects.text_unit(1920, 1080) == 1080 and effects.caption_bottom(0.075, 1920, 1080) == 0.075
    assert captionstyle.style_line(captionstyle.normalise(None), 1280, 720).endswith(",3,2.0,0.0,2,80,80,54,1")


def test_vertical_text_is_bigger_and_above_the_app_buttons():
    w, h = 1080, 1920
    assert effects.text_unit(w, h) == 1080 * 1.4
    line = captionstyle.style_line(captionstyle.normalise(None), w, h)
    assert line.endswith(f",{round(0.2 * h)},1")  # at least 20% up from the bottom
    lt_style, lt_events = effects.lower_third_ass({"name": "A", "role": "B"}, 6, w, h)
    y = int(lt_events[0].split("\\move(")[1].split(",")[1])
    assert y == round(h - 0.48 * h)  # name card above the footage label and captions
    assert effects.picture_filters("natural", {"letterbox": True}, w, h) == []  # no cinema bars in a tall frame
