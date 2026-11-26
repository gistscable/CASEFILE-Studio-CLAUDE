"""v0.4.59 Benchmark of the editor's ducking analysis (sound.duck_curve) on a 25-minute, 150-scene
documentary, for each way the export builds the voice bus:

  sliced   - an ordinary timeline: the narration is cut per scene (renderer.voice_graph's asplit path)
  guide    - an episode guide with one continuous narration recording
  inserts  - an episode guide whose narration pauses for soundbites (Mode O)

For each it times: the first analysis, a narration-volume change, a music/effects volume change, a
ducking switch, one scene edited, and returning to a timeline already analysed. Media is synthetic and
made once in CASEFILE_DATA_DIR.

    cd casefile-studio && PATH=$PWD/.venv/bin:$PATH CASEFILE_DATA_DIR=/tmp/duckbench \\
        .venv/bin/python qa/sound-design/duck_bench.py [sliced guide inserts] [--minutes 25]
"""
import copy
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CASEFILE_DATA_DIR", "/tmp/duckbench")
import renderer  # noqa: E402
import sound  # noqa: E402

DATA = renderer.DATA
MEDIA = DATA / "media" / "duckbench"


def make_media(minutes):
    MEDIA.mkdir(parents=True, exist_ok=True)
    voice = MEDIA / f"narration-{minutes}.mp3"
    if not voice.exists():
        # speech-like: a voiced buzz at syllable rate with sentence pauses, plus breath noise
        expr = ("0.35*sin(2*PI*(150+30*sin(2*PI*0.3*t))*t)*gt(sin(2*PI*4.3*t),-0.2)*lt(mod(t,6.7),5.2)"
                "+0.02*(random(0)-0.5)")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"aevalsrc='{expr}':s=44100:d={minutes * 60}", "-ac", "1", "-b:a", "128k", str(voice)], check=True)
    bite = MEDIA / "soundbite.mp4"
    if not bite.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=24:d=60",
                        "-f", "lavfi", "-i", "aevalsrc='0.2*sin(2*PI*220*t)*gt(sin(2*PI*3*t),0)':s=48000:d=60",
                        "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(bite)], check=True)
    return voice, bite


def project(kind, minutes, scenes_n=150):
    voice, bite = make_media(minutes)
    total = minutes * 60
    d = round(total / scenes_n * 24) / 24
    scenes, cursor = [], 0.0
    for i in range(scenes_n):
        s = {"id": f"{i:016x}", "duration": d, "audio_start": cursor, "audio_duration": d, "title": f"Scene {i}",
             "narration": "", "chapter": f"Chapter {i // 25 + 1}", "trim_start": 0}
        if kind == "inserts" and i % 15 == 7:
            s.update(insert_audio=True, asset_id="bite", trim_start=float(i % 4) * 5, duration=6.0)
        else:
            cursor += d
        scenes.append(s)
    p = {"id": f"duckbench-{kind}", "scenes": scenes, "narration_id": "voice", "music_id": "music",
         "assets": [{"id": "voice", "kind": "audio", "has_audio": True, "path": str(voice)},
                    {"id": "bite", "kind": "video", "has_audio": True, "path": str(bite)},
                    {"id": "music", "kind": "audio", "has_audio": True, "path": str(voice)}],
         "sound": {"enabled": True, "duck": True}, "music": {"duck": True}}
    if kind != "sliced":
        p["episode"] = {"guide": {"title": "bench"}}
    return p


def timed(name, p, out):
    t0 = time.perf_counter()
    r = sound.duck_curve(p, DATA, wait=True)
    wall = time.perf_counter() - t0
    out[name] = {"wall_s": round(wall, 2), "status": r["status"],
                 "child_peak_rss_mb": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024}
    print(f"  {name:34s} {wall:8.2f} s  {r['status']}", flush=True)
    return r


def bench(kind, minutes):
    import shutil

    shutil.rmtree(DATA / "cache" / "sfx" / "duck", ignore_errors=True)
    shutil.rmtree(DATA / "cache" / "voicebus", ignore_errors=True)
    sound._DUCK_FAILED.clear()
    out = {}
    p = project(kind, minutes)
    print(kind, flush=True)
    first = timed("first_analysis", p, out)
    q = copy.deepcopy(p)
    q["narration_volume"] = 0.7
    timed("narration_volume_changed", q, out)
    q = copy.deepcopy(p)
    q["music_volume"] = 0.3
    q["sound"]["master"] = 0.5
    timed("music_and_effects_volume_changed", q, out)
    q = copy.deepcopy(p)
    q["sound"]["duck"] = False
    timed("effects_ducking_switched_off", q, out)
    q = copy.deepcopy(p)
    k = len(q["scenes"]) // 2
    q["scenes"][k]["duration"] += 1.0
    q["scenes"][k]["audio_duration"] += 1.0
    timed("one_scene_edited_mid", q, out)
    back = timed("back_to_first_timeline_undo", p, out)
    out["same_curve_after_undo"] = back.get("gain") == first.get("gain")
    return out


def old_module():
    """sound.py of v0.4.58 (one FFmpeg pass per curve), for --compare."""
    import importlib.util

    src = subprocess.run(["git", "show", "52fdceb:casefile-studio/sound.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    path = Path("/tmp/sound_v0458.py")
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("sound_v0458", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def compare(kind, minutes):
    """The new two-step curves against the v0.4.58 single pass: max / p99.9 difference (1/255 steps)."""
    import base64

    import numpy as np

    old = old_module()
    out = {}
    for name, change in (("as_saved", {}), ("narration_70", {"narration_volume": 0.7}), ("narration_150", {"narration_volume": 1.5})):
        p = {**project(kind, minutes), **change}
        t0 = time.perf_counter()
        a = old.duck_curve(p, DATA, wait=True)
        t_old = time.perf_counter() - t0
        t0 = time.perf_counter()
        b = sound.duck_curve(p, DATA, wait=True)
        t_new = time.perf_counter() - t0
        row = {"old_s": round(t_old, 2), "new_s": round(t_new, 2)}
        for col in ("gain", "music"):
            x = np.frombuffer(base64.b64decode(a[col]), np.uint8).astype(int)
            y = np.frombuffer(base64.b64decode(b[col]), np.uint8).astype(int)
            n = min(len(x), len(y))
            d = np.abs(x[:n] - y[:n])
            row[col] = {"len_old": len(x), "len_new": len(y), "max_diff_steps": int(d.max()), "p999_diff_steps": float(np.percentile(d, 99.9)),
                        "share_identical": round(float(np.mean(d == 0)), 4), "min_gain": round(float(y.min()) / 255, 3)}
        out[name] = row
        print(f"  compare {name}: {row}", flush=True)
    return out


def main(argv):
    minutes = 25
    if "--minutes" in argv:
        minutes = int(argv[argv.index("--minutes") + 1])
    kinds = [a for a in argv if a in ("sliced", "guide", "inserts")] or ["sliced", "guide", "inserts"]
    res = {"minutes": minutes, "scenes": 150, "cpu_count": os.cpu_count()}
    for k in kinds:
        res[k] = compare(k, minutes) if "--compare" in argv else bench(k, minutes)
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main(sys.argv[1:])
