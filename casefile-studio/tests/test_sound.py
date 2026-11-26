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
    # related elements share one sound; unrelated ones rotate variations
    items, _ = sound.plan(proj(items=[gitem(lines=[{"text": f"Line number {k} of the findings", "at": 2 + k} for k in range(4)])]),
                          {"enabled": True, "density": 1.0})
    lines = [it for it in items if it["label"].startswith("Line")]
    assert len(lines) >= 3 and len({it["sound"] for it in lines}) == 1


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
