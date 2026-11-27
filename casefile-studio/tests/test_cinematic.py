"""v0.4.62 The story-aware cinematic graphics (cinegfx) inside the app: placement from the narration, the
Motion API, editing (category, photos, captions), the cache, preview = export, and the graphics' own
sound through the existing mix. The narration is the approved Javits script (qa/cinegfx-demos/)."""
import re
import subprocess

import numpy as np
import pytest
from PIL import Image

import cinematic
import motion
import sound
from storage import ROOT

SCRIPT = ROOT / "qa" / "cinegfx-demos" / "javits-script.md"
SIX = {"findings", "timeline", "contradiction", "legal", "digital", "turning"}


def javits_scenes():
    """The script's spoken chapters as scenes: one scene per paragraph, timed at a narrator's pace."""
    scenes, chapter = [], None
    for line in SCRIPT.read_text().splitlines():
        m = re.match(r"## Chapter \d+ — (.+)", line)
        if m:
            chapter = m.group(1).strip().upper()
            continue
        if line.startswith("#"):
            chapter = None if not line.startswith("## Chapter") else chapter
            continue
        if chapter and line.strip() and not line.startswith("**"):
            words = line.split()
            scenes.append({"id": f"s{len(scenes)}", "title": "", "chapter": chapter, "narration": line.strip(),
                           "duration": round(len(words) * 0.38 + 0.4, 2)})
    return scenes


def javits_project():
    return {"id": "jv", "title": "The Last Timeline — Javits Frimpong", "topic": "Javits Frimpong", "created_at": "2026-11-13T09:00:00",
            "scenes": javits_scenes(), "assets": [], "motion": {"enabled": True, "items": []}}


@pytest.fixture(scope="module")
def suggested():
    p = javits_project()
    return p, cinematic.suggest(p, [])


# ------------------------------------------------------------------ placement

def test_suggest_places_every_category_the_story_supports(suggested):
    p, items = suggested
    cats = [x["category"] for x in items]
    assert set(cats) == SIX, cats  # v0.4.62: no strong graphic lost to spacing on the full Javits script
    assert all(x["template"] == "cinematic" and x["status"] == "suggested" and x["source"] == "auto" for x in items)
    for a, b in zip(items, items[1:]):
        if b["start"] < a["end"]:  # back to back: the earlier graphic's last word stays readable before the next covers it,
            # as far as the next one's own first word allows (it never comes up after it)
            first, held = b["words"][0][1], b["start"] - (a["start"] + a["words"][-1][1])
            assert held >= cinematic.HOLD - 1 / 24 or first <= cinematic.MIN_LEAD + 1 / 24 + 1e-3
            assert first > 0
    for x in items:
        assert x["reason"] and x["words"] and x["text"]
        # every word on screen is the narration's own (nothing fabricated): each timed word (cinegfx's normalised
        # token) points at exactly that word of the item's text, and the text is the narration's
        assert all(x["text"][w[3]:w[4]].lower().replace("\u2019", "'") == w[0] for w in x["words"])
        assert x["text"] in " ".join(s["narration"] for s in p["scenes"])
        assert x["end"] == pytest.approx(x["start"] + cinematic.frames_of(x) / cinematic.FPS, abs=1e-3)


def test_suggest_keeps_what_you_decided(suggested):
    p, items = suggested
    mine = dict(items[0], status="approved", start=items[0]["start"])
    again = cinematic.suggest(p, [mine])
    assert all(x["category"] != mine["category"] or x["start"] != mine["start"] for x in again)
    assert all(x["end"] <= mine["start"] + 1e-6 or x["start"] >= mine["end"] - 1e-6 for x in again)


def test_normalise_round_trip_and_dispatch(suggested):
    p, items = suggested
    for x in items:
        y = motion.normalise_item(x)
        assert y == x and motion.normalise_item(y) == y
    # a broken item is dropped, not drawn
    assert motion.normalise_item(dict(items[0], words=[["x", 0, 1, 50, 10]])) is None
    assert motion.normalise_item(dict(items[0], category="nope")) is None
    # the server, not the client, decides the length
    assert motion.normalise_item(dict(items[0], end=items[0]["end"] + 30))["end"] == items[0]["end"]
    # a classic item is untouched by the new engine
    classic = motion.normalise_item({"template": "findings", "start": 1, "end": 9, "heading": "KEY FINDINGS", "lines": [{"text": "a", "at": 2}]})
    assert classic["template"] == "findings" and "payload" not in classic
    assert "cinematic" in motion.describe(items[0]) and items[0]["label"].split(" ")[0] in motion.describe(items[0])


