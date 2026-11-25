"""v0.4.49: every place the subscribe animation shows (start, length, stop at
the scene end, fade out when cut short), stickers, crop + fill of a media
file, and keyframes for the picture and stickers. Preview (JS) and export
(Python) are checked against each other, and real renders are measured."""
import json
import re
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image, ImageDraw

import cta
import picture
import renderer
import stickers
import storage

ROOT = storage.ROOT


def node_eval(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    out = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def eval_expr(expr, **vars):
    """Evaluate an FFmpeg expression made by picture.expr, in Python."""
    py = re.sub(r"\bif\(", "IF(", expr)
    py = re.sub(r"\blt\(", "LT(", py)
    return eval(py, {"IF": lambda c, a, b: a if c else b, "LT": lambda a, b: a < b, **vars})


def scenes_saying():
    return [
        {"id": "a", "duration": 4, "narration": "Hello.", "title": "Open"},
        {"id": "b", "duration": 6, "narration": "Please subscribe now.", "title": "Ask",
         "captions": [{"start": 0, "end": 2, "text": "Hold on."}, {"start": 2, "end": 6, "text": "Please subscribe now."}]},
        {"id": "c", "duration": 5, "narration": "More facts.", "title": "Facts"},
        {"id": "d", "duration": 8, "narration": "Subscribe for part two.", "title": "Outro",
         "captions": [{"start": 1, "end": 8, "text": "Subscribe for part two."}]},
    ]


# ------------------------------------------------------------------ CTA places

def test_cta_lists_every_subscribe_but_shows_the_first_until_you_tick_more():
    p = {"scenes": scenes_saying(), "cta": {"enabled": True, "asset_id": "ban", "seconds": 5}}
    rows = cta.spots(p)
    assert [(r["key"], r["start"], r["on"]) for r in rows] == [("s:b", 5.5, True), ("s:d", 15.5, False)]
    assert cta.events(p) == [(5.5, 10.5)]  # as before v0.4.49: the first one only
    p["cta"]["spots"] = {"s:d": {"on": True}}
    assert cta.events(p) == [(5.5, 10.5), (15.5, 20.5)]


def test_cta_start_nudge_length_scene_end_and_added_places():
    p = {"scenes": scenes_saying(), "cta": {"enabled": True, "asset_id": "ban", "seconds": 8,
                                            "spots": {"s:b": {"nudge": -0.3, "length": 3}, "s:d": {"on": True, "scene_end": True}},
                                            "extra": [{"id": "x1", "start": 1.0, "length": 2.0}]}}
    rows = {r["key"]: r for r in cta.spots(p)}
    assert (rows["s:b"]["start"], rows["s:b"]["end"], rows["s:b"]["fade_out"]) == (5.2, 8.2, True)
    # stops at the end of its scene (23 s), not 8 s later; the video ends there too
    assert (rows["s:d"]["start"], rows["s:d"]["end"]) == (15.5, 23.0)
    assert (rows["x1"]["start"], rows["x1"]["end"], rows["x1"]["auto"]) == (1.0, 3.0, False)
    assert cta.events(p) == [(1.0, 3.0), (5.2, 8.2), (15.5, 23.0)]
    # an added place that overlaps one already showing is skipped, not drawn twice
    p["cta"]["extra"].append({"id": "x2", "start": 6.0})
    assert [r["shown"] for r in cta.spots(p) if r["key"] == "x2"] == [False]


def test_cta_old_ticked_scenes_still_show():
    sc = scenes_saying()
    sc[2]["cta"] = True
    p = {"scenes": sc, "cta": {"enabled": True, "asset_id": "ban", "mode": "scenes", "seconds": 4}}
    assert cta.events(p) == [(10.0, 14.0)]


def test_cta_normalise_keeps_places_safe():
    c = cta.normalise({"spots": {"s:b": {"on": False, "nudge": 99, "length": 0.1}, "bad key": {}, "s:c": "x"},
                       "extra": [{"start": "nope"}, {"id": "../x", "start": -4, "length": 40}], "x": 3})
    assert c["spots"] == {"s:b": {"on": False, "nudge": 30.0, "length": 0.5, "scene_end": False}}
    assert c["extra"] == [{"id": "x", "start": 0.0, "on": True, "nudge": 0.0, "length": 15.0, "scene_end": False}]
    assert c["x"] == 0.9


def test_cta_fade_continues_across_a_scene_cut():
    # fades from 9.5 to 10.0; a scene cut at 9.8: the next scene starts at alpha 0.4
    assert cta.alpha_at(9.8, 7.0, 10.0, 5.0) == pytest.approx(0.4)
    f = cta.fade_filter(9.8, 10.0, 0.5, 0.0)
    assert "colorchannelmixer=aa=0.4000" in f and "d=0.200" in f
    assert cta.fade_filter(7.0, 10.0, 0.5, 2.0) == ",fade=t=out:st=4.500:d=0.500:alpha=1"
    assert cta.alpha_at(9.0, 7.0, 12.0, 5.0) == 1.0  # not cut short: no fade


def test_preview_lists_the_same_places_as_the_export():
    sc = scenes_saying()
    spec = {"enabled": True, "asset_id": "ban", "seconds": 6, "spots": {"s:d": {"on": True, "nudge": 0.4, "length": 2.5}, "s:b": {"scene_end": True}},
            "extra": [{"id": "x1", "start": 12.25, "length": 1.5}]}
    p = {"scenes": sc, "cta": spec}
    offsets = [0, 4, 10, 15]
    js = f"""
    const m = await import("./web/src/cta.js");
    const caps = (s) => s.captions || [];
    const rows = m.ctaSpots({json.dumps(p)}, {json.dumps(offsets)}, caps);
    console.log(JSON.stringify(rows.map((r) => [r.key, r.start, r.end, r.shown, r.fade_out])));
    """
    got = node_eval(js)
    want = [[r["key"], r["start"], r["end"], r["shown"], r["fade_out"]] for r in cta.spots(p)]
    assert got == want


# ------------------------------------------------------------------ picture

def test_crop_normalise_and_automatic_crop(tmp_path):
    assert picture.normalise_crop([0.5, 0.1, 0.2, 0.9]) == [0.2, 0.1, 0.5, 0.9]
    assert picture.normalise_crop([0, 0, 1, 1]) is None
    assert picture.normalise_crop([0.1, 0.1, 0.12, 0.9]) is None  # too thin
    im = Image.new("RGB", (800, 450), "black")  # black bars left and right
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 799, 39), fill=(200, 200, 205))  # a plain grey band at the top
    rng = np.random.default_rng(1)
    photo = Image.fromarray(rng.integers(40, 220, (410, 500, 3), dtype=np.uint8))
    im.paste(photo, (150, 40))
    im.save(tmp_path / "p.png")
    box = picture.detect_crop(tmp_path / "p.png")
    assert box == pytest.approx([150 / 800, 40 / 450, 650 / 800, 1.0], abs=0.01)


