"""v0.4.56 Intelligent sound design: the library, the plan (what gets a sound, what stays silent and
why), frame-accurate sync with the animation, selective edits, the stem, the export mix and the API."""
import json
import math
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

import history
import motion
import renderer
import sfxlib
import sound
from storage import ROOT


def gitem(**kw):
    base = {"id": "g1", "status": "approved", "template": "findings", "start": 1.0, "end": 9.0, "heading": "KEY FINDINGS",
            "title": "What the records showed", "lines": [{"text": "Phone records placed him near the scene", "at": 2.0},
                                                         {"text": "Video showed the car on Nebraska Avenue", "at": 4.5}]}
    base.update(kw)
    return motion.normalise_item(base)


def proj(scenes=None, items=(), on=True, **kw):
    scenes = scenes or [{"id": "s1", "title": "", "chapter": "CHAPTER 3 — THE EVIDENCE", "duration": 10.0,
                         "narration": "Phone records placed him near the scene. Video showed the car on Nebraska Avenue."}]
    p = {"id": "5d00000000000001", "scenes": scenes, "assets": [], "motion": {"enabled": bool(items), "items": list(items)},
         "sound": {"enabled": on}}
    p.update(kw)
    return p


@pytest.fixture
def data(tmp_path):
    return tmp_path / "data"


# ------------------------------------------------------------------ the library

def test_library_is_made_here_deterministic_and_never_clips(data):
    ids = [c[0] for c in sfxlib.CATALOG]
    assert len(ids) == len(set(ids)) >= 70
    m = sfxlib.ensure(data, ids)
    for sid, (_, cat, label, inten, _r, peak_db) in zip(ids, sfxlib.CATALOG):
        x = sfxlib.read_wav(sfxlib.path_of(data, sid))
        assert x.shape[0] == 2 and x.dtype == np.float32
        peak = 20 * math.log10(np.abs(x).max())
        assert peak <= -6.0 and abs(peak - peak_db) < 0.6, (sid, peak)  # designed level, headroom kept
        assert 0 <= m[sid]["sync"] < m[sid]["seconds"] <= 8.0
    a = (sfxlib.synth("whoosh-mid-1")[0] * 1e4).astype(int)
    b = (sfxlib.synth("whoosh-mid-1")[0] * 1e4).astype(int)
    assert np.array_equal(a, b)  # the same file every time on every computer
    # not normalised to one loudness: a click sits well below a low impact
    assert dict((c[0], c[5]) for c in sfxlib.CATALOG)["thump-deep-1"] - dict((c[0], c[5]) for c in sfxlib.CATALOG)["tick-1"] >= 8
    cats = {c[1] for c in sfxlib.CATALOG}
    for need in ("pop", "click", "click-muted", "typewriter", "keyboard", "whoosh", "reverse-whoosh", "thump", "bass-impact", "pulse",
                 "notification", "scan", "paper", "document", "shutter", "tick", "riser", "tonal-sweep", "swell", "transition-impact",
                 "bell", "cta-click"):
        assert need in cats, need
    # a second call writes nothing again
    before = {p: p.stat().st_mtime_ns for p in (data / "cache" / "sfx").rglob("*.wav")}
    sfxlib.ensure(data, ids)
    assert before == {p: p.stat().st_mtime_ns for p in (data / "cache" / "sfx").rglob("*.wav")}


def test_shutter_is_never_chosen_automatically():
    for cat in sfxlib.CATEGORIES:
        assert not any("shutter" in s for s in sound._candidates(cat, 0.4) + sound._candidates(cat, 0.9))


# ------------------------------------------------------------------ settings

def test_off_by_default_and_settings_stay_in_range():
    st = sound.normalise(None)
    assert st["enabled"] is False and st["preset"] == "cinematic" and st["items"] == []
    st = sound.normalise({"enabled": 1, "master": 9, "density": -3, "mode": "x", "preset": "x",
                          "items": [{"anchor": "t:3", "sound": "nope"}, {"anchor": "", "sound": "pop-soft-1"},
                                    {"anchor": "t:3", "sound": "pop-soft-1", "gain": 99, "offset": -99, "status": "x"}]})
    assert st["enabled"] and st["master"] == sound.LIM["master"][1] and st["density"] == 0 and st["mode"] == "auto"
    assert len(st["items"]) == 1
    it = st["items"][0]
    assert it["gain"] == sound.LIM["gain"][1] and it["offset"] == sound.LIM["offset"][0] and it["status"] == "approved"


# ------------------------------------------------------------------ the plan

def kinds_at(items):
    return {it["anchor"]: it for it in items}


def test_transitions_get_the_sound_their_movement_suggests():
    sc = []
    for k, (tr, ch) in enumerate([(None, "A"), ("slide-left", "A"), ("circle", "A"), ("cut", "A"), ("dip-black", "B"), ("fade", "B")]):
        s = {"id": f"s{k}", "title": f"Scene {k}", "chapter": f"CHAPTER {ch} — THE SEARCH", "duration": 6.0, "narration": ""}
        if tr:
            s["transition"], s["transition_duration"] = tr, 0.8
        sc.append(s)
    items, info = sound.plan(proj(sc), {"enabled": True, "density": 1.0})
    by = kinds_at(items)
    assert sfxlib.BY_ID[by["tr:s1"]["sound"]][1] == "whoosh" and by["tr:s1"]["sound"].endswith("-l")  # slide left: leftward whoosh
    assert sfxlib.BY_ID[by["tr:s2"]["sound"]][1] == "tonal-sweep"  # a masked reveal
    assert "tr:s3" not in by  # a hard cut: nothing
    assert sfxlib.BY_ID[by["tr:s4"]["sound"]][1] == "swell"  # a new chapter through black
    assert "tr:s5" not in by  # an ordinary dissolve: silence
    # placed at the visual middle of the transition, from the scene start on the timeline
    ev = {e["anchor"]: e for e in sound.events(proj(sc))}
    assert ev["tr:s1"]["t"] == pytest.approx(6.0 + effects_len(sc[1]) / 2, abs=1e-3)


def effects_len(s):
    import effects

    return effects.transition_length(s, s["duration"])


