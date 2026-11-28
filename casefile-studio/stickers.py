"""Stickers over the picture (v0.4.49).

`project["stickers"] = [{id, kind, asset_id?, start, length, x, y, size,
opacity, keyframes: [{t, x, y, size, opacity, ease}]}]`

* `kind` is a built-in sticker (effectsSpec.json stickers.catalog) or
  "image": one of your own pictures (`asset_id`, a PNG with transparency
  works best).
* `x`/`y` are the sticker's centre (fractions of the frame), `size` its width
  (fraction of the frame width). With keyframes, those follow the keyframes
  instead (t = seconds after the sticker starts).
* Built-in stickers are drawn here with Pillow, for the export and, through
  /api/stickers/<kind>/<frame>.png, for the preview: they look the same.

v0.4.72 "Point & mark":
* `text` (stickers whose catalog entry has a `text`): your words instead of
  the default ("LOOK HERE", "SHARE" ...). Stored only when you changed it.
* `ratio` (catalog `ratio: true`): width / height, so a box, a black bar or a
  blur can be wide or tall. Stored only when it differs from the default.
* `strength` (regions): how dark the spotlight is / how strong the blur.
* Regions (catalog `region`): "spot" darkens the whole frame except an
  ellipse; "blur" blurs inside an ellipse. They are drawn full-frame for each
  output frame (position baked in), so no overlay maths: a full-frame dark
  layer for the spotlight, a full-frame mask for the blur.
* Keyframes: up to `keyframes_max` (120) so a sticker that follows something
  (tracked in the editor) keeps a smooth path.
"""
from __future__ import annotations

import math
import os
import re
import shutil
from functools import lru_cache
from pathlib import Path

import hashlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import effects
import picture

SPEC = effects.SPEC["stickers"]
CATALOG = {c["id"]: c for c in SPEC["catalog"]}
FPS = 24
SS = 3  # drawn 3x larger, then reduced: smooth edges
FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/TTF"), Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]

RED = (230, 33, 23, 255)
GREY = (96, 96, 96, 255)
WHITE = (255, 255, 255, 255)
DARK = (24, 24, 28, 255)
BLUE = (37, 110, 230, 255)
YELLOW = (250, 190, 30, 255)
PEN = (226, 36, 43, 255)


@lru_cache(maxsize=None)
def _font_path():
    import renderer  # the same bundled font as the captions and titles
    return renderer.BOLD


def font(size):
    try:
        return ImageFont.truetype(_font_path(), max(6, int(size)))
    except (OSError, ImportError):
        return ImageFont.load_default()


# ---------------------------------------------------------------- the data

def _num(v, lo, hi, default):
    n = picture._num(v, lo, hi, None)
    return default if n is None else n


def normalise(value, image_assets=None):
    out = []
    lim = SPEC["limits"]
    if not isinstance(value, list):
        return out
    for i, s in enumerate(value[: SPEC["max"]]):
        if not isinstance(s, dict):
            continue
        kind = s.get("kind")
        if kind == "image":
            aid = s.get("asset_id")
            if not aid or (image_assets is not None and aid not in image_assets):
                continue
        elif kind not in CATALOG:
            continue
        cat = CATALOG.get(kind, {"size": 0.25, "x": 0.5, "y": 0.5})
        length = _num(s.get("length"), *lim["length"], SPEC["defaults"]["length"])
        st = {
            "id": re.sub(r"[^\w-]", "", str(s.get("id") or ""))[:24] or f"st{i + 1}",
            "kind": kind,
            "start": round(_num(s.get("start"), 0.0, 86400.0, 0.0), 3),
            "length": round(length, 3),
            "x": round(_num(s.get("x"), *lim["xy"], cat["x"]), 4),
            "y": round(_num(s.get("y"), *lim["xy"], cat["y"]), 4),
            "size": round(_num(s.get("size"), *lim["size"], cat["size"]), 4),
            "opacity": round(_num(s.get("opacity"), *lim["opacity"], SPEC["defaults"]["opacity"]), 3),
        }
        if kind == "image":
            st["asset_id"] = str(s["asset_id"])
        _extras(st, s, cat)
        st["keyframes"] = normalise_keyframes(s.get("keyframes"), length, st)
        out.append(st)
    return out