def test_back_to_back_graphics_hand_over(suggested):
    """The later graphic fades in, opaque, over the earlier one, which ends once covered: one graphic on screen
    (apart from the fade), the earlier one with no exit and no sound under the new one."""
    p, items = suggested
    pairs = [(a, b) for a, b in zip(items, items[1:]) if b["start"] < a["end"]]
    assert pairs  # the Javits script has back-to-back strong graphics (why two categories used to be lost)
    m = motion.normalise({"enabled": True, "items": [dict(x, status="approved") for x in items]})
    by = {x["id"]: x for x in m["items"]}
    for a, b in pairs:
        A, B = by[a["id"]], by[b["id"]]
        assert A["cut"] == round((B["start"] - A["start"] + cinematic.FADE_IN) * 24)
        assert A["end"] == pytest.approx(B["start"] + cinematic.FADE_IN, abs=1 / 24)
        assert all(c["t"] < B["start"] - A["start"] + 1e-3 for c in cinematic.cues(A))  # no sound under the new one
        assert len(cinematic.cues(A)) < len(cinematic.cues(a))
        g = cinematic.build(A)
        last = cinematic.frames_of(A) - 1
        assert np.asarray(cinematic.frame(g, A, last, 160, 90))[..., 3].min() == 255  # no exit fade under the cover
        assert np.asarray(cinematic.frame(cinematic.build(B), B, 0, 160, 90))[..., 3].max() < 255  # the cover fades in
    # only an approved graphic covers: a suggestion after it leaves it whole
    m2 = motion.normalise({"enabled": True, "items": [dict(x, status="approved" if x["id"] == pairs[0][0]["id"] else "suggested") for x in items]})
    A2 = next(x for x in m2["items"] if x["id"] == pairs[0][0]["id"])
    assert "cut" not in A2 and A2["end"] == pairs[0][0]["end"]
    # the cut is the list's to decide: a stale one sent by the client is replaced
    m3 = motion.normalise({"enabled": True, "items": [dict(pairs[0][0], cut=5, status="approved")]})
    assert "cut" not in m3["items"][0]


# ------------------------------------------------------------------ API

def _project(client, p):
    pid = client.post("/api/projects", json={"title": p["title"], "topic": p["topic"]}).json()["id"]
    return pid, client.patch(f"/api/projects/{pid}", json={"scenes": p["scenes"]}).json()