def test_keyframes_interpolate_and_ffmpeg_expression_agree():
    keys = picture.normalise_keyframes([{"t": 2, "zoom": 2, "x": 0.1, "y": 0.5}, {"t": 0, "zoom": 1}, {"t": 4, "zoom": 1.5, "x": 0.7, "ease": "linear"}, {"t": 5, "zoom": 1.2, "x": 0.4}])
    assert keys[1]["x"] == 0.25  # zoom 2 cannot centre at 0.1: clamped so the view stays inside
    for t in (0, 0.5, 1.3, 2, 2.7, 3.99, 4.5, 6):
        v = picture.camera_at(keys, t)
        for f in ("zoom", "x"):
            assert eval_expr(picture.expr(keys, f, "T"), T=t) == pytest.approx(v[f], abs=1e-4), (t, f)
    js = f"""
    const m = await import("./web/src/picture.js");
    const keys = m.normaliseKeyframes({json.dumps(keys)});
    console.log(JSON.stringify([0, 0.5, 1.3, 2, 2.7, 3.99, 4.5, 6].map((t) => m.cameraAt(keys, t))));
    """
    for t, g in zip((0, 0.5, 1.3, 2, 2.7, 3.99, 4.5, 6), node_eval(js)):
        w = picture.camera_at(keys, t)
        assert all(abs(g[k] - w[k]) < 1e-6 for k in ("zoom", "x", "y")), t


