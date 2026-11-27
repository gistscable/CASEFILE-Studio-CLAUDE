"""v0.4.63 The cinematic graphics' look: a project look (colour set per category, automatic variation, your own
colours, what the graphics are drawn over) with per-graphic changes; tested colour sets; the readability check;
backgrounds each design can take; the hand-over with a see-through graphic; preview = export; the default
look unchanged."""
import subprocess

import numpy as np
import pytest
from PIL import Image

import cinematic
import motion
from cinegfx import core, look as L
from test_cinematic import _project, javits_project

TC = core.load_collections()["truecrime"]


@pytest.fixture(scope="module")
def items():
    p = javits_project()
    return {x["category"]: x for x in cinematic.suggest(p, [])}


def styled(it, look=None, **item_look):
    x = dict(it, look=item_look) if item_look else dict(it)
    m = motion.normalise({"enabled": True, "items": [x], "look": look or {}})
    return m["items"][0]


def test_every_tested_set_is_readable():
    for cat in TC.categories.values():
        pals = L.palettes(cat)
        assert len([p for p in pals if L.is_light(p[2]) == L.is_light(pals[0][2])]) >= 3, cat.key  # 3 tested sets
        assert pals[0][2] == {r: getattr(cat.theme, r).upper() for r in L.ROLES}  # the first is the approved design
        for key, label, c in pals:
            assert L.contrast(c["ink"], c["bg"]) >= L.TEXT_MIN, (cat.key, key)
            assert L.contrast(c["accent"], c["bg"]) >= L.ACCENT_MIN and L.contrast(c["accent2"], c["bg"]) >= L.ACCENT_MIN, (cat.key, key)
            for on in (cat.looks or {}).get("on_accent") or ():
                assert L.contrast(c["accent"], on) >= L.ACCENT_MIN, (cat.key, key)