def test_api_catalog_suggest_draft_and_edit(isolated):
    client, root = isolated
    cat = client.get("/api/motion/catalog").json()
    tc = next(c for c in cat["collections"] if c["key"] == "truecrime")
    assert cat["default"] == "truecrime" and {c["key"] for c in tc["categories"]} == SIX
    assert all(c["label"] and c["about"] for c in tc["categories"])

    pid, p = _project(client, javits_project())
    # a classic suggestion stays when the cinematic engine suggests, and the other way round
    r = client.post(f"/api/projects/{pid}/motion/suggest", json={}).json()
    classic = [x for x in r["project"]["motion"]["items"] if x["template"] != "cinematic"]
    r = client.post(f"/api/projects/{pid}/motion/suggest", json={"engine": "cinematic"}).json()
    items = r["project"]["motion"]["items"]
    cine = [x for x in items if x["template"] == "cinematic"]
    assert {x["category"] for x in cine} == SIX and r["added"] == len(cine)
    assert [x["id"] for x in items if x["template"] != "cinematic"] == [x["id"] for x in classic]
    # suggesting again replaces only the cinematic suggestions (no pile-up)
    r2 = client.post(f"/api/projects/{pid}/motion/suggest", json={"engine": "cinematic"}).json()
    assert len([x for x in r2["project"]["motion"]["items"] if x["template"] == "cinematic"]) == len(cine)

    # what a passage can be, and a draft of one category; a category the passage lacks is refused, explained
    leg = next(x for x in cine if x["category"] == "legal")
    o = client.post(f"/api/projects/{pid}/motion/options", json={"start": leg["start"], "end": leg["end"]}).json()
    assert o["options"][0]["category"] == "legal" and len(o["sentences"]) == 2
    d = client.post(f"/api/projects/{pid}/motion/draft", json={"template": "cinematic", "category": "auto", "start": leg["start"], "end": leg["end"]})
    assert d.status_code == 200 and d.json()["item"]["category"] == "legal" and d.json()["item"]["status"] == "draft"
    bad = client.post(f"/api/projects/{pid}/motion/draft", json={"template": "cinematic", "category": "timeline", "start": leg["start"], "end": leg["end"]})
    assert bad.status_code == 422 and "timeline" in bad.json()["detail"].lower()
    # remaking a graphic as another category keeps its sentences (the window), whatever the times
    tl = next(x for x in cine if x["category"] == "timeline")
    rem = client.post(f"/api/projects/{pid}/motion/draft", json={"template": "cinematic", "category": "timeline", "start": tl["start"], "end": tl["end"],
                                                                 "window": tl["window"], "id": tl["id"]}).json()["item"]
    assert rem["window"] == tl["window"] and rem["id"] == tl["id"] and rem["words"] == tl["words"]

    # approve, hide captions off, a photo from the project (with its credit); PATCH keeps it all
    p = client.get(f"/api/projects/{pid}").json()
    img = Image.new("RGB", (900, 600), (90, 110, 130))
    up = root / "court.jpg"
    img.save(up)
    with open(up, "rb") as f:
        r = client.post(f"/api/projects/{pid}/upload", files=[("files", ("court.jpg", f, "image/jpeg"))])
    assert r.status_code == 200, r.text
    asset = next(a for a in r.json()["assets"] if a["kind"] == "image")
    items = client.get(f"/api/projects/{pid}").json()["motion"]["items"]
    leg = next(x for x in items if x.get("category") == "legal")
    slot = client.post(f"/api/projects/{pid}/motion/plan", json={"item": leg}).json()["slots"]
    assert slot and slot[0]["kind"] == "place" and slot[0]["filled"] is False
    leg2 = dict(leg, status="approved", hide_captions=False,
                photos={slot[0]["key"]: {"asset_id": asset["id"], "credit": "Test credit", "month": "Nov 2026", "auto": False}})
    out = client.patch(f"/api/projects/{pid}", json={"motion": {"enabled": True, "items": [leg2 if x["id"] == leg["id"] else x for x in items]}}).json()
    got = next(x for x in out["motion"]["items"] if x["id"] == leg["id"])
    assert got["status"] == "approved" and got["hide_captions"] is False
    assert got["photos"][slot[0]["key"]] == {"asset_id": asset["id"], "credit": "Test credit", "month": "Nov 2026", "auto": False}
    # a photo that is not one of the project's images is not kept
    fake = dict(got, photos={slot[0]["key"]: {"asset_id": "nope", "credit": "x", "month": "", "auto": False}})
    out = client.patch(f"/api/projects/{pid}", json={"motion": {"enabled": True, "items": [fake]}}).json()
    assert out["motion"]["items"][0]["photos"][slot[0]["key"]]["asset_id"] == ""

    # the preview: a plan and its frames; the photo fills the slot and changes the hash
    plan = client.post(f"/api/projects/{pid}/motion/plan", json={"item": got}).json()
    assert plan["fps"] == 24 and len(plan["frames"]) == cinematic.frames_of(got) and plan["slots"][0]["filled"] is True
    r = client.get(f"/api/motion/{plan['hash']}/{plan['frames'][len(plan['frames']) // 2]}.webp")
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    plan0 = client.post(f"/api/projects/{pid}/motion/plan", json={"item": dict(got, photos={})}).json()
    assert plan0["hash"] != plan["hash"]


# ------------------------------------------------------------------ preview = export

