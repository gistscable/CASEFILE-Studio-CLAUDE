"""Render a plan into files any editor can place: one video with transparency per graphic, its sound cues, a
preview MP4, and the placement lists (JSON, CSV, EDL).

Frames are pure functions of time, so they are drawn in parallel worker processes (spawn-safe on macOS and
Windows) and streamed to FFmpeg; each frame is drawn once and written to every format asked for.
"""
from __future__ import annotations

import csv
import json
import multiprocessing as mp
import os
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import graphics as G
from . import photos as P
from . import plan as PL
from .cinegfx import sfx as SFX
from .media import ensure_ffmpeg

# transparent video formats: (extension, FFmpeg video arguments)
ALPHA = {
    "prores": (".mov", ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16", "-vendor", "apl0"]),
    "qtrle": (".mov", ["-c:v", "qtrle", "-pix_fmt", "argb"]),
    "webm": (".webm", ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "26", "-row-mt", "1", "-deadline", "good",
                       "-cpu-used", "4", "-auto-alt-ref", "0"]),
    "png": ("", None),     # a numbered PNG sequence in a folder
    "none": ("", None),
}
EFFECTS_DB = 4.0           # the cue bus level the approved demos were mixed at (cinegfx sfx.mix)


# ---------------------------------------------------------------- frame workers

_W = {}


def _init(item, files, folder, W, H, fps):
    G.set_fps(fps)
    _W.update(g=G.build(item, files, folder), item=item, W=W, H=H)


def _draw(n):
    return G.frame(_W["g"], _W["item"], n, _W["W"], _W["H"]).tobytes()


def workers_for(n_frames, asked=None):
    """All cores but one, at most 6 (memory: ~120 MB each); in-process for short graphics or small machines."""
    if asked:
        return max(1, int(asked))
    env = os.environ.get("STORYROOM_WORKERS")
    if env and env.isdigit():
        return max(1, int(env))
    cpus = os.cpu_count() or 2
    if cpus <= 2 or n_frames < 96:
        return 1
    return max(1, min(6, cpus - 1))


def frames(item, files, folder, W, H, workers=None):
    """Every frame of the graphic as RGBA bytes, in order."""
    n = G.frames_of(item)
    w = workers_for(n, workers)
    if w <= 1:
        g = G.build(item, files, folder)
        for k in range(n):
            yield G.frame(g, item, k, W, H).tobytes()
        return
    ctx = mp.get_context("spawn")
    with ctx.Pool(w, initializer=_init, initargs=(item, files, folder, W, H, G.FPS)) as pool:
        yield from pool.imap(_draw, range(n), chunksize=4)


# ---------------------------------------------------------------- sound

def _write_wav(bus: np.ndarray, path: Path):
    raw = bus.T.astype(np.float32).tobytes()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-f", "f32le", "-ar", str(SFX.SR), "-ac", "2", "-i", "-",
                    "-af", "alimiter=limit=0.891:attack=3:release=60:level=disabled", "-c:a", "pcm_s24le", str(path)],
                   input=raw, check=True)


def sound(item, g, seconds, voice=None):
    """(effects, preview mix) as float32 stereo arrays: the graphic's cues at the demos' level, ducked 4 dB while
    the narrator speaks when the narration is given (cinegfx sfx.mix), and that narration under them."""
    n = int(round(seconds * SFX.SR))
    keep = {(c["t"], c["sfx"]) for c in G.cues(item, g)}
    cues = [c for c in g.cues if (float(c.t), c.sfx) in keep]
    bus = SFX.place(cues, n, 0.0, EFFECTS_DB)
    if voice is None:
        return bus, bus
    v = np.zeros((2, n), np.float32)
    v[:, :min(n, voice.shape[1])] = voice[:, :n]
    env = np.convolve(np.abs(v).max(axis=0), np.ones(int(0.04 * SFX.SR)) / int(0.04 * SFX.SR), mode="same")
    speaking = np.clip(env / 0.05, 0, 1)
    bus = bus * (1 - speaking * (1 - 10 ** (-4 / 20))).astype(np.float32)
    return bus, v + bus


# ---------------------------------------------------------------- one graphic

