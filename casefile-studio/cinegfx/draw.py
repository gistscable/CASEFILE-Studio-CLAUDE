"""Drawing kit on Pillow. Text and shapes are rendered once into cached RGBA sprites and composited per
frame (alpha_composite at an offset), so a frame costs a few blits instead of re-rasterising type.
Diagonals and circles are supersampled 3x then reduced, so edges stay crisp without any blur filter."""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from .theme import font_path, hexrgb

W, H = 1920, 1080
SS = 3


def scale_of(key: str) -> float:
    """v0.4.64: a font key may carry a text-size scale ("inter-bold@1.1": the look's Text size). 1.0 without one."""
    if "@" not in key:
        return 1.0
    try:
        return float(key.split("@", 1)[1])
    except ValueError:
        return 1.0


def lead(key: str, n: float) -> int:
    """A distance that follows the size of `key`'s text (line steps, the gap under a line): `n` at 100%."""
    s = scale_of(key)
    return n if s == 1.0 else int(round(n * s))


@lru_cache(maxsize=256)
def font(key: str, size: int) -> ImageFont.FreeTypeFont:
    if "@" in key:  # the look's Text size: the same font, scaled
        base = key.split("@", 1)[0]
        return ImageFont.truetype(font_path(base), max(6, int(round(size * scale_of(key)))))
    return ImageFont.truetype(font_path(key), size)


def col(c, a=None):
    if isinstance(c, str):
        c = hexrgb(c)
    if a is not None:
        c = (c[0], c[1], c[2], int(a))
    return c


# v0.4.65 measuring, wrapping and fitting are pure functions of their arguments, cached: a layout that is worked out
# while drawing (legal fitted its case lines on every frame: 88% of its frame time) costs it once, not 24 times a second.
# The results are the same numbers, so every frame is pixel-identical.
@lru_cache(maxsize=16384)
def measure(text: str, key: str, size: int, tracking: float = 0.0):
    f = font(key, size)
    if not tracking:
        l, t, r, b = f.getbbox(text)
        return r, f.getmetrics()
    w = sum(f.getlength(ch) for ch in text) + tracking * size * max(0, len(text) - 1)
    return int(round(w)), f.getmetrics()