def test_soundbites_victims_and_sensitive_narration_stay_silent(data):
    sc = [
        {"id": "a", "title": "", "chapter": "CHAPTER 2 — THE SEARCH", "duration": 6.0, "narration": "Detectives traced the phone."},
        {"id": "b", "title": "Sister interview", "chapter": "CHAPTER 2 — THE SEARCH", "duration": 8.0, "narration": "",
         "insert_audio": True, "transition": "slide-left", "transition_duration": 0.6},
        {"id": "c", "title": "", "chapter": "CHAPTER 3 — THE VICTIM", "duration": 6.0, "narration": "She loved her job.",
         "transition": "slide-left", "transition_duration": 0.6},
        {"id": "d", "title": "", "chapter": "CHAPTER 4 — THE SEARCH", "duration": 6.0, "transition": "slide-up", "transition_duration": 0.6,
         "narration": "Her body was found that morning, and her family was told."},
    ]
    items, info = sound.plan(proj(sc), {"enabled": True, "density": 1.0, "intensity": 0.9})
    anchors = {it["anchor"] for it in items}
    assert not anchors & {"tr:b", "tr:c", "tr:d"}
    whys = {s["label"]: s["why"] for s in info["silenced"]}
    assert "soundbite" in whys["Transition into Sister interview"]
    assert any("sensitive" in w or "victim" in w for w in whys.values())
    # nothing at all lands inside the soundbite (with its margin)
    placed, _ = sound.resolve(proj(sc), data, items)
    assert not any(6.0 - 0.6 <= p["t"] <= 14.0 + 0.6 for p in placed)


def test_a_legal_outcome_in_the_narration_gets_a_restrained_low_sound_on_the_word():
    words = "After a four day trial, the jury found him guilty of all charges.".split()
    sc = [{"id": "a", "title": "", "chapter": "CHAPTER 6 — THE TRIAL", "duration": 8.0, "narration": " ".join(words),
           "captions": [{"start": 1.0, "end": 6.0, "text": " ".join(words)}]}]
    items, _ = sound.plan(proj(sc), {"enabled": True})
    lows = [it for it in items if it["kind"] == "moments"]
    assert len(lows) == 1 and sfxlib.BY_ID[lows[0]["sound"]][1] in ("bass-impact", "thump") and lows[0]["gain"] <= -6
    t = {e["anchor"]: e["t"] for e in sound.events(proj(sc))}[lows[0]["anchor"]]
    assert 1.0 + 5 / len(words) * 5 * 0.5 < t < 6.0  # on the outcome words, not the caption start


def test_density_and_variation():
    sc = [{"id": f"s{k}", "title": "", "chapter": "CHAPTER 2 — THE SEARCH", "duration": 3.0, "narration": "",
           "transition": "slide-left", "transition_duration": 0.5} for k in range(40)]
    lo, _ = sound.plan(proj(sc), {"enabled": True, "density": 0.0})
    hi, _ = sound.plan(proj(sc), {"enabled": True, "density": 1.0})
    assert len(lo) < len(hi)
    t = sorted(e["t"] for e in sound.events(proj(sc)) if e["anchor"] in {i["anchor"] for i in hi})
    assert min(b - a for a, b in zip(t, t[1:])) >= sound.SPEC["spacing"]["whoosh"] - 1e-6  # whooshes never pile up
    # related elements stay in one family (v0.4.58: alternating variations, never the identical sample twice in a row)
    items, _ = sound.plan(proj(items=[gitem(lines=[{"text": f"Line number {k} of the findings", "at": 2 + k} for k in range(4)])]),
                          {"enabled": True, "density": 1.0})
    lines = [it for it in items if it["label"].startswith("Line")]
    assert len(lines) >= 3 and {sfxlib.BY_ID[it["sound"]][1] for it in lines} == {"click"}
    assert all(a["sound"] != b["sound"] for a, b in zip(lines, lines[1:]))


def test_sounds_follow_the_actual_animation_frames():
    g = gitem()
    p = proj(items=[g])
    ev = [e for e in sound.events(p) if e["anchor"].startswith("mg:")]
    lay = motion._layout(g, *motion.preview_size(p), None)
    actual = motion.sound_events(lay)
    first_line = next(a for a in actual if a["role"] in ("line", "marker"))
    line_ev = next(e for e in ev if e["label"].startswith("Line 1"))
    s0 = round(g["start"] * 24) / 24
    assert line_ev["t"] == pytest.approx(s0 + math.ceil(first_line["t"] * 24 - 1e-6) / 24, abs=1e-4)
    assert round(line_ev["t"] * 24, 6) == round(line_ev["t"] * 24)  # exactly on a video frame
    # the line's own time is what counts, not the caption or the graphic start
    assert line_ev["t"] > g["start"] + 0.5


def test_typing_keys_match_the_typed_characters(data):
    g = gitem(enter="type", lines=[{"text": "Caller gives one address", "at": 2.0}])
    p = proj(items=[g])
    ev = [e for e in sound.events(p) if e["typed"]]
    assert ev, "a typed graphic has typing events"
    lay = motion._layout(g, *motion.preview_size(p), None)
    for e, el in zip(ev, [x for x in motion.sound_events(lay) if x["chars"]]):
        assert len(e["typed"]) == len(el["chars"])
        for (t, sp), (lt, lsp) in zip(e["typed"], el["chars"]):
            assert sp == lsp and t == pytest.approx(round(g["start"] * 24) / 24 + math.ceil(lt * 24 - 1e-6) / 24, abs=1e-4)
    # no click or whoosh doubles the first key
    items, _ = sound.plan(p, {"enabled": True, "density": 1.0})
    typed_t = [e["t"] for e in ev]
    others = [e for e in sound.events(p) if e["anchor"] in {i["anchor"] for i in items} and not e["typed"] and "Exit" not in e["label"]]
    assert not any(abs(o["t"] - t) < 0.35 for o in others for t in typed_t)
    placed, _ = sound.resolve(p, data, items)
    keys = [k for r in placed if r["keys"] for k in r["keys"]]
    assert len(keys) == sum(len(e["typed"]) for e in ev)
    assert len({k[1] for k in keys}) >= 3  # not one sample looped


