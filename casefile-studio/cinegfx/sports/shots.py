"""v0.4.78 Footage analysis: where the shots are in a file and what each one shows.

`analyse(path, cache_dir)` decodes the file once at a small size (FFmpeg pipe, 12.5 fps, 160x90), finds the cuts
(frame difference plus a luma-histogram change, against the local median, so a fast pan isn't a cut) and
describes every shot from its own pixels:

    green   share of pitch-green pixels       (a wide or action shot of a match is mostly pitch)
    luma    mean brightness                   (low-key / night material)
    sat     mean saturation
    motion  mean frame-to-frame change        (action)
    edges   mean gradient                     (a crowd is fine texture; a close-up is large smooth areas)
    person  share of the frame that is a person, when the optional matte model is installed (else None)

and from those a `kind`: wide | action | close | crowd | dark (`why` says which numbers decided it). Nothing is
recognised by name: a shot is described, not identified. Results are cached per file (path, size, mtime).
Photos get kind "photo" with the same measurements.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from ..timing import ffbin

VERSION = 1
SW, SH = 160, 90          # analysis size
RATE = 12.5               # analysis frame rate
MIN_SHOT = 1.0            # shorter pieces (wipes, flashes, graphics stings) are not offered as shots
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")


def _key(path: str) -> str:
    st = os.stat(path)
    return hashlib.sha1(json.dumps([VERSION, os.path.abspath(path), st.st_size, int(st.st_mtime)]).encode()).hexdigest()[:16]


def _frames(path: str):
    """Small RGB frames at RATE fps, streamed (a 90-minute match is ~67k frames of 43 KB: never all in memory)."""
    p = subprocess.Popen([ffbin(), "-v", "error", "-nostdin", "-i", path, "-an", "-vf",
                          f"fps={RATE},scale={SW}:{SH}:flags=area", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = SW * SH * 3
    try:
        while True:
            b = p.stdout.read(n)
            if len(b) < n:
                break
            yield np.frombuffer(b, np.uint8).reshape(SH, SW, 3)
    finally:
        p.stdout.close()
        p.wait()


def measure(rgb: np.ndarray) -> dict:
    """Picture measurements of one small RGB frame (0-1 floats)."""
    a = rgb.astype(np.float32) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0)
    green = (g > r * 1.08) & (g > b * 1.08) & (sat > 0.18) & (mx > 0.12)
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    gx = np.abs(np.diff(y, axis=1)).mean()
    gy = np.abs(np.diff(y, axis=0)).mean()
    return {"green": float(green.mean()), "luma": float(y.mean()), "sat": float(sat.mean()), "edges": float(gx + gy)}


def classify(f: dict) -> tuple[str, str]:
    """(kind, why) from a shot's measurements."""
    g, lu, mo, ed, pe = f["green"], f["luma"], f["motion"], f["edges"], f.get("person")
    if lu < 0.2:
        return "dark", f"dark picture (brightness {lu:.2f})"
    if pe is not None and pe > 0.12 and g < 0.45:
        return "close", f"a person fills {pe * 100:.0f}% of the frame"
    if g > 0.42 and ed < 0.035:
        return "close", f"a soft-focus pitch behind (edges {ed:.3f}): a telephoto close-up"
    if g > 0.42:
        if mo > 0.055:
            return "action", f"pitch {g * 100:.0f}% of the frame, fast movement"
        return "wide", f"pitch {g * 100:.0f}% of the frame"
    if g > 0.22 and mo > 0.07:
        return "action", f"pitch {g * 100:.0f}% of the frame, fast movement"
    if ed > 0.065 and g < 0.15:
        return "crowd", f"fine texture all over (edges {ed:.2f}), little pitch"
    return "close", f"large shapes, little pitch ({g * 100:.0f}%)"


