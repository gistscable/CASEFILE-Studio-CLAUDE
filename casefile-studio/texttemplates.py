"""v0.4.73 Text templates (CapCut's Text → Templates): a notification card, subscribe + bell, a lower
third, a breaking-news bar, a quote, a place & date stamp and a chapter card.

They are stickers (stickers.py): placed on the Overlays track, sized, moved, keyframed and followed
like any other. What makes them text templates is `lines` — up to four paragraphs you type
(catalog `lines` are the defaults, `fields` their names) — and an intro that plays once
(catalog `once: true`, `cycle` = the intro's length) and then holds; the sticker's own end fade is
the outro.

Drawn with Pillow, here, for the export and (through /api/stickers/<kind>/<frame>.png?l=…) for the
preview, so both look the same. Everything is laid out in a 1000-unit-wide box (height
1000 / aspect) drawn SS times larger, then reduced: smooth edges at any size.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SS = 3
FONT_DIR = Path(__file__).resolve().parent / "web" / "assets" / "fonts"
FONTS = {
    "inter": "Inter-Bold.otf",
    "black": "Inter-Black.otf",
    "poppins": "Poppins-Bold.ttf",
    "oswald": "Oswald-Bold.ttf",
    "oswald-m": "Oswald-Medium.ttf",
    "oswald-r": "Oswald-Regular.ttf",
    "serif": "Caladea-Bold.ttf",
    "mono": "LiberationMono-Bold.ttf",
    "body": "DejaVuSans.ttf",
}

WHITE = (255, 255, 255)
INK = (20, 22, 26)
RED = (230, 33, 23)
GREEN = (52, 199, 89)
YELLOW = (250, 190, 30)
GREY = (120, 124, 132)


@lru_cache(maxsize=256)
def _font(name, px):
    try:
        return ImageFont.truetype(str(FONT_DIR / FONTS[name]), max(6, int(px)))
    except OSError:
        return ImageFont.load_default()


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _p(t, a, b):
    """Progress 0..1 of an animation from a to b seconds, eased."""
    return _ease((t - a) / (b - a)) if b > a else float(t >= a)


class Canvas:
    """A 1000-unit-wide drawing box at `width_px` × SS pixels; layers composite with alpha and offset."""

    def __init__(self, width_px, aspect):
        self.k = width_px * SS / 1000.0
        self.H = 1000.0 / aspect
        self.size = (max(1, round(width_px * SS)), max(1, round(width_px * SS / aspect)))
        self.im = Image.new("RGBA", self.size, (0, 0, 0, 0))
        self.width_px = width_px

    def layer(self):
        im = Image.new("RGBA", self.size, (0, 0, 0, 0))
        return im, ImageDraw.Draw(im)

    def q(self, *v):
        return [x * self.k for x in v]

    def fit(self, text, name, size, max_w):
        """The font `name` at `size` units, smaller until `text` fits in `max_w` units."""
        f = _font(name, size * self.k)
        while text and f.getlength(text) > max_w * self.k and f.size > 8:
            f = _font(name, f.size * 0.92)
        return f

    def text(self, d, x, y, text, name, size, colour, max_w=1e9, anchor="lm", alpha=255):
        if not text:
            return 0.0
        f = self.fit(text, name, size, max_w)
        d.text((x * self.k, y * self.k), text, font=f, fill=(*colour, alpha), anchor=anchor)
        return f.getlength(text) / self.k

    def put(self, layer, alpha=1.0, dx=0.0, dy=0.0, scale=1.0, origin=(500, 0)):
        if alpha <= 0.003:
            return
        im = layer
        if abs(scale - 1) > 1e-3:
            # scaled about `origin` (units): the layer grows or shrinks around that point
            w, h = im.size
            nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
            ox, oy = origin[0] * self.k, origin[1] * self.k
            small = im.resize((nw, nh), Image.BICUBIC)
            im = Image.new("RGBA", self.size, (0, 0, 0, 0))
            _over(im, small, round(ox - ox * scale), round(oy - oy * scale))
        if alpha < 0.997:
            a = im.getchannel("A").point(lambda v: round(v * alpha))
            im = im.copy()
            im.putalpha(a)
        _over(self.im, im, round(dx * self.k), round(dy * self.k))

    def done(self):
        return self.im.resize((max(1, round(self.width_px)), max(1, round(self.width_px * self.H / 1000))), Image.LANCZOS)


def _over(base, img, x, y):
    """alpha_composite `img` at (x, y) px, the parts outside `base` dropped."""
    W, H = base.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + img.width), min(H, y + img.height)
    if x1 > x0 and y1 > y0:
        base.alpha_composite(img.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def _reveal(c, text_layer, upto):
    """Only the part of `text_layer` left of `upto` units shows (a wipe)."""
    m = Image.new("L", c.size, 0)
    ImageDraw.Draw(m).rectangle((0, 0, upto * c.k, c.size[1]), fill=255)
    text_layer.putalpha(Image.fromarray(np.minimum(np.asarray(text_layer.getchannel("A")), np.asarray(m))))
    return text_layer


def _bell(d, k, cx, cy, s, colour, angle=0.0):
    """A bell `s` units tall centred at (cx, cy), swung by `angle` degrees about its top."""
    pts = []
    for x, y in [(-0.42, 0.25), (-0.36, -0.05), (-0.3, -0.3), (-0.15, -0.44), (0, -0.48), (0.15, -0.44),
                 (0.3, -0.3), (0.36, -0.05), (0.42, 0.25), (0.5, 0.33), (-0.5, 0.33)]:
        pts.append((x, y))
    a = math.radians(angle)
    top = (0, -0.5)

    def rot(x, y):
        x0, y0 = x - top[0], y - top[1]
        return ((top[0] + x0 * math.cos(a) - y0 * math.sin(a)) * s + cx, (top[1] + x0 * math.sin(a) + y0 * math.cos(a)) * s + cy)

    d.polygon([tuple(v * k for v in rot(x, y)) for x, y in pts], fill=colour)
    bx, by = rot(0, 0.42)
    r = 0.11 * s
    d.ellipse(((bx - r) * k, (by - r) * k, (bx + r) * k, (by + r) * k), fill=colour)
    tx, ty = rot(0, -0.53)
    r = 0.07 * s
    d.ellipse(((tx - r) * k, (ty - r) * k, (tx + r) * k, (ty + r) * k), fill=colour)


def draw(kind, t, width_px, lines, aspect):
    """The template `t` seconds into its intro (it holds after), `width_px` wide, with your `lines`."""
    c = Canvas(width_px, aspect)
    k, H = c.k, c.H
    L = list(lines) + [""] * 4
    if kind == "tt-message":
        # an iPhone-style notification: it drops in from above
        p = _p(t, 0, 0.45)
        lay, d = c.layer()
        d.rounded_rectangle(c.q(6, 6, 994, H - 6), radius=62 * k, fill=(246, 246, 248, 240))
        d.rounded_rectangle(c.q(44, 40, 124, 120), radius=20 * k, fill=(*GREEN, 255))
        # the speech bubble on the app icon
        d.ellipse(c.q(60, 58, 108, 96), fill=(255, 255, 255, 255))
        d.polygon([tuple(v * k for v in xy) for xy in [(70, 90), (64, 106), (84, 94)]], fill=(255, 255, 255, 255))
        c.text(d, 148, 80, L[0].upper(), "inter", 40, GREY, max_w=640)
        c.text(d, 952, 80, "now", "inter", 36, GREY, anchor="rm")
        c.text(d, 50, 168, L[1], "inter", 56, INK, max_w=900)
        c.text(d, 50, 238, L[2], "body", 50, (60, 62, 68), max_w=900)
        c.put(lay, alpha=min(1.0, p * 1.6), dy=-(1 - p) * H * 0.25, scale=0.96 + 0.04 * p, origin=(500, 0))
    elif kind == "tt-subscribe":
        # the button pops in, the bell joins it and rings once, your channel slides in underneath
        top, bot = 16, 196
        mid = (top + bot) / 2
        p = _p(t, 0, 0.35)
        lay, d = c.layer()
        d.rounded_rectangle(c.q(10, top, 650, bot), radius=(bot - top) / 2 * k, fill=(*RED, 255))
        c.text(d, 330, mid + 3, L[0].upper(), "inter", 84, WHITE, max_w=560, anchor="mm")
        c.put(lay, alpha=min(1.0, p * 2), scale=0.7 + 0.3 * p, origin=(330, mid))
        q = _p(t, 0.25, 0.6)
        lay, d = c.layer()
        bx = 680 + (bot - top) / 2
        d.ellipse(c.q(680, top, 680 + bot - top, bot), fill=(255, 255, 255, 255))
        swing = 26 * math.sin((t - 0.5) * 2 * math.pi * 3.2) * max(0.0, 1 - (t - 0.5) / 0.45) if t > 0.5 else 0.0
        _bell(d, k, bx, mid + 4, (bot - top) * 0.58, (*INK, 255), swing)
        c.put(lay, alpha=q, scale=0.6 + 0.4 * q, origin=(bx, mid))
        if L[1]:
            r = _p(t, 0.35, 0.7)
            lay, d = c.layer()
            sh = Image.new("RGBA", c.size, (0, 0, 0, 0))
            c.text(ImageDraw.Draw(sh), 24, (bot + H) / 2 + 4, L[1], "inter", 60, (0, 0, 0), max_w=960, alpha=150)
            c.text(d, 20, (bot + H) / 2, L[1], "inter", 60, WHITE, max_w=960)
            sh.alpha_composite(lay)
            c.put(sh, alpha=r, dx=-(1 - r) * 40)
    elif kind == "tt-lower":
        # a lower third: the accent bar grows, the name and the role wipe in
        p = _p(t, 0, 0.3)
        bar_h = (H - 20) * p
        if bar_h > 0:
            lay, d = c.layer()
            d.rectangle(c.q(0, H / 2 - bar_h / 2, 18, H / 2 + bar_h / 2), fill=(*YELLOW, 255))
            c.put(lay)
        q = _p(t, 0.15, 0.6)
        if q > 0:
            lay, d = c.layer()
            d.rectangle(c.q(18, 10, 18 + 960 * q, H * 0.6), fill=(14, 15, 18, 235))
            d.rectangle(c.q(18, H * 0.6, 18 + 760 * q, H - 10), fill=(255, 255, 255, 235))
            text = Image.new("RGBA", c.size, (0, 0, 0, 0))
            dt = ImageDraw.Draw(text)
            c.text(dt, 56, H * 0.33 + 4, L[0].upper(), "oswald", 98, WHITE, max_w=900)
            c.text(dt, 56, H * 0.8, L[1], "inter", 50, INK, max_w=700)
            lay.alpha_composite(_reveal(c, text, 18 + 960 * q))  # only what the panel has reached shows
            c.put(lay)
    elif kind == "tt-breaking":
        p = _p(t, 0, 0.3)
        lay, d = c.layer()
        tag_w = 270
        d.rectangle(c.q(0, 0, tag_w, H), fill=(*RED, 255))
        c.text(d, tag_w / 2, H / 2 + 2, L[0].upper(), "oswald", H * 0.5, WHITE, max_w=tag_w - 30, anchor="mm")
        c.put(lay, alpha=p, dx=-(1 - p) * 60)
        q = _p(t, 0.18, 0.55)
        if q > 0:
            lay, d = c.layer()
            d.rectangle(c.q(tag_w, 0, tag_w + (1000 - tag_w) * q, H), fill=(255, 255, 255, 245))
            text = Image.new("RGBA", c.size, (0, 0, 0, 0))
            c.text(ImageDraw.Draw(text), tag_w + 30, H / 2 + 2, L[1], "inter", H * 0.44, INK, max_w=1000 - tag_w - 50)
            lay.alpha_composite(_reveal(c, text, tag_w + (1000 - tag_w) * q))
            c.put(lay)
    elif kind == "tt-quote":
        p = _p(t, 0, 0.45)
        lay, d = c.layer()
        d.rounded_rectangle(c.q(0, 0, 1000, H), radius=28 * k, fill=(12, 13, 16, 215))
        d.rectangle(c.q(56, 150, 66, H - 60), fill=(*YELLOW, 255))
        c.text(d, 70, 92, "\u201c", "serif", 190, YELLOW, anchor="lm")
        words = L[0]
        # up to three lines, wrapped to the card
        f = _font("serif", 64 * k)
        rows, cur = [], ""
        for w in words.split():
            nxt = (cur + " " + w).strip()
            if f.getlength(nxt) > 820 * k and cur:
                rows.append(cur)
                cur = w
            else:
                cur = nxt
        if cur:
            rows.append(cur)
        rows = rows[:3]
        y0 = H / 2 - (len(rows) - 1) * 40 - 30
        for i, row in enumerate(rows):
            c.text(d, 110, y0 + i * 80, row, "serif", 64, WHITE, max_w=840)
        c.text(d, 110, H - 70, L[1], "inter", 40, (200, 202, 208), max_w=840)
        c.put(lay, alpha=p, dy=(1 - p) * 30)
    elif kind == "tt-place":
        # a typewriter stamp: the place types out, then the date
        a, b = L[0].upper(), L[1].upper()
        cps = 26.0
        na = min(len(a), int(max(0.0, t) * cps))
        nb = min(len(b), int(max(0.0, t - len(a) / cps - 0.08) * cps))
        lay, d = c.layer()
        c.text(d, 10, H * 0.32, a[:na], "mono", H * 0.36, WHITE, max_w=980)
        c.text(d, 10, H * 0.76, b[:nb], "mono", H * 0.26, YELLOW, max_w=980)
        typing = na < len(a) or (b and nb < len(b))
        if typing:
            fa = c.fit(a, "mono", H * 0.36, 980)
            fb = c.fit(b, "mono", H * 0.26, 980)
            if na < len(a):
                x = 10 * k + fa.getlength(a[:na])
                d.rectangle((x + 4, H * 0.18 * k, x + 4 + H * 0.05 * k, H * 0.46 * k), fill=(*WHITE, 255))
            else:
                x = 10 * k + fb.getlength(b[:nb])
                d.rectangle((x + 4, H * 0.66 * k, x + 4 + H * 0.04 * k, H * 0.86 * k), fill=(*YELLOW, 255))
        # a soft shadow so it reads on any picture
        sh = lay.copy()
        sh.putalpha(lay.getchannel("A").point(lambda v: v * 0.55))
        black = Image.new("RGBA", c.size, (0, 0, 0, 0))
        black.paste((0, 0, 0, 255), mask=sh.getchannel("A"))
        c.put(black, dx=4, dy=5, alpha=0.7)
        c.put(lay)
    elif kind == "tt-chapter":
        p = _p(t, 0, 0.5)
        q = _p(t, 0.25, 0.75)
        lay, d = c.layer()
        c.text(d, 500, H * 0.27, L[0].upper(), "oswald-m", 64, YELLOW, max_w=900, anchor="mm")
        c.put(lay, alpha=p, dy=(1 - p) * 24)
        w = 260 * p
        lay, d = c.layer()
        d.rectangle(c.q(500 - w, H * 0.43, 500 + w, H * 0.43 + 5), fill=(255, 255, 255, 200))
        c.put(lay)
        lay, d = c.layer()
        c.text(d, 500, H * 0.7, L[1], "poppins", 118, WHITE, max_w=960, anchor="mm")
        c.put(lay, alpha=q, dy=(1 - q) * 30)
    return c.done()
