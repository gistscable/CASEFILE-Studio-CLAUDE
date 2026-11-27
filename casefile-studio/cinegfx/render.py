"""Render a Graphic to MP4: frames are pure functions of time, so they are drawn in parallel worker
processes (all cores; spawn-safe for macOS) and streamed in order to one FFmpeg encoder. Preview mode
renders at half resolution / 15 fps from the same code path, so preview and export cannot drift."""
from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import time

from PIL import Image

from . import core
from .draw import H, W
from .timing import ffbin

_G = None
_SCALE = 1.0


def _init(spec, scale):
    global _G, _SCALE
    _G, _SCALE = build(spec), scale


def build(spec):
    """spec = (collection, category, beat, timeline, assets_folder) — all picklable."""
    coll, cat, beat, tl, folder = spec
    reg = core.load_collections()
    c = reg[coll].categories[cat]
    return c.graphic(beat, c.theme, tl, core.Assets(folder))


def _frame(t):
    im = _G.frame(t).convert("RGB")
    if _SCALE != 1.0:
        im = im.resize((int(W * _SCALE), int(H * _SCALE)), Image.BILINEAR)
    return im.tobytes()


def render(spec, out_mp4: str, audio_wav: str | None = None, fps: int = 30, preview: bool = False, workers: int | None = None,
           encoder: str | None = None):
    g = build(spec)
    scale = 0.5 if preview else 1.0
    fps = 15 if preview else fps
    n = int(round(g.duration * fps))
    times = [i / fps for i in range(n)]
    w, h = int(W * scale), int(H * scale)
    enc = encoder or os.environ.get("CINEGFX_ENCODER", "libx264")
    vargs = ["-c:v", enc]
    if enc == "libx264":
        vargs += ["-preset", "veryfast" if preview else "medium", "-crf", "24" if preview else "15", "-tune", "animation"]
    elif enc == "h264_videotoolbox":  # Apple-silicon hardware encoder (M1): frees the CPU cores for drawing
        vargs += ["-b:v", "20M" if not preview else "4M"]
    cmd = [ffbin(), "-v", "error", "-y", "-nostdin", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-"]
    if audio_wav:
        cmd += ["-i", audio_wav]
    cmd += vargs + ["-pix_fmt", "yuv420p", "-r", str(fps)]
    if audio_wav:
        cmd += ["-c:a", "aac", "-b:a", "256k", "-shortest"]
    cmd += ["-movflags", "+faststart", out_mp4]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    ctx = mp.get_context("spawn")
    with ctx.Pool(workers, initializer=_init, initargs=(spec, scale)) as pool:
        for buf in pool.imap(_frame, times, chunksize=4):
            proc.stdin.write(buf)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return {"frames": n, "fps": fps, "seconds": round(time.time() - t0, 2), "workers": workers, "duration": round(g.duration, 3), "cues": g.cues}


def still(spec, t: float, out_png: str):
    build(spec).frame(t).convert("RGB").save(out_png)
