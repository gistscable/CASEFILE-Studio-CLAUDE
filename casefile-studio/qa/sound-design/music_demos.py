"""v0.4.58 Background music demonstrations, rendered by the real exporter.

    cd casefile-studio && PATH=$PWD/.venv/bin:$PATH .venv/bin/python qa/sound-design/music_demos.py [--old /tmp/old_cf/casefile-studio]

  music-1-loop            a 16 s track under a 60 s documentary: v0.4.57 (hard restart, `-stream_loop`)
                          and v0.4.58 (seamless equal-power crossfade) — `--old` renders the "before"
                          with the v0.4.57 exporter itself (git archive c6ec51e)
  music-2-chapter-part    only in chapter 2, a chosen part of a longer track (0:24–0:48), with fades
  music-3-longer-track    a 96 s track under a 30 s documentary: starts 0:20 into the track, plays once,
                          cut (never edited) at the documentary's end
  music-4-all-layers      narration + a soundbite (its own sound) + a findings graphic with its sound
                          design + looping music ducked under both voices

Measured from the renders (music-only renders isolate the music): the exported duration against the
timeline, every loop seam (level step across it), silence outside the chosen chapter, which part of
the track plays (cross-correlation with the source), the dip under narration and the soundbite, and
the render time with and without music. Pictures are neutral placeholder plates; voices are the
AI-generated demo voices in qa/sound-design/voice; the music is synthesised here (no licences).
"""
from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_demos as md  # noqa: E402  (also puts the app on the path)
import motion  # noqa: E402
import music as musiclib  # noqa: E402
import numpy as np  # noqa: E402
import renderer  # noqa: E402

SR = 48000
WORK = md.WORK


