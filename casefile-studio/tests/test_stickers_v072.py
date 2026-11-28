"""v0.4.72 Point & mark stickers: spotlight, blur, block, box, ring, pointer, callout, label;
your words on a sticker, its shape, its strength, and up to 120 keyframes (the follow path)."""
import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image, ImageDraw

import effects
import renderer
import stickers
import storage
from tests.test_overlays_v049 import grab, render, node_eval

ROOT = storage.ROOT
MARK = ["spotlight", "blur", "block", "box", "ring", "pointer", "callout", "label"]


def test_spec_is_shared_and_mark_comes_first():
    spec = json.loads((ROOT / "web" / "src" / "effectsSpec.json").read_text())
    assert spec["stickers"] == effects.SPEC["stickers"]
    st = spec["stickers"]
    assert st["tabs"][0]["id"] == "mark"
    assert [c["id"] for c in st["catalog"] if c["tab"] == "mark"] == MARK
    assert st["keyframes_max"] == 120 and st["limits"]["text"] == 28


@pytest.mark.parametrize("kind", MARK)
def test_new_kinds_draw_at_their_shape(kind):
    c = stickers.CATALOG[kind]
    a = np.asarray(stickers.draw(kind, 0.3, 240))
    assert a.shape[1] == 240 and a[..., 3].max() == 255
    assert abs(a.shape[1] / a.shape[0] - c["aspect"]) < 0.05
    if c.get("ratio"):
        b = np.asarray(stickers.draw(kind, 0.3, 240, None, 2.0))
        assert abs(b.shape[1] / b.shape[0] - 2.0) < 0.05


def test_words_change_the_picture_and_are_cleaned():
    a = np.asarray(stickers.draw("callout", 0, 300))
    b = np.asarray(stickers.draw("callout", 0, 300, "THE BLUE CAR"))
    assert a.shape == b.shape and (a != b).any()
    assert stickers.clean_text("  the\n blue\tcar  ") == "the blue car"
    assert len(stickers.clean_text("x" * 99)) == 28
    assert stickers.clean_text(5) == ""


def test_normalise_keeps_only_what_differs():
    out = stickers.normalise([
        {"kind": "callout", "text": "LOOK HERE", "ratio": 3.2},  # the defaults: nothing extra kept
        {"kind": "callout", "text": " Suspect ", "ratio": 99},
        {"kind": "blur", "strength": 0.9},
        {"kind": "bell", "text": "no words on a bell", "ratio": 3, "strength": 1},
        {"kind": "spotlight", "keyframes": [{"t": i / 10, "x": 0.5} for i in range(300)], "length": 30},
    ])
    assert "text" not in out[0] and "ratio" not in out[0]
    assert out[1]["text"] == "Suspect" and out[1]["ratio"] == 6
    assert out[2]["strength"] == 0.9
    assert not {"text", "ratio", "strength"} & set(out[3])
    assert len(out[4]["keyframes"]) == 120
    assert stickers.aspect(out[1], []) == 6


def test_region_frames():
    spot = np.asarray(stickers.region_frame("spot", 320, 180, 0.5, 0.5, 0.25, 1, 0.6, 1))
    assert spot.shape == (180, 320, 4)
    assert spot[90, 160, 3] == 0 and spot[5, 5, 3] == round(0.6 * 255)  # light inside, darker outside
    blur = np.asarray(stickers.region_frame("blur", 320, 180, 0.5, 0.5, 0.25, 1, 0.6, 1))
    assert blur[90, 160] == 255 and blur[5, 5] == 0
    assert stickers.blur_radius(1920, 0.6) == round(1920 * 0.035 * 0.6)
    assert stickers.blur_radius(100, 0.1) == 2


def test_api_frame_with_words_and_shape(isolated):
    client, root = isolated
    r = client.get("/api/stickers/callout/0.png", params={"text": "THE BLUE CAR", "ratio": 2})
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    im = Image.open(__import__("io").BytesIO(r.content))
    assert abs(im.width / im.height - 2) < 0.05
    plain = client.get("/api/stickers/callout/0.png").content
    assert plain != r.content


