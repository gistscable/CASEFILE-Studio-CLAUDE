"""Crop, fill and keyframes for a scene's picture (v0.4.49).

* The crop belongs to the media file (`asset["crop"] = [x0, y0, x1, y1]`,
  fractions of the picture): crop it once and every scene that uses the file
  shows only that part. The original file is never changed.
* Each scene picks how the cropped picture fills the frame (`scene["fit"]`):
  "cover" fills it (edges cut off), "blur" centres the whole cropped picture
  over a darker blur of itself.
* Keyframes (`scene["keyframes"] = [{t, zoom, x, y, ease}]`) are your own
  push-in / pan between points; they replace the fixed photo movement.
  `x`/`y` are the centre of the view (fractions of the frame), `zoom` >= 1.

The numbers are shared with the preview through web/src/effectsSpec.json and
the same maths is in web/src/picture.js, so the preview moves like the export.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

import effects

SPEC = effects.SPEC["picture"]
FITS = [f["id"] for f in SPEC["fits"]]
BLUR = SPEC["over_blur"]
KF = SPEC["keyframes"]


def _num(v, lo, hi, default=None):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(n):
        return default
    return min(hi, max(lo, n))


# ---------------------------------------------------------------- crop

def normalise_crop(value):
    """[x0, y0, x1, y1] (fractions) or None for the whole picture."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    nums = [_num(n, 0.0, 1.0) for n in value]
    if any(n is None for n in nums):
        return None
    x0, y0, x1, y1 = nums
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    m = SPEC["crop_min"]
    if x1 - x0 < m or y1 - y0 < m:
        return None
    box = [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]
    return None if box == [0.0, 0.0, 1.0, 1.0] else box


def crop_of(asset):
    return normalise_crop((asset or {}).get("crop"))


def crop_filter(box):
    if not box:
        return ""
    x0, y0, x1, y1 = box
    return f"crop=w=iw*{x1 - x0:.4f}:h=ih*{y1 - y0:.4f}:x=iw*{x0:.4f}:y=ih*{y0:.4f},"


def detect_crop(path):
    """Automatic: cut away black bars and plain borders around the real photo.
    Rows/columns at the edges that are flat (one colour) or near-black are
    removed. Busy graphics (news panels, logos) need the box dragged by hand."""
    a = SPEC["auto_crop"]
    with Image.open(path) as im:
        im = im.convert("L")
        im.thumbnail((640, 640))
        g = np.asarray(im, dtype=np.float32)
    h, w = g.shape
    if h < 8 or w < 8:
        return None
    top, bottom, left, right = 0, h, 0, w

    def flat(line, ref):
        return (line.std() < a["flat"] and abs(line.mean() - ref) < a["same"]) or line.mean() < a["black"] and np.percentile(line, 95) < a["black"] * 2

    ref = g[0].mean()
    while top < bottom - 8 and flat(g[top, left:right], ref):
        top += 1
    ref = g[h - 1].mean()
    while bottom > top + 8 and flat(g[bottom - 1, left:right], ref):
        bottom -= 1
    ref = g[top:bottom, 0].mean()
    while left < right - 8 and flat(g[top:bottom, left], ref):
        left += 1
    ref = g[top:bottom, w - 1].mean()
    while right > left + 8 and flat(g[top:bottom, right - 1], ref):
        right -= 1
    return normalise_crop([left / w, top / h, right / w, bottom / h])