def test_moving_or_deleting_a_graphic_moves_or_removes_its_sounds(data):
    p = proj(items=[gitem()])
    a, _ = sound.resolve(p, data)
    p2 = proj(items=[gitem(start=3.0, end=11.0, lines=[{"text": "Phone records placed him near the scene", "at": 4.0},
                                                       {"text": "Video showed the car on Nebraska Avenue", "at": 6.5}])])
    b, _ = sound.resolve(p2, data)
    mg_a = {r["id"]: r["t"] for r in a if r["label"].startswith(("Line", "Entrance"))}
    mg_b = {r["id"]: r["t"] for r in b if r["label"].startswith(("Line", "Entrance"))}
    assert mg_a and set(mg_a) == set(mg_b)
    for k in mg_a:
        assert mg_b[k] - mg_a[k] == pytest.approx(2.0, abs=1 / 24 + 1e-6)
    # a sound you placed by hand on a graphic that is then deleted is reported, not left floating
    mine = {"anchor": "mg:g1:line:0", "sound": "pop-soft-2", "source": "manual"}
    p3 = proj(items=[], sound={"enabled": True, "items": [mine]})
    placed, gone = sound.resolve(p3, data)
    assert not placed and gone and "no longer on the timeline" in gone[0][1]


def test_editing_one_sound_leaves_every_other_sound_alone(data):
    sc = [{"id": f"s{k}", "title": "", "chapter": "CHAPTER 2 — THE SEARCH", "duration": 8.0, "narration": "",
           "transition": "slide-left", "transition_duration": 0.6} for k in range(4)]
    p = proj(sc, items=[gitem(start=17.0, end=23.0, lines=[{"text": "Phone records placed him near the scene", "at": 18.0}])])
    first, _ = sound.effective(p)
    target = dict(first[1], gain=-12.0, offset=0.25, edited=True)
    p["sound"] = {"enabled": True, "items": [target]}
    second, _ = sound.effective(p)
    assert {i["id"]: i for i in first}.keys() == {i["id"]: i for i in second}.keys()
    for x in second:
        if x["id"] == target["id"]:
            assert x["gain"] == -12.0 and x["offset"] == 0.25
        else:
            assert x == next(y for y in first if y["id"] == x["id"])
    # removing it keeps it silent through later re-plans (and it can be restored)
    p["sound"] = {"enabled": True, "items": [dict(target, status="removed")]}
    placed, _ = sound.resolve(p, data)
    assert target["id"] not in {r["id"] for r in placed}


def test_a_decided_sound_still_holds_its_moment(data):
    """Editing, removing or adding a sound never lets something else the plan had turned away
    take its place (found in the browser: a new variation of a marker tick brought back a second
    tick on the same frame)."""
    sc = [{"id": f"s{k}", "title": "", "chapter": "CHAPTER 2 — THE SEARCH" if k < 2 else "CHAPTER 3 — THE EVIDENCE",
           "duration": 6.0, "narration": "", "transition": ["slide-left", "circle", "dip-black", "cut"][k], "transition_duration": 0.6}
          for k in range(4)]
    g = motion.normalise_item({"id": "tl", "status": "approved", "template": "timeline", "layout": "horizontal",
                               "start": 0.3, "end": 11.0, "heading": "TIMELINE",
                               "lines": [{"text": "March 3 — Last seen", "at": 1.0}, {"text": "March 3 — Car found", "at": 1.0},
                                         {"text": "March 9 — Arrest", "at": 5.0}]})
    p = proj(sc, items=[g])
    first, info = sound.effective(p)
    anchors = {i["anchor"] for i in first}
    assert len(first) >= 3
    times = {e["anchor"]: e["t"] for e in sound.events(p)}
    # the scenario must really have a moment where one event was turned away for another
    assert any(a not in anchors and any(abs(t - times[b]) < 0.22 for b in anchors) for a, t in times.items())
    for it in first:
        other = next(x[0] for x in sfxlib.CATALOG if x[1] == sfxlib.BY_ID[it["sound"]][1] and x[0] != it["sound"])
        for change in ({"sound": other, "edited": True}, {"gain": -10.0, "edited": True}, {"status": "removed"},
                       {"offset": 0.5, "edited": True}, {"offset": -0.25, "edited": True}):
            p["sound"] = {"enabled": True, "items": [dict(it, **change)]}
            again, _ = sound.effective(p)
            assert {i["anchor"] for i in again} == anchors, (it["label"], change)
            assert sum(1 for i in again if i["anchor"] == it["anchor"]) == 1
    # a sound of your own next to a planned one: the planned one makes way, nothing is doubled
    t0 = times[first[0]["anchor"]]
    p["sound"] = {"enabled": True, "items": [{"anchor": f"t:{t0 + 0.05}", "sound": "pop-soft-1", "source": "manual"}]}
    again, _ = sound.effective(p)
    placed, gone = sound.resolve(p, data, again)
    assert not gone
    assert sorted(r["t"] for r in placed if abs(r["t"] - t0) < 0.22) == [pytest.approx(t0 + 0.05, abs=1e-4)]


def test_stem_is_sample_accurate_cached_and_never_clips(data, tmp_path):
    sc = [{"id": "s1", "title": "", "duration": 6.0, "narration": ""}]
    items = [{"anchor": f"t:{t}", "sound": sid, "gain": 6.0, "source": "manual"}
             for t, sid in [(1.0, "click-mech-1"), (1.0, "thump-deep-1"), (1.0, "bass-hit-1"), (1.0, "impact-tr-1"), (3.3, "tick-1")]]
    p = proj(sc, sound={"enabled": True, "master": 1.5, "items": items})
    path, placed, gone = sound.stem(p, data, 6.0, tmp_path)
    assert not gone and path.suffix == ".flac"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    assert x.shape[0] == round(6.0 * 48000)
    assert np.abs(x).max() <= 1.0  # four loud sounds at once, master 1.5: softly limited, no clipping
    # one sound alone: exactly at t - sync, to the sample, at its gain
    alone = proj(sc, sound={"enabled": True, "items": [items[4]]})
    path1, (tick,), _ = sound.stem(alone, data, 6.0, tmp_path)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path1), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    y = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    ref = sfxlib.read_wav(sfxlib.path_of(data, "tick-1"))[0] * tick["gain"]
    s = round(tick["start"] * 48000)
    assert tick["start"] == pytest.approx(3.3 - tick["sync"], abs=1e-4)
    assert np.allclose(y[s:s + ref.size, 0], ref, atol=1e-4) and np.abs(y[:s]).max() == 0
    mtime = path.stat().st_mtime_ns
    path2, _, _ = sound.stem(p, data, 6.0, tmp_path)
    assert path2 == path and path.stat().st_mtime_ns >= mtime  # the same plan: the cached stem
    p["sound"]["items"][4]["offset"] = 0.5
    path3, _, _ = sound.stem(p, data, 6.0, tmp_path)
    assert path3 != path  # one sound moved: a new stem


