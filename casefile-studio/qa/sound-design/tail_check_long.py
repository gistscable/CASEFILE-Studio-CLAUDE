# v0.4.60 QA script kept for reproducibility. From casefile-studio/:
#   PATH=$PWD/.venv/bin:$PATH CASEFILE_DATA_DIR=/tmp/tl python qa/sound-design/tail_check_long.py out.json [case ...] [--code DIR]
# --code DIR: import renderer / sound from another checkout (e.g. v0.4.59) for a before / after.
"""Is all of the narration in a long export, in the right place? 20-30 min timelines with soundbites, music in
several stretches with crossfades, sound effects (planned + manual), reordered scenes, and slices past the end of
a recording.

The test narration says where it is: a tone whose pitch encodes its own time (400 + 10 * (block % 40) Hz, a new
block every 5 s), and each soundbite clip likewise (1200 + 20 * (block % 15) Hz, every 2 s). The exported audio is
cut into 0.5 s windows inside every scene; in each, the strongest of those pitches must be the one of the part
of the recording that scene plays (a missing or misplaced piece is caught, not only silence), and a window that
should be silent (a slice past the end of its recording) must be."""
import json, os, random, subprocess, sys, time
from pathlib import Path

args = [a for a in sys.argv[1:]]
code = None
if "--code" in args:
    k = args.index("--code")
    code = args[k + 1]
    del args[k:k + 2]
sys.path.insert(0, code or ".")
import numpy as np
from PIL import Image
import renderer
import episode

episode.issues = lambda project: []
OUT = args[0] if args else "/tmp/tail-long.json"
WANT = args[1:]
D = renderer.DATA / "media" / "taillong"
D.mkdir(parents=True, exist_ok=True)
SR_OUT = 48000
NAR_F = lambda t: 400 + 10 * (np.floor(np.asarray(t) / 5) % 40)
CLIP_F = lambda t: 1200 + 20 * (np.floor(np.asarray(t) / 2) % 15)
NAR_SET = 400 + 10 * np.arange(40)
CLIP_SET = 1200 + 20 * np.arange(15)


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


def media(minutes):
    secs = minutes * 60
    nar = D / f"narration-{minutes}.mp3"
    if not nar.exists():
        ff("-f", "lavfi", "-i", f"aevalsrc='0.25*sin(2*PI*(400+10*mod(floor(t/5),40))*t)':s=44100:d={secs}", "-ac", "1",
           "-c:a", "libmp3lame", "-b:a", "128k", str(nar))
    clip = D / "soundbite.mp4"
    if not clip.exists():
        ff("-f", "lavfi", "-i", "testsrc=s=320x180:r=24:d=30", "-f", "lavfi", "-i",
           "aevalsrc='0.25*sin(2*PI*(1200+20*mod(floor(t/2),15))*t)':s=48000:d=30", "-shortest",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(clip))
    mus = D / "music.wav"
    if not mus.exists():
        ff("-f", "lavfi", "-i", "aevalsrc='0.2*sin(2*PI*110*t)':s=48000:d=9", "-ac", "2", str(mus))
    plate = D / "plate.png"
    if not plate.exists():
        Image.new("RGB", (640, 360), (40, 40, 48)).save(plate)
    return nar, clip, mus, plate, secs


