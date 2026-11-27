"""Look options for a category (v0.4.63): its tested colour sets, your own colours (checked for readability),
and what it may be drawn over (its own background, your footage darkened, a still, a photo).

Niche-agnostic: a collection declares each category's options as data on `Category.looks`:

    {"palettes": [(key, label, {bg, bg2, ink, muted, accent, accent2} or None for the category's own theme), ...],
     "backdrops": ("own", "footage", "still", "photo"),   # what it may be drawn over (default: all)
     "backdrop_note": "why a backdrop is not offered",
     "on_accent": ("#FFFFFF",)}                           # colours the design writes ON the accent

`resolve()` is a pure function of those choices, so the editor's preview and the export draw the same look.
The first palette is the category's approved design: with no choices made, its Theme object is returned
unchanged (the default look stays pixel-identical)."""
from __future__ import annotations

import colorsys
import dataclasses
import hashlib
import json
import re

ROLES = ("bg", "bg2", "ink", "muted", "accent", "accent2")
TEXT_MIN = 4.5      # text against its background (WCAG AA, body text)
ACCENT_MIN = 3.0    # accent colours: large type, rules, chips (WCAG AA, large text and graphics)
BACKDROPS = ("own", "footage", "still", "photo")
PICTURE = ("footage", "still", "photo")
DIM = (0.4, 0.85, 0.62)   # how much a picture behind a graphic is darkened: min, max, default
HEX = re.compile(r"#[0-9a-fA-F]{6}")


def is_hex(v) -> bool:
    return isinstance(v, str) and bool(HEX.fullmatch(v))


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(v * 255))) for v in rgb)


def luminance(h) -> float:
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def nearest(colour, rules):
    """`colour` if it meets every (other colour, minimum ratio) rule, else the nearest shade of the same hue
    that does (lighter or darker, whichever is closer). None when no shade of it can."""
    if all(contrast(colour, o) >= n for o, n in rules):
        return colour.upper()
    h, l, s = colorsys.rgb_to_hls(*_rgb(colour))
    for k in range(1, 201):
        for l2 in (l + k * 0.005, l - k * 0.005):
            if 0.0 <= l2 <= 1.0:
                c = _hex(colorsys.hls_to_rgb(h, l2, s))
                if all(contrast(c, o) >= n for o, n in rules):
                    return c
    return None


def picture_ref(dim) -> str:
    """What text sits on over a darkened picture, for the readability check: a mid-grey picture under the
    darkening (conservative: most of a frame is darker)."""
    v = 128 * (1 - dim) + 8 * dim
    return "#%02X%02X%02X" % (round(v), round(v), round(v + 2 * dim))


def _theme_colors(th):
    return {r: getattr(th, r).upper() for r in ROLES}


def palettes(cat):
    """[(key, label, colours)] for a category; the first is its approved design."""
    out = []
    for key, label, colors in (cat.looks or {}).get("palettes") or [("A", "Approved design", None)]:
        out.append((key, label, _theme_colors(cat.theme) if colors is None else {r: colors[r].upper() for r in ROLES}))
    return out


def backdrops(cat):
    return tuple((cat.looks or {}).get("backdrops") or BACKDROPS)


def is_light(colors) -> bool:
    return luminance(colors["bg"]) > 0.4


def theme_for(cat, colors):
    """The Theme drawn with these colours: the category's own Theme object for its approved colours (same name,
    same caches: pixel-identical), else a copy with a name unique to the colours (sprite caches key on it)."""
    base = cat.theme
    if not isinstance(colors, dict) or not all(is_hex(colors.get(r)) for r in ROLES):
        return base
    colors = {r: colors[r].upper() for r in ROLES}
    if colors == _theme_colors(base):
        return base
    tag = hashlib.sha1(json.dumps(colors, sort_keys=True).encode()).hexdigest()[:10]
    return dataclasses.replace(base, name=f"{base.name}~{tag}", **colors)


def varied(cat, seed: str) -> str:
    """Automatic variation: a tested set for this category picked from the project's seed (the same project
    always gets the same one). Only the tested sets of the same surface as the approved design (no light/dark swap)."""
    pals = palettes(cat)
    light = is_light(pals[0][2])
    keys = [k for k, _, c in pals if is_light(c) == light]
    h = int(hashlib.sha1(f"{seed}|{cat.key}".encode()).hexdigest(), 16)
    return keys[h % len(keys)]


def resolve(cat, palette=None, accent=None, text=None, backdrop="own", dim=None):
    """The look to draw: {palette, colors, backdrop, dim, notes, picked}. `notes` say, in plain words, every
    choice that could not be used as given (a backdrop the design cannot take, a colour too faint to read)."""
    pals = palettes(cat)
    by_key = {k: (lab, c) for k, lab, c in pals}
    notes = []
    key = palette if palette in by_key else pals[0][0]
    bd = backdrop if backdrop in BACKDROPS else "own"
    if bd not in backdrops(cat):
        notes.append((cat.looks or {}).get("backdrop_note") or f"{cat.label} keeps its own background.")
        bd = "own"
    d = None
    if bd in PICTURE:
        try:
            d = float(dim)
        except (TypeError, ValueError):
            d = DIM[2]
        d = round(max(DIM[0], min(DIM[1], d)), 2)
    colors = dict(by_key[key][1])
    if bd in PICTURE and is_light(colors):
        dark = next((k for k, _, c in pals if not is_light(c)), None)
        if dark:
            notes.append(f"Over a picture the text must be light, so it uses {by_key[dark][0].lower()} instead of {by_key[key][0].lower()}.")
            key, colors = dark, dict(by_key[dark][1])
    ref = colors["bg"] if bd == "own" else picture_ref(d)
    picked = {}
    if is_hex(text):
        fixed = nearest(text, [(ref, TEXT_MIN)])
        picked["text"] = {"picked": text.upper(), "used": fixed or colors["ink"], "ratio": round(contrast(text, ref), 1), "need": TEXT_MIN}
        if fixed and fixed != text.upper():
            notes.append(f"Your text colour {text.upper()} is too faint to read here ({contrast(text, ref):.1f}:1, needs {TEXT_MIN}:1): drawn as {fixed}.")
        elif not fixed:
            notes.append(f"Your text colour {text.upper()} cannot be made readable here: the design's own is used.")
        if fixed:
            colors["ink"] = fixed
    if is_hex(accent):
        rules = [(ref, ACCENT_MIN)] + [(c, ACCENT_MIN) for c in (cat.looks or {}).get("on_accent") or ()]
        fixed = nearest(accent, rules)
        worst = min(contrast(accent, o) for o, _ in rules)
        picked["accent"] = {"picked": accent.upper(), "used": fixed or colors["accent"], "ratio": round(worst, 1), "need": ACCENT_MIN}
        if fixed and fixed != accent.upper():
            what = "against the background" if len(rules) == 1 else "against the background and the white text it carries"
            notes.append(f"Your accent {accent.upper()} is too faint {what} ({worst:.1f}:1, needs {ACCENT_MIN}:1): drawn as {fixed}.")
        elif not fixed:
            notes.append(f"Your accent {accent.upper()} cannot be made readable here: the design's own is used.")
        if fixed:
            same = colors["accent2"] == colors["accent"]  # a one-accent design keeps one accent
            colors["accent"] = fixed
            if same:
                colors["accent2"] = fixed
    return {"palette": key, "colors": colors, "backdrop": bd, "dim": d, "notes": notes, "picked": picked}
