"""The cinematic graphics as items: how a chosen passage becomes something to draw, and how each frame is drawn.

This is Casefile Studio's `cinematic.py` without the app around it (no projects, no server, no cache). The
functions below are copied from it with the same names, constants and arithmetic, so a graphic the kit draws is
the frame Casefile draws for the same item: `tests/test_parity.py` compares them pixel for pixel whenever
Casefile is next to the kit.

An item (one graphic) is plain JSON, the same format Casefile stores:

    {id, template: "cinematic", status, start, end, collection, category, score, reason, window: [a, b],
     text, payload, words: [[text, start, end, a, b]] (seconds from the graphic's start; characters in `text`),
     dur, pauses, label, look, style, cut, cut_fade}
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageOps

from .cinegfx import anim as A
from .cinegfx import core
from .cinegfx import draw as D
from .cinegfx import look as L
from .cinegfx import text as T
from .cinegfx.timing import Timeline, Word

FPS = 24            # frames a second (Casefile's motion layer rate); a plan may choose another: set_fps
RATES = (24, 25, 30, 48, 50, 60)
LEAD = 0.45         # the graphic comes up this long before the first narrated word of its passage
TAIL = 0.25         # ... and its narration ends this long before the graphic's own exit
FADE_IN, FADE_OUT = 0.2, 0.3   # the whole graphic over the picture (no blur: an opacity ramp)
MIN_PAUSE = 0.12    # a gap between two words at least this long is a pause (the graphics hold on it)
LAST_HOLD = 1.0     # the last word stays on screen at least this long (from when it lands) before the exit
HOLD = 0.7          # back to back: the earlier graphic's last word stays readable this long before the next covers it
MIN_LEAD = 0.1      # ... for which the next graphic's lead-in may shrink to this
DEFAULT_COLLECTION = "truecrime"
BACKDROP = "__backdrop__"   # the picture behind a graphic, in `files`
PUSH = 1.04                 # a picture behind a graphic pushes in this much over the graphic


def set_fps(fps):
    """The frame rate graphics are placed and drawn at. A graphic is a function of time, so any rate draws the same
    design; the rate decides where its start lands on a frame and how many frames it has."""
    global FPS
    fps = int(fps or 24)
    if fps not in RATES:
        raise ValueError(f"Frame rate {fps}: use one of {', '.join(map(str, RATES))}.")
    FPS = fps
    return FPS


def registry():
    return core.load_collections()


def category_of(item):
    c = registry().get(item.get("collection") or "")
    return c.categories.get(item.get("category") or "") if c else None


def catalog():
    """Every collection and category with what each can take (colour sets, backgrounds, fonts, sizes)."""
    out = []
    for c in registry().values():
        cats = []
        for k in c.categories.values():
            lk = k.looks or {}
            cats.append({"key": k.key, "label": k.label, "about": k.about,
                         "palettes": [{"key": key, "label": lab, "colors": col} for key, lab, col in L.palettes(k)],
                         "backgrounds": [b for b in L.backdrops(k) if b != "still"], "fonts": [key for key, _ in L.fonts_of(k)],
                         "size": list(L.size_range(k)), "mirror": bool(lk.get("mirror")), "place": bool(lk.get("place")),
                         "dim": L.default_dim(k)})
        out.append({"key": c.key, "label": c.label, "categories": cats})
    return out


# ====================================================================== items

def local_timeline(st, times, words, a, b, lead=LEAD):
    """The window's text and its words with times from the graphic's start (cinegfx's word convention:
    punctuation outside the words). Returns (start on the timeline, text, words, duration, pauses).
    (Casefile: cinematic._local_timeline.)"""
    text = st.window_text(a, b)
    idx = [k for s in range(a, b) for k in times[s][2]]
    if not idx:
        return None
    start = max(0.0, round(words[idx[0]]["t"] - lead, 3))
    start = math.floor(start * FPS + 1e-6) / FPS  # on a frame
    toks = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    if len(toks) != len(idx):  # cannot happen (the text is the timeline's words joined); refuse rather than drift
        return None
    out = []
    for (ca, cb), k in zip(toks, idx):
        w = words[k]
        sub = [(x, ca + p, ca + q) for x, p, q in T.token_spans(text[ca:cb])]
        if not sub:
            continue
        t0, t1 = w["t"] - start, max(w["e"], w["t"] + 0.05) - start
        for j, (x, p, q) in enumerate(sub):
            out.append([x, round(t0 + (t1 - t0) * j / len(sub), 3), round(t0 + (t1 - t0) * (j + 1) / len(sub), 3), p, q])
    if not out:
        return None
    pauses = [[out[i][2], out[i + 1][1]] for i in range(len(out) - 1) if out[i + 1][1] - out[i][2] >= MIN_PAUSE]
    dur = round(max(out[-1][2] + TAIL, out[-1][1] + LAST_HOLD), 3)
    return start, text, out, dur, pauses


def timeline(item) -> Timeline:
    return Timeline(item["text"], [Word(w[0], float(w[1]), float(w[2]), int(w[3]), int(w[4])) for w in item["words"]],
                    float(item["dur"]), [tuple(p) for p in item.get("pauses") or []])


def full_frames(item):
    """How many frames the graphic lasts on its own (its narration plus its exit)."""
    return max(1, int(round((float(item["dur"]) + 0.6) * FPS)))


def frames_of(item):
    """How many frames are shown: all of them, or up to where the next graphic has covered this one (`cut`)."""
    n = full_frames(item)
    cut = item.get("cut")
    return max(1, min(n, int(cut))) if cut else n


def see_through(item):
    return (item.get("style") or {}).get("background") == "footage"


def handoffs(items):
    """Back to back, the later graphic takes over the screen: it fades in fully opaque over the earlier one, which
    ends once covered. Sets or clears `cut` (and `end`) on every item in place. A see-through graphic (over the
    footage) does not cover: the earlier one fades out under it (`cut_fade`). Skipped items are ignored."""
    cine = sorted((x for x in items if x.get("status") != "skipped"), key=lambda x: x["start"])
    for i, a in enumerate(cine):
        a.pop("cut", None)
        full_end = a["start"] + full_frames(a) / FPS
        nxt = next((b for b in cine[i + 1:] if b["id"] != a["id"]), None)
        a.pop("cut_fade", None)
        if nxt and a["start"] < nxt["start"] < full_end - 1e-6:
            cut = int(round((nxt["start"] - a["start"] + FADE_IN) * FPS))
            if cut < full_frames(a):
                a["cut"] = max(1, cut)
                if see_through(nxt):
                    a["cut_fade"] = True
        a["end"] = round(a["start"] + frames_of(a) / FPS, 3)
    return items


def label(cat, payload):
    """A short name for the graphic (Casefile: cinematic._label)."""
    p = payload
    key = cat.key
    if key == "findings" and p.get("source"):
        return f"What {p['source'].split()[-1]} said"
    if key == "timeline" and p.get("events"):
        d0, d1 = p["events"][0]["date"], p["events"][-1]["date"]
        if p.get("clock"):
            e0, e1 = p["events"][0], p["events"][-1]
            return f"{_short(d0)} · {e0['clock'].split('–')[0]}–{e1['clock'].split('–')[-1]} {e1.get('ampm', '')}".strip()
        return f"{_short(d0)} – {_short(d1)}"
    if key == "legal":
        return " · ".join(x for x in [(p.get("outcome") or "").capitalize(), p.get("court") or ""] if x) or cat.label
    if key == "turning" and p.get("question"):
        return p["question"]
    if key == "turning" and p.get("event"):
        return f"{(p.get('who') + ' ' if p.get('who') else '')}{p['event']} · {_short(p['date'])}".capitalize()
    if key == "contradiction":
        return "Conflicting accounts"
    if key == "digital":
        return "Evidence and route" if p.get("route") else f"Evidence log · {len(p.get('items') or [])} items"
    return cat.label


def _short(iso):
    try:
        d = dt.date.fromisoformat(iso)
        return f"{T.MONTH_ABBR[d.month].title()} {d.day}"
    except (TypeError, ValueError):
        return ""


def make_item(narr, beat, lead=LEAD):
    """One graphic from a chosen passage of the narration (`narr`: script.Narration)."""
    loc = local_timeline(narr.story, narr.times, narr.words, beat.a, beat.b, lead)
    if not loc:
        return None
    start, text, wl, dur, pauses = loc
    cat = registry()[beat.collection].categories[beat.category]
    payload = json.loads(json.dumps(beat.payload, default=str))
    it = {
        "id": "cg" + hashlib.sha1(f"{beat.category}|{beat.a}|{beat.b}|{text}".encode()).hexdigest()[:10],
        "template": "cinematic", "status": "approved", "start": start, "end": 0.0,
        "reason": "; ".join(str(r) for r in beat.reasons)[:240],
        "collection": beat.collection, "category": beat.category, "score": round(float(beat.score), 3),
        "window": [beat.a, beat.b], "text": text, "payload": payload, "words": wl, "dur": dur, "pauses": pauses,
        "label": label(cat, payload)[:120],
    }
    it["end"] = round(start + frames_of(it) / FPS, 3)
    return it


def suggest(narr, collection=DEFAULT_COLLECTION, categories=None):
    """Read the whole narration and place this collection's graphics where they are meaningful (cinegfx
    `core.select`). Back to back, the later graphic comes up later (a shorter lead-in) so the earlier graphic's
    last word stays readable, never before its own first word. (Casefile: cinematic.suggest.)"""
    coll = registry().get(collection)
    if not coll:
        raise ValueError(f"Unknown collection {collection!r}. Known: {', '.join(registry())}")
    st = narr.story
    if not st.sentences:
        return []
    cands = core.candidates(st, coll, categories) if categories else None
    out = []
    for beat in core.select(st, coll, cands=cands, allowed=lambda b: narr.times[b.a][0] is not None):
        it = make_item(narr, beat)
        if not it:
            continue
        prev = out[-1] if out else None
        if prev and it["start"] < prev["end"]:
            last = prev["start"] + prev["words"][-1][1]
            first = it["start"] + it["words"][0][1]
            lead = min(LEAD, max(MIN_LEAD, first - (last + HOLD)))
            it = make_item(narr, beat, lead=lead) or it
        out.append(it)
    return out


# ====================================================================== look

_KEY = re.compile(r"[A-Za-z0-9_-]{1,12}")


def _num(v, lo, hi, d):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return d if not math.isfinite(x) else max(lo, min(hi, x))


def normalise_look(v, project=False):
    """A look as given in the plan: only the choices made. (Casefile: cinematic.normalise_look; a photo
    background names its file with `photo` instead of a project photo id.)
    Plan-wide (project=True): {vary, seed, palettes: {category: set}, accent, text, background, photo, dim, font, size, mirror, place}.
    One graphic: {palette, accent, text ("own"), background, photo, dim, font ("design"), size, mirror, place}."""
    if not isinstance(v, dict):
        return {}
    out = {}
    if project:
        if v.get("vary") is True:
            out["vary"] = True
            out["seed"] = re.sub(r"[^\w-]", "", str(v.get("seed") or ""))[:40]
        pals = v.get("palettes") if isinstance(v.get("palettes"), dict) else {}
        pals = {re.sub(r"[^\w-]", "", str(k))[:40]: x for k, x in list(pals.items())[:40] if isinstance(x, str) and _KEY.fullmatch(x)}
        if pals:
            out["palettes"] = pals
    elif isinstance(v.get("palette"), str) and _KEY.fullmatch(v["palette"]):
        out["palette"] = v["palette"]
    for k in ("accent", "text"):
        x = v.get(k)
        if L.is_hex(x):
            out[k] = x.upper()
        elif not project and x == "own":
            out[k] = "own"
    bg = v.get("background")
    if bg in ("own", "footage", "photo"):
        out["background"] = bg
        if bg == "photo" and isinstance(v.get("photo"), str):
            out["photo"] = v["photo"]
    if v.get("dim") is not None:
        out["dim"] = round(_num(v.get("dim"), L.DIM[0], L.DIM[1], L.DIM[2]), 2)
    f = v.get("font")
    if isinstance(f, str) and (f in L.STYLES or (f == "design" and not project)):
        out["font"] = f
    if v.get("size") is not None:
        sz = round(_num(v.get("size"), L.SIZE[0], L.SIZE[1], 1.0), 2)
        if sz != 1.0 or not project:
            out["size"] = sz
    if isinstance(v.get("mirror"), bool) and (v["mirror"] or not project):
        out["mirror"] = v["mirror"]
    pl = v.get("place")
    if isinstance(pl, dict):
        q = {"scale": round(_num(pl.get("scale"), L.PLACE[0], L.PLACE[1], 1.0), 3),
             "x": round(_num(pl.get("x"), -1.0, 1.0, 0.0), 3), "y": round(_num(pl.get("y"), -1.0, 1.0, 0.0), 3)}
        if q != {"scale": 1.0, "x": 0.0, "y": 0.0} or not project:
            out["place"] = q
    return out


def style_of(item, look=None):
    """What the graphic is drawn with: its own choices over the plan's over the design's
    {palette, colors, background, dim, photo, notes, picked, from, type}. (Casefile: cinematic.style_of.)"""
    cat = category_of(item)
    G = normalise_look(item.get("look"))
    P = normalise_look(look, project=True)
    src = {}
    if G.get("palette"):
        pal, src["palette"] = G["palette"], "graphic"
    elif (P.get("palettes") or {}).get(cat.key):
        pal, src["palette"] = P["palettes"][cat.key], "plan"
    elif P.get("vary"):
        pal, src["palette"] = L.varied(cat, P.get("seed") or ""), "vary"
    else:
        pal, src["palette"] = None, "design"
    picks = {}
    for k in ("accent", "text"):
        if G.get(k):
            picks[k], src[k] = (None if G[k] == "own" else G[k]), "graphic"
        else:
            picks[k], src[k] = P.get(k), ("plan" if P.get(k) else "design")
    if G.get("background"):
        bg, photo, src["background"] = G["background"], G.get("photo") or "", "graphic"
    else:
        bg, photo, src["background"] = P.get("background") or "own", P.get("photo") or "", ("plan" if P.get("background") else "design")
    dim = G.get("dim") if G.get("dim") is not None else P.get("dim")
    r = L.resolve(cat, pal, picks["accent"], picks["text"], bg, dim)
    ty = {}
    for k in ("font", "size", "mirror", "place"):
        if k in G:
            ty[k], src[k] = G[k], "graphic"
        elif k in P:
            ty[k], src[k] = P[k], "plan"
        else:
            ty[k], src[k] = None, "design"
    rt = L.resolve_type(cat, ty["font"], ty["size"], ty["mirror"], ty["place"])
    if src["mirror"] == "plan" and not (cat.looks or {}).get("mirror"):
        rt["notes"] = [n for n in rt["notes"] if "mirrored" not in n]
    out = {"palette": r["palette"], "colors": r["colors"], "background": r["backdrop"], "notes": r["notes"] + rt["notes"], "picked": r["picked"],
           "from": src, "type": {"font": rt["font"], "fonts": rt["fonts"], "size": rt["size"], "mirror": rt["mirror"], "place": rt["place"]}}
    if r["backdrop"] in L.PICTURE:
        out["dim"] = r["dim"]
    if r["backdrop"] == "photo":
        out["photo"] = photo
    return out


# ====================================================================== photos

def slots(item):
    cat = category_of(item)
    return cat.photo_slots(item.get("payload") or {}) if cat else []


def backdrop_used(item, files):
    """What the graphic is actually drawn over: its own background, the footage, or the photo when its file
    was found (else its own background: nothing is made up)."""
    bg = (item.get("style") or {}).get("background") or "own"
    if bg == "photo" and BACKDROP not in (files or {}):
        return "own"
    return bg


def _assets(item, files, folder=None):
    """The photos a graphic is drawn with: a folder with sources.json (the demo convention: the graphic finds
    the person / place / tag itself), else the files chosen for its slots."""
    if folder and (Path(folder) / "sources.json").is_file():
        return core.Assets(folder)
    items = {}
    by_key = {sl["key"]: sl for sl in slots(item)}
    for k, f in (files or {}).items():
        sl = by_key.get(k)
        if not sl:
            continue
        items[k] = {"file": f["file"], "credit": f.get("credit") or "", "month": f.get("month") or "", "subject": sl["value"],
                    "people": [sl["value"]] if sl["kind"] == "person" else [], "places": [sl["value"]] if sl["kind"] == "place" else [],
                    "tags": [sl["value"]] if sl["kind"] == "tag" else []}
    return core.Assets(items=items)


# ====================================================================== drawing

def build(item, files=None, folder=None):
    """The cinegfx Graphic for an item (Casefile: cinematic.build)."""
    cat = category_of(item)
    if not cat:
        raise ValueError(f"Unknown graphic {item.get('collection')}/{item.get('category')}.")
    beat = core.Beat(item["collection"], item["category"], *item["window"], item.get("score", 0.0), item["payload"], [])
    style = item.get("style") or {}
    g = cat.graphic(beat, L.theme_for(cat, style.get("colors"), style.get("type")), timeline(item), _assets(item, files, folder))
    g.place = L.placement((style.get("type") or {}).get("place"), D.W, D.H) if (style.get("type") or {}).get("place") else None
    used = backdrop_used(item, files)
    dim = float(style.get("dim") or L.DIM[2])
    g.backdrop = None
    if used == "footage":
        g.backdrop = ("footage", dim)
    elif used == "photo":
        g.backdrop = ("picture", _picture(files[BACKDROP]["file"], dim))
    return g


def _picture(path, dim):
    with Image.open(path) as src:
        im = ImageOps.exif_transpose(src).convert("RGB")
    size = (round(D.W * PUSH), round(D.H * PUSH))
    im = ImageOps.fit(im, size, Image.LANCZOS)
    return Image.blend(im, Image.new("RGB", size, (8, 8, 10)), dim).convert("RGBA")


def _canvas(g, t, total):
    bd = getattr(g, "backdrop", None)
    place = getattr(g, "place", None)
    if place is not None:
        return _placed(g, t, total, bd, place)
    if bd is None:
        return g.frame(t)
    if bd[0] == "footage":
        canvas = Image.new("RGBA", (D.W, D.H), (8, 8, 10, int(round(255 * bd[1]))))
    else:
        pic = bd[1]
        z = 1.0 + (PUSH - 1.0) * A.clamp(t / max(1.0, total))
        pw, ph = pic.size
        cw, ch = pw / z, ph / z
        box = ((pw - cw) / 2, (ph - ch) / 2, (pw + cw) / 2, (ph + ch) / 2)
        canvas = pic.resize((D.W, D.H), Image.BILINEAR, box=box)
    g.draw(canvas, t)
    return canvas


def _background(g, t, total, bd):
    if bd is None:
        return Image.new("RGBA", (D.W, D.H), g.th.c("bg"))
    if bd[0] == "footage":
        return Image.new("RGBA", (D.W, D.H), (8, 8, 10, int(round(255 * bd[1]))))
    pic = bd[1]
    z = 1.0 + (PUSH - 1.0) * A.clamp(t / max(1.0, total))
    pw, ph = pic.size
    cw, ch = pw / z, ph / z
    return pic.resize((D.W, D.H), Image.BILINEAR, box=((pw - cw) / 2, (ph - ch) / 2, (pw + cw) / 2, (ph + ch) / 2))


def _placed(g, t, total, bd, place):
    sc, dx, dy = place
    layer = Image.new("RGBA", (D.W, D.H), (0, 0, 0, 0))
    g.draw(layer, t)
    if sc != 1.0:
        layer = layer.resize((max(1, round(D.W * sc)), max(1, round(D.H * sc))), Image.LANCZOS)
    canvas = _background(g, t, total, bd)
    top = Image.new("RGBA", (D.W, D.H), (0, 0, 0, 0))
    top.paste(layer, (dx, dy))
    canvas.alpha_composite(top)
    return canvas


def _envelope(t, total, cut_fade=None):
    a_in = A.out_cubic(A.clamp(t / FADE_IN))
    a_out = A.out_cubic(A.clamp((total - t) / FADE_OUT))
    if cut_fade is not None:
        a_out = min(a_out, A.out_cubic(A.clamp((cut_fade - t) / FADE_IN)))
    return min(a_in, a_out)


def frame(g, item, n, W, H):
    """Frame `n` (at FPS) as RGBA at W x H, with the fade in and out in its transparency. The composition is 16:9
    at 1920x1080: other 16:9 sizes are a sharp (Lanczos) resize of it; a tall or square video gets it as a
    full-width panel. (Casefile: cinematic.frame.)"""
    t = n / FPS
    total = full_frames(item) / FPS
    im = _canvas(g, t, total)
    see = getattr(g, "backdrop", None) is not None and g.backdrop[0] == "footage"
    if (W, H) != (D.W, D.H):
        if abs(W / H - D.W / D.H) < 0.01:
            im = im.resize((W, H), Image.LANCZOS)
        else:
            h = round(W * D.H / D.W)
            if h > H:
                w = round(H * D.W / D.H)
                panel, pos = im.resize((w, H), Image.LANCZOS), ((W - w) // 2, 0)
            else:
                panel, pos = im.resize((W, h), Image.LANCZOS), (0, (H - h) // 2)
            bg = Image.new("RGBA", (W, H), (8, 8, 10, int(round(255 * g.backdrop[1]))) if see else g.th.c("bg"))
            bg.paste(panel, pos)
            im = bg
    a = _envelope(t, total, frames_of(item) / FPS if item.get("cut_fade") else None)
    if a < 0.999:
        if see:
            im.putalpha(im.getchannel("A").point(lambda v: int(round(v * a))))
        else:
            im.putalpha(int(round(255 * a)))
    return im


def cues(item, g):
    """The graphic's designed sound cues: [{t (seconds from its start), sfx, gain_db, why}], built from the same
    Graphic the frames come from. A covered graphic loses the cues after it is covered."""
    until = (frames_of(item) / FPS - FADE_IN) if item.get("cut") else float("inf")
    return [{"t": float(c.t), "sfx": c.sfx, "gain_db": float(c.gain_db), "why": c.why} for c in g.cues if c.t < until - 1e-6]


def with_style(item, look=None):
    """A copy of the item with its resolved `style`."""
    it = json.loads(json.dumps(item))
    it["style"] = style_of(it, look)
    return it