def render_item(item, out: Path, name: str, files, folder=None, W=1920, H=1080, alpha="prores", mp4=True, wav=True,
                voice=None, workers=None):
    """Write one graphic. Returns what was written."""
    if alpha not in ALPHA:
        raise ValueError(f"Unknown transparent format {alpha!r}: {', '.join(ALPHA)}")
    n = G.frames_of(item)
    seconds = n / G.FPS
    g = G.build(item, files, folder)
    written = {"frames": n, "seconds": round(seconds, 3)}
    effects, mix = sound(item, g, seconds, voice)
    tmp_mix = None
    if wav:
        _write_wav(effects, out / f"{name}.wav")
        written["sound"] = f"{name}.wav"
    if mp4:
        tmp_mix = out / f".{name}.mix.wav"
        _write_wav(mix, tmp_mix)
    procs = []
    ext, vargs = ALPHA[alpha]
    raw_in = ["ffmpeg", "-v", "error", "-y", "-nostdin", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(G.FPS), "-i", "-"]
    if vargs:
        procs.append(subprocess.Popen(raw_in + vargs + ["-r", str(G.FPS), str(out / f"{name}{ext}")], stdin=subprocess.PIPE))
        written["video"] = f"{name}{ext}"
    if mp4:  # over black, with the sound cues (and the narration when given): to watch, or for editors without transparency
        procs.append(subprocess.Popen(raw_in + ["-i", str(tmp_mix), "-filter_complex",
                                                f"color=c=black:s={W}x{H}:r={G.FPS}[bg];[bg][0:v]overlay=shortest=1:format=auto,format=yuv420p[v]",
                                                "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                                                "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(out / f"{name}-preview.mp4")],
                                      stdin=subprocess.PIPE))
        written["preview"] = f"{name}-preview.mp4"
    seq = None
    if alpha == "png":
        seq = out / name
        seq.mkdir(parents=True, exist_ok=True)
        written["video"] = f"{name}/%05d.png"
    t0 = time.time()
    try:
        for k, buf in enumerate(frames(item, files, folder, W, H, workers)):
            for p in procs:
                p.stdin.write(buf)
            if seq is not None:
                Image.frombytes("RGBA", (W, H), buf).save(seq / f"{k:05d}.png", compress_level=3)
        for p in procs:
            p.stdin.close()
            if p.wait() != 0:
                raise RuntimeError(f"FFmpeg could not write {name}.")
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        if tmp_mix:
            tmp_mix.unlink(missing_ok=True)
    written["render_seconds"] = round(time.time() - t0, 2)
    return written


# ---------------------------------------------------------------- a whole plan

def _decode_voice(path):
    return SFX.decode(str(path))