def test_fit_choice():
    assert picture.fit_of({}, {}) == "cover"
    assert picture.fit_of({}, {"fit": "blur"}) == "blur"
    assert picture.fit_of({"aspect": "9:16"}, {}) == "legacy-blur"
    assert picture.fit_of({"aspect": "9:16"}, {"fit": "cover"}) == "cover"
    cropped = {"crop": [0.2, 0, 0.6, 1]}  # a cropped file: over a blur of itself, unless the scene says cover
    assert picture.fit_of({}, {}, cropped) == "blur"
    assert picture.fit_of({}, {"fit": "cover"}, cropped) == "cover"
    assert picture.fit_of({}, {}, {"crop": [0, 0, 1, 1]}) == "cover"
    js = """const {fitOf} = await import("./web/src/picture.js"); const c = {crop: [0.2, 0, 0.6, 1]};
    console.log(JSON.stringify([fitOf({}, {}, c), fitOf({}, {fit: "cover"}, c), fitOf({}, {}, {})]));"""
    assert node_eval(js) == ["blur", "cover", "cover"]


def grab(out, t, w=854, h=480):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).astype(int)


def render(tmp_path, name, assets, scenes, **extra):
    p = {"id": name, "title": name, "look": "natural", "captions": False, "music_volume": 0, "assets": assets, "scenes": scenes, **extra}
    out = tmp_path / f"{name}.mp4"
    renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    return out


