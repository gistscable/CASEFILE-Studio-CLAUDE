"""v0.4.58 Background music: placement, loops and crossfades, the same in the preview and the export;
the timeline is authoritative and nothing is copied."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

import music

ROOT = Path(__file__).resolve().parent.parent
FPS = 24


def scenes_of(n, length, chapters=None):
    return [{"id": f"s{k}", "duration": length, "chapter": (chapters[k] if chapters else "")} for k in range(n)]


def covered(lay, total, step=0.05):
    """The share of the timeline (sampled) where the music is heard, and the min envelope inside runs
    away from their fades."""
    ts = np.arange(0, total, step)
    g = np.array([music.gain_at(lay, t) for t in ts])
    return ts, g


# ------------------------------------------------------------------ the layout

def test_a_three_minute_track_loops_seamlessly_under_a_25_minute_documentary():
    total = 25 * 60.0
    lay = music.layout({"crossfade": 2.0}, 180.0, total, scenes_of(150, 10.0))
    (run,) = lay["runs"]
    assert run["at"] == 0 and run["end"] == pytest.approx(total)  # the timeline's length, exactly
    x = lay["crossfade"]
    assert x == 2.0
    iters = run["iters"]
    assert len(iters) == 1 + math.ceil((total - 180) / 178)  # 9
    for a, b in zip(iters, iters[1:]):
        assert b["at"] == pytest.approx(a["at"] + 178.0)  # a pass every (part - crossfade)
        assert a["at"] + a["len"] - b["at"] == pytest.approx(x)  # overlapping by the crossfade
    assert iters[-1]["at"] + iters[-1]["len"] == pytest.approx(total)
    # equal power: no dip or bump at any seam (away from the fades of the whole stretch)
    ts, g = covered(lay, total, 0.01)
    inner = (ts > 2.0) & (ts < total - 2.5)
    assert g[inner].min() == pytest.approx(1.0, abs=1e-6) and g[inner].max() == pytest.approx(1.0, abs=1e-6)


def test_a_track_longer_than_the_documentary_is_cut_not_edited():
    lay = music.layout({}, 40 * 60.0, 25 * 60.0, scenes_of(150, 10.0))
    (run,) = lay["runs"]
    assert run["iters"] == [{"at": 0.0, "src": 0.0, "len": 1500.0}]
    assert run["end"] == 1500.0


def test_custom_start_and_end_choose_the_part_of_the_track():
    lay = music.layout({"start": 12.5, "end": 72.5, "crossfade": 1.0}, 180.0, 300.0)
    assert lay["part"] == [12.5, 72.5]
    assert all(it["src"] == 12.5 for it in lay["runs"][0]["iters"])
    assert all(it["len"] <= 60.0 for it in lay["runs"][0]["iters"])
    # an end beyond the track, or before the start, falls back to the track's end
    assert music.layout({"start": 10, "end": 999}, 100.0, 50.0)["part"] == [10.0, 100.0]
    assert music.layout({"start": 10, "end": 5}, 100.0, 50.0)["part"] == [10.0, 100.0]


def test_loop_off_and_once_play_the_part_once_and_never_lengthen_the_timeline():
    off = music.layout({"loop": False}, 180.0, 600.0)
    assert off["runs"][0]["iters"] == [{"at": 0.0, "src": 0.0, "len": 180.0}] and off["runs"][0]["end"] == 180.0
    once = music.layout({"mode": "once", "offset": 500.0}, 180.0, 600.0)
    assert once["runs"][0]["at"] == 500.0 and once["runs"][0]["end"] == 600.0  # cut at the end of the documentary
    assert once["crossfade"] == 0.0


def test_a_range_and_chosen_chapters_or_scenes():
    sc = scenes_of(6, 10.0, ["A", "A", "B", "B", "C", "C"])
    rng = music.layout({"mode": "range", "offset": 15.0, "until": 45.0}, 20.0, 60.0, sc)
    assert [(r["at"], r["end"]) for r in rng["runs"]] == [(15.0, 45.0)]
    ch = music.layout({"mode": "scenes", "chapters": ["B"], "scenes": ["s5"]}, 100.0, 60.0, sc)
    assert [(r["at"], r["end"]) for r in ch["runs"]] == [(20.0, 40.0), (50.0, 60.0)]
    # each stretch starts the part again, with its own fades
    assert all(r["iters"][0]["src"] == 0.0 for r in ch["runs"])
    nothing = music.layout({"mode": "scenes"}, 100.0, 60.0, sc)
    assert nothing["runs"] == []


def test_the_preview_and_the_export_lay_the_music_out_identically():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    sc = scenes_of(8, 7.3, ["A", "A", "B", "B", "B", "C", "C", "C"])
    cases = [
        ({"crossfade": 2.0}, 180.0, 1500.0),
        ({"start": 3.25, "end": 41.7, "crossfade": 3.3, "fade_in": 4, "fade_out": 0.5}, 60.0, 300.0),
        ({"mode": "range", "offset": 10.0, "until": 50.0, "crossfade": 1.0}, 12.0, 58.4),
        ({"mode": "once", "offset": 5.0}, 30.0, 58.4),
        ({"loop": False}, 30.0, 58.4),
        ({"mode": "scenes", "chapters": ["B"], "scenes": ["s7"], "crossfade": 0.7}, 6.0, 58.4),
        ({"crossfade": 9.0}, 5.0, 58.4),  # crossfade longer than half the part: limited
        ({}, 2000.0, 58.4),
    ]
    script = (
        "import { musicLayout, musicGainAt } from './web/src/music.js';"
        "const cases = JSON.parse(process.argv[1]); const sc = JSON.parse(process.argv[2]);"
        "const out = cases.map(([m, tr, tot]) => { const lay = musicLayout(m, tr, tot, sc);"
        " const g = []; for (let t = 0; t < tot; t += tot / 997) g.push(musicGainAt(lay, t)); return [lay, g]; });"
        "console.log(JSON.stringify(out));"
    )
    res = subprocess.run([node, "--input-type=module", "-e", script, json.dumps(cases), json.dumps(sc)],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    js = json.loads(res.stdout)
    for (m, tr, tot), (lay_js, g_js) in zip(cases, js):
        lay = music.layout(m, tr, tot, sc)
        assert _close(lay, lay_js), (m, lay, lay_js)
        ts = [k * tot / 997 for k in range(len(g_js))]
        g_py = [music.gain_at(lay, t) for t in ts]
        assert max(abs(a - b) for a, b in zip(g_py, g_js)) < 1e-9, m


def _close(a, b):
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-9
    return a == b


# ------------------------------------------------------------------ the export

def _render_bed(lay, path, total, out):
    args, f = music.filters(lay, path, 0, total)
    cmd = ["ffmpeg", "-v", "error", "-y", *args, "-filter_complex", ";".join(f), "-map", "[mus]", "-c:a", "pcm_f32le", str(out)]
    subprocess.run(cmd, check=True, timeout=600)
    return cmd


def _pcm(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, "<f4")


@pytest.fixture
def track(tmp_path):
    """A 3-minute 'music' file: noise (so a seam would show as a level change) with a marker tone
    whose pitch rises through the track (so the position in the track can be read back)."""
    p = tmp_path / "track.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=180:a=0.2:c=pink:seed=7",
                    "-f", "lavfi", "-i", "aevalsrc='0.2*sin(2*PI*(200*t+2*t*t/2))':s=48000:d=180",
                    "-filter_complex", "[0][1]amix=2:normalize=0,aformat=channel_layouts=stereo[o]", "-map", "[o]",
                    "-c:a", "libmp3lame", "-b:a", "192k", str(p)], check=True)
    return p


def test_the_export_loops_by_reference_with_seamless_crossfades_and_the_exact_length(track, tmp_path):
    total = 25 * 60.0
    lay = music.layout({"crossfade": 2.0}, 180.0, total)
    out = tmp_path / "bed.wav"
    cmd = _render_bed(lay, track, total, out)
    # no copies, no intermediate files: every pass is the original file, read with -ss/-t
    assert cmd.count(str(track)) == len(lay["runs"][0]["iters"]) and "-stream_loop" not in cmd
    assert sorted(x.name for x in tmp_path.iterdir()) == ["bed.wav", "track.mp3"]
    x = _pcm(out)
    assert len(x) == round(total * 48000)  # the documentary's length, to the sample
    # the level is continuous across every seam (equal-power crossfade of the track's noise)
    win = 4800
    rms = lambda a: 20 * math.log10(float(np.sqrt(np.mean(a ** 2))) + 1e-12)
    ref = rms(x[60 * 48000:70 * 48000])
    for it in lay["runs"][0]["iters"][1:]:
        for c in np.arange(it["at"] - 1.0, it["at"] + 2.6, 0.1):  # through the 2 s crossfade
            i = int(c * 48000)
            assert abs(rms(x[i:i + win]) - ref) < 1.8, (it["at"], c)
    # and the export envelope follows the layout (fade in / out of the stretch)
    assert rms(x[: win // 4]) < ref - 15 and rms(x[-win // 4:]) < ref - 15


def test_many_short_passes_use_one_period_in_memory_and_match_the_reference_chain(track, tmp_path):
    total = 240.0
    m = {"start": 30.0, "end": 40.0, "crossfade": 1.0}
    lay = music.layout(m, 180.0, total)
    assert len(lay["runs"][0]["iters"]) > music.CHAIN_MAX  # 27 passes: the aloop path
    a = tmp_path / "aloop.wav"
    cmd = _render_bed(lay, track, total, a)
    assert "aloop" in " ".join(cmd) and cmd.count(str(track)) == 1
    old = music.CHAIN_MAX
    try:
        music.CHAIN_MAX = 999  # the same layout as a chain of references
        b = tmp_path / "chain.wav"
        _render_bed(lay, track, total, b)
    finally:
        music.CHAIN_MAX = old
    xa, xb = _pcm(a), _pcm(b)
    assert len(xa) == len(xb) == round(total * 48000)
    d = xa - xb
    assert 20 * math.log10(float(np.sqrt(np.mean(d ** 2))) / float(np.sqrt(np.mean(xb ** 2)))) < -30  # the same music


def test_the_music_sits_where_the_layout_says(track, tmp_path):
    sc = scenes_of(6, 10.0, ["A", "A", "B", "B", "C", "C"])
    total = 60.0
    lay = music.layout({"mode": "scenes", "chapters": ["B"], "fade_in": 0.5, "fade_out": 0.5}, 180.0, total, sc)
    out = tmp_path / "bed.wav"
    _render_bed(lay, track, total, out)
    x = _pcm(out)
    assert len(x) == round(total * 48000)
    rms = lambda s, e: float(np.sqrt(np.mean(x[int(s * 48000):int(e * 48000)] ** 2)))
    assert rms(1, 19) < 1e-6 and rms(41, 59) < 1e-6  # silent outside chapter B
    assert rms(21, 39) > 0.05


def test_a_full_export_with_narration_music_and_sound_effects_keeps_the_timeline(track, tmp_path, monkeypatch):
    """Narration, music under it (ducked), sound effects: the duration is the timeline's; the narration
    is untouched; the music is where the settings put it."""
    import renderer
    import storage
    from PIL import Image

    import episode

    monkeypatch.setattr(episode, "issues", lambda project: [])
    media = storage.DATA / "tmp-test-music"
    media.mkdir(parents=True, exist_ok=True)
    try:
        Image.new("RGB", (640, 360), (40, 40, 48)).save(media / "plate.png")
        voice = media / "voice.wav"
        gate = "0.3*sin(2*PI*1000*t)*gt(sin(2*PI*0.25*t)\\,0)"  # 2 s phrases, 2 s pauses
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc={gate}|{gate}:s=48000:d=20", str(voice)], check=True)
        shutil.copy(track, media / "music.mp3")
        assets = [{"id": "img", "kind": "image", "path": str(media / "plate.png"), "name": "plate.png", "width": 640, "height": 360},
                  {"id": "nar", "kind": "audio", "path": str(voice), "name": "voice.wav", "duration": 20.0},
                  {"id": "mus", "kind": "audio", "path": str(media / "music.mp3"), "name": "music.mp3", "duration": 180.0}]
        sc = [{"id": f"s{k}", "title": "", "narration": "", "duration": 5.0, "asset_id": "img", "motion": "none", "show_title": False,
               "chapter": "ONE" if k < 2 else "TWO", "audio_start": 5.0 * k, "audio_duration": 5.0} for k in range(4)]
        p = {"id": "5d00000000000058", "title": "music", "look": "natural", "captions": False, "music_volume": 0.3, "assets": assets,
             "scenes": sc, "narration_id": "nar", "music_id": "mus", "exports": [], "episode": {"guide": True, "plan": {"mode": "final"}},
             "music": {"mode": "scenes", "chapters": ["TWO"], "fade_in": 0.2, "fade_out": 0.2, "start": 10.0, "end": 14.0, "crossfade": 1.0},
             "sound": {"enabled": True, "items": [{"anchor": "t:12.0", "sound": "swell-2", "source": "manual", "gain": 0.0}]}}
        out = tmp_path / "doc.mp4"
        renderer.render(dict(p), {"resolution": "480p", "draft": True, "captions": False}, out, lambda *a: None, lambda: False)
        info = renderer.probe(out)
        assert abs(info["duration"] - 20.0) < 0.05
        x = _pcm(out)
        sr = 48000
        # the narration is there, as recorded (1 kHz phrases), in both halves
        def band(s, e, f):
            seg = x[int(s * sr):int(e * sr)]
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
            freqs = np.fft.rfftfreq(len(seg), 1 / sr)
            return float(spec[(freqs > f - 30) & (freqs < f + 30)].max())
        assert band(0.3, 1.7, 1000) > 100 and band(12.3, 13.7, 1000) > 100
        # no music in chapter ONE (0-10 s): the pauses are silent; music in chapter TWO's pauses
        pause_one = x[int(2.3 * sr):int(3.7 * sr)]
        pause_two = x[int(14.3 * sr):int(15.7 * sr)]
        assert float(np.sqrt(np.mean(pause_one ** 2))) < 0.002
        assert float(np.sqrt(np.mean(pause_two ** 2))) > 0.01
    finally:
        shutil.rmtree(media, ignore_errors=True)


def test_the_music_mix_never_delays_or_lifts_the_voices():
    """v0.4.58: every final mix uses the transparent limiter (no make-up gain, no look-ahead delay);
    the default alimiter moved the narration and soundbites 239 samples late when music played
    without effects."""
    import inspect
    import re

    import renderer

    src = inspect.getsource(renderer.render)
    assert not re.search(r"alimiter=limit=0\.95\[", src)
    assert "level=disabled" in renderer.SFX_LIMIT and "latency=1" in renderer.SFX_LIMIT
    assert src.count("{SFX_LIMIT}[aout]") >= 4


# ------------------------------------------------------------------ v0.4.59 chosen-scene music follows its scenes

def _sc(sid, start, length, **kw):
    return {"id": sid, "duration": length, "audio_start": start, "audio_duration": length, "title": sid.upper(), **kw}


def test_chosen_scene_music_follows_split_rebuilt_replaced_and_reordered_scenes():
    before = [_sc("a", 0, 10), _sc("b", 10, 10), _sc("c", 20, 10), _sc("d", 30, 10)]
    m = {"mode": "scenes", "scenes": ["b", "c"], "chapters": []}
    # reordered (ids kept): nothing to follow; the music moves with the scenes
    after = [before[2], before[0], before[1], before[3]]
    same, rep = music.follow_scenes(m, before, after)
    assert same["scenes"] == ["b", "c"] and rep == {"followed": [], "lost": []}
    assert music.stretches(same, 40, after) == [(0.0, 10.0), (20.0, 30.0)]  # c moved first, then b
    # split: the new right half of b plays b's narration -> it has b's music too
    split = [before[0], {**before[1], "duration": 4, "audio_duration": 4}, _sc("b2", 14, 6), before[2], before[3]]
    got, rep = music.follow_scenes(m, before, split)
    assert got["scenes"] == ["b", "c", "b2"] and rep["followed"] == ["b2"]
    assert music.stretches(got, 40, split) == [(10.0, 30.0)]  # b, b2 and c: one stretch, as before the split
    # rebuilt / replaced: c has a new id but plays the same narration window -> it keeps the music
    rebuilt = [before[0], before[1], _sc("c-new", 20, 10), before[3]]
    got, rep = music.follow_scenes(m, before, rebuilt)
    assert "c-new" in got["scenes"] and rep["lost"] == []
    assert music.stretches(got, 40, rebuilt) == music.stretches(m, 40, before)
    # a new scene inserted elsewhere (other narration) does not get it
    inserted = [before[0], _sc("new", 40, 5), before[1], before[2], before[3]]
    got, rep = music.follow_scenes(m, before, inserted)
    assert got["scenes"] == ["b", "c"]
    # deleted with no successor: reported (not silently dropped), id kept so an undo plays it again
    deleted = [before[0], before[2], before[3]]
    got, rep = music.follow_scenes(m, before, deleted)
    assert rep["lost"] == ["B"] and got["scenes"] == ["b", "c"]
    # a renamed chapter keeps its music; other modes are left alone
    ch = {"mode": "scenes", "scenes": [], "chapters": ["TWO"]}
    b2 = [dict(s, chapter="ONE" if k < 2 else "TWO") for k, s in enumerate(before)]
    a2 = [dict(s, chapter="ONE" if k < 2 else "THE TRIAL") for k, s in enumerate(before)]
    assert music.follow_scenes(ch, b2, a2)[0]["chapters"] == ["THE TRIAL"]
    assert music.follow_scenes({"mode": "whole", "scenes": ["b"]}, before, deleted)[0] == {"mode": "whole", "scenes": ["b"]}
    # soundbites follow by their clip window, never a narration scene
    bite = {"id": "i1", "duration": 6, "insert_audio": True, "asset_id": "clip", "trim_start": 30, "title": "BITE"}
    mi = {"mode": "scenes", "scenes": ["i1"], "chapters": []}
    got, rep = music.follow_scenes(mi, [before[0], bite], [before[0], dict(bite, id="i1-new"), _sc("x", 30, 6)])
    assert got["scenes"] == ["i1", "i1-new"]


def test_chosen_scene_music_survives_scene_edits_through_the_editor(isolated):
    client, _ = isolated
    pid = client.post("/api/projects", json={"title": "Music follows", "topic": "t"}).json()["id"]
    ids = ["%016x" % (k + 1) for k in range(4)]
    scenes = [{"id": ids[k], "title": f"S{k}", "chapter": "ONE", "narration": "", "duration": 10.0, "audio_start": 10.0 * k,
               "audio_duration": 10.0} for k in range(4)]
    p = client.patch(f"/api/projects/{pid}", json={"scenes": scenes}).json()
    assert [s["id"] for s in p["scenes"]] == ids  # the editor's ids are kept
    p = client.patch(f"/api/projects/{pid}", json={"music": {"mode": "scenes", "scenes": [ids[1]]}}).json()
    assert p["music"]["scenes"] == [ids[1]]
    # reorder: the same ids, the music moves with its scene
    p = client.patch(f"/api/projects/{pid}", json={"scenes": [p["scenes"][k] for k in (1, 0, 2, 3)]}).json()
    assert p["music"]["scenes"] == [ids[1]] and "music_follow" not in p
    # edit its text and length: still chosen
    sc = p["scenes"]
    sc[0] = dict(sc[0], narration="Edited", duration=12.0)
    p = client.patch(f"/api/projects/{pid}", json={"scenes": sc}).json()
    assert p["music"]["scenes"] == [ids[1]]
    # split at the playhead (the editor gives the right half a new id): both halves keep the music
    sc = p["scenes"]
    right = dict(sc[0], id="%016x" % 99, duration=5.0, audio_start=15.0, audio_duration=5.0)
    sc = [dict(sc[0], duration=7.0, audio_duration=7.0), right] + sc[1:]
    p = client.patch(f"/api/projects/{pid}", json={"scenes": sc}).json()
    assert p["music"]["scenes"] == [ids[1], "%016x" % 99] and p["music_follow"]["followed"] == ["%016x" % 99]
    assert "music_follow" not in client.get(f"/api/projects/{pid}").json()  # reported once, never stored
    # replaced by a new scene playing the same narration: it keeps the music
    sc = p["scenes"]
    sc[0] = dict(sc[0], id="%016x" % 77, title="Replaced")
    p = client.patch(f"/api/projects/{pid}", json={"scenes": sc}).json()
    assert "%016x" % 77 in p["music"]["scenes"]
    # deleted: you are told, and undo brings it back with its music
    gone = [s for s in p["scenes"] if s["id"] not in p["music"]["scenes"]]
    p = client.patch(f"/api/projects/{pid}", json={"scenes": gone}).json()
    assert len(p["music_follow"]["lost"]) == 2
    p = client.post(f"/api/projects/{pid}/undo").json()
    assert "music_follow" not in p
    lay = music.layout(p["music"], 180.0, sum(s["duration"] for s in p["scenes"]), p["scenes"])
    assert lay["runs"] and lay["runs"][0]["at"] == 0.0 and lay["runs"][0]["end"] == pytest.approx(12.0)


# ------------------------------------------------------------------ v0.4.59 the music never changes the timeline

@pytest.mark.parametrize("mode", ["whole", "range", "once", "scenes"])
def test_the_music_never_lengthens_or_shortens_the_timeline(mode):
    """Every combination of track length, used part, loop, crossfade and fades: the music lies inside
    the timeline (and inside its stretch); the timeline is the scenes' and nothing else."""
    sc = scenes_of(7, 13.0, ["A", "A", "B", "B", "B", "C", "C"])
    total = sum(round(s["duration"] * FPS) / FPS for s in sc)
    checked = 0
    for track in (0.4, 1.0, 1.5, 7.0, 30.0, total - 0.01, total, total + 0.5, 600.0):
        for part in ({}, {"start": 0.2}, {"start": 2.0, "end": 5.5}):
            for loop in (True, False):
                for x in (0.0, 0.5, 2.0, 10.0):
                    for fades in ((0.0, 0.0), (1.5, 2.0), (15.0, 15.0)):
                        m = {"mode": mode, "loop": loop, "crossfade": x, "fade_in": fades[0], "fade_out": fades[1], **part,
                             "offset": 20.0, "until": 70.0, "chapters": ["B"], "scenes": ["s6"]}
                        lay = music.layout(m, track, total, sc)
                        spans = music.stretches(m, total, sc)
                        for run, (s, e) in zip(lay["runs"], spans):
                            assert run["at"] == s and run["end"] <= e + 1e-6 and run["end"] <= total + 1e-6
                            for it in run["iters"]:
                                assert it["at"] >= s - 1e-6 and it["at"] + it["len"] <= e + 1e-4
                                assert it["src"] + it["len"] <= track + 1e-4  # never past the end of the file
                            if loop and mode != "once" and lay["part"][1] - lay["part"][0] >= 1.0:
                                assert run["end"] == pytest.approx(e, abs=1e-3)  # a loop fills its stretch exactly
                        assert len(lay["runs"]) == len(spans) if track > 0 else not lay["runs"]
                        checked += 1
    assert checked == 9 * 3 * 2 * 4 * 3