def project(name, minutes, guide, bites, past_end, reorder, seed):
    """bites: [(index, trim_start, seconds)]; past_end: [(index, audio_start)] (sliced only)."""
    rnd = random.Random(seed)
    nar, clip, mus, plate, secs = media(minutes)
    assets = [{"id": "img", "kind": "image", "path": str(plate), "name": "plate.png", "width": 640, "height": 360},
              {"id": "nar", "kind": "audio", "path": str(nar), "name": nar.name, "duration": float(secs), "has_audio": True},
              {"id": "mus", "kind": "audio", "path": str(mus), "name": "music.wav", "duration": 9.0, "has_audio": True},
              {"id": "clip", "kind": "video", "path": str(clip), "name": "soundbite.mp4", "duration": 30.0, "has_audio": True,
               "width": 320, "height": 180}]
    n = secs // 10
    blocks = list(range(n))
    if reorder:
        rnd.shuffle(blocks)
    scenes = [{"id": f"{k + 1:016x}", "title": "", "narration": "", "duration": 10.0, "asset_id": "img", "motion": "none",
               "show_title": False, "audio_start": b * 10.0, "audio_duration": 10.0, "chapter": f"CHAPTER {k // 15 + 1}"}
              for k, b in enumerate(blocks)]
    for i, a in sorted(past_end, reverse=True):
        scenes.insert(i, {"id": f"{0xe000 + i:016x}", "title": "", "narration": "", "duration": 6.0, "asset_id": "img",
                          "motion": "none", "show_title": False, "audio_start": a, "audio_duration": 6.0, "chapter": scenes[i]["chapter"]})
    for i, a, d in sorted(bites, reverse=True):
        scenes.insert(i, {"id": f"{0xb000 + i:016x}", "title": "", "narration": "", "duration": float(d), "asset_id": "clip",
                          "motion": "none", "show_title": False, "insert_audio": True, "trim_start": float(a), "chapter": scenes[i]["chapter"]})
    total = sum(round(s["duration"] * 24) / 24 for s in scenes)
    items = [{"anchor": f"t:{t:.3f}", "sound": snd, "source": "manual", "gain": 0.0, "id": f"m{j}", "kind": "manual",
              "status": "approved"} for j, (t, snd) in enumerate(
                  (rnd.uniform(5, total - 5), rnd.choice(["swell-1", "swell-2", "rwhoosh-1", "shutter-1", "riser-1", "bell-2", "paper-1"])) for _ in range(24))]
    p = {"id": f"7a11{seed:012x}", "title": name, "look": "natural", "captions": False, "assets": assets, "scenes": scenes,
         "narration_id": "nar", "exports": [], "music_id": "mus", "music_volume": 0.2,
         "music": {"mode": "scenes", "chapters": ["CHAPTER 2", "CHAPTER 4", "CHAPTER 5", "CHAPTER 8"], "crossfade": 2.0, "loop": True,
                   "fade_in": 1.5, "fade_out": 2.0},
         "sound": {"enabled": True, "items": items}}
    if guide:
        p["episode"] = {"guide": True, "plan": {"mode": "final"}}
    return p, total


CASES = {
    # guide: the narration pauses for each soundbite and resumes at the same word; 6 soundbites, one running past the clip's end
    "guide-25min-6-soundbites": dict(minutes=25, guide=True, bites=[(9, 2.0, 8), (31, 12.0, 6), (52, 20.0, 8), (77, 4.0, 10), (101, 25.0, 8), (140, 0.0, 12)],
                                     past_end=[], reorder=False, seed=1),
    # sliced: 150 scenes in a new order, two 6 s scenes past the end of the recording in the middle
    "sliced-25min-reordered-past-end": dict(minutes=25, guide=False, bites=[], past_end=[(40, 1503.0), (96, 1520.0)], reorder=True, seed=2),
    # guide, 30 min: 8 soundbites, one wholly past the end of its clip (a clip replaced by a shorter one)
    "guide-30min-8-soundbites-one-past-clip-end": dict(minutes=30, guide=True,
                                                       bites=[(6, 1.0, 8), (25, 10.0, 8), (44, 34.0, 6), (70, 6.0, 8), (95, 18.0, 10), (120, 3.0, 8), (150, 21.0, 9), (170, 0.0, 6)],
                                                       past_end=[], reorder=False, seed=3),
    # quick checks of this script (run only when named)
    "smoke-guide-3min": dict(minutes=3, guide=True, bites=[(4, 2.0, 6), (12, 34.0, 5)], past_end=[], reorder=False, seed=4),
    "smoke-sliced-3min": dict(minutes=3, guide=False, bites=[], past_end=[(7, 185.0)], reorder=True, seed=5),
}


def amp(x, fs):
    """Amplitude of each frequency in `fs` in window x (Hann)."""
    if len(x) < SR_OUT // 2:  # past the end of the exported audio: nothing there
        return np.zeros(len(fs))
    w = np.hanning(len(x))
    t = np.arange(len(x)) / SR_OUT
    return np.abs((x * w) @ np.exp(-2j * np.pi * np.outer(t, fs))) * 2 / w.sum()