@pytest.fixture
def media(tmp_path):
    folder = ROOT / "qa" / ("v049-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


def test_render_crop_then_photo_over_a_blur_of_itself(tmp_path, media):
    # a red photo between black bars and a white "news panel" on the right
    im = Image.new("RGB", (1600, 900), "black")
    d = ImageDraw.Draw(im)
    d.rectangle((400, 0, 1000, 899), fill=(220, 30, 30))
    d.rectangle((1000, 0, 1599, 899), fill=(250, 250, 250))
    im.save(media / "news.png")
    a = {"id": "n", "kind": "image", "path": str(media / "news.png"), "name": "news.png", "width": 1600, "height": 900, "crop": [0.25, 0, 0.625, 1]}
    sc = [{"id": "s1", "title": "", "narration": "", "duration": 1.0, "asset_id": "n", "motion": "none", "show_title": False, "fit": "blur"},
          {"id": "s2", "title": "", "narration": "", "duration": 1.0, "asset_id": "n", "motion": "none", "show_title": False, "fit": "cover"},
          {"id": "s3", "title": "", "narration": "", "duration": 1.0, "asset_id": "n", "motion": "none", "show_title": False}]
    out = render(tmp_path, "crop", [a], sc)
    f = grab(out, 0.5)
    assert f[240, 427][0] > 180 and f[240, 427][2] < 80  # the photo in the middle
    edge = f[240, 15]  # the sides: a darker blur of the red photo, no black bars, no white panel
    assert edge[0] > 60 and edge[0] < 200 and edge[1] < 60, edge
    assert f[240, 840].max() < 200  # the white panel is cut away
    g = grab(out, 1.5)
    assert g[240, 10][0] > 180 and g[240, 844][0] > 180 and g[240, 844][1] < 80  # cover: red edge to edge
    h = grab(out, 2.5)  # no choice made: a cropped file shows over a blur of itself
    assert abs(h[240, 15].astype(int) - f[240, 15].astype(int)).max() < 12 and h[240, 427][0] > 180


def test_render_picture_keyframes_on_a_photo_and_a_clip(tmp_path, media):
    im = Image.new("RGB", (1280, 720), (30, 200, 60))
    ImageDraw.Draw(im).rectangle((640, 0, 1279, 719), fill=(40, 60, 220))
    im.save(media / "half.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(media / "half.png"), "-t", "3", "-r", "24", "-pix_fmt", "yuv420p", str(media / "half.mp4")], check=True)
    keys = [{"t": 0, "zoom": 1, "x": 0.5, "y": 0.5}, {"t": 1.0, "zoom": 2, "x": 0.25, "y": 0.5}]
    assets = [{"id": "i", "kind": "image", "path": str(media / "half.png"), "name": "half.png", "width": 1280, "height": 720},
              {"id": "v", "kind": "video", "path": str(media / "half.mp4"), "name": "half.mp4", "width": 1280, "height": 720, "duration": 3.0, "video_duration": 3.0}]
    sc = [{"id": "s1", "title": "", "narration": "", "duration": 2.0, "asset_id": "i", "motion": "slow-zoom", "show_title": False, "keyframes": keys},
          {"id": "s2", "title": "", "narration": "", "duration": 2.0, "asset_id": "v", "motion": "none", "show_title": False, "keyframes": keys}]
    out = render(tmp_path, "kf", assets, sc)
    for t in (0.05, 2.05):  # the start: the whole picture, green left and blue right
        f = grab(out, t)
        assert f[240, 800][2] > 150 and f[240, 50][1] > 150
    for t in (1.6, 3.6):  # after the push-in on the green half: green everywhere
        f = grab(out, t)
        assert f[240, 800][1] > 150 and f[240, 800][2] < 120, (t, f[240, 800])


# ------------------------------------------------------------------ stickers

def test_every_builtin_sticker_draws_and_animates():
    for kind, c in stickers.CATALOG.items():
        a = np.asarray(stickers.draw(kind, 0.3, 200))
        assert a.shape[1] == 200 and a[..., 3].max() == 255, kind
        assert abs(a.shape[1] / a.shape[0] - c["aspect"]) < 0.05, kind
        if c["animated"]:
            frames = {stickers.draw(kind, i / 24, 120).tobytes() for i in range(0, round(c["cycle"] * 24), 5)}
            assert len(frames) > 1, kind


def test_sticker_normalise_and_sample():
    s = stickers.normalise([{"kind": "like", "start": 2, "length": 3, "x": 9, "keyframes": [{"t": 0, "x": 0.2}, {"t": 2, "x": 0.8, "ease": "linear"}, {"t": 9}]},
                            {"kind": "nope"}, {"kind": "image", "asset_id": "gone"}], image_assets=set())
    assert len(s) == 1 and s[0]["x"] == 1.25 and [k["t"] for k in s[0]["keyframes"]] == [0.0, 2.0, 3.0]  # past the end: held at the end
    assert stickers.sample(s[0], 0)["opacity"] == 1  # shows at once, where you added it
    assert stickers.sample(s[0], 2.9)["opacity"] == pytest.approx(0.5)  # fades out at its end
    mid = stickers.sample(s[0], 1.0)
    assert mid["x"] == pytest.approx(0.5) and mid["opacity"] == 1
    js = f"""
    const m = await import("./web/src/stickers.js");
    const s = m.normaliseStickers({json.dumps(s)});
    console.log(JSON.stringify([0, 0.1, 1, 1.7, 2.9].map((t) => m.stickerAt(s[0], t))));
    """
    for t, g in zip((0, 0.1, 1, 1.7, 2.9), node_eval(js)):
        w = stickers.sample(s[0], t)
        assert all(abs(g[k] - w[k]) < 1e-6 for k in ("x", "y", "size", "opacity")), t


def test_render_a_sticker_that_moves(tmp_path, media):
    Image.new("RGB", (640, 360), (200, 40, 40)).save(media / "red.png")
    a = {"id": "r", "kind": "image", "path": str(media / "red.png"), "name": "red.png", "width": 640, "height": 360}
    sc = [{"id": "s1", "title": "", "narration": "", "duration": 1.5, "asset_id": "r", "motion": "none", "show_title": False},
          {"id": "s2", "title": "", "narration": "", "duration": 2.0, "asset_id": "r", "motion": "none", "show_title": False}]
    st = [{"id": "st1", "kind": "like", "start": 0.5, "length": 2.5, "size": 0.2, "y": 0.5,
           "keyframes": [{"t": 0, "x": 0.25, "y": 0.5}, {"t": 1.5, "x": 0.75, "y": 0.5, "ease": "linear"}]}]
    out = render(tmp_path, "st", [a], sc, stickers=st)
    s = stickers.normalise(st)[0]

    def centre(t):
        row = grab(out, t)[240]
        hit = np.where((row[:, 2] > 150) & (row[:, 0] < 150))[0]  # the blue circle
        return (hit.min() + hit.max()) / 2 / 854 if len(hit) else None

    assert centre(0.25) is None  # before it starts
    for t in (0.55, 0.75, 1.0, 1.25, 2.0, 2.4):  # follows its keyframes, across the scene cut at 1.5 s
        assert centre(t) == pytest.approx(stickers.sample(s, t - 0.5)["x"], abs=0.01), t
    assert centre(3.2) is None  # gone


# ------------------------------------------------------------------ the CTA in a render

def banner(path):
    im = Image.new("RGB", (1280, 720), "#202020")
    ImageDraw.Draw(im).rounded_rectangle((540, 400, 740, 450), radius=8, fill=(160, 22, 30))
    im.save(path)
    return path


def test_render_cta_cut_short_fades_out_and_leaves(tmp_path, media):
    Image.new("RGB", (640, 360), "#3060a0").save(media / "bg.png")
    b = banner(media / "banner.png")
    assets = [{"id": "bg", "kind": "image", "path": str(media / "bg.png"), "name": "bg.png"},
              {"id": "ban", "kind": "image", "path": str(b), "name": "banner.png"}]
    sc = [{"id": "a", "title": "", "narration": "Please subscribe now.", "chapter": "CTA", "duration": 3.0, "asset_id": "bg", "motion": "none", "show_title": False,
           "captions": [{"start": 1.0, "end": 3.0, "text": "Please subscribe now."}]},
          {"id": "b", "title": "", "narration": "", "duration": 4.0, "asset_id": "bg", "motion": "none", "show_title": False}]
    c = {"enabled": True, "asset_id": "ban", "button": cta.detect_button(b), "seconds": 5, "spots": {"s:a": {"length": 2.0}}}
    out = render(tmp_path, "ctashort", assets, sc, cta=c)
    btn = (round(640 / 1280 * 854), round(425 / 720 * 480))
    assert grab(out, 1.4)[btn[1], btn[0]][0] > 120  # showing (0.5 s to 2.5 s)
    mid = grab(out, 2.3)[btn[1], btn[0]]  # fading out
    end = grab(out, 2.7)[btn[1], btn[0]]  # gone: before v0.4.49 it lingered until 5.5 s
    assert end[2] > 120 and end[0] < 90, end
    assert mid[2] < end[2]


# ------------------------------------------------------------------ the API

def test_api_stickers_crop_and_frames(isolated):
    client, root = isolated
    p = client.post("/api/projects", json={"title": "Overlays", "topic": "t"}).json()
    im = Image.new("RGB", (400, 300), "black")
    ImageDraw.Draw(im).rectangle((100, 0, 299, 299), fill=(200, 120, 40))
    path = root / "pic.png"
    im.save(path)
    with path.open("rb") as fh:
        p = client.post(f"/api/projects/{p['id']}/upload", files={"files": ("pic.png", fh, "image/png")}).json()
    aid = p["assets"][-1]["id"]
    r = client.post(f"/api/projects/{p['id']}/assets/{aid}/autocrop").json()
    assert r["found"] and r["crop"] == pytest.approx([0.25, 0, 0.75, 1], abs=0.01)
    p = client.patch(f"/api/projects/{p['id']}/assets/{aid}", json={"crop": r["crop"], "sticker": True}).json()
    a = next(x for x in p["assets"] if x["id"] == aid)
    assert a["crop"] == pytest.approx([0.25, 0, 0.75, 1], abs=0.01) and a["sticker"] is True
    p = client.patch(f"/api/projects/{p['id']}/assets/{aid}", json={"crop": [0, 0, 1, 1]}).json()
    assert "crop" not in next(x for x in p["assets"] if x["id"] == aid)
    p = client.patch(f"/api/projects/{p['id']}", json={"stickers": [{"kind": "bell", "start": 1}, {"kind": "image", "asset_id": aid}, {"kind": "image", "asset_id": "nope"}]}).json()
    assert [s["kind"] for s in p["stickers"]] == ["bell", "image"]
    sc = {"id": "k1", "title": "K", "narration": "Words.", "duration": 4, "fit": "blur", "keyframes": [{"t": 0, "zoom": 1.5}, {"t": "x"}]}
    p = client.patch(f"/api/projects/{p['id']}", json={"scenes": [sc]}).json()
    assert p["scenes"][0]["fit"] == "blur" and p["scenes"][0]["keyframes"][0]["zoom"] == 1.5 and len(p["scenes"][0]["keyframes"]) == 1
    r = client.get("/api/stickers/bell/3.png")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert client.get("/api/stickers/nothing/0.png").status_code == 404


def test_render_own_mov_cut_short_fades_across_the_scene_cut_and_moves_left(tmp_path, media):
    """A 3 s transparent .MOV cut to 2.2 s: it fades out from 1.7 s to 2.2 s,
    across the scene cut at 2.0 s, with no jump, and sits where you put it."""
    from test_cta_file import animation
    Image.new("RGB", (640, 360), (40, 60, 200)).save(media / "bg.png")
    anim = animation(media, "mov")
    info = renderer.probe(anim)
    assets = [{"id": "bg", "kind": "image", "path": str(media / "bg.png"), "name": "bg.png"},
              dict(info, id="sub", kind="video", path=str(anim), name=anim.name)]
    sc = [{"id": "a", "title": "", "narration": "Please subscribe now.", "chapter": "CTA", "duration": 2.0, "asset_id": "bg", "motion": "none", "show_title": False,
           "captions": [{"start": 0.5, "end": 2.0, "text": "Please subscribe now."}]},
          {"id": "b", "title": "", "narration": "", "duration": 2.0, "asset_id": "bg", "motion": "none", "show_title": False}]
    c = {"enabled": True, "source": "file", "file_id": "sub", "size": 0.5, "x": 0.3, "y": 0.5, "spots": {"s:a": {"length": 2.2}}}
    p = {"scenes": sc, "assets": assets, "cta": c}
    assert cta.events(p) == [(0.0, 2.2)]
    out = render(tmp_path, "movshort", assets, sc, cta=c)
    cx = round(0.3 * 854)  # the red box: the middle of the animation, now left of centre

    def redness(t):
        r, g, b = grab(out, t)[240, cx]
        return (r - b + 160) / 350  # 1: solid red (220, 20, 30); 0: the blue picture (40, 60, 200)

    assert redness(1.2) > 0.85
    assert grab(out, 1.2)[240, 427][2] > 150  # the middle of the frame is the picture
    seq = [redness(t) for t in (1.75, 1.9, 2.05, 2.15)]
    assert seq == pytest.approx([0.9, 0.6, 0.3, 0.1], abs=0.08), seq  # keeps fading through the cut at 2.0
    assert redness(2.6) < 0.05  # gone (it used to play on to 3.0 s)


def test_render_base_fill_scene_cropped_over_blur_keeps_its_motion(tmp_path, media):
    """Base-fill scenes are ordinary scenes using a media file: the file's crop
    applies, over a blur of itself, and the slow push-in still plays."""
    im = Image.new("RGB", (1600, 900), "black")
    d = ImageDraw.Draw(im)
    d.rectangle((400, 0, 1000, 899), fill=(220, 30, 30))
    d.rectangle((1000, 0, 1599, 899), fill=(250, 250, 250))
    im.save(media / "base.png")
    a = {"id": "b", "kind": "image", "path": str(media / "base.png"), "name": "base.png", "width": 1600, "height": 900, "crop": [0.25, 0, 0.625, 1]}
    sc = [{"id": "s1", "title": "Base image · Archive", "narration": "", "duration": 3.0, "asset_id": "b", "motion": "slow-zoom", "show_title": False}]
    out = render(tmp_path, "basefill", [a], sc)

    def photo_width(t):
        row = grab(out, t)[240].astype(int)
        red = (row[:, 0] > 170) & (row[:, 1] < 70)
        return int(red.sum()), row

    w0, r0 = photo_width(0.05)
    w1, r1 = photo_width(2.9)
    assert 200 < w0 < 320, w0  # the cropped photo (a 2:3 strip) in the middle, not stretched
    assert w1 > w0 * 1.05, (w0, w1)  # pushes in
    assert r0[10][0] < 200 and r0[10][0] > 50 and r0[10].max() < 230  # sides: blur of the photo, no black bar, no white panel