def test_the_rendered_music_bed_is_the_timeline_to_the_sample(track, tmp_path):
    """The export's music bed for short and long tracks, loops, parts, crossfades and fades: exactly the
    timeline's length (the export's -t and the video decide nothing; the music never pads or cuts it)."""
    sc = scenes_of(4, 7.5, ["A", "B", "B", "C"])
    total = 30.0
    short = tmp_path / "short.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=4.3:a=0.2:seed=3", "-ac", "2", str(short)], check=True)
    cases = [({"crossfade": 2.0}, track, 180.0), ({"crossfade": 0.5, "start": 10, "end": 13}, track, 180.0),
             ({"loop": False}, short, 4.3), ({"crossfade": 1.0}, short, 4.3), ({"mode": "once", "offset": 27.0}, track, 180.0),
             ({"mode": "range", "offset": 3.3, "until": 11.1, "fade_in": 0, "fade_out": 0}, short, 4.3),
             ({"mode": "scenes", "chapters": ["B"], "crossfade": 10.0}, short, 4.3)]
    for k, (m, path, length) in enumerate(cases):
        lay = music.layout(m, length, total, sc)
        out = tmp_path / f"bed{k}.wav"
        _render_bed(lay, path, total, out)
        assert len(_pcm(out)) == round(total * 48000), m


