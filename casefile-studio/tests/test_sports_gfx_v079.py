"""v0.4.79 Sports on the Edit page: the editing guide builds the video (its clips, crops and auto-fit decide the
shots); the sports engine adds graphics as motion graphics on the Edit timeline, fills only the scenes without a
clip, and proposes the storytelling style (look, chapter transitions, an original music bed). Export is the usual
export, with the type behind the player where segmentation is available (mocked here: no model in CI)."""
from __future__ import annotations

import pathlib
import wave

import numpy as np
import pytest

import episode
import motion
import sfxlib
import sportsedit
import sportsgfx
from cinegfx.sports import matte as M
from cinegfx.sports import score
from cinegfx.timing import ffbin
from test_sports_edit_v078 import SCRIPT, import_text, make_project, wait_job


def scenes_for(client, pid, clip_first_only=True):
    p = client.get(f"/api/projects/{pid}").json()
    vid = next(a["id"] for a in p["assets"] if a["kind"] == "video")
    paras = SCRIPT.split("\n\n")
    scenes = [{"title": f"Part {i + 1}", "narration": t, "duration": d, "chapter": ["Intro", "Intro", "The night", "The night"][i],
               "asset_id": vid if (i == 0 or not clip_first_only) else None, "trim_start": [6.5, 0, 0, 4][i]}
              for i, (t, d) in enumerate(zip(paras, [2.5, 3.5, 6, 2.5]))]
    r = client.patch(f"/api/projects/{pid}", json={"scenes": scenes})
    assert r.status_code == 200, r.text
    return r.json(), vid