def clean_text(v):
    """Your words on a sticker: one line, no control characters, at most limits.text."""
    if not isinstance(v, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", v)).strip()[: SPEC["limits"]["text"]]


def _extras(st, s, cat):
    """v0.4.72 text / ratio / strength, kept only when they differ from the default
    (so older projects normalise exactly as before)."""
    lim = SPEC["limits"]
    if cat.get("text"):
        t = clean_text(s.get("text"))
        if t and t != cat["text"]:
            st["text"] = t
    if cat.get("ratio"):
        r = _num(s.get("ratio"), *lim["ratio"], None)
        if r is not None and abs(r - cat["aspect"]) > 1e-4:
            st["ratio"] = round(r, 4)
    if cat.get("region"):
        g = _num(s.get("strength"), *lim["strength"], None)
        if g is not None and abs(g - SPEC["defaults"]["strength"]) > 1e-4:
            st["strength"] = round(g, 3)


def text_of(st):
    c = CATALOG.get(st.get("kind")) or {}
    return st.get("text") or c.get("text") or ""


def strength_of(st):
    return float(st.get("strength") or SPEC["defaults"]["strength"])


def normalise_keyframes(value, length, base):
    if not isinstance(value, list):
        return []
    lim = SPEC["limits"]
    out = {}
    for k in value[: SPEC["keyframes_max"] * 2]:
        if not isinstance(k, dict):
            continue
        t = picture._num(k.get("t"), 0.0, float(length), None)
        if t is None:
            continue
        out[round(t, 3)] = {
            "t": round(t, 3),
            "x": round(_num(k.get("x"), *lim["xy"], base["x"]), 4),
            "y": round(_num(k.get("y"), *lim["xy"], base["y"]), 4),
            "size": round(_num(k.get("size"), *lim["size"], base["size"]), 4),
            "opacity": round(_num(k.get("opacity"), *lim["opacity"], base["opacity"]), 3),
            "ease": "linear" if k.get("ease") == "linear" else "smooth",
        }
    return [out[t] for t in sorted(out)][: SPEC["keyframes_max"]]


def sample(st, local):
    """{x, y, size, opacity} `local` seconds after the sticker starts. It pops
    in (so it shows right where you added it) and fades out quickly at its end
    (preview: stickers.js stickerAt)."""
    v = picture.interpolate(st["keyframes"], local, ("x", "y", "size", "opacity")) or {k: st[k] for k in ("x", "y", "size", "opacity")}
    f = min(SPEC["fade"], st["length"] / 4)
    a = 1.0
    if f > 0:
        a = min(1.0, max(0.0, (st["length"] - local) / f))
    return {**v, "opacity": v["opacity"] * a}


def aspect(st, assets):
    if st["kind"] == "image":
        a = (assets or {}).get(st.get("asset_id")) or {}
        return float(a.get("width") or 1) / float(a.get("height") or 1)
    return float(st.get("ratio") or CATALOG[st["kind"]]["aspect"])


def cycle_frames(kind):
    c = CATALOG.get(kind)
    return max(1, round(c["cycle"] * FPS)) if c and c.get("animated") else 1


# ---------------------------------------------------------------- drawing

class Pen:
    """Draws in a 1000-unit-wide box, scaled to the pixels asked for."""

    def __init__(self, width_px, aspect):
        self.k = width_px * SS / 1000.0
        self.w = 1000.0
        self.h = 1000.0 / aspect
        self.im = Image.new("RGBA", (max(1, round(width_px * SS)), max(1, round(width_px * SS / aspect))), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def p(self, *xy):
        return [v * self.k for v in xy]

    def rr(self, x0, y0, x1, y1, r, fill, outline=None, width=0):
        self.d.rounded_rectangle(self.p(x0, y0, x1, y1), radius=r * self.k, fill=fill, outline=outline, width=round(width * self.k))

    def ellipse(self, x0, y0, x1, y1, fill=None, outline=None, width=0):
        self.d.ellipse(self.p(x0, y0, x1, y1), fill=fill, outline=outline, width=round(width * self.k))

    def poly(self, pts, fill):
        self.d.polygon([(x * self.k, y * self.k) for x, y in pts], fill=fill)

    def stroke(self, pts, colour, width):
        q = [(x * self.k, y * self.k) for x, y in pts]
        self.d.line(q, fill=colour, width=max(1, round(width * self.k)), joint="curve")
        r = width * self.k / 2
        for x, y in (q[0], q[-1]):
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=colour)

    def text(self, cx, cy, s, size, colour, max_w=None):
        f = font(size * self.k)
        if max_w:
            while f.getlength(s) > max_w * self.k and f.size > 8:
                f = font(f.size * 0.92)
        self.d.text((cx * self.k, cy * self.k), s, fill=colour, font=f, anchor="mm")

    def paste(self, layer, x, y):
        self.im.alpha_composite(layer, (round(x * self.k), round(y * self.k)))

    def done(self, width_px):
        w = max(1, round(width_px))
        h = max(1, round(width_px * self.h / self.w))
        return self.im.resize((w, h), Image.LANCZOS)


def icon(name, box, colour, angle=0.0, scale=1.0, k=1.0):
    """A small icon (thumb, bell, share arrow) drawn in a 100-unit box of
    `box` units, as its own layer (so it can swing or pop)."""
    px = max(4, round(box * k))
    big = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    u = px / 100.0 * scale
    o = px / 2 - 50 * u

    def P(pts):
        return [(o + x * u, o + y * u) for x, y in pts]

    def B(x0, y0, x1, y1):
        return [o + x0 * u, o + y0 * u, o + x1 * u, o + y1 * u]

    if name == "thumb":
        d.rounded_rectangle(B(8, 44, 27, 92), radius=4 * u, fill=colour)
        d.rounded_rectangle(B(33, 42, 88, 92), radius=11 * u, fill=colour)
        d.polygon(P([(33, 50), (44, 14), (52, 9), (60, 14), (60, 44)]), fill=colour)
        d.ellipse(B(44, 6, 62, 24), fill=colour)
        line = (0, 0, 0, 0)
        for yy in (58, 70, 81):
            d.line(P([(62, yy), (90, yy)]), fill=line, width=max(1, round(3 * u)))
    elif name == "bell":
        d.ellipse(B(44, 6, 56, 18), fill=colour)
        d.chord(B(22, 14, 78, 70), 180, 360, fill=colour)
        d.polygon(P([(22, 42), (78, 42), (82, 70), (90, 78), (10, 78), (18, 70)]), fill=colour)
        d.ellipse(B(41, 78, 59, 95), fill=colour)
    elif name == "share":
        d.polygon(P([(58, 18), (94, 48), (58, 78), (58, 60)]), fill=colour)
        d.polygon(P([(58, 36), (58, 60), (36, 60), (20, 70), (8, 86), (12, 62), (28, 44)]), fill=colour)
    if angle:
        big = big.rotate(angle, resample=Image.BICUBIC, center=(px / 2, px * 0.1))
    return big


def _pop(t, at, d=0.35, amount=0.25):
    if at <= t < at + d:
        return 1 + amount * math.sin(math.pi * (t - at) / d)
    return 1.0


def _wiggle(t, a, b, deg=22):
    if a <= t < b:
        return deg * math.sin((t - a) * 2 * math.pi * 4) * (1 - (t - a) / (b - a))
    return 0.0


def _cursor(pen, x, y, size, pressed):
    s = size * (0.85 if pressed else 1.0) / 20.0
    pts = [(0, 0), (0, 17), (4.2, 13.2), (7, 19.5), (9.6, 18.4), (6.9, 12.2), (12.2, 12.2)]
    q = [((x + px * s) * pen.k, (y + py * s) * pen.k) for px, py in pts]
    pen.d.polygon(q, fill=WHITE, outline=(0, 0, 0, 255), width=max(1, round(1.2 * s * pen.k)))


def draw(kind, t, width_px, text=None, ratio=None):
    """The sticker `t` seconds into its animation, `width_px` wide (RGBA).
    `text`: your words (stickers with a catalog `text`); `ratio`: width/height."""
    c = CATALOG[kind]
    if c.get("animated") and c["cycle"] > 0:
        t = t % c["cycle"]
    words = clean_text(text) or c.get("text") or ""
    pen = Pen(width_px, float(ratio) if ratio and c.get("ratio") else c["aspect"])
    k = pen.k
    H = pen.h
    if kind == "subscribe-click":
        clicked = t >= 1.1
        sc = 0.95 if 1.0 <= t < 1.15 else 1.0
        cx, cy, w, h = 400, H / 2, 720 * sc, 150 * sc
        pen.rr(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, h / 2, GREY if clicked else RED)
        pen.text(cx, cy + 2, "SUBSCRIBED" if clicked else "SUBSCRIBE", 64 * sc, WHITE, max_w=w - 70)
        pen.ellipse(805, cy - 75, 955, cy + 75, fill=WHITE)
        pen.ellipse(815, cy - 65, 945, cy + 65, fill=GREY)
        pen.paste(icon("bell", 110, WHITE, _wiggle(t, 1.4, 2.3), k=k), 825, cy - 55)
        if t < 1.7:
            m = min(1.0, max(0.0, (t - 0.2) / 0.7))
            m = m * m * (3 - 2 * m)
            _cursor(pen, 760 + (420 - 760) * m, H + 10 + (cy - H - 10) * m, 95, 1.0 <= t < 1.15)
    elif kind == "like-subscribe-bell":
        clicked = t >= 1.4
        pen.rr(10, 20, 990, H - 20, 26, WHITE)
        th = _pop(t, 0.4)
        pen.paste(icon("thumb", 130 * th, BLUE, k=k), 95 - 65 * th, H / 2 - 65 * th)
        pen.rr(200, H / 2 - 48, 800, H / 2 + 48, 48, GREY if clicked else RED)
        pen.text(500, H / 2 + 2, "SUBSCRIBED" if clicked else "SUBSCRIBE", 46, WHITE, max_w=520)
        pen.paste(icon("bell", 130, YELLOW, _wiggle(t, 1.8, 2.8), k=k), 840, H / 2 - 65)
    elif kind == "subscribed":
        pen.rr(10, 10, 990, H - 10, 22, RED)
        pen.paste(icon("thumb", 110, WHITE, k=k), 50, H / 2 - 55)
        pen.text(500, H / 2 + 3, words, 70, WHITE, max_w=640)
        pen.paste(icon("bell", 110, WHITE, k=k), 840, H / 2 - 55)
    elif kind == "bell":
        pen.ellipse(40, 40, 960, 960, fill=YELLOW)
        pen.paste(icon("bell", 600, WHITE, _wiggle(t, 0.0, 0.9, 26), k=k), 200, 190)
    elif kind == "like":
        pen.ellipse(40, 40, 960, 960, fill=BLUE)
        pen.paste(icon("thumb", 560, WHITE, k=k), 210, 200)
    elif kind == "share":
        pen.rr(10, 10, 990, H - 10, (H - 20) / 2, WHITE)
        pen.paste(icon("share", 150, DARK, k=k), 130, H / 2 - 75)
        pen.text(600, H / 2 + 3, words, 92, DARK, max_w=520)
    elif kind == "comment":
        top, bot = 10, H - 70
        pen.rr(10, top, 990, bot, 40, WHITE)
        pen.poly([(90, bot - 10), (80, H - 8), (200, bot - 10)], WHITE)
        for i in range(3):
            pen.ellipse(85 + i * 70, (top + bot) / 2 - 24, 133 + i * 70, (top + bot) / 2 + 24, fill=BLUE)
        pen.text(640, (top + bot) / 2 + 3, words, 84, DARK, max_w=560)
    elif kind in ("arrow-ne", "arrow-nw"):
        p0, p1, p2 = (110, H - 70), (400, 170), (850, 150)
        pts = [((1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * p1[0] + u * u * p2[0], (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * p1[1] + u * u * p2[1])
               for u in (i / 40 for i in range(41))]
        pen.stroke(pts, PEN, 44)
        ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        for side in (-1, 1):
            a = ang + math.pi - side * 0.62
            pen.stroke([p2, (p2[0] + 190 * math.cos(a), p2[1] + 190 * math.sin(a))], PEN, 44)
        if kind == "arrow-nw":
            return ImageOps.mirror(pen.done(width_px))
    elif kind == "circle":
        cx, cy, rx, ry = 500, H / 2, 440, H / 2 - 50
        pts = []
        for i in range(121):
            a = math.radians(200 + 385 * i / 120)
            wob = 1 + 0.035 * (i / 120) + 0.012 * math.sin(i / 7)
            pts.append((cx + rx * wob * math.cos(a), cy + ry * wob * math.sin(a)))
        pen.stroke(pts, PEN, 30)
    elif kind == "rec-frame":
        m, L, s = 40, 120, 16
        for x, y, dx, dy in ((m, m, 1, 1), (1000 - m, m, -1, 1), (m, H - m, 1, -1), (1000 - m, H - m, -1, -1)):
            pen.stroke([(x, y + dy * L), (x, y), (x + dx * L, y)], WHITE, s)
        if t < 0.6:
            pen.ellipse(m + 45, m + 40, m + 85, m + 80, fill=(235, 30, 30, 255))
        pen.text(m + 150, m + 61, words, 40, WHITE)
    elif kind == "spotlight":  # the tile; the export draws the region full-frame (region_frame)
        pen.rr(0, 0, 1000, H, 60, (16, 16, 19, 255))
        glow = Image.new("RGBA", pen.im.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(pen.p(260, H * 0.2, 740, H * 0.8), fill=(255, 238, 205, 255))
        pen.im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(40 * k)))
    elif kind == "blur":  # the tile
        pen.rr(0, 0, 1000, H, 60, (92, 96, 104, 255))
        for i, col in enumerate(((230, 190, 160, 255), (70, 60, 55, 255), (200, 200, 210, 255))):
            pen.ellipse(220 + i * 150, H * 0.25 + i * 60, 520 + i * 150, H * 0.65 + i * 60, fill=col)
        pen.im = pen.im.filter(ImageFilter.GaussianBlur(70 * k))
        pen.d = ImageDraw.Draw(pen.im)
        pen.rr(0, 0, 1000, H, 60, None, outline=(255, 255, 255, 255), width=14)
    elif kind == "block":
        pen.rr(0, 0, 1000, H, min(1000, H) * 0.06, (10, 10, 12, 255))
    elif kind == "box":
        sw = 26
        pen.rr(sw / 2, sw / 2, 1000 - sw / 2, H - sw / 2, min(1000, H) * 0.06, None, outline=PEN, width=sw)
    elif kind == "ring":
        u = t / c["cycle"]
        cx, cy = 500, H / 2
        r0 = 290
        r1 = r0 + 190 * u
        a = round(255 * (1 - u) ** 1.4)
        if a > 0:
            pen.ellipse(cx - r1, cy - r1, cx + r1, cy + r1, outline=(PEN[0], PEN[1], PEN[2], a), width=26)
        pen.ellipse(cx - r0, cy - r0, cx + r0, cy + r0, outline=PEN, width=40)
        pen.ellipse(cx - 60, cy - 60, cx + 60, cy + 60, fill=PEN)
    elif kind == "pointer":
        b = 30 + 150 * (0.5 - 0.5 * math.cos(2 * math.pi * t / c["cycle"]))
        tip = H - 200 + b
        pts = [(380, b), (620, b), (620, tip - 380), (860, tip - 380), (500, tip), (140, tip - 380), (380, tip - 380)]
        pen.d.polygon([(x * k, y * k) for x, y in pts], fill=PEN, outline=WHITE, width=max(1, round(34 * k)))
    elif kind == "callout":
        bot = H - 92
        pen.rr(8, 8, 992, bot, 34, WHITE)
        pen.poly([(110, bot - 6), (90, H - 4), (250, bot - 6)], WHITE)
        pen.rr(8, 8, 40, bot, 16, PEN)
        pen.text(520, bot / 2 + 6, words, min(118, bot * 0.52), DARK, max_w=860)
    elif kind == "label":
        pen.rr(0, 0, 1000, H, 22, (18, 18, 22, 236))
        pen.rr(0, 0, 44, H, 14, YELLOW)
        pen.text(530, H / 2 + 4, words, min(124, H * 0.48), WHITE, max_w=850)
    elif kind == "waveform":
        n = 31
        for i in range(n):
            env = 0.25 + 0.75 * math.sin(math.pi * (i + 0.5) / n) ** 1.5
            amp = env * (0.45 + 0.55 * abs(math.sin(2 * math.pi * t / c["cycle"] * 2 + i * 0.9)))
            x = 30 + i * (940 / (n - 1))
            hh = (H - 30) * amp / 2
            pen.rr(x - 9, H / 2 - hh, x + 9, H / 2 + hh, 9, WHITE)
    return pen.done(width_px)


def preview_frame(kind, i, folder, text=None, ratio=None):
    """Frame `i` of a built-in sticker for the preview (cached PNG). v0.4.72 with
    your words (`text`) and shape (`ratio`) when the sticker has them."""
    if kind not in CATALOG:
        raise KeyError(kind)
    c = CATALOG[kind]
    n = cycle_frames(kind)
    i = max(0, min(n - 1, int(i)))
    words = clean_text(text) if c.get("text") else ""
    if words == c.get("text"):
        words = ""
    r = _num(ratio, *SPEC["limits"]["ratio"], None) if c.get("ratio") else None
    if r is not None and abs(r - c["aspect"]) < 1e-4:
        r = None
    r = round(r, 3) if r is not None else None
    folder = Path(folder) / kind
    tag = "" if not words and r is None else "-" + hashlib.sha1(f"{words}|{r}".encode()).hexdigest()[:12]
    out = folder / f"{i:04d}{tag}.png"
    if not out.exists():
        folder.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.png")
        draw(kind, i / FPS, SPEC["preview_width"], words or None, r).save(tmp)
        os.replace(tmp, out)
    return out


# ---------------------------------------------------------------- regions (v0.4.72)

def region_frame(kind, width, height, x, y, size, ratio, strength, opacity):
    """A full-frame layer for a region sticker: "spot" -> RGBA dark everywhere except a soft
    ellipse; "blur" -> L mask, white inside a soft ellipse. The ellipse is `size` of the
    frame width wide and `ratio` wide-for-tall, centred at (x, y). The edge ramps from
    `region_soft` to 1 of the radius, exactly as the preview's CSS radial-gradient."""
    rx = max(1.0, size * width / 2)
    ry = max(1.0, rx / max(0.05, ratio))
    cx, cy = x * width, y * height
    soft = SPEC["region_soft"]
    x0, x1 = max(0, int(cx - rx) - 1), min(width, int(math.ceil(cx + rx)) + 1)
    y0, y1 = max(0, int(cy - ry) - 1), min(height, int(math.ceil(cy + ry)) + 1)
    inside = None
    if x1 > x0 and y1 > y0:
        X = (np.arange(x0, x1, dtype=np.float32) + 0.5 - cx) / rx
        Y = (np.arange(y0, y1, dtype=np.float32) + 0.5 - cy) / ry
        r = np.sqrt(X[None, :] ** 2 + Y[:, None] ** 2)
        inside = np.clip((r - soft) / (1 - soft), 0.0, 1.0)  # 0 in the middle, 1 outside
    if kind == "spot":
        a = np.full((height, width), strength * opacity * 255, dtype=np.float32)
        if inside is not None:
            a[y0:y1, x0:x1] *= inside
        arr = np.zeros((height, width, 4), dtype=np.uint8)
        arr[..., 3] = np.round(a).astype(np.uint8)
        return Image.fromarray(arr, "RGBA")
    m = np.zeros((height, width), dtype=np.float32)
    if inside is not None:
        m[y0:y1, x0:x1] = (1.0 - inside) * opacity * 255
    return Image.fromarray(np.round(m).astype(np.uint8), "L")


def blur_radius(width, strength):
    """boxblur's radius (power 2) for a blur sticker; the preview's CSS blur is 0.82 x this."""
    return max(2, min(round(width * SPEC["blur_radius"] * strength), round(width / 16)))


# ---------------------------------------------------------------- export

def _with_opacity(im, a):
    if a >= 0.999:
        return im
    arr = np.asarray(im).copy()
    arr[..., 3] = (arr[..., 3].astype(np.float32) * max(0.0, a)).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _link(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def prepare(project, assets, width, height, folder, total, image_path):
    """Draw every sticker's frames for the export, once.
    Returns [{start, end, dir, w, h, keys, x, y}]: `dir/%05d.png` is one frame
    per output frame of the sticker, each centred in a w x h box; x/y follow
    the keyframes."""
    out = []
    folder = Path(folder)
    for n, st in enumerate(normalise(project.get("stickers"), {a for a, v in assets.items() if v.get("kind") == "image"})):
        start = st["start"]
        end = min(total, start + st["length"])
        frames = round(end * FPS) - round(start * FPS)
        if frames < 1:
            continue
        ratio = aspect(st, assets)
        region = (CATALOG.get(st["kind"]) or {}).get("region")
        if region:
            out.append(_prepare_region(st, region, n, frames, start, ratio, width, height, folder))
            continue
        sizes = [st["size"]] + [k["size"] for k in st["keyframes"]]
        bw = round(width * max(sizes) / 2) * 2 + 2
        bh = round(bw / ratio / 2) * 2 + 2
        d = folder / f"st{n}"
        d.mkdir(parents=True, exist_ok=True)
        base_img = None
        if st["kind"] == "image":
            with Image.open(image_path(assets[st["asset_id"]])) as im:
                base_img = ImageOps.exif_transpose(im).convert("RGBA")
                base_img.thumbnail((bw * 2, bh * 2))
        cyc = cycle_frames(st["kind"]) if st["kind"] != "image" else 1
        made = {}
        for f in range(frames):
            local = f / FPS
            v = sample(st, local)
            pw = max(2, round(width * v["size"]))
            key = (f % cyc, pw, round(v["opacity"], 2))
            src = made.get(key)
            if src is None:
                if base_img is not None:
                    img = base_img.resize((pw, max(1, round(pw / ratio))), Image.LANCZOS)
                else:
                    img = draw(st["kind"], (f % cyc) / FPS, pw, st.get("text"), st.get("ratio"))
                img = _with_opacity(img, key[2])
                box = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
                box.alpha_composite(img.crop((0, 0, min(bw, img.width), min(bh, img.height))),
                                    (max(0, (bw - img.width) // 2), max(0, (bh - img.height) // 2)))
                src = d / f"u{len(made):05d}.png"
                box.save(src, compress_level=1)
                made[key] = src
            _link(src, d / f"{f:05d}.png")
        out.append({"start": round(start * FPS) / FPS, "end": round(start * FPS) / FPS + frames / FPS, "dir": d,
                    "w": bw, "h": bh, "keys": st["keyframes"], "x": st["x"], "y": st["y"]})
    return out


def _prepare_region(st, region, n, frames, start, ratio, width, height, folder):
    d = Path(folder) / f"st{n}"
    d.mkdir(parents=True, exist_ok=True)
    strength = strength_of(st)
    made = {}
    for f in range(frames):
        v = sample(st, f / FPS)
        key = (round(v["x"] * width), round(v["y"] * height), round(v["size"] * width), round(v["opacity"], 2))
        src = made.get(key)
        if src is None:
            img = region_frame(region, width, height, key[0] / width, key[1] / height, key[2] / width, ratio, strength, key[3])
            src = d / f"u{len(made):05d}.png"
            img.save(src, compress_level=1)
            made[key] = src
        _link(src, d / f"{f:05d}.png")
    s0 = round(start * FPS) / FPS
    return {"start": s0, "end": s0 + frames / FPS, "dir": d, "w": width, "h": height, "keys": [], "x": 0.5, "y": 0.5,
            "region": region, "radius": blur_radius(width, strength)}


def overlay_filters(layer, k, scene_start, scene_len, width, height):
    """(input args, filter text) to overlay a prepared sticker on a scene, or
    None when it does not show in it. The filter text continues a chain:
    "[in{k}];[in{k}][k:v]overlay=…"."""
    a, b = max(layer["start"], scene_start), min(layer["end"], scene_start + scene_len)
    if b - a < 1 / FPS:
        return None
    first = round((a - layer["start"]) * FPS)
    ra, rb = a - scene_start, b - scene_start
    rs = layer["start"] - scene_start  # when the sticker began, in the scene's clock
    T = f"(t-({rs:.4f}))"
    if layer["keys"]:
        X = f"({picture.expr(layer['keys'], 'x', T)})*{width}-{layer['w'] / 2}"
        Y = f"({picture.expr(layer['keys'], 'y', T)})*{height}-{layer['h'] / 2}"
    else:
        X = f"{layer['x'] * width - layer['w'] / 2:.2f}"
        Y = f"{layer['y'] * height - layer['h'] / 2:.2f}"
    args = ["-framerate", str(FPS), "-start_number", str(first), "-i", str(Path(layer["dir"]) / "%05d.png")]
    if layer.get("region") == "blur":
        # v0.4.72 the scene blurred, kept only inside the mask (a full-frame frame per output frame)
        text = (
            f"[stb{k}];[stb{k}]split[sba{k}][sbb{k}];"
            f"[sbb{k}]boxblur=luma_radius={layer['radius']}:luma_power=2,format=rgba[sbl{k}];"
            f"[{k}:v]format=gray,setpts=PTS-STARTPTS,tpad=start_duration={ra:.4f}:color=black[sbm{k}];"
            f"[sbl{k}][sbm{k}]alphamerge[sbx{k}];"
            f"[sba{k}][sbx{k}]overlay=0:0:eof_action=pass:enable='between(t,{ra:.4f},{rb:.4f})':format=auto"
        )
        return args, text
    if layer.get("region") == "spot":
        X, Y = "0", "0"
    text = (
        f"[stb{k}];[{k}:v]format=rgba,setpts=PTS-STARTPTS+{ra:.4f}/TB[stv{k}];"
        f"[stb{k}][stv{k}]overlay=x='{X}':y='{Y}':eof_action=pass:enable='between(t,{ra:.4f},{rb:.4f})':format=auto"
    )
    return args, text