# ------------------------------------------------------------------ the export

def pcm(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ar", "48000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 2)[:, 0]


@pytest.fixture
def media(tmp_path, monkeypatch):
    folder = ROOT / "qa" / ("v056-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(renderer, "DATA", tmp_path / "data")
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


def test_export_adds_the_effects_without_touching_the_narration(tmp_path, media, monkeypatch):
    Image.new("RGB", (640, 360), (40, 40, 48)).save(media / "plate.png")
    voice = media / "voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=6", "-af",
                    "volume=0.3,apulsator=hz=3", "-ar", "48000", "-ac", "2", str(voice)], check=True)
    assets = [{"id": "img", "kind": "image", "path": str(media / "plate.png"), "name": "plate.png", "width": 640, "height": 360},
              {"id": "nar", "kind": "audio", "path": str(voice), "name": "voice.wav", "duration": 6.0}]
    sc = [{"id": "s1", "title": "", "narration": "", "duration": 3.0, "asset_id": "img", "motion": "none", "show_title": False,
           "audio_start": 0, "audio_duration": 3.0, "chapter": "CHAPTER 2 — THE SEARCH"},
          {"id": "s2", "title": "", "narration": "", "duration": 3.0, "asset_id": "img", "motion": "none", "show_title": False,
           "audio_start": 3.0, "audio_duration": 3.0, "chapter": "CHAPTER 2 — THE SEARCH", "transition": "slide-left", "transition_duration": 0.6}]
    base = {"id": "5d00000000000002", "title": "fx", "look": "natural", "captions": False, "music_volume": 0, "assets": assets, "scenes": sc,
            "narration_id": "nar", "exports": [], "episode": {"guide": True, "plan": {"mode": "final"}}}
    import episode

    monkeypatch.setattr(episode, "issues", lambda project: [])
    opts = {"resolution": "480p", "draft": False, "captions": False}
    # off (the default): the effects code is never reached
    called = []
    monkeypatch.setattr(sound, "stem", lambda *a, **k: called.append(1))
    off = tmp_path / "off.mp4"
    renderer.render(dict(base), opts, off, lambda *a: None, lambda: False)
    assert not called
    monkeypatch.undo()
    monkeypatch.setattr(renderer, "DATA", tmp_path / "data")
    monkeypatch.setattr(episode, "issues", lambda project: [])
    on = tmp_path / "on.mp4"
    lost = {"anchor": "tr:gone", "sound": "pop-soft-1", "source": "manual", "label": "Old pop"}
    r = renderer.render(dict(base, sound={"enabled": True, "items": [lost]}), opts, on, lambda *a: None, lambda: False)
    a, b = pcm(on), pcm(off)
    n = min(len(a), len(b))
    assert abs(len(a) - len(b)) < 2048 and renderer.probe(on)["duration"] == pytest.approx(6.0, abs=0.06)
    d = a[:n] - b[:n]
    sr = 48000
    rms = lambda x: float(np.sqrt(np.mean(x ** 2)) + 1e-12)
    # the whoosh is there, at the middle of the slide (3.0 + 0.3 s)
    assert rms(d[int(3.1 * sr):int(3.5 * sr)]) > 10 * rms(d[int(1.0 * sr):int(2.0 * sr)])
    # elsewhere the narration is the same, sample for sample (no delay, no level change)
    quiet = slice(int(0.3 * sr), int(2.0 * sr))
    assert rms(d[quiet]) < 0.02 * rms(b[quiet])
    assert np.abs(a).max() < 1.0
    assert any("Old pop" in w and "no longer on the timeline" in w for w in r["warnings"])


# ------------------------------------------------------------------ history and the API

def test_undo_names_for_sound_edits():
    it = sound._item({"anchor": "t:2", "sound": "pop-soft-1"})
    b = {"sound": {"enabled": True, "items": [it]}}
    assert history.describe(b, {"sound": {"enabled": True, "items": [dict(it, offset=0.2)]}})[0] == "Move sound effect"
    assert history.describe(b, {"sound": {"enabled": True, "items": [dict(it, gain=-3.0)]}})[0] == "Sound effect volume"
    assert history.describe(b, {"sound": {"enabled": True, "items": [dict(it, status="removed")]}})[0] == "Mute sound effect"
    assert history.describe(b, {"sound": {"enabled": False, "items": [it]}})[0] == "Sound design off"
    assert history.describe(b, {"sound": {"enabled": True, "density": 0.8, "items": [it]}})[0] == "Sound density"


def test_api_sound_flow(isolated):
    client, root = isolated
    p = client.post("/api/projects", json={"title": "Sound", "topic": "t"}).json()
    pid = p["id"]
    assert not p.get("sound")
    scenes = [{"id": f"s{k}", "title": f"Scene {k}", "chapter": "CHAPTER 2 — THE INVESTIGATION", "narration": "The house stood at the end of the road.",
               "duration": 5.0, **({"transition": "slide-left", "transition_duration": 0.6} if k else {})} for k in range(3)]
    client.patch(f"/api/projects/{pid}", json={"scenes": scenes})
    cat = client.get("/api/sound/catalog").json()
    assert len(cat["sounds"]) == len(sfxlib.CATALOG)
    r = client.get("/api/sound/lib/whoosh-dir-l.wav")
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    assert client.get("/api/sound/lib/../../etc.wav").status_code == 404
    p = client.patch(f"/api/projects/{pid}", json={"sound": {"enabled": True}}).json()
    assert p["sound"]["enabled"] and p["history"]["undo"][-1] == "Sound design on"
    plan = client.get(f"/api/projects/{pid}/sound/plan").json()
    assert plan["total"] == pytest.approx(15.0) and len(plan["items"]) == 2
    first = plan["items"][0]
    assert first["t"] == pytest.approx(5.3, abs=0.01) and first["reason"] and first["label"] == "Transition into Scene 1"
    edited = {k: first[k] for k in ("id", "anchor", "kind", "sound", "gain", "status", "source", "reason", "label")}
    edited.update(gain=-9.0, edited=True)
    p = client.patch(f"/api/projects/{pid}", json={"sound": {**p["sound"], "items": [edited]}}).json()
    assert p["history"]["undo"][-1] == "Edit sound effect"
    # v0.4.57 several planned sounds changed in one step (a scope) are named as an edit, not a plan
    both = [dict({k: it[k] for k in ("id", "anchor", "kind", "sound", "gain", "status", "source", "reason", "label")}, sound="whoosh-short-1", edited=True)
            for it in plan["items"]]
    q = history._sound_name({**p["sound"], "items": []}, {**p["sound"], "items": both})[0]
    assert q == "Edit 2 sound effects"
    q = history._sound_name({**p["sound"], "items": []}, {**p["sound"], "items": [dict(x, status="removed") for x in both]})[0]
    assert q == "Remove 2 sound effects"
    plan2 = client.get(f"/api/projects/{pid}/sound/plan").json()
    assert [i["id"] for i in plan2["items"]] == [i["id"] for i in plan["items"]]
    assert plan2["items"][0]["gain"] == -9.0 and plan2["items"][1] == plan["items"][1]
    g = client.post(f"/api/projects/{pid}/sound/generate").json()
    assert len(g["project"]["sound"]["items"]) == 2
    p = client.post(f"/api/projects/{pid}/undo").json()
    p = client.post(f"/api/projects/{pid}/undo").json()
    assert not p["sound"]["items"]
    assert p["scenes"][1]["narration"] == "The house stood at the end of the road."  # the layer never touches the scenes