def test_export_frames_are_the_preview_frames(suggested, tmp_path):
    """The export's transparent video holds exactly the frames the preview draws (same code, lossless)."""
    p, items = suggested
    it = next(x for x in items if x["category"] == "turning")
    W, H = 320, 180
    out = tmp_path / "g.mov"
    n = cinematic.encode(it, {}, W, H, out, workers=1)
    assert n == cinematic.frames_of(it)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                         capture_output=True, check=True).stdout
    vid = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 4)
    assert len(vid) == n
    g = cinematic.build(it, {})
    for k in (0, n // 3, n // 2, n - 2):
        want = np.asarray(cinematic.frame(g, it, k, W, H).convert("RGBA"))
        assert np.array_equal(vid[k], want), k


def test_parallel_export_equals_serial(suggested, tmp_path):
    p, items = suggested
    it = next(x for x in items if x["category"] == "digital")
    W, H = 320, 180
    a, b = tmp_path / "a.mov", tmp_path / "b.mov"
    cinematic.encode(it, {}, W, H, a, workers=1)
    cinematic.encode(it, {}, W, H, b, workers=2)

    def frames(path):
        return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True, check=True).stdout
    assert frames(a) == frames(b)


def test_workers_follow_the_machine(monkeypatch):
    monkeypatch.delenv("CASEFILE_CINEMATIC_WORKERS", raising=False)
    monkeypatch.setattr(cinematic.os, "cpu_count", lambda: 8)
    assert cinematic.workers_for(300) == 6  # an M1: cores - 1, at most 6
    assert cinematic.workers_for(40) == 1  # too short to be worth the start-up
    monkeypatch.setattr(cinematic.os, "cpu_count", lambda: 2)
    assert cinematic.workers_for(300) == 1
    monkeypatch.setenv("CASEFILE_CINEMATIC_WORKERS", "3")
    assert cinematic.workers_for(300) == 3


# ------------------------------------------------------------------ sound

def test_designed_sound_goes_through_the_mix_exactly(suggested):
    p, items = suggested
    p = dict(p, motion={"enabled": True, "items": [dict(x, status="approved") for x in items]})
    evs = [e for e in sound.events(p) if e["anchor"].startswith("mg:cg")]
    assert evs and all(e.get("layer") for e in evs)
    shown = motion.normalise(p["motion"])["items"]  # with the handoffs: no sound under a covering graphic
    designed = sum(1 for x in shown for c in cinematic.cues(x) if not c["sfx"].startswith("key-soft"))
    assert sum(1 for e in evs if not e["typed"]) == designed
    planned, info = sound.plan(p)
    by = {i["anchor"]: i for i in planned}
    ev = {e["anchor"]: e for e in evs}
    full = [a for a in ev if a in by and "softened" not in by[a]["reason"]]
    assert full
    for a in full:  # the exact designed sound at its designed level (intensity 0.4 = no offset)
        e = ev[a]
        if e.get("sid"):
            assert by[a]["sound"] == e["sid"]
        assert by[a]["gain"] == pytest.approx(e["gain"], abs=0.06)
    # a graphic is never half loud, half softened
    for gid in {a.split(":")[1] for a in ev}:
        states = {("soft" if "softened" in by[a]["reason"] else "full") for a in ev if a.startswith(f"mg:{gid}:") and a in by}
        assert len(states) <= 1, (gid, states)
    # unapproved graphics make no sound
    p2 = dict(p, motion={"enabled": True, "items": [dict(x, status="suggested") for x in items]})
    assert not [e for e in sound.events(p2) if e["anchor"].startswith("mg:cg")]


# ------------------------------------------------------------------ the export encoder (v0.4.62)