def check(p, total, wav):
    scenes, secs = p["scenes"], p["assets"][1]["duration"]
    guide = bool(p.get("episode", {}).get("guide"))
    res = {"narration": [0, 0], "narration_wrong_part": 0, "soundbite": [0, 0], "should_be_silent": [0, 0], "failures": []}
    t0, ncur = 0.0, 0.0
    last_narr = 0.0
    for s in scenes:
        d = round(s["duration"] * 24) / 24
        if s.get("insert_audio"):
            src0, kind = float(s.get("trim_start") or 0), "clip"
            src_len = 30.0
        else:
            src0, kind = (ncur if guide else float(s["audio_start"])), "nar"
            src_len = secs
            ncur += d
        w = t0 + 0.3
        while w + 0.5 <= t0 + d - 0.3:
            src = src0 + (w - t0)
            block = 5 if kind == "nar" else 2
            # skip a window that crosses a pitch change of its source (and the mp3's start delay)
            if np.floor((src - 0.06) / block) != np.floor((src + 0.56) / block):
                w += 0.5
                continue
            i0 = round(w * SR_OUT)
            x = wav[i0:i0 + SR_OUT // 2]
            a_n, a_c = amp(x, NAR_SET), amp(x, CLIP_SET)
            if src + 0.56 > src_len:  # past the end of its recording: should be silent
                ok = bool(a_n.max() < 0.003 and a_c.max() < 0.003)
                res["should_be_silent"][0] += ok
                res["should_be_silent"][1] += 1
                if not ok:
                    res["failures"].append({"t": round(w, 2), "expected": "silence", "narr": round(float(a_n.max()), 4), "clip": round(float(a_c.max()), 4)})
            else:
                fset, a = (NAR_SET, a_n) if kind == "nar" else (CLIP_SET, a_c)
                want = float((NAR_F if kind == "nar" else CLIP_F)(src + 0.25))
                k = int(np.argmin(abs(fset - want)))
                ok = bool(a[k] > 0.01 and int(np.argmax(a)) == k)
                key = "narration" if kind == "nar" else "soundbite"
                res[key][0] += ok
                res[key][1] += 1
                if ok and kind == "nar":
                    last_narr = w + 0.5
                if not ok:
                    if kind == "nar" and a[k] > 0.01:
                        res["narration_wrong_part"] += 1
                    res["failures"].append({"t": round(w, 2), "expected": f"{kind} {want:.0f} Hz", "got_amp": round(float(a[k]), 4),
                                            "strongest": float(fset[int(np.argmax(a))])})
            w += 0.5
        t0 += d
    res["failures"] = res["failures"][:12]
    res["last_narration_window_end"] = round(float(last_narr), 2)
    return res


out = json.load(open(OUT)) if os.path.exists(OUT) else {}
for name, spec in CASES.items():
    if (WANT and name not in WANT) or (not WANT and name.startswith("smoke")):
        continue
    p, total = project(name, **spec)
    f = Path(f"/tmp/tail-long-{name}.mp4")
    began = time.monotonic()
    try:
        info = renderer.render(json.loads(json.dumps(p)), {"resolution": "480p", "draft": True, "captions": False}, f, lambda *a: None, lambda: False)
    except RuntimeError as e:  # e.g. a guide export refused by its own check
        out[name + (" @ " + code if code else "")] = {"code": code or "this checkout", "timeline_s": round(total, 3), "export_refused": str(e)}
        print(name, "EXPORT REFUSED:", e, flush=True)
        json.dump(out, open(OUT, "w"), indent=1)
        continue
    took = time.monotonic() - began
    wav = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-f", "f32le", "-ac", "1", "-ar", str(SR_OUT), "-"],
                                       capture_output=True).stdout, np.float32)
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(f)],
                                      capture_output=True, text=True).stdout)["streams"]
    dur = {s["codec_type"]: float(s.get("duration") or 0) for s in probe}
    r = {"code": code or "this checkout", "timeline_s": round(total, 3), "scenes": len(p["scenes"]),
         "soundbites": sum(1 for s in p["scenes"] if s.get("insert_audio")), "manual_effects": len(p["sound"]["items"]),
         "music": p["music"], "video_s": dur.get("video"), "audio_s": dur.get("audio"), "decoded_audio_s": round(len(wav) / SR_OUT, 3),
         "render_s": round(took, 1), "warnings": info.get("warnings"), **check(p, total, wav)}
    out[name + (" @ " + code if code else "")] = r
    print(name, json.dumps({k: v for k, v in r.items() if k not in ("music", "failures")}, default=lambda o: o.item() if hasattr(o, "item") else str(o)), flush=True)
    if r["failures"]:
        print("  first failures:", r["failures"][:4], flush=True)
    json.dump(out, open(OUT, "w"), indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    f.unlink(missing_ok=True)