def test_importing_a_sound_never_touches_the_timeline(isolated, tmp_path):
    client, root = isolated
    p = client.post("/api/projects", json={"title": "Sfx", "topic": "t"}).json()
    pid = p["id"]
    scenes = [{"id": "s0", "title": "", "narration": "The house.", "duration": 5.0}]
    client.patch(f"/api/projects/{pid}", json={"scenes": scenes})
    wav = tmp_path / "knock.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=0.4", str(wav)], check=True)
    r = client.post(f"/api/projects/{pid}/upload", files={"files": ("knock.wav", wav.read_bytes(), "audio/wav")}, data={"episode_role": "sfx"})
    assert r.status_code == 200, r.text
    p = r.json()
    a = p["assets"][-1]
    assert a["kind"] == "audio" and a["sfx"] and p["scenes"][0]["narration"] == "The house." and not p.get("narration_id")
    long = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=d=31", str(long)], check=True)
    r = client.post(f"/api/projects/{pid}/upload", files={"files": ("long.wav", long.read_bytes(), "audio/wav")}, data={"episode_role": "sfx"})
    assert r.status_code == 422 and "30 seconds" in r.text
    # it can be used and previewed
    item = {"anchor": f"sc:{p['scenes'][0]['id']}:1.0", "sound": f"a:{a['id']}", "source": "manual", "label": "Knock"}
    client.patch(f"/api/projects/{pid}", json={"sound": {"enabled": True, "items": [item]}})
    plan = client.get(f"/api/projects/{pid}/sound/plan").json()
    mine = [i for i in plan["items"] if i["sound"] == f"a:{a['id']}"]
    assert mine and not mine[0]["gone"], mine
    assert mine[0]["t"] == pytest.approx(1.0, abs=0.02) and mine[0]["seconds"] == pytest.approx(0.4, abs=0.05)
    w = client.get(f"/api/projects/{pid}/sound/custom/{a['id']}.wav")
    assert w.status_code == 200 and w.content[:4] == b"RIFF"


# ------------------------------------------------------------------ v0.4.57 narration level and the preview's ducking

def test_narration_level_is_clamped_and_saved(isolated):
    assert renderer.narration_volume({}) == 1.0
    assert renderer.narration_volume({"narration_volume": 3}) == 2.0
    assert renderer.narration_volume({"narration_volume": -1}) == 0.0
    assert renderer.narration_volume({"narration_volume": float("nan")}) == 1.0
    assert renderer.narration_volume({"narration_volume": "x"}) == 1.0
    client, _ = isolated
    pid = client.post("/api/projects", json={"title": "Level", "topic": "t"}).json()["id"]
    p = client.patch(f"/api/projects/{pid}", json={"narration_volume": 1.4}).json()
    assert p["narration_volume"] == 1.4 and p["history"]["undo"][-1] == "Narration volume"
    assert client.patch(f"/api/projects/{pid}", json={"narration_volume": 7}).json()["narration_volume"] == 2.0
    assert client.patch(f"/api/projects/{pid}/episode/options", json={"narration_volume": 2.5}).status_code == 422
    assert client.patch(f"/api/projects/{pid}/episode/options", json={"narration_volume": 0.5}).status_code == 200
    assert client.get(f"/api/projects/{pid}").json()["narration_volume"] == 0.5
    # no narration: nothing to duck under
    assert client.get(f"/api/projects/{pid}/sound/duck").json() == {"status": "none"}