def test_encoder_is_libx264_unless_videotoolbox_is_asked_for_and_works(monkeypatch):
    import renderer
    monkeypatch.delenv("CASEFILE_VIDEO_ENCODER", raising=False)
    assert renderer.video_encoder() == ("libx264", None)
    assert renderer.video_codec_args("libx264", 1920, 1080, "4") == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "4"]
    monkeypatch.setenv("CASEFILE_VIDEO_ENCODER", "videotoolbox")
    monkeypatch.setitem(renderer._ENCODER_PROBE, renderer.VIDEOTOOLBOX, (False, "Unknown encoder"))
    enc, why = renderer.video_encoder()
    assert enc == "libx264" and "VideoToolbox" in why and "libx264" in why  # never a failed export: said, and software
    monkeypatch.setitem(renderer._ENCODER_PROBE, renderer.VIDEOTOOLBOX, (True, ""))
    assert renderer.video_encoder() == (renderer.VIDEOTOOLBOX, None)
    args = renderer.video_codec_args(renderer.VIDEOTOOLBOX, 1920, 1080, "4")
    assert args[:2] == ["-c:v", "h264_videotoolbox"] and "-b:v" in args and args[args.index("-b:v") + 1] == "12M"
    monkeypatch.setenv("CASEFILE_VIDEO_ENCODER", "nope")
    assert renderer.video_encoder()[0] == "libx264"


# ------------------------------------------------------------------ a real export

def _grab(path, t, w, h):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(int)


def test_export_shows_the_preview_frames_hands_over_and_mixes_the_designed_sound(tmp_path, monkeypatch):
    """One chapter of Javits (the investigators: an evidence log, then the findings, back to back) exported at
    480p over plain footage: the picture is the preview's frame (to H.264 accuracy), the findings take over
    from the evidence log, the footage comes back after, and the graphics' designed sounds are in the mix."""
    import shutil

    import renderer
    folder = ROOT / "qa" / ("v062-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(renderer, "DATA", tmp_path / "data")
    try:
        Image.new("RGB", (640, 360), (40, 140, 60)).save(folder / "green.png")
        a = {"id": "g", "kind": "image", "path": str(folder / "green.png"), "name": "green.png", "width": 640, "height": 360}
        sc = [dict(s, asset_id="g", motion="none", show_title=False) for s in javits_scenes() if s["chapter"] == "WHAT INVESTIGATORS SAID"]
        p = {"id": "cine", "title": "The Last Timeline — Javits Frimpong", "topic": "Javits Frimpong", "created_at": "2026-11-13", "look": "natural",
             "captions": False, "music_volume": 0, "assets": [a], "scenes": sc}
        items = cinematic.suggest(p, [])
        assert [x["category"] for x in items] == ["digital", "findings"]
        p["motion"] = motion.normalise({"enabled": True, "items": [dict(x, status="approved") for x in items]})
        p["sound"] = {"enabled": True}
        A, B = p["motion"]["items"]
        assert A.get("cut") and A["end"] == pytest.approx(B["start"] + cinematic.FADE_IN, abs=1 / 24)
        out = tmp_path / "cine.mp4"
        r = renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
        W, H = 854, 480
        assert renderer.probe(out)["duration"] == pytest.approx(sum(s["duration"] for s in sc), abs=0.1)  # timeline untouched
        green = lambda px: px[1] > 110 and px[0] < 90 and px[2] < 90
        assert green(_grab(out, max(0.2, A["start"] - 0.5), W, H)[240, 427])  # before: the footage
        for it, local in ((A, 6.0), (B, 1.0), (B, 9.0)):  # the export's picture is the preview's frame
            k = round(local * 24)
            want = np.asarray(cinematic.frame(cinematic.build(it), it, k, W, H).convert("RGB")).astype(int)
            got = _grab(out, it["start"] + (k + 0.5) / 24, W, H)
            assert np.abs(got - want).mean() < 4.0, (it["category"], np.abs(got - want).mean())
        # the handover: just after the findings have faded in, the evidence log is gone (the findings' own frame)
        k = round((cinematic.FADE_IN + 0.1) * 24)
        want = np.asarray(cinematic.frame(cinematic.build(B), B, k, W, H).convert("RGB")).astype(int)
        assert np.abs(_grab(out, B["start"] + (k + 0.5) / 24, W, H) - want).mean() < 4.0
        assert green(_grab(out, B["end"] + 0.5, W, H)[240, 427])  # after: the footage again
        assert r["timing"]["motion_graphics"] and r["timing"]["sound_effects"] >= 6 and r["timing"]["encoder"] == "libx264"
    finally:
        shutil.rmtree(folder, ignore_errors=True)