def test_default_look_is_the_approved_design_pixel_for_pixel(items):
    for cat, it in items.items():
        s = styled(it)
        assert s["style"]["palette"] == L.palettes(TC.categories[cat])[0][0] and s["style"]["background"] == "own"
        assert not s["style"]["notes"] and "look" not in s
        g0, g1 = cinematic.build(it), cinematic.build(s)
        assert g1.th is TC.categories[cat].theme  # the same Theme object: same caches, same pixels
        n = cinematic.frames_of(it)
        for k in (n // 2, n - 3):
            assert np.array_equal(np.asarray(cinematic.frame(g0, it, k, 320, 180)), np.asarray(cinematic.frame(g1, s, k, 320, 180)))


def test_project_look_with_changes_per_graphic(items):
    tl, leg = items["timeline"], items["legal"]
    look = {"palettes": {"timeline": "B", "legal": "C"}}
    assert styled(tl, look)["style"]["palette"] == "B" and styled(leg, look)["style"]["palette"] == "C"
    # one graphic changed by hand wins over the project
    s = styled(tl, look, palette="C")
    assert s["style"]["palette"] == "C" and s["style"]["from"]["palette"] == "graphic" and s["look"] == {"palette": "C"}
    # its own colours over the project's; "own" puts the design's colour back over a project colour
    s = styled(tl, {"accent": "#2BB3A3"})
    assert s["style"]["colors"]["accent"] == "#2BB3A3" and s["style"]["from"]["accent"] == "project"
    s = styled(tl, {"accent": "#2BB3A3"}, accent="own")
    assert s["style"]["colors"]["accent"] == TC.categories["timeline"].theme.accent.upper()
    # different colours draw a different picture
    n = cinematic.frames_of(tl) - 5
    a = np.asarray(cinematic.frame(cinematic.build(styled(tl)), tl, n, 320, 180))
    b = np.asarray(cinematic.frame(cinematic.build(styled(tl, look)), tl, n, 320, 180))
    assert not np.array_equal(a, b)


def test_automatic_variation_is_per_project_and_stable(items):
    picks = {}
    for seed in ("p1", "p2", "p3", "p4", "p5", "p6"):
        picks[seed] = tuple(styled(items[c], {"vary": True, "seed": seed})["style"]["palette"] for c in sorted(items))
        assert picks[seed] == tuple(styled(items[c], {"vary": True, "seed": seed})["style"]["palette"] for c in sorted(items))
    assert len(set(picks.values())) > 1  # projects differ
    for c in items:  # only the tested sets of the design's own surface (the paper docket stays paper)
        cat = TC.categories[c]
        light = L.is_light(L.palettes(cat)[0][2])
        for seed in picks:
            key = styled(items[c], {"vary": True, "seed": seed})["style"]["palette"]
            assert L.is_light(dict((k, col) for k, _, col in L.palettes(cat))[key]) == light
    # a set chosen for the project, or for a graphic, wins over the variation
    assert styled(items["timeline"], {"vary": True, "seed": "p1", "palettes": {"timeline": "C"}})["style"]["palette"] == "C"
    assert styled(items["timeline"], {"vary": True, "seed": "p1"}, palette="A")["style"]["palette"] == "A"


def test_own_colours_are_checked_for_readability(items):
    s = styled(items["digital"], accent="#1F3A68")  # navy on the black terminal: too faint
    st = s["style"]
    assert st["picked"]["accent"]["picked"] == "#1F3A68" and st["picked"]["accent"]["ratio"] < 3
    used = st["colors"]["accent"]
    assert used != "#1F3A68" and L.contrast(used, st["colors"]["bg"]) >= 3 and "too faint" in st["notes"][0]
    # the turning point writes white on its accent: gold is readable on black but not under white text
    st = styled(items["turning"], accent="#E8B04B")["style"]
    assert L.contrast(st["colors"]["accent"], "#FFFFFF") >= 3 and L.contrast(st["colors"]["accent"], "#000000") >= 3
    # a readable colour is used exactly as picked
    st = styled(items["timeline"], text="#FFFFFF", accent="#E8B04B")["style"]
    assert st["colors"]["ink"] == "#FFFFFF" and st["colors"]["accent"] == "#E8B04B" and not st["notes"]
    # bad values are not kept
    assert "look" not in styled(items["timeline"], accent="red", palette="no such set!")


def test_backgrounds_each_design_can_take(items):
    # conflicting accounts: its columns fill the screen, so it keeps its own background (and says why)
    st = styled(items["contradiction"], {"background": "footage"})["style"]
    assert st["background"] == "own" and "columns" in st["notes"][0]
    # the paper docket over a picture: its dark version (the text must be light)
    st = styled(items["legal"], {"background": "footage", "palettes": {"legal": "B"}})["style"]
    assert st["background"] == "footage" and st["palette"] == "D" and not L.is_light(st["colors"]) and st["notes"]
    # a light version over a picture: the dark design instead
    st = styled(items["findings"], {"background": "still"}, palette="L")["style"]
    assert st["palette"] == "A" and st["still_at"] == items["findings"]["start"]


def test_footage_is_see_through_and_a_photo_is_drawn_behind(items, tmp_path):
    it = styled(items["timeline"], {"background": "footage", "dim": 0.5})
    g = cinematic.build(it)
    mid = cinematic.frames_of(it) // 2
    a = np.asarray(cinematic.frame(g, it, mid, 320, 180))[..., 3]
    # the darkening shows the video through (most of the frame), the type is solid
    assert np.bincount(a.ravel()).argmax() == round(255 * 0.5) and a.max() == 255
    full = np.asarray(cinematic.frame(g, it, mid, 1920, 1080))[..., 3]  # the composition's own size: no resampling
    assert full.min() == round(255 * 0.5)
    # a photo behind it (found): opaque, and not the design's own background
    pic = tmp_path / "pic.jpg"
    Image.new("RGB", (800, 500), (200, 60, 40)).save(pic)
    ph = styled(items["timeline"], {"background": "photo", "photo_id": "x"})
    files = {cinematic.BACKDROP: {"file": str(pic), "credit": "", "month": ""}}
    assert cinematic.backdrop_used(ph, files) == "photo" and cinematic.backdrop_used(ph, {}) == "own"
    f_photo = np.asarray(cinematic.frame(cinematic.build(ph, files), ph, mid, 320, 180))
    f_own = np.asarray(cinematic.frame(cinematic.build(items["timeline"]), items["timeline"], mid, 320, 180))
    assert f_photo[..., 3].min() == 255 and f_photo[2, 2, 0] > f_photo[2, 2, 2] and not np.array_equal(f_photo, f_own)
    # the photo is part of the cache key; its file missing: the design's own background (nothing made up)
    assert cinematic.item_hash(ph, 320, 180, files) != cinematic.item_hash(ph, 320, 180, {})
    assert np.array_equal(np.asarray(cinematic.frame(cinematic.build(ph, {}), ph, mid, 320, 180)), f_own)


def test_see_through_graphic_hands_over_with_a_crossfade(items):
    order = sorted([items[c] for c in items], key=lambda x: x["start"])
    pairs = [(a, b) for a, b in zip(order, order[1:]) if b["start"] < a["end"]]
    a, b = pairs[0]
    base = [dict(x, status="approved") for x in (a, b)]
    m = motion.normalise({"enabled": True, "items": base})
    A = next(x for x in m["items"] if x["id"] == a["id"])
    assert A.get("cut") and not A.get("cut_fade")  # the next one is opaque: it covers
    last = cinematic.frames_of(A) - 1
    assert np.asarray(cinematic.frame(cinematic.build(A), A, last, 160, 90))[..., 3].min() == 255
    # the next one is over the footage (see-through): the earlier one fades out under it instead of vanishing
    see = [base[0], dict(base[1], look={"background": "footage"})]
    if TC.categories[b["category"]].looks.get("backdrops") == ("own",):
        pytest.skip("the later graphic of this pair cannot take the footage")
    m = motion.normalise({"enabled": True, "items": see})
    A = next(x for x in m["items"] if x["id"] == a["id"])
    assert A["cut"] and A["cut_fade"] is True and A["end"] == pytest.approx(A["start"] + A["cut"] / 24, abs=1e-3)
    g = cinematic.build(A)
    assert np.asarray(cinematic.frame(g, A, last, 160, 90))[..., 3].max() < 160
    assert np.asarray(cinematic.frame(g, A, A["cut"] - 12, 160, 90))[..., 3].min() == 255  # before the next one: whole


def test_see_through_export_equals_preview(items, tmp_path):
    it = styled(items["digital"], {"background": "footage", "palettes": {"digital": "B"}})
    W, H = 320, 180
    out = tmp_path / "g.mov"
    n = cinematic.encode(it, {}, W, H, out, workers=1)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True, check=True).stdout
    vid = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 4)
    g = cinematic.build(it, {})
    for k in (0, n // 2, n - 2):
        assert np.array_equal(vid[k], np.asarray(cinematic.frame(g, it, k, W, H))), k


def test_api_project_look_and_graphic_look(isolated):
    client, root = isolated
    cat = client.get("/api/motion/catalog").json()
    tc = next(c for c in cat["collections"] if c["key"] == "truecrime")
    by = {c["key"]: c for c in tc["categories"]}
    assert [p["key"] for p in by["timeline"]["looks"]["palettes"]][:3] == ["A", "B", "C"]
    assert by["contradiction"]["looks"]["backdrops"] == ["own"] and by["contradiction"]["looks"]["backdrop_note"]
    assert cat["dim"]["default"] == L.DIM[2]

    pid, p = _project(client, javits_project())
    r = client.post(f"/api/projects/{pid}/motion/suggest", json={"engine": "cinematic"}).json()
    items = r["project"]["motion"]["items"]
    look = {"palettes": {"timeline": "B"}, "background": "footage", "accent": "#zzz", "vary": True, "seed": pid}
    out = client.patch(f"/api/projects/{pid}", json={"motion": {"enabled": True, "items": items, "look": look}}).json()
    assert out["motion"]["look"] == {"vary": True, "seed": pid, "palettes": {"timeline": "B"}, "background": "footage"}
    tl = next(x for x in out["motion"]["items"] if x["category"] == "timeline")
    assert tl["style"]["palette"] == "B" and tl["style"]["background"] == "footage"
    # suggesting again keeps the project look
    r = client.post(f"/api/projects/{pid}/motion/suggest", json={"engine": "cinematic"}).json()
    assert r["project"]["motion"]["look"]["palettes"] == {"timeline": "B"}
    # the preview uses the look the editor has now (before it is saved)
    plan = client.post(f"/api/projects/{pid}/motion/plan", json={"item": tl, "look": {"palettes": {"timeline": "C"}}}).json()
    assert plan["style"]["palette"] == "C" and plan["backdrop"] == "own"
    plan2 = client.post(f"/api/projects/{pid}/motion/plan", json={"item": tl}).json()
    assert plan2["style"]["palette"] == "B" and plan2["backdrop"] == "footage" and plan2["hash"] != plan["hash"]
    # a still from the footage where there is none (no video in this project): its own background, said so
    plan3 = client.post(f"/api/projects/{pid}/motion/plan", json={"item": dict(tl, look={"background": "still"})}).json()
    assert plan3["style"]["background"] == "still" and plan3["backdrop"] == "own"
    # a project photo behind one graphic
    Image.new("RGB", (900, 600), (90, 110, 130)).save(root / "bg.jpg")
    with open(root / "bg.jpg", "rb") as f:
        asset = next(a for a in client.post(f"/api/projects/{pid}/upload", files=[("files", ("bg.jpg", f, "image/jpeg"))]).json()["assets"]
                     if a["kind"] == "image")
    plan4 = client.post(f"/api/projects/{pid}/motion/plan", json={"item": dict(tl, look={"background": "photo", "photo_id": asset["id"]})}).json()
    assert plan4["backdrop"] == "photo"
    r = client.get(f"/api/motion/{plan4['hash']}/{plan4['frames'][len(plan4['frames']) // 2]}.webp")
    assert r.status_code == 200
    # a photo that is not the project's is not kept
    items = client.get(f"/api/projects/{pid}").json()["motion"]["items"]
    bad = [dict(x, look={"background": "photo", "photo_id": "nope"}) for x in items]
    out = client.patch(f"/api/projects/{pid}", json={"motion": {"enabled": True, "items": bad}}).json()
    assert all(x["look"]["photo_id"] == "" for x in out["motion"]["items"])


def test_export_over_the_footage_and_over_a_photo(tmp_path, monkeypatch):
    """Javits' investigators chapter exported at 480p over plain green footage, the project look over the footage
    (darkened 50%), the second graphic over a project photo instead: the export's picture is the preview's frame
    over the footage (to H.264 accuracy), the footage shows through the first one, and it hands over."""
    import shutil

    import renderer
    from storage import ROOT
    from test_cinematic import _grab, javits_scenes
    folder = ROOT / "qa" / ("v063-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(renderer, "DATA", tmp_path / "data")
    try:
        Image.new("RGB", (640, 360), (40, 140, 60)).save(folder / "green.png")
        Image.new("RGB", (640, 360), (170, 40, 40)).save(folder / "red.png")
        a = {"id": "g", "kind": "image", "path": str(folder / "green.png"), "name": "green.png", "width": 640, "height": 360}
        b = {"id": "r", "kind": "image", "path": str(folder / "red.png"), "name": "red.png", "width": 640, "height": 360}
        sc = [dict(s, asset_id="g", motion="none", show_title=False) for s in javits_scenes() if s["chapter"] == "WHAT INVESTIGATORS SAID"]
        p = {"id": "cine", "title": "The Last Timeline — Javits Frimpong", "topic": "Javits Frimpong", "created_at": "2026-11-13", "look": "natural",
             "captions": False, "music_volume": 0, "assets": [a, b], "scenes": sc}
        items = cinematic.suggest(p, [])
        assert [x["category"] for x in items] == ["digital", "findings"]
        p["motion"] = motion.normalise({"enabled": True, "items": [dict(items[0], status="approved"),
                                                                    dict(items[1], status="approved", look={"background": "photo", "photo_id": "r"})],
                                        "look": {"background": "footage", "dim": 0.5, "palettes": {"digital": "B"}}}, {"g", "r"})
        A, B = p["motion"]["items"]
        assert A["style"]["background"] == "footage" and A["style"]["palette"] == "B" and B["style"]["background"] == "photo"
        assert A.get("cut") and not A.get("cut_fade")  # the photo one is opaque: it covers
        out = tmp_path / "cine.mp4"
        renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
        W, H = 854, 480
        green = Image.new("RGBA", (W, H), (40, 140, 60, 255))
        for it, local, files in ((A, 6.0, {}), (B, 6.0, motion.background_path(p, B, renderer.DATA, renderer.asset_path))):
            k = round(local * 24)
            fr = cinematic.frame(cinematic.build(it, files), it, k, W, H)
            want = np.asarray(Image.alpha_composite(green, fr).convert("RGB")).astype(int)
            got = _grab(out, it["start"] + (k + 0.5) / 24, W, H)
            assert np.abs(got - want).mean() < 4.0, (it["category"], np.abs(got - want).mean())
        # through the first one: the footage, darkened by half (somewhere with no type: the bottom-left corner)
        px = _grab(out, A["start"] + 6.25, W, H)[470, 5]
        assert abs(px[1] - 140 * 0.5 - 8 * 0.5) < 12 and px[1] > px[0] + 20, px
        # the second: over the red photo (darkened), not over the footage
        px = _grab(out, B["start"] + 6.25, W, H)[470, 5]
        assert px[0] > px[1] + 20, px
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_a_still_from_your_footage_behind_a_graphic(items, tmp_path):
    """The frame of your own video playing on the timeline at the graphic's moment, taken once with FFmpeg."""
    vid = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x2060C0:s=320x180:d=600", "-r", "24", "-pix_fmt", "yuv420p",
                    str(vid)], check=True)
    it = items["timeline"]
    a = {"id": "v", "kind": "video", "path": str(vid), "name": "clip.mp4", "duration": 600}
    p = {"scenes": [{"id": "s", "asset_id": "v", "duration": 600}], "assets": [a]}
    st = styled(it, {"background": "still"})
    files = cinematic.photo_files(p, st, lambda x: x["path"], tmp_path)
    assert cinematic.backdrop_used(st, files) == "still" and files[cinematic.BACKDROP]["file"].endswith(".jpg")
    fr = np.asarray(cinematic.frame(cinematic.build(st, files), st, cinematic.frames_of(st) // 2, 320, 180))
    assert fr[..., 3].min() == 255 and fr[175, 5, 2] > fr[175, 5, 0] + 15  # the blue footage, darkened, behind it
    # no footage at that moment: its own background
    assert cinematic.backdrop_used(st, cinematic.photo_files({"scenes": [], "assets": []}, st, lambda x: x["path"], tmp_path)) == "own"