def test_preview_ducking_and_narration_level_match_the_export(tmp_path, media, monkeypatch):
    """The editor's effects dip comes from the export's own compressor on the export's own voice bus:
    applied to the stem it reproduces the exported effects; the narration level scales only the voice."""
    import base64

    import episode

    monkeypatch.setattr(episode, "issues", lambda project: [])
    Image.new("RGB", (640, 360), (40, 40, 48)).save(media / "plate.png")
    voice = media / "voice.wav"
    gate = "0.3*sin(2*PI*220*t)*max(0\\,sin(2*PI*0.4*t))"  # speech-like: loud phrases, then pauses
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc={gate}|{gate}:s=48000:d=8", str(voice)], check=True)
    data = tmp_path / "data"
    assets = [{"id": "img", "kind": "image", "path": str(media / "plate.png"), "name": "plate.png", "width": 640, "height": 360},
              {"id": "nar", "kind": "audio", "path": str(voice), "name": "voice.wav", "duration": 8.0}]
    sc = [{"id": "s1", "title": "", "narration": "", "duration": 8.0, "asset_id": "img", "motion": "none", "show_title": False,
           "audio_start": 0, "audio_duration": 8.0}]
    items = [{"anchor": f"t:{t}", "sound": "swell-2", "source": "manual", "gain": 6.0} for t in (2.2, 5.6)]
    p = {"id": "5d00000000000003", "title": "fx", "look": "natural", "captions": False, "music_volume": 0, "assets": assets, "scenes": sc,
         "narration_id": "nar", "narration_volume": 0.6, "exports": [], "episode": {"guide": True, "plan": {"mode": "final"}},
         "sound": {"enabled": True, "master": 1.0, "items": items}}
    opts = {"resolution": "480p", "draft": False, "captions": False}
    on, off = tmp_path / "on.mp4", tmp_path / "off.mp4"
    renderer.render(dict(p), opts, on, lambda *a: None, lambda: False)
    renderer.render(dict(p, sound={"enabled": False}), opts, off, lambda *a: None, lambda: False)
    a, b = pcm(on), pcm(off)
    n = min(len(a), len(b))
    sr, w = 48000, 960
    rms = lambda x: float(np.sqrt(np.mean(x ** 2)) + 1e-12)
    # narration level 60%: the exported voice is the file at 0.6 (-4.4 dB)
    v = pcm(voice)[:n]
    assert 20 * math.log10(rms(b[sr:7 * sr]) / rms(v[sr:7 * sr])) == pytest.approx(20 * math.log10(0.6), abs=0.25)
    # the curve, applied to the stem, gives the effects the export actually has
    fx = a[:n] - b[:n]
    stem_path, _, _ = sound.stem(p, data, 8.0, data)
    st = pcm(stem_path)[:n]
    c = sound.duck_curve(p, data, wait=True)
    assert c["status"] == "ready" and c["rate"] == sound.DUCK_RATE
    g = np.frombuffer(base64.b64decode(c["gain"]), dtype=np.uint8) / 255
    assert g.min() < 0.6 and g.max() > 0.99  # it really dips, and recovers in the pauses
    gi = np.interp(np.arange(n) / sr, (np.arange(len(g)) + 0.5) / sound.DUCK_RATE, g)
    err, flat = [], []
    for k in range(0, n - w, w):
        s_ = rms(st[k:k + w])
        if s_ < 0.06:  # loud enough to be above the AAC noise of the difference
            continue
        err.append(abs(20 * math.log10(rms(fx[k:k + w]) / rms(st[k:k + w] * gi[k:k + w]))))
        flat.append(abs(20 * math.log10(rms(fx[k:k + w]) / s_)))
    assert len(err) > 40
    assert float(np.percentile(err, 95)) < 0.5  # the preview's dip is the export's dip
    assert float(np.percentile(flat, 80)) > 3  # without it the preview would be several dB too loud under the voice
    # cached: the second ask is immediate and identical; a different level is a different curve
    assert sound.duck_curve(p, data) == c
    assert sound.duck_curve(dict(p, narration_volume=1.2), data)["status"] == "working"
    assert sound.duck_curve(dict(p, sound=dict(p["sound"], duck=False)), data) == {"status": "none"}


# ------------------------------------------------------------------ v0.4.57 context, not keywords

def _ctx_project(lines, chapter="CHAPTER 3 — THE INVESTIGATION", title="", asset=None, victims=("Maurco Toler",), suspects=("Duane Jackson",)):
    scenes = [{"id": f"s{k}", "title": title if k == 0 else "", "chapter": chapter, "duration": 6.0, "narration": t,
               **({"asset_id": "pic"} if asset and k == 0 else {})} for k, t in enumerate(lines)]
    p = proj(scenes, episode={"guide": {"setup": {"victims": list(victims), "suspects": list(suspects)}}})
    if asset:
        p["assets"] = [{"id": "pic", "kind": "image", "name": asset}]
    return p


def _scores(p):
    sents = sound._sentences(p)
    return sound.context(p, sents)


def test_a_family_word_alone_never_decides():
    # the gg case: evidence about the suspect's family is the investigation, not grief
    p = _ctx_project(["The vehicle, he said, was registered to Duane Jackson's mother.",
                      "Jackson's mother testified that he had access to it that day."],
                     title="The vehicle, he said, was registered to Duane Jackson's mother.")
    c = _scores(p)
    assert max(c["sent"]) < sound.SENSITIVE_AT and c["scene"][0] < sound.SENSITIVE_AT
    assert not sound.protected(p)
    # the same word in a passage of grief about the victim is protected
    p = _ctx_project(["That was a mother remembering her son.", "Maurco's mother described the last time she saw him."])
    c = _scores(p)
    assert min(c["sent"]) >= sound.SENSITIVE_AT
    assert all(z[2] == sound.SENSITIVE_TEXT for z in sound.protected(p))


def test_neighbouring_sentences_chapter_and_role_are_weighed():
    # a neutral sentence inside a passage of grief is part of that passage
    p = _ctx_project(["Maurco's godmother remembered him as outgoing and adventurous.", "He was thirteen.",
                      "His family still holds a vigil every year."], chapter="CHAPTER 1")
    assert _scores(p)["sent"][1] >= sound.SENSITIVE_AT
    # ...but not across a chapter change
    p2 = _ctx_project(["His family still holds a vigil every year.", "Detectives traced the phone."])
    p2["scenes"][1]["chapter"] = "CHAPTER 4 — THE EVIDENCE"
    assert _scores(p2)["sent"][1] < sound.SENSITIVE_AT
    # a violent word naming the charge in a legal outcome is case progress (a restrained hit on the word)
    p3 = _ctx_project(["The jury acquitted both men of the aggravated-murder count."], chapter="CHAPTER 6 — THE TRIAL")
    assert _scores(p3)["sent"][0] < sound.SENSITIVE_AT
    items, _ = sound.plan(p3, {"enabled": True})
    assert [sfxlib.BY_ID[i["sound"]][1] for i in items if i["kind"] == "moments"] in (["bass-impact"], ["thump"])
    # ...the violence itself is not
    p4 = _ctx_project(["Maurco was shot as he stood in the doorway."], chapter="CHAPTER 2 — THAT NIGHT")
    assert _scores(p4)["sent"][0] >= sound.SENSITIVE_AT
    assert not [i for i in sound.plan(p4, {"enabled": True})[0] if i["kind"] == "moments"]


def test_the_picture_is_judged_by_what_it_shows():
    # a victim base image is protected whatever is said over it; a suspect or scene image is not,
    # even when a family word is in the narration
    v = _ctx_project(["The case went to trial in the spring."], asset="BASE-V--portrait--01.jpg")
    assert _scores(v)["scene"][0] >= sound.SENSITIVE_AT
    s_ = _ctx_project(["His mother was in the courtroom."], asset="BASE-S--court+2026--04.jpg")
    assert _scores(s_)["scene"][0] < sound.SENSITIVE_AT
    # a personal photograph named in the scene: protected; a document about a family member: not
    ph = _ctx_project(["The case went to trial."], title="Family photo of Maurco smiling")
    assert _scores(ph)["scene"][0] >= sound.SENSITIVE_AT
    doc = _ctx_project(["The car was traced."], title="Registration record — owner: Jackson's mother")
    assert _scores(doc)["scene"][0] < sound.SENSITIVE_AT
    # every decision says why
    assert _scores(ph)["why_scene"][0] and _scores(v)["why_scene"][0]


