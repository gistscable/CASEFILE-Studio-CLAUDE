"""Type for the sports editorial look: bold condensed caps in cool white (white -> pale blue gradient) with a
soft dark shadow; small labels in condensed semibold, cream/yellow used only as an accent.
Sprites are rendered once and cached; reveals (masked wipe, letters, scramble) only crop or re-alpha them."""
from __future__ import annotations

import random
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..theme import font_path

COOL = ((255, 255, 255), (198, 222, 244))      # top -> bottom
WHITE = ((248, 250, 252), (232, 238, 246))
CREAM = ((246, 232, 196), (236, 214, 168))
YELLOW = ((255, 214, 92), (240, 190, 60))
STYLES = {"cool": COOL, "white": WHITE, "cream": CREAM, "yellow": YELLOW}
GLYPHS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789&#%"


@lru_cache(maxsize=64)
def font(key: str, size: int):
    return ImageFont.truetype(font_path(key), int(size))


@lru_cache(maxsize=256)
def cap_height(key: str, size: int) -> float:
    b = font(key, size).getbbox("H")
    return b[3] - b[1]


def size_for_cap(key: str, cap_px: float) -> int:
    """Font size whose capital height is cap_px."""
    ref = 200
    return max(8, int(round(ref * cap_px / cap_height(key, ref))))


def advance(text: str, key: str, size: int, tracking: float = 0.0) -> float:
    f = font(key, size)
    if not tracking:
        return f.getlength(text)
    return sum(f.getlength(c) for c in text) + tracking * max(0, len(text) - 1)


def slots(text: str, key: str, size: int, tracking: float = 0.0):
    """x offset of each character (kerning-free, so scrambled glyphs can sit in fixed slots)."""
    f = font(key, size)
    xs, x = [], 0.0
    for c in text:
        xs.append(x)
        x += f.getlength(c) + tracking
    return xs, x - tracking if text else 0.0


@lru_cache(maxsize=512)
def _mask(text: str, key: str, size: int, tracking: float):
    """L-mode mask of the text; returns (mask, ascent offset). Box: x from 0, y so that cap top ~ PAD."""
    f = font(key, size)
    asc, desc = f.getmetrics()
    w = int(advance(text, key, size, tracking)) + 4
    h = asc + desc
    m = Image.new("L", (max(1, w), max(1, h)), 0)
    d = ImageDraw.Draw(m)
    if tracking:
        x = 0.0
        for c in text:
            d.text((x, 0), c, font=f, fill=255)
            x += f.getlength(c) + tracking
    else:
        d.text((0, 0), text, font=f, fill=255)
    top = f.getbbox("H")[1]
    return m, top


def _gradient(w, h, c0, c1, y0, y1):
    """Vertical gradient between rows y0..y1 (cap top..baseline), clamped outside."""
    ys = np.clip((np.arange(h, dtype=np.float32) - y0) / max(1, (y1 - y0)), 0, 1)[:, None]
    c0, c1 = np.array(c0, np.float32), np.array(c1, np.float32)
    g = c0 + (c1 - c0) * ys[..., None]
    return np.broadcast_to(g, (h, w, 3))


def _falloff(m, r):
    """A soft shadow without any blur filter (the engine has none): the mask grown one pixel at a time, rings
    stacked with falling opacity, so the shade fades away from the letter edges."""
    acc = m * 0.0
    cur = m
    steps = max(1, int(r))
    for k in range(steps):
        g = cur.copy()
        g[1:, :] = np.maximum(g[1:, :], cur[:-1, :])
        g[:-1, :] = np.maximum(g[:-1, :], cur[1:, :])
        g[:, 1:] = np.maximum(g[:, 1:], g[:, :-1].copy())
        g[:, :-1] = np.maximum(g[:, :-1], g[:, 1:].copy())
        cur = g
        acc += cur * (1 - k / steps) ** 2
    return np.clip(acc / (steps / 3.0), 0, 1) * 0.85