def detect(frames) -> tuple[list[tuple[int, int]], list[dict], list[float]]:
    """Cuts in a stream of small frames -> ([(f0, f1)], per-frame measurements, per-frame motion)."""
    hist_prev = small_prev = None
    diffs, meas, motion = [], [], []
    for fr in frames:
        y = (fr.astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32))
        h = np.histogram(y, bins=32, range=(0, 255))[0].astype(np.float32)
        h /= max(1.0, h.sum())
        if small_prev is None:
            d = 0.0
            m = 0.0
        else:
            m = float(np.abs(y - small_prev).mean()) / 255
            d = 0.5 * m + 0.5 * 0.5 * float(np.abs(h - hist_prev).sum())
        diffs.append(d)
        motion.append(m)
        meas.append(measure(fr) if len(meas) % 3 == 0 else None)  # every third frame is plenty to describe
        small_prev, hist_prev = y, h
    n = len(diffs)
    if n == 0:
        return [], [], []
    d = np.array(diffs)
    cuts = [0]
    w = 12
    for i in range(1, n):
        lo, hi = max(0, i - w), min(n, i + w + 1)
        local = np.median(np.r_[d[lo:i], d[i + 1:hi]]) if hi - lo > 1 else 0
        if d[i] > max(0.11, 2.6 * local + 0.02) and i - cuts[-1] >= 6:
            cuts.append(i)
    cuts.append(n)
    return list(zip(cuts[:-1], cuts[1:])), meas, motion


def _person(path: str, t: float) -> float | None:
    """Share of the frame that is a person at t (matte model), or None without it."""
    from . import matte as M
    if not M.available():
        return None
    try:
        out = subprocess.run([ffbin(), "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                              "-vf", f"scale={M.MATTE_W}:-2", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                             capture_output=True, check=True).stdout
        h = len(out) // (M.MATTE_W * 3)
        if h < 8:
            return None
        rgb = np.frombuffer(out[: M.MATTE_W * 3 * h], np.uint8).reshape(h, M.MATTE_W, 3)
        a = M.still(rgb)
        return float((np.asarray(a, np.float32) / 255 > 0.5).mean())
    except Exception:
        return None


def cached(path: str, cache_dir) -> dict | None:
    """The analysis if this file (as it is now) was analysed before, else None. Never decodes."""
    try:
        f = Path(cache_dir) / f"shots-{_key(path)}.json"
    except OSError:
        return None
    return json.loads(f.read_text()) if f.exists() else None


def analyse(path: str, cache_dir, progress=lambda *a: None, duration: float | None = None) -> dict:
    """{"kind": "video", "duration", "shots": [{t0, t1, kind, why, green, luma, sat, motion, edges, person}]}"""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / f"shots-{_key(path)}.json"
    if f.exists():
        return json.loads(f.read_text())
    if path.lower().endswith(IMAGE_EXT):
        im = Image.open(path).convert("RGB")
        small = np.asarray(im.resize((SW, max(1, round(SW * im.height / im.width))), Image.BILINEAR))
        m = measure(small)
        out = {"kind": "image", "duration": None, "width": im.width, "height": im.height,
               "shots": [{"t0": 0.0, "t1": None, "kind": "photo", "why": "a still photo", **m, "motion": 0.0, "person": None}]}
    else:
        def frames():
            for k, fr in enumerate(_frames(path)):
                if duration and k % 125 == 0:
                    progress(min(99, int(100 * k / RATE / duration)))
                yield fr
        spans, meas, motion = detect(frames())
        shots = []
        for f0, f1 in spans:
            t0, t1 = f0 / RATE, f1 / RATE
            if t1 - t0 < MIN_SHOT:
                continue
            ms = [m for m in meas[f0:f1] if m]
            agg = {k: float(np.mean([m[k] for m in ms])) for k in ("green", "luma", "sat", "edges")} if ms else \
                {"green": 0, "luma": 0, "sat": 0, "edges": 0}
            agg["motion"] = float(np.mean(motion[f0 + 1:f1])) if f1 - f0 > 1 else 0.0
            agg["person"] = _person(path, (t0 + t1) / 2)
            kind, why = classify(agg)
            shots.append({"t0": round(t0, 3), "t1": round(t1, 3), "kind": kind, "why": why,
                          **{k: round(v, 4) if isinstance(v, float) else v for k, v in agg.items()}})
        out = {"kind": "video", "duration": round(len(motion) / RATE, 3), "shots": shots}
    tmp = f.with_name(f.stem + ".tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, f)
    return out