# ------------------------------------------------------------------ v0.4.57 sync through edits

def _times(p, data):
    placed, gone = sound.resolve(p, data)
    return {r["id"]: r for r in placed}, gone


def test_sounds_stay_in_sync_through_edits_moves_shortening_and_replacement(data, tmp_path):
    sc = [{"id": f"s{k}", "title": f"Scene {k}", "chapter": "CHAPTER 2 — THE SEARCH", "duration": 8.0, "narration": "",
           **({"transition": "slide-left", "transition_duration": 0.6} if k else {})} for k in range(4)]
    g = gitem(start=1.0, end=5.5, lines=[{"text": "Phone records placed him near the scene", "at": 2.0},
                                         {"text": "Video showed the car on Nebraska Avenue", "at": 3.5}])
    p = proj(sc, items=[g])
    base, _ = _times(p, data)
    tr = {r["label"]: r for r in base.values() if r["kind"] == "transitions"}
    assert tr["Transition into Scene 1"]["t"] == pytest.approx(8.0 + 0.3, abs=1e-4)  # the middle of the slide

    # shorten a scene: every later cut (and its sound) moves by exactly the frames removed
    p2 = json.loads(json.dumps(p))
    p2["scenes"][1]["duration"] = 6.5  # (later whooshes stay further apart than the 5 s spacing)
    moved, _ = _times(p2, data)
    for k, r in base.items():
        if r["kind"] == "transitions" and r["t"] > 16:
            assert moved[k]["t"] == pytest.approx(r["t"] - 1.5, abs=1e-4), r["label"]
    # the graphic before the cut is untouched
    for k, r in base.items():
        if r["kind"] == "motion":
            assert moved[k]["t"] == r["t"]

    # a longer transition: its sound stays on the middle of it
    p3 = json.loads(json.dumps(p))
    p3["scenes"][2]["transition_duration"] = 1.2
    longer, _ = _times(p3, data)
    r = next(x for x in longer.values() if x["label"] == "Transition into Scene 2")
    assert r["t"] == pytest.approx(16.0 + 0.6, abs=1e-4)

    # replace the transition: the sound is replaced to match the new movement, at the new middle
    p4 = json.loads(json.dumps(p))
    p4["scenes"][3]["transition"] = "slide-up"
    rep, _ = _times(p4, data)
    r = next(x for x in rep.values() if x["label"] == "Transition into Scene 3")
    assert r["sound"] == "whoosh-dir-up" and r["t"] == pytest.approx(24.3, abs=1e-4)
    p4["scenes"][3]["transition"] = "cut"
    assert not any(x["label"] == "Transition into Scene 3" for x in _times(p4, data)[0].values())

    # reorder scenes: a transition's sound belongs to its scene and goes where the scene goes
    p5 = json.loads(json.dumps(p))
    p5["scenes"] = [p5["scenes"][0], p5["scenes"][2], p5["scenes"][1], p5["scenes"][3]]
    re_, _ = _times(p5, data)
    assert {x["label"]: round(x["t"], 3) for x in re_.values() if x["kind"] == "transitions"}["Transition into Scene 2"] == pytest.approx(8.3)

    # edit a line's text and its timing: its sound follows the line's new first frame
    p6 = json.loads(json.dumps(p))
    p6["motion"]["items"][0]["lines"][1] = {"text": "A neighbour's camera caught the car", "at": 4.25}
    p6["motion"]["items"][0] = motion.normalise_item(p6["motion"]["items"][0])
    ed, _ = _times(p6, data)
    line2 = next(e for e in sound.events(p6) if e["label"].startswith("Line 2"))
    assert next(x for x in ed.values() if x["label"].startswith("Line 2"))["t"] == pytest.approx(line2["t"], abs=1e-4)
    assert line2["t"] > next(e for e in sound.events(p) if e["label"].startswith("Line 2"))["t"] + 0.5

    # change the animation (reveal -> typed): clicks give way to keys on each typed character
    p7 = json.loads(json.dumps(p))
    p7["motion"]["items"][0]["enter"] = "type"
    p7["motion"]["items"][0] = motion.normalise_item(p7["motion"]["items"][0])
    ty, _ = _times(p7, data)
    assert any(x["keys"] for x in ty.values()) and not any(x["label"].startswith("Line") for x in ty.values())

    # your own edits ride along: a whole-graphic change and a hand-moved sound follow a moved graphic
    eff, _ = sound.effective(p)
    mine = [dict(i, gain=-9.0, edited=True) for i in eff if i["anchor"].startswith("mg:g1:")]
    mine[0] = dict(mine[0], offset=0.125)
    p8 = json.loads(json.dumps(p))
    p8["sound"] = {"enabled": True, "items": mine}
    before, _ = _times(p8, data)
    p8["motion"]["items"][0].update(start=2.0, end=6.5, lines=[{**ln, "at": ln["at"] + 1.0} for ln in p8["motion"]["items"][0]["lines"]])
    after, gone = _times(p8, data)
    assert not gone
    for i in mine:
        assert after[i["id"]]["t"] == pytest.approx(before[i["id"]]["t"] + 1.0, abs=1 / 24 + 1e-6)
        assert after[i["id"]]["gain"] == before[i["id"]]["gain"]
    # ...and the stem really has them there (not only the plan): sample-exact against the waveform
    total = sum(s["duration"] for s in p8["scenes"])
    path, placed, _ = sound.stem(p8, data, total, tmp_path)
    st = pcm(path)
    r = after[mine[0]["id"]]
    w, sync = sfxlib.synth(r["sound"])
    w = w[0][: int(0.2 * 48000)]
    start = int(round((r["t"] - sync) * 48000))
    seg = st[start - 960: start + 960 + len(w)]
    assert abs(int(np.argmax(np.correlate(seg, w, mode="valid"))) - 960) <= 1