def detect_crop_video(path, duration, work):
    """Automatic crop for a clip: the union of the boxes of a few frames."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    boxes = []
    for k, frac in enumerate((0.2, 0.5, 0.8)):
        out = work / f"autocrop{k}.png"
        at = max(0.0, float(duration or 0) * frac)
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", str(path),
                        "-frames:v", "1", "-vf", "scale='min(640,iw)':-2", str(out)], capture_output=True, timeout=60)
        if out.exists():
            boxes.append(detect_crop(out) or [0.0, 0.0, 1.0, 1.0])
    if not boxes:
        return None
    return normalise_crop([min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)])


# ---------------------------------------------------------------- fit

def fit_of(project, scene, asset=None):
    """"cover", "blur" (photo over a blur of itself) or "legacy-blur" (the
    9:16 blurred background from v0.4.28, when the scene has not chosen).
    A cropped file shows over a blur of itself unless the scene picks cover."""
    f = (scene or {}).get("fit")
    if f in FITS:
        return f
    if effects.aspect_of(project) == "9:16" and effects.fit_of(project) == "blur":
        return "legacy-blur"
    return "blur" if crop_of(asset) else "cover"


def fit_filter(fit, width, height):
    """FFmpeg filters turning the (cropped) picture into a width x height frame."""
    cover = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    if fit == "legacy-blur":
        return (
            f"split[fa][fb];[fa]{cover},"
            f"boxblur=24:2,eq=brightness=-0.07:saturation=0.85,setsar=1[bgv];"
            f"[fb]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[fgv];"
            f"[bgv][fgv]overlay=(W-w)/2:(H-h)/2"
        )
    if fit == "blur":
        rad = max(2, min(round(min(width, height) * BLUR["radius"]), min(width, height) // 4 - 1))
        iw, ih = round(width * BLUR["inset"] / 2) * 2, round(height * BLUR["inset"] / 2) * 2
        return (
            f"split[fa][fb];[fa]{cover},"
            f"boxblur={rad}:2,eq=brightness={BLUR['brightness']}:saturation={BLUR['saturation']},setsar=1[bgv];"
            f"[fb]scale={iw}:{ih}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[fgv];"
            f"[bgv][fgv]overlay=(W-w)/2:(H-h)/2"
        )
    return cover


# ---------------------------------------------------------------- keyframes

def ease(u, kind):
    u = min(1.0, max(0.0, u))
    return u if kind == "linear" else u * u * (3 - 2 * u)


def interpolate(keys, t, fields):
    """Values of `fields` at time t: held before the first and after the last
    keyframe; between two, linear or smooth (the earlier key's `ease`)."""
    if not keys:
        return None
    if t <= keys[0]["t"]:
        return {f: keys[0][f] for f in fields}
    for a, b in zip(keys, keys[1:]):
        if t < b["t"]:
            span = b["t"] - a["t"]
            e = ease((t - a["t"]) / span if span > 0 else 1.0, a.get("ease"))
            return {f: a[f] + (b[f] - a[f]) * e for f in fields}
    return {f: keys[-1][f] for f in fields}


def expr(keys, field, T):
    """The same interpolation as an FFmpeg expression of the time `T`."""
    if not keys:
        return "0"
    out = f"{keys[-1][field]:.5f}"
    for a, b in reversed(list(zip(keys, keys[1:]))):
        span = max(1e-6, b["t"] - a["t"])
        u = f"(({T})-{a['t']:.4f})/{span:.4f}"
        e = u if a.get("ease") == "linear" else f"({u})*({u})*(3-2*({u}))"
        out = f"if(lt({T},{b['t']:.4f}),{a[field]:.5f}+({b[field] - a[field]:.5f})*{e},{out})"
    return f"if(lt({T},{keys[0]['t']:.4f}),{keys[0][field]:.5f},{out})"


def _clamp_centre(c, z):
    half = 0.5 / z
    return min(1 - half, max(half, c))


def normalise_keyframes(value, length=600.0):
    if not isinstance(value, list):
        return []
    zl, zh = KF["zoom"]
    out = {}
    for k in value[: KF["max"] * 2]:
        if not isinstance(k, dict):
            continue
        t = _num(k.get("t"), 0.0, float(length))
        z = _num(k.get("zoom"), zl, zh, 1.0)
        if t is None:
            continue
        x = _clamp_centre(_num(k.get("x"), 0.0, 1.0, 0.5), z)
        y = _clamp_centre(_num(k.get("y"), 0.0, 1.0, 0.5), z)
        out[round(t, 3)] = {"t": round(t, 3), "zoom": round(z, 4), "x": round(x, 4), "y": round(y, 4),
                            "ease": "linear" if k.get("ease") == "linear" else "smooth"}
    return [out[t] for t in sorted(out)][: KF["max"]]


def camera_at(keys, t):
    """{zoom, x, y} at t seconds into the scene (preview: picture.js cameraAt)."""
    return interpolate(keys, t, ("zoom", "x", "y")) or {"zoom": 1.0, "x": 0.5, "y": 0.5}


def camera_filter(keys, width, height, frames, still):
    """zoompan following the keyframes. `on` is the output frame number, so
    `on/FPS` is the time in the scene for a still (d=frames) and a clip (d=1)."""
    fps = 24
    T = f"on/{fps}"
    z = expr(keys, "zoom", T)
    x = f"({expr(keys, 'x', T)})*iw-iw/zoom/2"
    y = f"({expr(keys, 'y', T)})*ih-ih/zoom/2"
    d = frames if still else 1
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={d}:s={width}x{height}:fps={fps}"