@lru_cache(maxsize=2048)
def sprite(text: str, key: str, size: int, color: tuple, tracking: float = 0.0) -> Image.Image:
    """Text as a tight RGBA sprite whose top is the font ascent line (so mixed sizes share baselines)."""
    f = font(key, size)
    asc, desc = f.getmetrics()
    w, _ = measure(text, key, size, tracking)
    im = Image.new("RGBA", (max(1, w + 4), asc + desc + 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if not tracking:
        d.text((0, 0), text, font=f, fill=color)
    else:
        x = 0.0
        for ch in text:
            d.text((x, 0), ch, font=f, fill=color)
            x += f.getlength(ch) + tracking * size
    return im


def wrap(text: str, key: str, size: int, maxw: int, tracking: float = 0.0):
    return list(_wrap(text, key, size, maxw, tracking))  # a fresh list: callers may change theirs


@lru_cache(maxsize=4096)
def _wrap(text: str, key: str, size: int, maxw: int, tracking: float = 0.0):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if measure(trial, key, size, tracking)[0] <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return tuple(lines)


@lru_cache(maxsize=4096)
def fit_size(text: str, key: str, maxw: int, start: int, minimum: int = 18, tracking: float = 0.0, lines: int = 1):
    """Largest size <= start at which `text` fits in `lines` lines of `maxw`."""
    s = start
    while s > minimum:
        if len(wrap(text, key, s, maxw, tracking)) <= lines and all(measure(l, key, s, tracking)[0] <= maxw for l in wrap(text, key, s, maxw, tracking)):
            return s
        s -= 2
    return minimum


def with_alpha(im: Image.Image, a: float) -> Image.Image:
    if a >= 0.999:
        return im
    r, g, b, al = im.split()
    al = al.point(lambda v: int(v * a))
    return Image.merge("RGBA", (r, g, b, al))


def blit(canvas: Image.Image, im: Image.Image, x: float, y: float, alpha: float = 1.0, clip=None):
    """Composite `im` at (x, y). `clip` = (x0, y0, x1, y1) in canvas coords: a hard mask (wipe reveals)."""
    if alpha <= 0.002 or im is None:
        return
    x, y = int(round(x)), int(round(y))
    sx0, sy0, sx1, sy1 = 0, 0, im.width, im.height
    if clip:
        cx0, cy0, cx1, cy1 = (int(round(v)) for v in clip)
        sx0, sy0 = max(sx0, cx0 - x), max(sy0, cy0 - y)
        sx1, sy1 = min(sx1, cx1 - x), min(sy1, cy1 - y)
    # clamp to canvas
    sx0, sy0 = max(sx0, -x), max(sy0, -y)
    sx1, sy1 = min(sx1, canvas.width - x), min(sy1, canvas.height - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    part = im if (sx0, sy0, sx1, sy1) == (0, 0, im.width, im.height) else im.crop((sx0, sy0, sx1, sy1))
    canvas.alpha_composite(with_alpha(part, alpha), (x + sx0, y + sy0))


RECORD = None  # v0.4.64: a list to collect every text drawn (layout checks in the tests); None in use (no cost)


def text(canvas, s, key, size, color, x, y, alpha=1.0, tracking=0.0, anchor="l", clip=None):
    if not s:
        return 0
    sp = sprite(s, key, size, col(color), tracking)
    if anchor == "c":
        x -= sp.width / 2
    elif anchor == "r":
        x -= sp.width
    blit(canvas, sp, x, y, alpha, clip)
    if RECORD is not None and alpha > 0.002:
        RECORD.append((s, key, size, x, y, sp, clip, alpha))
    return sp.width


def rect(canvas, x0, y0, x1, y1, color, alpha=1.0):
    """Axis-aligned filled rect (crisp at 1x). Opaque rects draw directly; translucent ones composite."""
    x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
    if x1 <= x0 or y1 <= y0 or alpha <= 0.002:
        return
    c = col(color)
    a = int(c[3] * alpha)
    if a >= 255:
        ImageDraw.Draw(canvas).rectangle((x0, y0, x1 - 1, y1 - 1), fill=c[:3] + (255,))
    else:
        tile = Image.new("RGBA", (x1 - x0, y1 - y0), c[:3] + (a,))
        blit(canvas, tile, x0, y0)


def outline(canvas, x0, y0, x1, y1, color, width=2, alpha=1.0):
    rect(canvas, x0, y0, x1, y0 + width, color, alpha)
    rect(canvas, x0, y1 - width, x1, y1, color, alpha)
    rect(canvas, x0, y0, x0 + width, y1, color, alpha)
    rect(canvas, x1 - width, y0, x1, y1, color, alpha)


@lru_cache(maxsize=512)
def rounded(w: int, h: int, r: int, fill: tuple, border: tuple | None = None, bw: int = 0) -> Image.Image:
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=fill, outline=border, width=bw * SS if border else 0)
    return big.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=256)
def disc(d: int, fill: tuple, ring: tuple | None = None, rw: int = 0) -> Image.Image:
    big = Image.new("RGBA", (d * SS, d * SS), (0, 0, 0, 0))
    dr = ImageDraw.Draw(big)
    dr.ellipse((0, 0, d * SS - 1, d * SS - 1), fill=fill, outline=ring, width=rw * SS if ring else 0)
    return big.resize((d, d), Image.LANCZOS)


def polyline(canvas, pts, color, width, alpha=1.0, pad=8):
    """Supersampled polyline (route maps, connectors) drawn into a tight tile."""
    if len(pts) < 2:
        return
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0 = int(min(xs)) - pad - width, int(min(ys)) - pad - width
    w, h = int(max(xs)) - x0 + pad + width, int(max(ys)) - y0 + pad + width
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    sp = [((x - x0) * SS, (y - y0) * SS) for x, y in pts]
    d.line(sp, fill=col(color), width=width * SS, joint="curve")
    r = width * SS / 2
    for px, py in (sp[0], sp[-1]):
        d.ellipse((px - r, py - r, px + r, py + r), fill=col(color))
    blit(canvas, big.resize((w, h), Image.LANCZOS), x0, y0, alpha)


def path_point(pts, p):
    """Point at fraction p of a polyline's length, and the truncated polyline up to it."""
    import math
    segs = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(segs) or 1.0
    goal, acc = total * max(0.0, min(1.0, p)), 0.0
    out = [pts[0]]
    for i, s in enumerate(segs):
        if acc + s >= goal:
            f = (goal - acc) / s if s else 0
            q = (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f)
            out.append(q)
            return q, out
        acc += s
        out.append(pts[i + 1])
    return pts[-1], out


# ---------------------------------------------------------------- photos

@lru_cache(maxsize=32)
def _photo_src(path: str, bw: int, bh: int, fx: float, fy: float, headroom: float, sat: float, contrast: float, bright: float):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    # cover-crop around the focus point at the box aspect, with headroom for a push-in
    tw, th = bw * headroom, bh * headroom
    s = max(tw / im.width, th / im.height)
    if s > 1.0:  # never upscale past the source by more than needed; use LANCZOS once
        im = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)), Image.LANCZOS)
        s = 1.0
    cw, ch = tw / s, th / s
    cx = min(max(fx * im.width, cw / 2), im.width - cw / 2)
    cy = min(max(fy * im.height, ch / 2), im.height - ch / 2)
    im = im.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2)))
    im = im.resize((int(tw), int(th)), Image.LANCZOS)
    if sat != 1.0:
        im = ImageEnhance.Color(im).enhance(sat)
    if contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    if bright != 1.0:
        im = ImageEnhance.Brightness(im).enhance(bright)
    return im.convert("RGBA")


def photo(path: str, bw: int, bh: int, focus=(0.5, 0.5), zoom: float = 1.0, headroom: float = 1.12,
          sat: float = 1.0, contrast: float = 1.0, bright: float = 1.0, pan=(0.0, 0.0)) -> Image.Image:
    """The photo cover-cropped to (bw, bh) around `focus`, pushed in by `zoom` (1..headroom): a sharp
    resample of a cached, pre-graded source — never a blur."""
    src = _photo_src(path, bw, bh, focus[0], focus[1], headroom, sat, contrast, bright)
    z = max(1.0, min(zoom, headroom))
    vw, vh = src.width / z, src.height / z
    cx = src.width / 2 + pan[0] * (src.width - vw) / 2
    cy = src.height / 2 + pan[1] * (src.height - vh) / 2
    return src.resize((bw, bh), Image.BICUBIC, box=(cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2))


@lru_cache(maxsize=8)
def gradient(w: int, h: int, c0: tuple, c1: tuple, vertical: bool = True) -> Image.Image:
    """Linear gradient tile (used for legibility scrims instead of blurring the photo)."""
    import numpy as np
    n = h if vertical else w
    t = np.linspace(0, 1, n, dtype=np.float32)[:, None]
    a, b = np.array(c0, np.float32), np.array(c1, np.float32)
    row = (a + (b - a) * t).clip(0, 255).astype("uint8")
    arr = np.repeat(row[:, None, :], w if vertical else h, axis=1)
    if not vertical:
        arr = arr.transpose(1, 0, 2)
    return Image.fromarray(arr.reshape((h, w, 4)), "RGBA")