class FakeNet:
    """Stands in for the RVM model: the 'player' is the middle fifth of the picture."""
    id = "fake"

    def reset(self):
        return []

    def step(self, rgb, rec):
        h, w = rgb.shape[:2]
        a = np.zeros((h, w), np.float32)
        a[h // 5:, w * 2 // 5: w * 3 // 5] = 1
        return a, rec


@pytest.fixture
def fake_matte(monkeypatch):
    monkeypatch.setattr(M, "_has_ort", lambda: True)
    monkeypatch.setattr(M, "model_path", lambda: pathlib.Path("/nonexistent/fake.onnx"))
    monkeypatch.setattr(M, "_SESSION", FakeNet())


# ---------------------------------------------------------------- settings and eligibility
def test_settings_are_only_the_style():
    assert sportsedit.normalise(None) == {"style": "auto"}
    assert sportsedit.normalise({"style": "high_energy"}) == {"style": "high_energy"}
    with pytest.raises(ValueError):
        sportsedit.normalise({"style": "nope"})
    assert sportsedit.settings({"sports_edit": {"style": "bogus"}}) == {"style": "auto"}
    assert sportsedit.eligible({"niche": "football"}) and sportsedit.eligible({"niche": "wrestling"})
    assert not sportsedit.eligible({"niche": "truecrime"}) and not sportsedit.eligible({})


def test_every_sound_the_graphics_cue_is_in_the_library():
    import re
    from cinegfx.sports import families
    src = open(families.__file__).read()
    ids = set(re.findall(r'Cue\([^,]+, "([a-z0-9-]+)"', src))
    assert {"sp-glitch", "sp-scramble"} <= ids
    for sid in ids:
        assert sid in sfxlib.BY_ID, sid                 # the Edit page's sound design plays every one of them
    for sid in ("sp-glitch", "sp-scramble"):
        x, _ = sfxlib.synth(sid)
        assert x.shape[0] == 2 and 0 < np.abs(x).max() <= 1


def test_true_crime_projects_are_untouched(isolated):
    client, root = isolated
    pid = client.post("/api/projects", json={"title": "A case", "mode": "script", "target_minutes": 20}).json()["id"]
    v = client.get(f"/api/projects/{pid}/sportsedit").json()
    assert v["eligible"] is False and "fill" not in v
    assert client.patch(f"/api/projects/{pid}/sportsedit", json={"style": "emotional"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/motion/suggest", json={"engine": "sports"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/motion/draft", json={"template": "sports", "start": 0, "end": 5}).status_code == 422
    for path in ("fill", "music", "analyse"):
        assert client.post(f"/api/projects/{pid}/sportsedit/{path}", json={}).status_code == 422
    assert client.post(f"/api/projects/{pid}/sportsedit/style", json={"parts": ["look"]}).status_code == 422
    assert "sports_edit" not in client.get(f"/api/projects/{pid}").json()


# ---------------------------------------------------------------- the item
def test_item_shape_and_timing():
    from cinegfx.sports import semantics as S
    el = S.Element("impact", 10.0, 12.5, {"value": "4", "t": 10.2, "label": "GOALS", "label_t": 10.6}, "a number said aloud")
    it = sportsgfx.make_item(el)
    assert it["template"] == "sports" and it["status"] == "suggested" and it["start"] == 10.0
    assert it["data"]["t"] == pytest.approx(0.2)          # stored relative to the start: moving it keeps it whole
    assert it["end"] == round(10.0 + sportsgfx.frames_of(it) / sportsgfx.FPS, 3)
    assert motion.normalise_item(it) == it
    assert motion.normalise_item({**it, "family": "pie-chart"}) is None
    back = sportsgfx.element({**it, "start": 20.0})
    assert back.t_in == 20.0 and back.data["t"] == pytest.approx(20.2)
    assert all(c["t"] >= 0 for c in sportsgfx.cues(it))


# ---------------------------------------------------------------- the Edit-page flow
def test_edit_page_flow(isolated):
    client, root = isolated
    import app as server
    pid = make_project(client, root)
    import_text(client, pid)
    p, vid = scenes_for(client, pid)
    v = client.get(f"/api/projects/{pid}/sportsedit").json()
    assert v["eligible"] and v["narration"]["exact"] and v["narration"]["found"] >= 2
    assert v["fill"]["gaps"] == 3 and not v["fill"]["proposals"] and v["fill"]["waiting"]
    assert v["resolved"]["key"] in sportsedit.P.STYLES
    # graphics: suggested on the timeline as motion graphics
    r = client.post(f"/api/projects/{pid}/motion/suggest", json={"engine": "sports"})
    assert r.status_code == 200 and r.json()["added"] >= 2
    items = r.json()["project"]["motion"]["items"]
    assert all(x["template"] == "sports" and x["status"] == "suggested" for x in items)
    assert "LIONEL MESSI" in " ".join(x["text"] for x in items)
    # suggesting again replaces only the sports suggestions; an approved one stays and is not doubled
    m = r.json()["project"]["motion"]
    m["items"][0]["status"] = "approved"
    client.patch(f"/api/projects/{pid}", json={"motion": m})
    again = client.post(f"/api/projects/{pid}/motion/suggest", json={"engine": "sports"}).json()["project"]["motion"]["items"]
    assert len(again) == len(items) and sum(x["status"] == "approved" for x in again) == 1
    # a graphic from a passage, and a family the passage does not support says so
    d = client.post(f"/api/projects/{pid}/motion/draft", json={"template": "sports", "start": 5.0, "end": 12.0, "family": "numbered"})
    assert d.status_code == 200 and d.json()["item"]["family"] == "numbered" and d.json()["item"]["status"] == "draft"
    bad = client.post(f"/api/projects/{pid}/motion/draft", json={"template": "sports", "start": 0.0, "end": 1.5, "family": "cumulative"})
    assert bad.status_code == 422 and "Nothing in this passage" in bad.json()["detail"]
    # preview frames over the footage
    pl = client.post(f"/api/projects/{pid}/motion/plan", json={"item": items[0]})
    assert pl.status_code == 200 and pl.json()["unique"] > 5
    f = client.get(f"/api/motion/{pl.json()['hash']}/3.webp")
    assert f.status_code == 200 and f.headers["content-type"] == "image/webp"

    # empty scenes: analyse (a job), then the proposals are for the empty scenes only
    j = wait_job(server, client.post(f"/api/projects/{pid}/sportsedit/analyse").json()["job_id"])
    assert j["status"] == "done", j
    v = client.get(f"/api/projects/{pid}/sportsedit").json()
    props = v["fill"]["proposals"]
    first = client.get(f"/api/projects/{pid}").json()["scenes"][0]
    assert len(props) == 3 and first["id"] not in {x["scene_id"] for x in props}
    assert all(x["why"] and "slowed" not in x["why"] for x in props)
    photo = next(x for x in props if x["photo"])
    assert "camp" in photo["why"]                       # the photo named for what is said there
    # fill one scene, then the rest; the guide's own clip is never touched
    one = client.post(f"/api/projects/{pid}/sportsedit/fill", json={"scene_ids": [props[0]["scene_id"]]})
    assert one.status_code == 200 and one.json()["filled"] == 1
    rest = client.post(f"/api/projects/{pid}/sportsedit/fill", json={}).json()
    assert rest["filled"] == 2
    sc = rest["project"]["scenes"]
    assert sc[0]["asset_id"] == vid and sc[0]["trim_start"] == 6.5 and "sports_fill" not in sc[0]
    assert all(s["asset_id"] and sportsedit.is_fill(s) for s in sc[1:])
    assert next(s for s in sc if s["id"] == photo["scene_id"])["motion"] == "slow-zoom"
    assert client.post(f"/api/projects/{pid}/sportsedit/fill", json={}).status_code == 422   # nothing left to fill
    assert client.get(f"/api/projects/{pid}/sportsedit").json()["filled"] == 3
    # undo puts the last fill back
    client.post(f"/api/projects/{pid}/undo")
    assert sum(1 for s in client.get(f"/api/projects/{pid}").json()["scenes"] if not s["asset_id"]) == 2

    # the style: look and chapter transitions (only where none is chosen)
    client.patch(f"/api/projects/{pid}/sportsedit", json={"style": "historical"})
    v = client.get(f"/api/projects/{pid}/sportsedit").json()
    assert v["style"]["look"][1] == "archive" and len(v["style"]["transitions"]) == 1
    assert v["style"]["transitions"][0]["index"] == 2 and v["style"]["transitions"][0]["to"] == "dissolve"
    r = client.post(f"/api/projects/{pid}/sportsedit/style", json={"parts": ["look", "transitions"]}).json()
    assert r["look"] and r["transitions"] == 1
    assert r["project"]["look"] == "archive" and r["project"]["scenes"][2]["transition"] == "dissolve"
    assert client.get(f"/api/projects/{pid}/sportsedit").json()["style"]["transitions"] == []
    assert client.post(f"/api/projects/{pid}/sportsedit/style", json={"parts": ["music"]}).status_code == 422

    # the music: an original bed for the whole timeline, set as the project's music
    j = wait_job(server, client.post(f"/api/projects/{pid}/sportsedit/music").json()["job_id"])
    assert j["status"] == "done", j.get("message")
    p = client.get(f"/api/projects/{pid}").json()
    music = next(a for a in p["assets"] if a["id"] == p["music_id"])
    assert music["kind"] == "audio" and music["generated"] and music["sports_score"]["style"] == "historical"
    with wave.open(str(server.renderer.asset_path(music)), "rb") as w:
        assert w.getnchannels() == 2 and w.getnframes() / w.getframerate() == pytest.approx(15.5, abs=0.05)


def test_music_can_be_stopped(isolated, monkeypatch):
    client, root = isolated
    import app as server
    pid = make_project(client, root)
    import_text(client, pid)
    scenes_for(client, pid)
    real = score.bed_wav

    def slow(*a, cancelled=None, **k):                 # stop asked for before the first piece is written
        server.JOBS[next(iter(j for j in server.JOBS if server.JOBS[j]["kind"] == "sportsedit"))]["cancel_requested"] = True
        return real(*a, cancelled=cancelled, **k)
    monkeypatch.setattr(score, "bed_wav", slow)
    j = wait_job(server, client.post(f"/api/projects/{pid}/sportsedit/music").json()["job_id"])
    assert j["status"] == "cancelled" or "Stopped" in (j.get("result") or {}).get("summary", "")
    p = client.get(f"/api/projects/{pid}").json()
    assert not p.get("music_id") and not list((server.DATA / "media" / pid).glob("*.f32"))


def test_a_fill_survives_a_guide_rebuild_and_the_guides_clip_wins():
    s = {"id": "a" * 16, "guide_cue_id": "C04", "audio_start": 12.0, "asset_id": None}
    p = {"assets": [{"id": "v1"}, {"id": "v2"}], "episode": {"guide": {"text": "x"}, "overrides": {}}, "scenes": [dict(s)]}
    n = sportsedit.apply_fill(p, [{"scene_id": s["id"], "asset_id": "v1", "in": 3.0, "photo": False, "why": "close", "kind": "close", "name": "m.mp4"}])
    assert n == 1 and p["scenes"][0]["asset_id"] == "v1"
    key = episode.scene_key(s)
    assert p["episode"]["overrides"][key]["sports_fill"]["asset_id"] == "v1"
    rebuilt = [dict(s)]                                  # the guide still has no clip there: the fill is kept
    episode.apply_overrides(p, rebuilt)
    assert rebuilt[0]["asset_id"] == "v1" and rebuilt[0]["trim_start"] == 3.0 and sportsedit.is_fill(rebuilt[0])
    with_clip = [{**s, "asset_id": "v2", "trim_start": 0.5}]   # the guide supplies its own clip: it wins
    episode.apply_overrides(p, with_clip)
    assert with_clip[0]["asset_id"] == "v2" and with_clip[0]["trim_start"] == 0.5 and "sports_fill" not in with_clip[0]
    p["episode"]["overrides"][key]["asset_id"] = "v2"   # you chose another picture there since: yours, not a fill
    mine = [dict(s)]
    episode.apply_overrides(p, mine)
    assert mine[0]["asset_id"] == "v2" and not sportsedit.is_fill(mine[0])


# ---------------------------------------------------------------- export
def frame_at(path, t):
    import subprocess
    raw = subprocess.run([ffbin(), "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(480, 854, 3).astype(int)


def export(client, server, pid):
    r = client.post(f"/api/projects/{pid}/render", json={"resolution": "480p", "draft": True})
    assert r.status_code == 200, r.text
    j = wait_job(server, r.json()["job_id"], 600)
    assert j["status"] == "done", j.get("message")
    return server.DATA / "exports" / j["result"]["id"] / "documentary.mp4"


def approve_all(client, pid):
    p, _ = scenes_for(client, pid, clip_first_only=False)
    m = client.post(f"/api/projects/{pid}/motion/suggest", json={"engine": "sports"}).json()["project"]["motion"]
    m["enabled"] = True
    for it in m["items"]:
        it["status"] = "approved"
    assert client.patch(f"/api/projects/{pid}", json={"motion": m}).status_code == 200
    return m["items"]


def test_export_puts_the_type_behind_the_player(isolated, fake_matte, monkeypatch):
    client, root = isolated
    import app as server
    monkeypatch.setenv("CASEFILE_X264_PRESET", "ultrafast")
    pid = make_project(client, root)
    import_text(client, pid)
    items = approve_all(client, pid)
    name = next(x for x in items if x["family"] == "name")
    out = export(client, server, pid)
    assert list((server.DATA / "cache" / "sportsmatte").glob("scene-*.npy"))   # the player found in the export's own picture
    behind = frame_at(out, name["start"] + 1.8)
    # the same export without the type: where the 'player' stands the picture is the footage
    m = client.get(f"/api/projects/{pid}").json()["motion"]
    m["enabled"] = False
    client.patch(f"/api/projects/{pid}", json={"motion": m})
    plain = frame_at(export(client, server, pid), name["start"] + 1.8)
    W = plain.shape[1]
    centre = (slice(150, 470), slice(W * 2 // 5 + 25, W * 3 // 5 - 25))
    outside = np.abs(behind - plain).sum(axis=2) > 60
    assert outside.mean() > 0.02                         # the type is on screen
    assert np.abs(behind[centre] - plain[centre]).mean() < 12   # but not over the player


def test_export_without_segmentation_puts_the_type_in_front(isolated, monkeypatch):
    client, root = isolated
    import app as server
    monkeypatch.setenv("CASEFILE_X264_PRESET", "ultrafast")
    monkeypatch.setattr(M, "available", lambda: False)
    pid = make_project(client, root)
    import_text(client, pid)
    approve_all(client, pid)
    out = export(client, server, pid)
    assert out.stat().st_size > 10000
    assert not (server.DATA / "cache" / "sportsmatte").exists() or not list((server.DATA / "cache" / "sportsmatte").glob("scene-*.npy"))


def test_sound_design_plays_the_graphics_cues(isolated):
    client, root = isolated
    import sound
    pid = make_project(client, root)
    import_text(client, pid)
    approve_all(client, pid)
    p = client.get(f"/api/projects/{pid}").json()
    ev = sound.events(p)
    mine = [e for e in ev if "graphic at" in (e.get("label") or "")]
    assert mine and all(e["sid"] in sfxlib.BY_ID for e in mine)


# ---------------------------------------------------------------- the music bed
def test_bed_wav_matches_the_in_memory_bed(tmp_path):
    secs = [(0.0, 6.0, "nostalgic"), (6.0, 14.0, "peak"), (14.0, 20.0, "triumph")]
    x = score.bed(20.0, secs)
    path = score.bed_wav(tmp_path / "b.wav", 20.0, secs)
    with wave.open(str(path), "rb") as w:
        y = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2).T.astype(np.float32) / 32767
    n = min(x.shape[1], y.shape[1]) - score.SR          # the last second fades differently
    a, b = x[:, :n] / np.abs(x).max(), y[:, :n] / np.abs(y).max()
    assert np.abs(a - b).mean() < 2e-3