def test_preview_ducking_runs_one_job_per_project_and_drops_obsolete_ones(tmp_path, monkeypatch):
    """v0.4.57 On a long timeline the curve takes a while (the export's loudnorm): an edit while it is
    being made stops the obsolete job instead of piling up FFmpeg runs; other projects are untouched."""
    import sys
    import time

    ones = "import sys,time; time.sleep({}); sys.stdout.buffer.write(b'\\x00\\x00\\x80?' * 2000)"
    jobs = {"A": 30, "B": 0, "C": 0.5}
    monkeypatch.setattr(sound, "_duck_job", lambda p: ([sys.executable, "-c", ones.format(jobs[p["v"]])], p["v"] + p["id"]))
    assert sound.duck_curve({"id": "p1", "v": "A"}, tmp_path)["status"] == "working"
    assert sound.duck_curve({"id": "p2", "v": "C"}, tmp_path)["status"] == "working"  # another project
    for _ in range(100):
        if "p1" in sound._DUCK_PROC:
            break
        time.sleep(0.05)
    slow = sound._DUCK_PROC["p1"][1]
    t = time.time()
    r = sound.duck_curve({"id": "p1", "v": "B"}, tmp_path, wait=True)  # the timeline was edited
    assert r["status"] == "ready" and len(r["gain"]) > 0
    assert slow.wait(timeout=5) is not None and time.time() - t < 10  # the obsolete job was stopped
    for _ in range(100):
        if "Ap1" not in sound._DUCK_BUSY:
            break
        time.sleep(0.05)
    assert "Ap1" not in sound._DUCK_FAILED  # stopped, not failed: it is made again if you undo
    assert sound.duck_curve({"id": "p2", "v": "C"}, tmp_path, wait=True)["status"] == "ready"
    assert sound.duck_curve({"id": "p1", "v": "A"}, tmp_path)["status"] == "working"  # undo: made again
    sound.duck_curve({"id": "p1", "v": "B"}, tmp_path)  # redo: the cached curve, and A stops again


def test_each_motion_graphics_template_has_its_own_coordinated_sound_palette(data):
    """v0.4.58 A template sounds like itself (a family per template, shaped by the actual entrance /
    exit animation, layout and kind of line); two graphics of one template are related, not identical."""
    def g(gid, start, **kw):
        return gitem(id=gid, start=start, end=start + 8.0, **kw)
    lines3 = [{"text": "Phone records placed him near the scene", "at": 2.0}, {"text": "Video showed the car", "at": 3.5},
              {"text": "A receipt eleven minutes later", "at": 5.0}]
    shift = lambda ls, s: [dict(x, at=x["at"] + s) for x in ls]
    items = [
        g("fa", 1.0, lines=shift(lines3, 0)),                                   # findings
        g("fb", 41.0, lines=shift(lines3, 40)),                                 # findings again
        g("fs", 81.0, lines=shift(lines3, 80), enter="slide", exit="slide"),    # slides in and out
        g("tl", 121.0, template="timeline", layout="horizontal",
          lines=[dict(x, label=f"MARCH {k + 3}") for k, x in enumerate(shift(lines3, 120))]),
        g("cx", 161.0, template="contrast", layout="rows",
          lines=[{"text": "I was home all night", "kind": "statement", "at": 162.0},
                 {"text": "His phone pinged two miles away", "kind": "finding", "at": 164.0},
                 {"text": "His car was on camera at 11:52", "kind": "finding", "at": 165.5}]),
        g("lg", 201.0, template="legal", layout="list",
          lines=[{"text": "Charged with murder", "label": "CHARGED", "at": 202.0}, {"text": "Jury trial", "label": "TRIAL", "at": 203.5}]),
    ]
    scenes = [{"id": f"s{k}", "title": "", "chapter": "CHAPTER 3 — THE EVIDENCE", "duration": 20.0, "narration": ""} for k in range(12)]
    placed, _ = sound.resolve(proj(scenes, items=items), data)
    at = {"fa": "0:01", "fb": "0:41", "fs": "1:21", "tl": "2:01", "cx": "2:41", "lg": "3:21"}
    by = {gid: [r for r in placed if r["label"].endswith(f"graphic at {m}")] for gid, m in at.items()}
    fam = lambda gid, word: [r["sound"] for r in by[gid] if r["label"].startswith(word)]
    cat = lambda sid: sfxlib.BY_ID[sid][1]
    # findings: mechanical clicks on every line, one sound per graphic; the next findings graphic rotates
    la, lb = fam("fa", "Line"), fam("fb", "Line")
    assert len(la) == 3 and all(x.startswith("click-mech-") for x in la + lb)
    assert all(a != b for a, b in zip(la, la[1:])), la  # never the identical click twice in a row
    assert lb[0] != la[0]  # the next findings graphic starts on another variation
    lv = [r["gain"] for r in by["lg"] if r["label"].startswith("Legal step")]
    assert len(set(lv)) == len(lv), lv  # the steady legal steps are accented, not one identical hit
    assert all("dir-" not in s for s in fam("fa", "Entrance") + fam("fb", "Entrance"))  # nothing moves sideways: no directional air
    assert cat(fam("fa", "Divider")[0]) == "tonal-sweep" and "up" in fam("fa", "Divider")[0]
    # the animation decides the movement: slides in from the right -> leftward; slides out -> rightward
    assert fam("fs", "Entrance") == ["whoosh-dir-l"] and fam("fs", "Exit") in ([], ["whoosh-dir-r"])
    # timeline: travel along the time axis, a tick on each date
    assert fam("tl", "Entrance") == ["whoosh-dir-r"] and [cat(s) for s in fam("tl", "Diagram marker")] == ["tick"] * 3
    # contradiction: soft statement, a low pulse where the record contradicts it, firmer record after
    assert cat(fam("cx", "Entrance")[0]) == "reverse-whoosh" and "down" in fam("cx", "Divider")[0]
    assert fam("cx", "Statement")[0] in ("click-muted-1", "click-muted-2")
    assert cat(fam("cx", "Contradiction")[0]) == "pulse" and fam("cx", "Record") == ["click-muted-3"]
    # legal: the document, the heavy click on each step
    assert cat(fam("lg", "Document")[0]) == "document" and set(fam("lg", "Legal step")) == {"click-mech-3"}
    # and the templates do not share their line sound
    lines_of = {gid: {s for r in by[gid] for s in [r["sound"]] if r["kind"] in ("motion", "diagrams") and not r["label"].startswith(("Entrance", "Exit", "Divider"))}
                for gid in ("fa", "tl", "cx", "lg")}
    for a in lines_of:
        for b in lines_of:
            assert a == b or not (lines_of[a] & lines_of[b]), (a, b)
