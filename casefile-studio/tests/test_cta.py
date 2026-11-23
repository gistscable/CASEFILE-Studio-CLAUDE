"""Subscribe call-to-action (v0.4.29): button detection on the banner, the
shared timeline, where it is placed, and a real render."""
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageDraw

import cta
import renderer
import storage


def banner(path, button=True):
    im = Image.new("RGB", (1280, 720), "#202020")
    d = ImageDraw.Draw(im)
    d.rectangle((200, 200, 1080, 520), outline=(150, 20, 20), width=3)  # a thin red frame: not a button
    if button:
        d.rounded_rectangle((540, 400, 740, 450), radius=8, fill=(160, 22, 30))
    im.save(path)
    return path


def test_finds_the_button_not_the_frame(tmp_path):
    b = cta.detect_button(banner(tmp_path / "b.png"))
    assert b and abs(b[0] - 540 / 1280) < 0.01 and abs(b[1] - 400 / 720) < 0.015 and abs(b[2] - 740 / 1280) < 0.01
    assert cta.detect_button(banner(tmp_path / "n.png", button=False)) is None


def test_timeline_fades_moves_and_clicks():
    s = cta.state(0, 5)
    assert s["fade"] == 0 and s["move"] == 0 and not s["subscribed"]
    mid = cta.state(1.0, 5)
    assert mid["fade"] == 1 and 0 < mid["move"] < 1
    after = cta.state(2.0, 5)
    assert after["subscribed"] and after["bell"] and after["move"] == 1
    assert cta.state(4.9, 5)["fade"] < 0.3


def test_auto_picks_the_cta_section_and_starts_at_the_word():
    scenes = [
        {"duration": 4, "narration": "Her story begins.", "chapter": "HOOK", "captions": [{"start": 0, "end": 4, "text": "Her story begins."}]},
        {"duration": 6, "narration": "If this matters, subscribe and comment.", "chapter": "SUBSCRIBE / COMMENT CTA",
         "captions": [{"start": 0, "end": 2, "text": "If this matters,"}, {"start": 2, "end": 6, "text": "subscribe and comment."}]},
        {"duration": 3, "narration": "Subscribe for more.", "chapter": "OUTRO"},
    ]
    p = {"scenes": scenes, "cta": {"enabled": True, "asset_id": "b"}}
    assert cta.events(p) == [(5.5, 10.5)]  # 4 s + 2 s - 0.5 s lead; one CTA only
    p["cta"]["mode"] = "scenes"
    scenes[2]["cta"] = True
    assert cta.events(p) == [(10.0, 13.0)]  # ticked by hand; clipped at the end of the video
    p["cta"]["enabled"] = False
    assert cta.events(p) == []


def test_normalise():
    c = cta.normalise({"enabled": True, "opacity": 9, "seconds": 1, "mode": "x", "button": [0.1, 0.2, 0.3, 0.25]}, assets=set())
    assert c["opacity"] == 1.0 and c["seconds"] == 3.0 and c["mode"] == "auto" and c["asset_id"] is None
    assert c["button"] == [0.1, 0.2, 0.3, 0.25]


def test_render_draws_it_across_a_scene_cut(tmp_path):
    folder = storage.ROOT / "qa" / ("cta-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        Image.new("RGB", (640, 360), "#3060a0").save(folder / "bg.png")
        bpath = banner(folder / "banner.png")
        assets = [{"id": "bg", "kind": "image", "path": str(folder / "bg.png"), "name": "bg.png"},
                  {"id": "ban", "kind": "image", "path": str(bpath), "name": "banner.png"}]
        scenes = [
            {"id": "a", "title": "", "narration": "Please subscribe now.", "chapter": "CTA", "duration": 3.0, "asset_id": "bg", "motion": "none", "show_title": False,
             "captions": [{"start": 1.0, "end": 3.0, "text": "Please subscribe now."}]},
            {"id": "b", "title": "", "narration": "", "duration": 4.0, "asset_id": "bg", "motion": "none", "show_title": False},
        ]
        p = {"id": "c", "title": "C", "look": "natural", "captions": False, "music_volume": 0, "assets": assets, "scenes": scenes,
             "cta": {"enabled": True, "asset_id": "ban", "button": cta.detect_button(bpath)}}
        out = tmp_path / "o.mp4"
        renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    def px(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.uint8).reshape(480, 854, 3).astype(int)

    btn = (round(640 / 1280 * 854), round(425 / 720 * 480))
    assert px(0.2)[btn[1], btn[0]][2] > 120  # before: just the blue picture
    red = px(1.4)[btn[1], btn[0]]
    assert red[0] > 120 and red[2] < 90  # the button at full strength while the banner is see-through
    grey = px(3.5)[btn[1], btn[0]]  # after the click, and after the scene cut at 3 s
    assert abs(grey[0] - grey[1]) < 25 and grey.max() < 120  # SUBSCRIBED: dark grey
    assert px(6.0)[btn[1], btn[0]][2] > 120  # gone after 5 s
