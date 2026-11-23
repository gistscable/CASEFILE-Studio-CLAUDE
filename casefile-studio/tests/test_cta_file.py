"""Your own subscribe animation (v0.4.35): a .mov/.webm with transparency or a
GIF laid over the video, with the video behind it blurred, rendered into the
final MP4 by Casefile."""
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image, ImageDraw

import cta
import renderer
import storage


def stripes(path):
    im = Image.new("RGB", (640, 360), "#f0f0f0")
    d = ImageDraw.Draw(im)
    for x in range(0, 640, 8):
        d.rectangle((x, 0, x + 3, 360), fill="#101010")
    im.save(path)


def animation(folder, kind):
    """3 s, 320x180: a red box in the middle, transparent all round."""
    src = folder / "f%03d.png"
    for n in range(36):
        im = Image.new("RGBA", (320, 180), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle((110, 60, 210, 120), fill=(220, 20, 30, 255))
        im.save(folder / f"f{n:03d}.png")
    out = folder / f"sub.{kind}"
    base = ["ffmpeg", "-v", "error", "-y", "-framerate", "12", "-i", str(src)]
    if kind == "mov":
        cmd = base + ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(out)]
    elif kind == "webm":
        cmd = base + ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "1M", str(out)]
    else:
        cmd = base + ["-filter_complex", "split[a][b];[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse", str(out)]
    subprocess.run(cmd, check=True)
    return out


def test_normalise_keeps_the_new_choices():
    c = cta.normalise({"enabled": True, "style": "blur", "source": "file", "file_id": "v", "size": 9, "y": 0}, files={"v"})
    assert (c["style"], c["source"], c["file_id"], c["size"], c["y"]) == ("blur", "file", "v", 1.0, 0.15)
    c = cta.normalise({"style": "x", "source": "y", "file_id": "gone"}, files=set())
    assert (c["style"], c["source"], c["file_id"]) == ("overlay", "casefile", None)


def test_own_file_sets_the_length():
    p = {"assets": [{"id": "v", "kind": "video", "duration": 3.2}],
         "scenes": [{"duration": 10, "narration": "subscribe", "chapter": "CTA"}],
         "cta": {"enabled": True, "source": "file", "file_id": "v"}}
    (a, b), = cta.events(p)
    assert round(b - a, 2) == 3.2
    p["assets"] = []  # the file was deleted: nothing to show
    assert cta.events(p) == []


@pytest.mark.parametrize("kind", ["mov", "webm", "gif"])
def test_render_blurs_behind_your_animation(tmp_path, kind):
    folder = storage.ROOT / "qa" / (f"ctafile-{kind}-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        stripes(folder / "bg.png")
        anim = animation(folder, kind)
        info = renderer.probe(anim)
        assets = [{"id": "bg", "kind": "image", "path": str(folder / "bg.png"), "name": "bg.png"},
                  dict(info, id="sub", kind="video", path=str(anim), name=anim.name)]
        scenes = [
            {"id": "a", "title": "", "narration": "Please subscribe now.", "chapter": "CTA", "duration": 2.0, "asset_id": "bg", "motion": "none", "show_title": False,
             "captions": [{"start": 0.5, "end": 2.0, "text": "Please subscribe now."}]},
            {"id": "b", "title": "", "narration": "", "duration": 4.0, "asset_id": "bg", "motion": "none", "show_title": False},
        ]
        p = {"id": "c", "title": "C", "look": "natural", "captions": False, "music_volume": 0, "assets": assets, "scenes": scenes,
             "cta": {"enabled": True, "source": "file", "file_id": "sub", "style": "blur", "size": 0.5, "y": 0.5}}
        (t0, t1), = cta.events(p)
        assert 2.5 < t1 - t0 < 3.5
        out = tmp_path / "o.mp4"
        renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    def frame(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.uint8).reshape(480, 854, 3).astype(int)

    # The animation is 427 px wide in the middle; its red box is at its centre.
    for t in (t0 + 1.0, 2.3):  # before and after the scene cut at 2 s
        f = frame(t)
        r, g, b = f[240, 427]
        assert r > 150 and g < 90 and b < 90, (t, f[240, 427])  # your animation, solid
        strip = f[150, 300:400].mean(axis=1)  # transparent part of your file: blurred stripes show through
        assert strip.std() < 25 and 40 < strip.mean() < 200, (t, strip.std(), strip.mean())
    before = frame(max(0.05, t0 - 0.3))[150, 300:400].mean(axis=1)
    assert before.std() > 60  # sharp stripes before
    after = frame(t1 + 0.5)
    assert after[150, 300:400].mean(axis=1).std() > 60 and after[240, 427][0] - after[240, 427][2] < 40  # all gone after


def test_casefile_banner_as_a_card_over_blur(tmp_path):
    folder = storage.ROOT / "qa" / ("ctacard-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        stripes(folder / "bg.png")
        im = Image.new("RGB", (1280, 720), "#202020")
        ImageDraw.Draw(im).rounded_rectangle((540, 400, 740, 450), radius=8, fill=(160, 22, 30))
        im.save(folder / "banner.png")
        assets = [{"id": "bg", "kind": "image", "path": str(folder / "bg.png"), "name": "bg.png"},
                  {"id": "ban", "kind": "image", "path": str(folder / "banner.png"), "name": "banner.png", "width": 1280, "height": 720}]
        scenes = [{"id": "a", "title": "", "narration": "Subscribe.", "chapter": "CTA", "duration": 6.0, "asset_id": "bg", "motion": "none", "show_title": False,
                   "captions": [{"start": 0.5, "end": 2.0, "text": "Subscribe."}]}]
        p = {"id": "c", "title": "C", "look": "natural", "captions": False, "music_volume": 0, "assets": assets, "scenes": scenes,
             "cta": {"enabled": True, "asset_id": "ban", "style": "blur", "size": 0.5, "y": 0.5, "button": cta.detect_button(folder / "banner.png")}}
        out = tmp_path / "o.mp4"
        renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "2.5", "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    f = np.frombuffer(raw, dtype=np.uint8).reshape(480, 854, 3).astype(int)
    assert f[200, 427].max() < 60  # the banner card is solid (dark), not see-through
    side = f[100, 40:140].mean(axis=1)  # outside the card: blurred video
    assert side.std() < 25 and side.mean() > 40