def test_render_spotlight_follows_and_blur_and_block(tmp_path):
    folder = ROOT / "qa" / ("v072-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        # a mid-grey picture with fine detail (so a blur shows), a white square left
        im = Image.new("RGB", (1280, 720), (128, 128, 128))
        d = ImageDraw.Draw(im)
        for x in range(0, 1280, 8):
            d.line((x, 0, x, 719), fill=(30, 30, 30) if (x // 8) % 2 else (230, 230, 230), width=4)
        im.save(folder / "lines.png")
        a = {"id": "l", "kind": "image", "path": str(folder / "lines.png"), "name": "lines.png", "width": 1280, "height": 720}
        sc = [{"id": "s1", "title": "", "narration": "", "duration": 3.0, "asset_id": "l", "motion": "none", "show_title": False, "fit": "cover"}]
        sts = [
            # the spotlight moves from the left to the right in the first 2 s
            {"id": "st1", "kind": "spotlight", "start": 0, "length": 3, "x": 0.25, "y": 0.5, "size": 0.2, "strength": 0.8,
             "keyframes": [{"t": 0, "x": 0.25, "y": 0.5, "size": 0.2}, {"t": 2, "x": 0.75, "y": 0.5, "size": 0.2}]},
            {"id": "st2", "kind": "blur", "start": 0, "length": 3, "x": 0.5, "y": 0.2, "size": 0.15, "strength": 1},
            {"id": "st3", "kind": "block", "start": 0, "length": 3, "x": 0.5, "y": 0.85, "size": 0.2},
        ]
        out = render(tmp_path, "mark", [a], sc, stickers=sts)
        f = grab(out, 0.05)
        g = grab(out, 2.4)

        def bright(fr, x, y, r=12):
            return fr[y - r:y + r, x - r:x + r].mean()

        def detail(fr, x, y, r=14):
            return fr[y - r:y + r, x - r:x + r].std()
        # the spotlight: light under it, dark away from it; it has moved by 2.4 s
        assert bright(f, 214, 240) > 100 and bright(f, 640, 240) < 70
        assert bright(g, 640, 240) > 100 and bright(g, 214, 240) < 70
        # the blur: the stripes are smoothed under it (the spotlight darkens it too, so compare detail)
        assert detail(f, 427, 96) < 0.5 * detail(f, 427, 400) + 1
        # the black bar
        assert bright(f, 427, 408, 6) < 25
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_js_twin_agrees():
    py = stickers.normalise([
        {"kind": "callout", "text": "  Suspect\n", "ratio": 2.5, "x": 0.3},
        {"kind": "blur", "strength": 0.25, "ratio": 0.8},
        {"kind": "label", "text": "EVIDENCE"},
    ])
    js = node_eval(
        'import { normaliseStickers, stickerAspect, stickerFrameUrl, cleanText } from "./web/src/stickers.js";'
        'const l = normaliseStickers([{kind:"callout",text:"  Suspect\\n",ratio:2.5,x:0.3},{kind:"blur",strength:0.25,ratio:0.8},{kind:"label",text:"EVIDENCE"}]);'
        'console.log(JSON.stringify({l, a: stickerAspect(l[0]), u: stickerFrameUrl("callout", 0, l[0]), c: cleanText("x".repeat(40)).length}))'
    )
    assert js["l"] == py
    assert js["a"] == 2.5 and js["u"] == "/api/stickers/callout/0.png?text=Suspect&ratio=2.5" and js["c"] == 28


# ------------------------------------------------------------------ v0.4.73 text templates

TEXT = ["tt-message", "tt-subscribe", "tt-lower", "tt-breaking", "tt-quote", "tt-place", "tt-chapter"]


def test_text_templates_in_the_spec():
    st = effects.SPEC["stickers"]
    assert {"id": "text", "label": "Text templates"} in st["tabs"]
    cat = [c for c in st["catalog"] if c["tab"] == "text"]
    assert [c["id"] for c in cat] == TEXT
    for c in cat:
        assert c["once"] and c["animated"] and len(c["lines"]) == len(c["fields"]) <= 4


@pytest.mark.parametrize("kind", TEXT)
def test_text_template_intro_plays_once_and_holds(kind):
    c = stickers.CATALOG[kind]
    n = stickers.cycle_frames(kind)
    first = np.asarray(stickers.draw(kind, 0, 300))
    last = np.asarray(stickers.draw(kind, (n - 1) / 24, 300))
    assert abs(last.shape[1] / last.shape[0] - c["aspect"]) < 0.05
    assert last[..., 3].max() == 255 and (first != last).any()  # it animates in
    assert last[..., 3].sum() > first[..., 3].sum()  # …to more than it started with
    assert stickers.frame_index(kind, 0) == 0 and stickers.frame_index(kind, n + 50) == n - 1  # then holds
    assert stickers.frame_index("bell", stickers.cycle_frames("bell") + 3) == 3  # a loop still loops


def test_text_template_lines():
    out = stickers.normalise([
        {"kind": "tt-lower", "lines": ["JANE DOE", "Lead detective"]},  # the template's own: nothing stored
        {"kind": "tt-lower", "lines": ["  Sam\nRivers ", ""]},
        {"kind": "tt-message", "lines": ["X" * 99]},
        {"kind": "bell", "lines": ["no"]},
    ])
    assert "lines" not in out[0]
    assert out[1]["lines"][0] == "Sam Rivers"
    assert out[1]["lines"][1] == ""
    assert out[2]["lines"] == ["X" * 60, "Laura", "Have a nice one."]
    assert "lines" not in out[3]
    a = np.asarray(stickers.draw("tt-lower", 9, 300))
    b = np.asarray(stickers.draw("tt-lower", 9, 300, lines=["SAM RIVERS", "Witness"]))
    assert (a != b).any()


def test_api_text_template_frame(isolated):
    client, root = isolated
    r = client.get("/api/stickers/tt-lower/14.png", params=[("l", "SAM RIVERS"), ("l", "Witness")])
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert r.content != client.get("/api/stickers/tt-lower/14.png").content


def test_render_a_text_template(tmp_path):
    folder = ROOT / "qa" / ("v073-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        Image.new("RGB", (1280, 720), (60, 90, 140)).save(folder / "blue.png")
        a = {"id": "b", "kind": "image", "path": str(folder / "blue.png"), "name": "blue.png", "width": 1280, "height": 720}
        sc = [{"id": "s1", "title": "", "narration": "", "duration": 2.0, "asset_id": "b", "motion": "none", "show_title": False, "fit": "cover"}]
        sts = [{"id": "t1", "kind": "tt-breaking", "start": 0, "length": 2, "x": 0.5, "y": 0.5, "size": 0.9, "lines": ["BREAKING", "Test headline"]}]
        out = render(tmp_path, "tt", [a], sc, stickers=sts)
        f0, f1 = grab(out, 0.0), grab(out, 1.2)
        # the red tag on the left of the bar, the white headline panel after the intro
        assert f1[240, 80][0] > 180 and f1[240, 80][1] < 80
        assert f1[240, 600].min() > 200
        assert f0[240, 600][2] > 120 and f0[240, 600][0] < 100  # not there yet at the start: the picture
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_js_twin_agrees_on_text_templates():
    src = [{"kind": "tt-message", "lines": ["MESSAGES", "  Ana ", "See you at 9"]}, {"kind": "tt-quote", "lines": ["x" * 70]}, {"kind": "tt-chapter"}]
    js = node_eval(
        'import { normaliseStickers } from "./web/src/stickers.js";'
        f'console.log(JSON.stringify(normaliseStickers({json.dumps(src)})))'
    )
    assert js == stickers.normalise(src)