def render_plan(plan: dict, out, base=".", only=None, alpha="prores", mp4=True, wav=True, narration=None, size=None,
                workers=None, edl_fps=None, log=print):
    """Render every graphic of the plan (not the skipped ones) into `out`, plus render.json, placements.csv and
    timeline.edl. `only`: graphic numbers (1-based) to render. `narration`: the full recording, for the preview
    MP4s and the ducking (its time 0 is the plan's timing offset). `size`: (W, H), default 1920x1080."""
    ensure_ffmpeg()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    base = Path(base)
    PL.refresh(plan)
    W, H = size or (plan.get("width", 1920), plan.get("height", 1080))
    folder = plan.get("photos", {}).get("folder")
    if folder and P.has_sources(base / folder):
        folder = str((base / folder).resolve())
    elif folder and P.has_sources(folder):
        folder = str(Path(folder).resolve())
    else:
        folder = None
    voice = _decode_voice(narration) if narration else None
    offset = float(plan.get("timing", {}).get("offset") or 0.0)
    report = {"kit": "storyroom-kit", "version": plan.get("version"), "fps": G.FPS, "width": W, "height": H,
              "transparent_format": alpha, "title": plan["script"].get("title"), "graphics": []}
    for n, it in enumerate(plan["graphics"], 1):
        if it.get("status") == "skipped" or (only and n not in only):
            continue
        name = f"{n:02d}-{it['category']}"
        files = P.files_for(it, base)
        seg = None
        if voice is not None:
            a = max(0, int(round((it["start"] - offset) * SFX.SR)))
            seg = voice[:, a:a + int(round(G.frames_of(it) / G.FPS * SFX.SR)) + 1]
        log(f"{name}: {G.frames_of(it)} frames …")
        w = render_item(it, out, name, files, folder, W, H, alpha, mp4, wav, seg, workers)
        log(f"{name}: done in {w['render_seconds']} s")
        filled = sorted(k for k in files if k != G.BACKDROP) if not folder else "sources.json"
        report["graphics"].append({
            "n": n, "id": it["id"], "category": it["category"], "label": it["label"], "start": it["start"], "end": it["end"],
            "frames": w["frames"], "files": {k: w[k] for k in ("video", "preview", "sound") if k in w},
            "background": it["style"]["background"], "see_through": G.see_through(it),
            "covered_by_next": bool(it.get("cut")), "fades_under_next": bool(it.get("cut_fade")),
            "hide_captions": True, "photos": filled, "notes": it["style"].get("notes") or [],
            "cues": G.cues(it, G.build(it, files, folder)), "text": it["text"], "render_seconds": w["render_seconds"]})
    (out / "render.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(report, out / "placements.csv")
    write_edl(report, out / "timeline.edl", edl_fps or G.FPS)
    return report


def tc(t, fps):
    f = int(round(t * fps))
    return f"{f // (3600 * fps):02d}:{f // (60 * fps) % 60:02d}:{f // fps % 60:02d}:{f % fps:02d}"


def write_csv(report, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["n", "category", "label", "start_s", "end_s", "start_tc", "end_tc", "video", "sound", "preview", "background",
                    "covered_by_next", "text"])
        for g in report["graphics"]:
            w.writerow([g["n"], g["category"], g["label"], g["start"], g["end"], tc(g["start"], G.FPS), tc(g["end"], G.FPS),
                        g["files"].get("video", ""), g["files"].get("sound", ""), g["files"].get("preview", ""), g["background"],
                        "yes" if g["covered_by_next"] else "", g["text"]])


def write_edl(report, path, fps):
    """A CMX 3600 edit list: each graphic on the video track and its sound on the audio track, at its time.
    Premiere, Resolve and Final Cut (via conversion) import it; relink the clips to the rendered files."""
    lines = [f"TITLE: {(report.get('title') or 'storyroom graphics')[:60]}", "FCM: NON-DROP FRAME", ""]
    k = 0
    for g in report["graphics"]:
        dur = g["frames"] / G.FPS
        for track, key in (("V", "video"), ("A", "sound")):
            clip = g["files"].get(key)
            if not clip:
                continue
            k += 1
            lines.append(f"{k:03d}  AX       {track:<5} C        {tc(0, fps)} {tc(dur, fps)} {tc(g['start'], fps)} {tc(g['start'] + dur, fps)}")
            lines.append(f"* FROM CLIP NAME: {clip}")
            lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def stills(plan: dict, out, base=".", at=None, only=None, size=None):
    """PNG frames for checking: at the given seconds, else at each sound cue (+0.35 s), 0.6 s and near the end."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    base = Path(base)
    PL.refresh(plan)
    W, H = size or (plan.get("width", 1920), plan.get("height", 1080))
    folder = plan.get("photos", {}).get("folder")
    folder = str((base / folder).resolve()) if folder and P.has_sources(base / folder) else None
    written = []
    for n, it in enumerate(plan["graphics"], 1):
        if it.get("status") == "skipped" or (only and n not in only):
            continue
        files = P.files_for(it, base)
        g = G.build(it, files, folder)
        last = G.frames_of(it) - 1
        marks = at or sorted({0.6} | {round(c["t"] + 0.35, 2) for c in G.cues(it, g)} | {round(last / G.FPS - 0.5, 2)})
        for t in marks:
            k = max(0, min(last, int(round(t * G.FPS))))
            p = out / f"{n:02d}-{it['category']}-{t:06.2f}.png"
            G.frame(g, it, k, W, H).save(p)
            written.append(p)
    return written