def chords_track(name, seconds, variations=1):
    """A small synthesised piece: Am–F–C–G, 4 s each, a soft pad and a plucked arpeggio. With
    `variations` > 1 the arpeggio moves up an octave every 16 s, so each part of a long track is
    recognisably different (to hear which part plays)."""
    out = WORK / f"{name}.mp3"
    if out.exists():
        return out
    roots = [220.0, 174.61, 261.63, 196.0]  # A3 F3 C4 G3
    thirds = [261.63, 220.0, 329.63, 246.94]  # minor/major third of each
    fifths = [329.63, 261.63, 392.0, 293.66]
    t = np.arange(int(seconds * SR)) / SR
    k = (t // 4).astype(int) % 4
    octave = 2.0 ** ((t // 16).astype(int) % variations) if variations > 1 else 1.0
    pad = sum(0.06 * np.sin(2 * np.pi * np.take(f, k) * t) for f in (roots, thirds, fifths))
    step = (t // 0.25).astype(int) % 4  # sixteenth notes: root, third, fifth, third
    note = np.choose(step, [np.take(roots, k), np.take(thirds, k), np.take(fifths, k), np.take(thirds, k)]) * 2 * octave
    env = np.exp(-9 * (t % 0.25))
    pluck = 0.10 * env * np.sin(2 * np.pi * note * t)
    bass = 0.08 * np.exp(-2.5 * (t % 2)) * np.sin(2 * np.pi * np.take(roots, k) / 2 * t)
    x = (pad + pluck + bass).astype(np.float32)
    raw = np.stack([x, x], 1).tobytes()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "libmp3lame", "-b:a", "192k", str(out)],
                   input=raw, check=True)
    return out


def doc(chapters, voices, pid, title, music=None, music_asset=None, volume=0.25, extra_scenes=None, extra_assets=(), sound_on=False, motion_items=()):
    """Scenes from the demo narration clips, one plate each; the narration is one joined file."""
    parts = [md.padded(v, lead=1.2, tail=1.4) for v in voices]
    joined = WORK / f"{pid}-narration.wav"
    if not joined.exists():
        md.run(["ffmpeg", "-v", "error", "-y", *sum((["-i", str(p)] for p in parts), []), "-filter_complex",
                "".join(f"[{i}:a]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1", str(joined)])
    assets = [md.asset("nar", joined, "audio")]
    scenes, at = [], 0.0
    for i, (v, p, ch) in enumerate(zip(voices, parts, chapters)):
        d = round(md.duration(p), 3)
        img = md.plate(f"m-{v}", f"{ch.split(' — ')[-1].title()} · placeholder", (28 + 6 * i, 34, 40 - 3 * i))
        assets.append(md.asset(f"img{i}", img, "image"))
        scenes.append({"id": f"s{i}", "title": v, "chapter": ch, "narration": "", "duration": d, "asset_id": f"img{i}", "motion": "none",
                       "show_title": False, "audio_start": round(at, 3), "audio_duration": d})
        at += d
    if extra_scenes:
        scenes = extra_scenes(scenes)
    assets += list(extra_assets)
    p = md.project(pid, title, scenes, assets, "nar", motion_items, sound_on=sound_on)
    if music_asset:
        assets.append(md.asset("mus", music_asset, "audio"))
        p.update(music_id="mus", music_volume=volume)
        if music is not None:
            p["music"] = music
    return p


def timeline(p):
    return sum(max(1, round(float(s["duration"]) * 24)) / 24 for s in p["scenes"])


def render(p, name, old=None):
    """The new exporter in-process, or the v0.4.57 exporter (`old` = its casefile-studio folder) in a
    subprocess, so the "before" is the old code itself."""
    out = md.OUT / f"{name}.mp4"
    t0 = time.monotonic()
    r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    if old:
        job = WORK / f"{name}.json"
        job.write_text(json.dumps(p))
        code = ("import json,sys,episode,renderer; episode.issues=lambda p: []; p=json.load(open(sys.argv[1]));"
                "renderer.render(p, {'resolution':'720p','draft':False,'captions':False}, __import__('pathlib').Path(sys.argv[2]), lambda *a: None, lambda: False)")
        env = dict(os.environ, CASEFILE_DATA_DIR=str(WORK), PYTHONPATH=str(old))
        subprocess.run([sys.executable, "-c", code, str(job), str(out)], cwd=old, env=env, check=True)
    else:
        renderer.render(p, {"resolution": "720p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    return out, round(time.monotonic() - t0, 2), round(r1.ru_utime + r1.ru_stime - r0.ru_utime - r0.ru_stime, 2)


def music_only(p):
    q = json.loads(json.dumps(p))
    q["narration_id"] = None
    q["sound"] = {"enabled": False}
    q["motion"] = {"enabled": False, "items": []}
    for s in q["scenes"]:
        s.pop("insert_audio", None)
        s.pop("audio_break", None)
    q["id"] = q["id"][:-2] + "m0"
    return q


def no_music(p):
    q = json.loads(json.dumps(p))
    q["music_id"] = None
    q["id"] = q["id"][:-2] + "n0"
    return q


def rms_db(x, a, b):
    seg = x[max(0, int(a * SR)):int(b * SR)]
    return round(float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9)), 1) if seg.size else None


def seam_steps(x, seams, w=0.1):
    """The level step across each seam (dB): 100 ms RMS just after minus just before. A hard restart
    shows a jump (or a gap); a crossfade keeps the level."""
    out = []
    for s in seams:
        out.append(round(rms_db(x, s + 0.005, s + w) - rms_db(x, s - w, s - 0.005), 1))
    return out


def envelope_jumps(x, seams, w=0.02):
    """The biggest 20 ms level change within ±0.5 s of each seam (dB) — clicks and sudden attacks."""
    out = []
    for s in seams:
        lo, hi = int((s - 0.5) * SR), int((s + 0.5) * SR)
        seg = x[lo:hi]
        n = int(w * SR)
        e = 20 * np.log10(np.sqrt(np.convolve(seg ** 2, np.ones(n) / n, mode="valid")[::n]) + 1e-6)
        out.append(round(float(np.abs(np.diff(e)).max()), 1))
    return out


def lag_samples(a, b, s0, s1, L=480):
    """How many samples `a` is late against `b` between s0 and s1 (cross-correlation, ±10 ms)."""
    x, y = a[int(s0 * SR):int(s1 * SR)], b[int(s0 * SR):int(s1 * SR)]
    c = [float(np.dot(x[max(0, k):len(x) + min(0, k)], y[max(0, -k):len(y) - max(0, k)])) for k in range(-L, L + 1)]
    return int(np.argmax(c)) - L


def corr(a, b, s0, s1):
    x, y = a[int(s0 * SR):int(s1 * SR)], b[int(s0 * SR):int(s1 * SR)]
    return round(float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-12)), 4)


def which_part(x, src, at, seconds=4.0):
    """Where in the source track the exported music at `at` comes from (s), by cross-correlation."""
    seg = x[int(at * SR):int((at + seconds) * SR)]
    c = np.correlate(src, seg, mode="valid")
    return round(float(np.argmax(c) / SR), 3)


def main(argv):
    old = None
    if "--old" in argv:
        old = argv[argv.index("--old") + 1]
    WORK.mkdir(parents=True, exist_ok=True)
    renderer.DATA = WORK / "data"
    want = [a for a in argv if a.isdigit()] or ["1", "2", "3", "4"]
    rpath = md.OUT / "music-demo-report.json"
    report = json.loads(rpath.read_text()) if rpath.exists() else {}
    loop16 = chords_track("music-loop16", 16.0)
    long96 = chords_track("music-long96", 96.0, variations=6)
    src96 = md.pcm(long96)
    voices = ["n1-findings", "n2-typing", "n3-timeline", "n4-transitions", "n5-development"]
    chapters = ["CHAPTER 1 — THE NIGHT", "CHAPTER 1 — THE NIGHT", "CHAPTER 2 — THE SEARCH", "CHAPTER 3 — THE TRIAL", "CHAPTER 3 — THE TRIAL"]

    # ---- 1: the loop, before and after
    if "1" in want:
        demo_loop(report, loop16, voices, chapters, old)
    if "2" in want:
        demo_chapter(report, long96, src96, voices, chapters)
    if "3" in want:
        demo_long(report, long96, src96, voices, chapters)
    if "4" in want:
        demo_layers(report, loop16, old)
    report["max_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    rpath.write_text(json.dumps(report, indent=1))


def demo_loop(report, loop16, voices, chapters, old):
    settings = {"crossfade": 3.0, "fade_in": 1.5, "fade_out": 2.5}
    p = doc(chapters, voices, "5d0000000000e001", "Music 1 — loop", settings, loop16, volume=0.3)
    total = timeline(p)
    lay = musiclib.layout(musiclib.normalise(settings), md.duration(loop16), total, p["scenes"])
    seams = [it["at"] for r in lay["runs"] for it in r["iters"][1:]]
    rep = {"timeline_s": round(total, 3), "track_s": round(md.duration(loop16), 3), "seams_new_s": [round(s, 2) for s in seams]}
    after, t_after, cpu_after = render(p, "demo-music-1-loop-after")
    nm, t_nomusic, cpu_nomusic = render(no_music(p), "_tmp-nomusic")
    narration_lag = lag_samples(md.pcm(after), md.pcm(nm), 1.3, 11.0)  # the voices are not moved by the music
    nm.unlink()
    mo_new, _, _ = render(music_only(p), "_tmp-music-only-new")
    xn = md.pcm(mo_new)
    rep["after"] = {"duration_s": round(renderer.probe(after)["duration"], 3), "seam_level_step_db": seam_steps(xn, seams),
                    "seam_biggest_20ms_jump_db": envelope_jumps(xn, seams), "narration_lag_vs_export_without_music_samples": narration_lag, "render_s": t_after, "cpu_s": cpu_after,
                    "render_without_music_s": t_nomusic, "cpu_without_music_s": cpu_nomusic}
    if old:
        b = json.loads(json.dumps(p))
        b.pop("music", None)
        before, t_before, cpu_before = render(b, "demo-music-1-loop-before", old=old)
        mo_old, _, _ = render(music_only(b), "_tmp-music-only-old", old=old)
        xo = md.pcm(mo_old)
        old_seams = [16.0 * k for k in range(1, int(total // 16) + 1)]
        rep["before"] = {"duration_s": round(renderer.probe(before)["duration"], 3), "seams_s": old_seams, "seam_level_step_db": seam_steps(xo, old_seams),
                         "seam_biggest_20ms_jump_db": envelope_jumps(xo, old_seams), "render_s": t_before, "cpu_s": cpu_before}
        (md.OUT / "_tmp-music-only-old.mp4").unlink()
    (md.OUT / "_tmp-music-only-new.mp4").unlink()
    report["music-1-loop"] = rep
    print("1", json.dumps(rep))


def demo_chapter(report, long96, src96, voices, chapters):
    """only in chapter 2, a chosen part of a longer track"""
    settings = {"mode": "scenes", "chapters": ["CHAPTER 2 — THE SEARCH"], "start": 24.0, "end": 48.0, "fade_in": 1.5, "fade_out": 2.5}
    p = doc(chapters, voices, "5d0000000000e002", "Music 2 — chapter", settings, long96, volume=0.3)
    total = timeline(p)
    s2 = next(i for i, s in enumerate(p["scenes"]) if s["chapter"].startswith("CHAPTER 2"))
    a2 = sum(max(1, round(float(s["duration"]) * 24)) / 24 for s in p["scenes"][:s2])
    b2 = a2 + max(1, round(float(p["scenes"][s2]["duration"]) * 24)) / 24
    after, t_after, _ = render(p, "demo-music-2-chapter-part")
    mo, _, _ = render(music_only(p), "_tmp-mo2")
    x = md.pcm(mo)
    report["music-2-chapter-part"] = rep = {
        "timeline_s": round(total, 3), "duration_s": round(renderer.probe(after)["duration"], 3), "chapter_2_s": [round(a2, 2), round(b2, 2)],
        "music_db_before_chapter": rms_db(x, 0, a2 - 0.05), "music_db_in_chapter": rms_db(x, a2 + 2, b2 - 3), "music_db_after_chapter": rms_db(x, b2 + 0.05, total),
        "track_position_at_chapter_start_plus_2s": which_part(x, src96, a2 + 2.0), "expected": 24.0 + 2.0, "render_s": t_after}
    (md.OUT / "_tmp-mo2.mp4").unlink()
    print("2", json.dumps(rep))


def demo_long(report, long96, src96, voices, chapters):
    """a track longer than the documentary"""
    settings = {"mode": "once", "start": 20.0, "fade_in": 1.0, "fade_out": 3.0}
    p = doc(chapters[:3], voices[:3], "5d0000000000e003", "Music 3 — long track", settings, long96, volume=0.3)
    total = timeline(p)
    after, t_after, _ = render(p, "demo-music-3-longer-track")
    mo, _, _ = render(music_only(p), "_tmp-mo3")
    x = md.pcm(mo)
    report["music-3-longer-track"] = rep = {
        "timeline_s": round(total, 3), "track_s": 96.0, "duration_s": round(renderer.probe(after)["duration"], 3),
        "track_position_at_5s": which_part(x, src96, 5.0), "expected": 25.0,
        "music_db_last_0.3s": rms_db(x, total - 0.3, total), "music_db_middle": rms_db(x, total / 2 - 2, total / 2 + 2), "render_s": t_after}
    (md.OUT / "_tmp-mo3.mp4").unlink()
    print("3", json.dumps(rep))


def demo_layers(report, loop16, old=None):
    """every layer: narration, a soundbite, a graphic with sound design, ducked looping music"""
    q = md.demo_interview(True)
    di = next(s["duration"] for s in q["scenes"] if s["id"] == "s2")
    da = next(s["duration"] for s in q["scenes"] if s["id"] == "s1")
    db = next(s["duration"] for s in q["scenes"] if s["id"] == "s3")
    g = motion.normalise_item({"id": "mgm4", "status": "approved", "template": "findings", "start": da + di + 0.2, "end": da + di + db - 0.4,
                               "heading": "KEY FINDINGS", "title": "The return to the house",
                               "lines": [{"text": "Police records: three days later", "at": da + di + 0.8}, {"text": "Investigators returned with a warrant", "at": da + di + 3.0}]})
    q["id"] = "5d0000000000e004"
    q["title"] = "Music 4 — all layers"
    q["motion"] = {"enabled": True, "items": [g]}
    q["assets"].append(md.asset("mus", loop16, "audio"))
    q.update(music_id="mus", music_volume=0.3, music={"crossfade": 2.0, "fade_in": 1.0, "fade_out": 2.0})
    total = timeline(q)
    after, t_after, _ = render(q, "demo-music-4-all-layers")
    nm, _, _ = render(no_music(q), "_tmp-nm4")
    x_all, x_nm = md.pcm(after), md.pcm(nm)
    # the music's dip: the gain the export's music compressor applies, computed by the same compressor
    # on the same voice bus (sound.duck_curve — verified against exports); 200 values per second
    import base64
    import sound
    d = sound.duck_curve(q, renderer.DATA, wait=True)
    g = np.frombuffer(base64.b64decode(d["music"]), dtype=np.uint8) / 255.0
    def dip(a, b):
        seg = g[int(a * 200):int(b * 200)]
        return round(float(20 * np.log10(max(seg.mean(), 1e-4))), 1)
    # the voices are not moved by the music: lag of the full mix against the mix without music
    x7 = None
    if old:  # the same interview, no music, exported by the v0.4.57 exporter itself
        o7, _, _ = render(no_music(q), "_tmp-old4", old=old)
        x7 = md.pcm(o7)
        o7.unlink()
    report["music-4-all-layers"] = rep = {
        "timeline_s": round(total, 3), "duration_s": round(renderer.probe(after)["duration"], 3),
        "music_gain_under_narration_db": dip(1.2, da - 0.7), "music_gain_under_soundbite_db": dip(da + 1.0, da + di - 1.0),
        "music_gain_in_the_last_pause_db": dip(total - 1.4, total - 1.0),
        "mix_vs_no_music_lag_samples": {"narration": lag_samples(x_all, x_nm, 0.8, da - 0.6), "soundbite": lag_samples(x_all, x_nm, da + 0.5, da + di - 0.5)},
        "soundbite_vs_v0457_export": None if x7 is None else {"lag_samples": lag_samples(x_nm, x7, da + 0.5, da + di - 0.5), "correlation": corr(x_nm, x7, da + 0.5, da + di - 0.5)},
        "narration_vs_v0457_export": None if x7 is None else {"lag_samples": lag_samples(x_nm, x7, 0.8, da - 0.6), "correlation": corr(x_nm, x7, 0.8, da - 0.6)},
        "render_s": t_after}
    (md.OUT / "_tmp-nm4.mp4").unlink()
    print("4", json.dumps(rep))


def page(report):
    """music.html: the four music demos, playable, with what was measured."""
    import html as h
    r1, r2, r3, r4 = (report.get(k, {}) for k in ("music-1-loop", "music-2-chapter-part", "music-3-longer-track", "music-4-all-layers"))
    a1, b1 = r1.get("after", {}), r1.get("before", {})
    def li(xs):
        return "".join(f"<li>{h.escape(str(x))}</li>" for x in xs if x)
    def video(src, cap):
        return f'<figure><figcaption>{h.escape(cap)}</figcaption><video controls preload="metadata" src="{src}"></video></figure>'
    sections = [
        ("1 \u2014 A 16 s track looping under a 60 s documentary",
         "Listen at 0:13, 0:26, 0:39, 0:52 (after) and 0:16, 0:32, 0:48 (before): the old export restarted the track abruptly; now each pass crossfades into the next (3 s, equal power).",
         video("demo-music-1-loop-before.mp4", "Before (v0.4.57 exporter: -stream_loop, hard restart)") + video("demo-music-1-loop-after.mp4", "After (v0.4.58: crossfaded loop)"),
         [f"duration {b1.get('duration_s')} s before, {a1.get('duration_s')} s after (timeline {r1.get('timeline_s')} s)",
          f"level step across each seam: before {b1.get('seam_level_step_db')} dB, after {a1.get('seam_level_step_db')} dB",
          f"narration vs the same export without music: {a1.get('narration_lag_vs_export_without_music_samples')} samples",
          f"render {b1.get('render_s')} s before, {a1.get('render_s')} s after ({a1.get('render_without_music_s')} s without music)"]),
        ("2 \u2014 Music only in chapter 2, from a chosen part of a longer track",
         "Chapter 2 is the third narration clip. The music fades in when it starts and out when it ends; the rest is narration only.",
         video("demo-music-2-chapter-part.mp4", "After"),
         [f"chapter 2: {r2.get('chapter_2_s')} s; music before it {r2.get('music_db_before_chapter')} dB, in it {r2.get('music_db_in_chapter')} dB, after it {r2.get('music_db_after_chapter')} dB",
          f"track position 2 s into the chapter: {r2.get('track_position_at_chapter_start_plus_2s')} s (asked: part 0:24\u20130:48, so {r2.get('expected')} s)",
          f"duration {r2.get('duration_s')} s = timeline {r2.get('timeline_s')} s"]),
        ("3 \u2014 A 96 s track under a 37 s documentary",
         "Starts 0:20 into the track, plays once and fades out with the documentary; the file is never cut or copied.",
         video("demo-music-3-longer-track.mp4", "After"),
         [f"track position at 0:05: {r3.get('track_position_at_5s')} s (asked {r3.get('expected')} s)",
          f"duration {r3.get('duration_s')} s = timeline {r3.get('timeline_s')} s; music in the last 0.3 s {r3.get('music_db_last_0.3s')} dB (faded)"]),
        ("4 \u2014 Every layer: narration, a soundbite, a findings graphic with its sounds, looping music",
         "The music dips under the narration and under the interview, and comes back in the pauses.",
         video("demo-music-4-all-layers.mp4", "After"),
         [f"music gain under narration {r4.get('music_gain_under_narration_db')} dB, under the soundbite {r4.get('music_gain_under_soundbite_db')} dB, in the last pause {r4.get('music_gain_in_the_last_pause_db')} dB",
          f"voices vs the same export without music: {r4.get('mix_vs_no_music_lag_samples')} samples",
          f"narration / soundbite vs the v0.4.57 export of the same interview: {r4.get('narration_vs_v0457_export')} / {r4.get('soundbite_vs_v0457_export')}",
          f"duration {r4.get('duration_s')} s = timeline {r4.get('timeline_s')} s"]),
    ]
    body = "".join(f'<section><h3>Demo {t}</h3><p class="listen">{h.escape(listen)}</p><div class="pair">{v}</div><ul class="facts">{li(f)}</ul></section>'
                   for t, listen, v, f in sections)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Casefile background music \u2014 v0.4.58 demos</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
body{{font:15px/1.5 Inter,system-ui,sans-serif;background:#111317;color:#e9e5dc;margin:0;padding:28px 36px;max-width:1500px}}
h1{{font-size:26px;margin:0 0 4px}} h3{{margin:30px 0 6px;color:#d9b77a}} a{{color:#d9b77a}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} figure{{margin:0}} figcaption{{font-size:13px;color:#9a968e;margin-bottom:4px}}
video{{width:100%;background:#000;border-radius:6px}} .listen{{color:#cfc6b4;margin:0 0 10px}}
.facts{{font-size:13px;color:#b8b2a6}} .note{{background:#1a1d22;border-left:3px solid #d9b77a;padding:10px 14px;margin:14px 0}}
</style></head><body><h1>Background music \u2014 v0.4.58</h1>
<p>Rendered by the real exporter at 720p. The music is synthesised for these demos (Am\u2013F\u2013C\u2013G); the voices are the AI-generated demo voices;
the pictures are neutral plates. <a href="index.html">Sound design demos and library</a>.</p>
<div class="note">Not a final approval: this page is for your review.</div>{body}</body></html>"""


if __name__ == "__main__":
    main(sys.argv[1:])
    (md.OUT / "music.html").write_text(page(json.loads((md.OUT / "music-demo-report.json").read_text())))