def test_a_scene_sliced_export_keeps_its_last_seconds_under_music_and_effects(track, tmp_path):
    """v0.4.59 An ordinary (not episode-guide) timeline's voice goes through loudnorm, which hands over
    its last 3 s only at the end; mixed with ducked music or effects in the same graph, the export's
    whole audio — narration included — ended ~2.9 s early. Now: the full timeline, narration intact."""
    import renderer
    import storage
    from PIL import Image

    media = storage.DATA / "tmp-test-tail"
    media.mkdir(parents=True, exist_ok=True)
    try:
        Image.new("RGB", (320, 180), (40, 40, 48)).save(media / "plate.png")
        voice = media / "voice.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*220*t)':s=48000:d=12",
                        "-ac", "1", str(voice)], check=True)
        shutil.copy(track, media / "music.mp3")
        assets = [{"id": "img", "kind": "image", "path": str(media / "plate.png"), "name": "plate.png", "width": 320, "height": 180},
                  {"id": "nar", "kind": "audio", "path": str(voice), "name": "voice.wav", "duration": 12.0},
                  {"id": "mus", "kind": "audio", "path": str(media / "music.mp3"), "name": "music.mp3", "duration": 180.0}]
        sc = [{"id": f"s{k}", "title": "", "narration": "", "duration": 4.0, "asset_id": "img", "motion": "none", "show_title": False,
               "audio_start": 4.0 * k, "audio_duration": 4.0} for k in range(3)]
        base = {"id": "5d00000000000059", "title": "tail", "look": "natural", "captions": False, "assets": assets, "scenes": sc,
                "narration_id": "nar", "exports": [], "music_volume": 0.2}
        fx = {"enabled": True, "items": [{"anchor": "t:2.0", "sound": "swell-2", "source": "manual", "gain": 0.0}]}
        ref = None
        for name, extra in (("narration only", {}), ("music", {"music_id": "mus"}), ("effects", {"sound": fx}),
                            ("music and effects", {"music_id": "mus", "sound": fx})):
            out = tmp_path / f"{len(name)}.mp4"
            renderer.render(json.loads(json.dumps({**base, **extra})), {"resolution": "480p", "draft": True, "captions": False},
                            out, lambda *a: None, lambda: False)
            x = _pcm(out)
            assert abs(len(x) / 48000 - 12.0) < 0.03, (name, len(x) / 48000)
            last = float(np.sqrt(np.mean(x[-24000:] ** 2)))
            ref = ref or last
            assert last == pytest.approx(ref, rel=0.15), name  # the narration is still speaking at the very end
    finally:
        shutil.rmtree(media, ignore_errors=True)