@lru_cache(maxsize=256)
def sprite(text: str, key: str, size: int, style: str = "cool", tracking: float = 0.0, shadow: float = 0.55,
           blur: int | None = None):
    """RGBA sprite with soft shadow. Returns (image, (ox, oy)) where (ox, oy) is where the text's cap-top-left
    sits inside the sprite (so callers position by cap top / left edge)."""
    m, top = _mask(text, key, size, tracking)
    c0, c1 = STYLES[style]
    blur = blur if blur is not None else max(4, size // 14)
    pad = blur * 3
    W, H = m.width + pad * 2, m.height + pad * 2
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if shadow > 0:
        sh = Image.new("L", (W, H), 0)
        sh.paste(m, (pad, pad + max(2, size // 40)))
        sa = (_falloff(np.asarray(sh, np.float32) / 255, blur) * 255 * shadow).astype(np.uint8)
        shadow_img = np.zeros((H, W, 4), np.uint8)
        shadow_img[..., 0:3] = (8, 10, 14)
        shadow_img[..., 3] = sa
        out = Image.fromarray(shadow_img, "RGBA")
    cap = cap_height(key, size)
    grad = _gradient(m.width, m.height, c0, c1, top, top + cap)
    fill = np.dstack([grad.astype(np.uint8), np.asarray(m)])
    out.alpha_composite(Image.fromarray(np.ascontiguousarray(fill), "RGBA"), (pad, pad))
    return out, (pad, pad + top)


def place(canvas: Image.Image, spr, x: float, y: float, alpha: float = 1.0, scale: float = 1.0, crop=None):
    """Put a sprite so the text's cap-top-left lands at (x, y). crop = (x0, x1) visible fraction of the text
    width (masked wipe), with a short soft edge."""
    img, (ox, oy) = spr
    if alpha <= 0.003:
        return
    if scale != 1.0:
        w, h = max(1, int(img.width * scale)), max(1, int(img.height * scale))
        img = img.resize((w, h), Image.BICUBIC)
        ox, oy = ox * scale, oy * scale
    if crop is not None:
        a = np.asarray(img).copy()
        tw = img.width - 2 * ox
        x0 = ox + crop[0] * tw
        x1 = ox + crop[1] * tw
        cols = np.arange(img.width, dtype=np.float32)
        soft = max(2.0, tw * 0.02)
        ramp = np.clip((x1 - cols) / soft, 0, 1) * np.clip((cols - x0) / soft + (1 if crop[0] <= 0 else 0), 0, 1)
        a[..., 3] = (a[..., 3] * ramp[None, :]).astype(np.uint8)
        img = Image.fromarray(a, "RGBA")
    if alpha < 1.0:
        a = np.asarray(img).copy()
        a[..., 3] = (a[..., 3] * alpha).astype(np.uint8)
        img = Image.fromarray(a, "RGBA")
    canvas.alpha_composite(img, (int(round(x - ox)), int(round(y - oy))))


def letters(canvas, text, key, size, x, y, style="cool", tracking=0.0, times=None, t=0.0, dur=0.12, rise=0,
            anchor="l", shadow=0.5, alpha=1.0):
    """Letter-by-letter soft reveal; times[i] = when letter i starts appearing."""
    xs, total = slots(text, key, size, tracking)
    if anchor == "c":
        x -= total / 2
    elif anchor == "r":
        x -= total
    for i, c in enumerate(text):
        if c == " ":
            continue
        p = 1.0 if times is None else min(1.0, max(0.0, (t - times[i]) / dur))
        if p <= 0:
            continue
        place(canvas, sprite(c, key, size, style, 0.0, shadow), x + xs[i], y + rise * (1 - p), alpha=p * alpha)
    return total


def scramble_text(text: str, t: float, t0: float, dur: float, seed: int, fps: int = 25):
    """The reference's character-scramble: characters lock left->right over `dur`; ahead of the lock front a
    short tail of random glyphs flickers (new glyphs every frame). Returns (string, locked_count)."""
    if t < t0:
        return "", 0
    p = min(1.0, (t - t0) / dur)
    n = len(text)
    locked = int(p * n + 1e-6)
    tail = min(n - locked, max(2, int(n * 0.45 * (1 - p)) + 2)) if p < 1 else 0
    frame = int(t * fps)
    r = random.Random(seed * 7919 + frame)
    out = []
    for i, c in enumerate(text):
        if i < locked or c == " ":
            out.append(c if i < locked or c == " " else " ")
        elif i < locked + tail:
            out.append(r.choice(GLYPHS))
        else:
            out.append(" ")
    return "".join(out), locked


def scramble(canvas, text, key, size, x, y, t, t0, dur, seed, style="cool", tracking=0.0, fps=25, alpha=1.0):
    s, locked = scramble_text(text, t, t0, dur, seed, fps)
    xs, _ = slots(text, key, size, tracking)
    for i, c in enumerate(s):
        if c == " ":
            continue
        st = style if i < locked else ("cool" if style != "yellow" else "yellow")
        a = alpha if i < locked else alpha * 0.85
        place(canvas, sprite(c, key, size, st, 0.0, 0.8, max(5, size // 6)), x + xs[i], y, alpha=a)
    return locked
