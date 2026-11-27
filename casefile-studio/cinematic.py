"""v0.4.62 Cinematic motion graphics: the story-aware cinegfx engine inside the Motion section.

A cinematic graphic is one more kind of motion item (`template: "cinematic"`) in `project["motion"]`, so
it shares everything the classic templates have: suggested -> draft -> approved, "Add approved graphics to
the export", caption hiding, the preview layer, the content-addressed cache and the export overlay.

    {id, template: "cinematic", status, start, end, hide_captions, source, reason,
     collection, category, score, reasons, window: [a, b], text, payload,
     words: [[text, start, end, a, b]] (seconds from the graphic's start; characters in `text`),
     dur, pauses: [[start, end]], photos: {slot key: {asset_id, credit, month, auto}}, label}

* The story is read from the narration on the timeline (`motion.timeline_words`: the episode's word clock,
  else the captions, else the scene's narration spread over the scene), so a graphic's reveals land on the
  words as they are actually spoken in this edit, and nothing else is analysed.
* An item carries everything it is drawn from (content, word times, photo choices), so the editor's
  preview and the export draw exactly the same frames: same code, same inputs, only the size differs.
* Words on screen come from the narration itself (cinegfx detectors); photos only from the project, in the
  slots the producer fills (matched by file name or chosen by hand), with the credit they type. A slot
  left empty is simply not drawn: nothing is generated or substituted.
* Frames are pure functions of time: the export draws them in parallel worker processes (spawn-safe on
  macOS and Windows) and streams them to one FFmpeg.
* v0.4.63 Look: a project look (`motion.look`: colour set per category, automatic variation, your own accent and
  text colours, what the graphics are drawn over) and, per graphic, `look` overrides of any of it. Both resolve into
  the item's `style` (cinegfx/look.py: tested sets, readability check), which is what is drawn and cached.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import multiprocessing as mp
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image

import motion
from cinegfx import anim as A
from cinegfx import core
from cinegfx import draw as D
from cinegfx import look as L
from cinegfx import story as S
from cinegfx import text as T
from cinegfx.timing import Timeline, Word

ENGINE = 3          # bump when the drawing or the item format changes: cached frames are made again
FPS = motion.FPS    # the app's motion layer rate (frames are sampled from the graphic at this rate)
LEAD = 0.45         # the graphic comes up this long before the first narrated word of its passage
TAIL = 0.25         # ... and its narration ends this long before the graphic's own exit
FADE_IN, FADE_OUT = 0.2, 0.3   # the whole graphic over the picture (no blur: an opacity ramp)
MIN_PAUSE = 0.12    # a gap between two words at least this long is a pause (the graphics hold on it)
LAST_HOLD = 1.0     # the last word stays on screen at least this long (from when it lands) before the exit
HOLD = 0.7          # back to back: the earlier graphic's last word stays readable this long before the next covers it
MIN_LEAD = 0.1      # ... for which the next graphic's lead-in may shrink to this
DEFAULT_COLLECTION = "truecrime"
MAX_PAYLOAD = 60_000


def registry():
    return core.load_collections()


def catalog():
    """The collections and their categories, for the editor (new niches appear here on their own)."""
    return {"collections": [
        {"key": c.key, "label": c.label,
         "categories": [{"key": k.key, "label": k.label, "about": k.about, "looks": _looks(k)} for k in c.categories.values()]}
        for c in registry().values()], "default": DEFAULT_COLLECTION,
        "dim": {"min": L.DIM[0], "max": L.DIM[1], "default": L.DIM[2]},
        "type": {"styles": [{"key": k, "label": lab} for k, (lab, _) in L.STYLES.items()], "size": list(L.SIZE),
                 "place": list(L.PLACE)}}


def _looks(cat):
    """v0.4.63 What the editor can offer for a category's look."""
    lk = cat.looks or {}
    return {"palettes": [{"key": k, "label": lab, "colors": c, "light": L.is_light(c)} for k, lab, c in L.palettes(cat)],
            "backdrops": list(L.backdrops(cat)), "backdrop_note": lk.get("backdrop_note") or "",
            # v0.4.64 type and layout
            "fonts": [{"key": k, "label": lab} for k, lab in L.fonts_of(cat)], "size": list(L.size_range(cat)),
            "mirror": lk.get("mirror") or "", "place": bool(lk.get("place")), "dim": L.default_dim(cat)}


def _category(item):
    c = registry().get(item.get("collection") or "")
    return c.categories.get(item.get("category") or "") if c else None


# ====================================================================== the story, from the timeline

_STORY: "OrderedDict[str, tuple]" = OrderedDict()
_STORY_LOCK = threading.Lock()

_NOT_NAMES = {"The", "This", "That", "Chief", "Judge", "Police", "Under", "After", "Before", "When", "At", "In", "On",
              "Subscribe", "Chapter", "State", "City", "County", "Department", "Office", "Court", "New", "North", "South",
              "East", "West", "Street", "Avenue", "Mayor", "Detective", "Officer", "Attorney", "District", "Assistant"}
_MONTH_WORDS = set(T.MONTHS) | {m.capitalize() for m in T.MONTHS}


def _subject(project, text):
    """Whose story it is: the project's topic when it is a name the narration uses, else the person the
    narration names most (full name plus first-name mentions)."""
    names = {}
    for m in re.finditer(r"\b([A-Z][a-z]+)\s([A-Z][a-z]+)\b", text):
        a, b = m.group(1), m.group(2)
        if a in _NOT_NAMES or b in _NOT_NAMES or a in _MONTH_WORDS or b in _MONTH_WORDS:
            continue
        names[f"{a} {b}"] = names.get(f"{a} {b}", 0) + 1
    for topic in (project.get("topic"), project.get("title")):
        t = re.sub(r"\s+", " ", str(topic or "")).strip()
        if t in names:
            return t
    if not names:
        return ""
    score = {n: c * 2 + len(re.findall(rf"\b{re.escape(n.split()[0])}\b", text)) for n, c in names.items()}
    return max(score, key=lambda n: (score[n], n))


def _reference(project, text):
    years = [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", text)]
    if years:
        return dt.date(max(years), 12, 31)
    try:
        return dt.date.fromisoformat(str(project.get("created_at") or "")[:10])
    except ValueError:
        return dt.date(dt.date.today().year, 12, 31)


def _chapter(title, i):
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    num = re.search(r"chapter\s+(\d+)", title, re.I)
    name = re.split(r"\s+[—–-]\s+|\s+·\s+", title, maxsplit=1)
    nice = name[-1].strip() if (num and len(name) > 1) else title
    if nice.isupper():
        nice = nice.title().replace("’S", "’s").replace("'S", "'s")
    return S.Chapter(i, nice, int(num.group(1)) if num else None)


def story_for(project):
    """(story, sentence times [(t0, t1, [word index ...])], words) for the narration on the timeline.
    Cached by the narration's words, chapters and times."""
    words = motion.timeline_words(project)
    scenes = project.get("scenes") or []
    key = hashlib.sha1(json.dumps([[w["w"], w["t"], w["e"], w["scene"]] for w in words] +
                                  [[s.get("chapter") for s in scenes], project.get("topic"), project.get("title"),
                                   str(project.get("created_at") or "")[:10]]).encode()).hexdigest()
    with _STORY_LOCK:
        hit = _STORY.get(key)
        if hit:
            _STORY.move_to_end(key)
            return hit
    # a chapter changes only between sentences: the scene slices of a guide can give a chapter's first word to
    # the scene before it ("Jevario | Buie was fourteen"); each sentence takes the chapter most of its words are in
    titles = [scenes[w["scene"]].get("chapter") if w["scene"] < len(scenes) else "" for w in words]
    flat, offs = "", []
    for w in words:
        offs.append(len(flat) + (1 if flat else 0))
        flat = (flat + " " + w["w"]) if flat else w["w"]
    k = 0
    for a, b in T.split_sentences(flat):
        idx = []
        while k < len(words) and offs[k] < b:
            idx.append(k)
            k += 1
        if idx:
            votes = {}
            for j in idx:
                votes[titles[j]] = votes.get(titles[j], 0) + 1
            best = max(votes, key=lambda t: (votes[t], -idx[[titles[j] for j in idx].index(t)]))
            for j in idx:
                titles[j] = best
    chapters, paras, para_words = [], [], []  # para_words: [(char start, char end, word index)] per paragraph
    cur_title = object()
    for i, w in enumerate(words):
        title = titles[i]
        if title != cur_title:
            cur_title = title
            chapters.append(_chapter(title, len(chapters)))
            paras.append([len(chapters) - 1, ""])
            para_words.append([])
        text = paras[-1][1]
        start = len(text) + (1 if text else 0)
        paras[-1][1] = (text + " " + w["w"]) if text else w["w"]
        para_words[-1].append((start, start + len(w["w"]), i))
    full = " ".join(p[1] for p in paras)
    st = S.build(chapters, [tuple(p) for p in paras], title=str(project.get("title") or ""),
                 subject=_subject(project, full), reference=_reference(project, full))
    times = []
    for s in st.sentences:
        a, b = s.span
        idx = [k for (ca, cb, k) in para_words[s.para] if ca >= a and cb <= b]
        times.append((words[idx[0]]["t"], words[idx[-1]]["e"], idx) if idx else (None, None, []))
    out = (st, times, words)
    with _STORY_LOCK:
        _STORY[key] = out
        while len(_STORY) > 6:
            _STORY.popitem(last=False)
    return out


# ====================================================================== items

def _local_timeline(st, times, words, a, b, lead=LEAD):
    """The window's text and its words with times from the graphic's start (cinegfx's word convention:
    punctuation outside the words). Returns (start on the timeline, text, words, duration, pauses)."""
    text = st.window_text(a, b)
    idx = [k for s in range(a, b) for k in times[s][2]]
    if not idx:
        return None
    start = max(0.0, round(words[idx[0]]["t"] - lead, 3))
    start = math.floor(start * FPS + 1e-6) / FPS  # on a frame: the export places it on this frame
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
    """How many frames the graphic lasts on its own (the graphic decides: its narration plus its exit)."""
    return max(1, int(round((float(item["dur"]) + 0.6) * FPS)))


def frames_of(item):
    """How many frames are shown: all of them, or up to where the next graphic has covered this one (`cut`)."""
    n = full_frames(item)
    cut = item.get("cut")
    return max(1, min(n, int(cut))) if cut else n


def handoffs(items):
    """Back to back, the later graphic takes over the screen: each graphic fades in fully opaque over the earlier
    one, which ends once covered (no exit of its own under the new one). Sets or clears `cut` (and `end`) on
    every cinematic item, in place: the next approved cinematic graphic that starts before this one has ended
    covers it. Run on the whole list whenever it changes (motion.normalise), so preview and export agree.
    v0.4.63: a see-through graphic (over the footage) does not cover: the earlier one fades out under it (`cut_fade`)."""
    cine = sorted((x for x in items if x.get("template") == "cinematic"), key=lambda x: x["start"])
    for i, a in enumerate(cine):
        a.pop("cut", None)
        full_end = a["start"] + full_frames(a) / FPS
        nxt = next((b for b in cine[i + 1:] if b["status"] == "approved" and b["id"] != a["id"]), None)
        a.pop("cut_fade", None)
        if nxt and a["start"] < nxt["start"] < full_end - 1e-6:
            cut = int(round((nxt["start"] - a["start"] + FADE_IN) * FPS))
            if cut < full_frames(a):
                a["cut"] = max(1, cut)
                if see_through(nxt):  # v0.4.63: the next one is see-through (over the footage): this one fades out under it
                    a["cut_fade"] = True
        a["end"] = round(a["start"] + frames_of(a) / FPS, 3)
    return items


def _label(cat, payload):
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


def make_item(project, beat, item_id=None, source="auto", status="suggested", prev=None, lead=LEAD):
    st, times, words = story_for(project)
    loc = _local_timeline(st, times, words, beat.a, beat.b, lead)
    if not loc:
        return None
    start, text, wl, dur, pauses = loc
    cat = registry()[beat.collection].categories[beat.category]
    payload = json.loads(json.dumps(beat.payload, default=str))
    it = {
        "id": item_id or "cg" + hashlib.sha1(f"{beat.category}|{beat.a}|{beat.b}|{text}".encode()).hexdigest()[:10],
        "template": "cinematic", "status": status, "start": start, "end": 0.0, "hide_captions": True,
        "source": source, "reason": "; ".join(str(r) for r in beat.reasons)[:240],
        "collection": beat.collection, "category": beat.category, "score": round(float(beat.score), 3),
        "window": [beat.a, beat.b], "text": text, "payload": payload, "words": wl, "dur": dur, "pauses": pauses,
        "photos": {}, "label": _label(cat, payload)[:120],
    }
    it["end"] = round(start + frames_of(it) / FPS, 3)
    it["photos"] = auto_photos(project, it, st, keep=(prev or {}).get("photos"))
    return normalise_item(it) or it  # exactly what the server keeps (a save changes nothing)


def _soundbite_spans(project):
    scenes = project.get("scenes") or []
    offsets, _ = motion.scene_offsets(scenes)
    return [(offsets[i], offsets[i] + max(1, round(float(s.get("duration") or 0) * FPS)) / FPS)
            for i, s in enumerate(scenes) if s.get("insert_audio")]


def _span(times, a, b):
    t0 = times[a][0]
    t1 = times[b - 1][1]
    return (None, None) if t0 is None or t1 is None else (max(0.0, t0 - LEAD), t1 + max(TAIL, LAST_HOLD) + 0.6)


def suggest(project, existing=(), collection=DEFAULT_COLLECTION):
    """Read the whole narration and place this collection's graphics where they are meaningful
    (cinegfx `core.select`): never over another graphic you keep, never across a soundbite."""
    coll = registry().get(collection)
    if not coll:
        raise ValueError("Unknown collection.")
    st, times, words = story_for(project)
    if not st.sentences:
        return []
    taken = [(float(x["start"]), float(x["end"])) for x in existing]
    bites = _soundbite_spans(project)

    def allowed(beat):
        a0, a1 = _span(times, beat.a, beat.b)
        if a0 is None:
            return False
        if any(a0 < e and s < a1 for s, e in taken):
            return False
        t0, t1 = times[beat.a][0], times[beat.b - 1][1]
        return not any(t0 < e and s < t1 for s, e in bites)  # a soundbite inside the passage: not here

    out = []
    for beat in core.select(st, coll, allowed=allowed):
        it = make_item(project, beat)
        if not it:
            continue
        prev = out[-1] if out else None
        if prev and it["start"] < prev["end"]:
            # back to back: this graphic will cover the previous one; it comes up later (a shorter lead-in) so the
            # previous graphic's last word stays readable, never before its own first word
            last = prev["start"] + prev["words"][-1][1]
            first = it["start"] + it["words"][0][1]
            lead = min(LEAD, max(MIN_LEAD, first - (last + HOLD)))
            it = make_item(project, beat, lead=lead) or it
        out.append(it)
    return out


def passage_window(project, start, end):
    """The sentences of the narration between `start` and `end` (timeline seconds): (a, b) or None."""
    st, times, _ = story_for(project)
    inside = [i for i, (t0, t1, _) in enumerate(times) if t0 is not None and t1 > start + 1e-3 and t0 < end - 1e-3]
    return (inside[0], inside[-1] + 1) if inside else None


def options(project, start, end, collection=DEFAULT_COLLECTION, window=None):
    """What the passage can be: [{category, label, score, a, b}], best first (one per category: its best
    window inside the passage). `window`: the sentences (a, b) themselves (remaking a graphic)."""
    coll = registry().get(collection)
    win = _window(project, window) if window else passage_window(project, start, end)
    if not coll or not win:
        return [], win
    st, _, _ = story_for(project)
    a, b = win
    best = {}
    for beat in core.candidates(st, coll):
        if beat.a >= a and beat.b <= b and (beat.category not in best or beat.score > best[beat.category].score):
            best[beat.category] = beat
    out = sorted(best.values(), key=lambda bt: -bt.score)
    return [{"category": bt.category, "label": coll.categories[bt.category].label, "score": bt.score, "a": bt.a, "b": bt.b,
             "beat": bt} for bt in out], win


def _window(project, window):
    try:
        a, b = int(window[0]), int(window[1])
    except (TypeError, ValueError, IndexError):
        return None
    n = len(story_for(project)[0].sentences)
    return (a, b) if 0 <= a < b <= n else None


def draft(project, start, end, collection=DEFAULT_COLLECTION, category="auto", item_id=None, prev=None, window=None):
    """A graphic from a passage you chose: the best category for it ("auto") or the one you asked for.
    Returns (item, options); raises ValueError with what the passage lacks."""
    coll = registry().get(collection)
    if not coll:
        raise ValueError("Unknown collection.")
    opts, win = options(project, start, end, collection, window)
    if not win:
        raise ValueError("There is no narration in this passage.")
    pick = opts[0] if (category == "auto" and opts) else next((o for o in opts if o["category"] == category), None)
    if not pick:
        if category == "auto":
            raise ValueError("Nothing in this passage calls for a cinematic graphic: " + _needs(coll))
        cat = coll.categories.get(category)
        raise ValueError(f"This passage has no {cat.label.lower() if cat else category}: {cat.about if cat else ''}".strip())
    it = make_item(project, pick["beat"], item_id=item_id, source="manual", status="draft", prev=prev)
    if not it:
        raise ValueError("The passage's words could not be timed.")
    return it, [{k: v for k, v in o.items() if k != "beat"} for o in opts]


def _needs(coll):
    return " ".join(f"{c.label}: {c.about}" for c in coll.categories.values())


# ====================================================================== the data

def _num(v, lo, hi, d):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return d if not math.isfinite(x) else max(lo, min(hi, x))


def normalise_item(it, n=0, image_assets=None):
    if not isinstance(it, dict) or it.get("template") != "cinematic":
        return None
    cat = _category(it)
    words = it.get("words")
    text = it.get("text")
    if not cat or not isinstance(text, str) or not isinstance(words, list) or not words or not isinstance(it.get("payload"), dict):
        return None
    try:
        payload = json.loads(json.dumps(it["payload"]))
        if len(json.dumps(payload)) > MAX_PAYLOAD:
            return None
        wl = []
        for w in words[:4000]:
            a, b = int(w[3]), int(w[4])
            if not (0 <= a < b <= len(text)):
                return None
            wl.append([str(w[0])[:60], round(float(w[1]), 3), round(float(w[2]), 3), a, b])
    except (TypeError, ValueError, IndexError):
        return None
    start = round(_num(it.get("start"), 0.0, 86400.0, 0.0), 3)
    dur = round(_num(it.get("dur"), 0.5, 600.0, wl[-1][2] + TAIL), 3)
    photos = {}
    for k, v in (it.get("photos") or {}).items() if isinstance(it.get("photos"), dict) else []:
        if not isinstance(v, dict):
            continue
        aid = str(v.get("asset_id") or "")
        if image_assets is not None and aid and aid not in image_assets:
            aid = ""
        photos[str(k)[:160]] = {"asset_id": aid, "credit": re.sub(r"\s+", " ", str(v.get("credit") or "")).strip()[:120],
                                "month": re.sub(r"\s+", " ", str(v.get("month") or "")).strip()[:30], "auto": v.get("auto") is True}
    out = {
        "id": re.sub(r"[^\w-]", "", str(it.get("id") or ""))[:24] or f"cg{n + 1}",
        "template": "cinematic",
        "status": it.get("status") if it.get("status") in ("suggested", "draft", "approved") else "draft",
        "start": start, "end": 0.0,
        "hide_captions": it.get("hide_captions") is not False,
        "source": "auto" if it.get("source") == "auto" else "manual",
        "reason": re.sub(r"\s+", " ", str(it.get("reason") or "")).strip()[:240],
        "collection": it["collection"], "category": it["category"],
        "score": round(_num(it.get("score"), 0.0, 10.0, 0.0), 3),
        "window": [int(_num((it.get("window") or [0, 0])[0], 0, 1e6, 0)), int(_num((it.get("window") or [0, 0])[-1], 0, 1e6, 0))],
        "text": text[:20000], "payload": payload, "words": wl, "dur": dur,
        "pauses": [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in (it.get("pauses") or [])[:2000]
                   if isinstance(p, (list, tuple)) and len(p) == 2],
        "photos": photos, "label": re.sub(r"\s+", " ", str(it.get("label") or cat.label)).strip()[:120],
    }
    try:  # where the next graphic covers it (motion.normalise sets it from the list; kept for the preview)
        cut = int(it.get("cut") or 0)
    except (TypeError, ValueError):
        cut = 0
    if 0 < cut < full_frames(out):
        out["cut"] = cut
        if it.get("cut_fade") is True:
            out["cut_fade"] = True
    look = normalise_look(it.get("look"), image_assets=image_assets)
    if look:
        out["look"] = look
    out["end"] = round(start + frames_of(out) / FPS, 3)
    return out


# ====================================================================== look (v0.4.63)

_KEY = re.compile(r"[A-Za-z0-9_-]{1,12}")


def normalise_look(v, project=False, image_assets=None):
    """A look as stored: only the choices made (an empty look follows the project / the design).
    Project: {vary, seed, palettes: {category: set}, accent, text, background, photo_id, dim}.
    Graphic: {palette, accent, text ("own": the design's own, over the project's), background, photo_id, still_at, dim}."""
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
    if bg in L.BACKDROPS:
        out["background"] = bg
        if bg == "photo":
            pid = re.sub(r"[^\w-]", "", str(v.get("photo_id") or ""))[:40]
            out["photo_id"] = pid if (image_assets is None or pid in image_assets) else ""
        if bg == "still" and not project and v.get("still_at") is not None:
            out["still_at"] = round(_num(v.get("still_at"), 0.0, 86400.0, 0.0), 3)
    if v.get("dim") is not None:
        out["dim"] = round(_num(v.get("dim"), L.DIM[0], L.DIM[1], L.DIM[2]), 2)
    # v0.4.64 type and layout. Project: {font, size, mirror, place}; a graphic's own: the same, where font "design",
    # size 1, mirror False or a full-size place mean "as designed" over the project's choice.
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
    """What the graphic is drawn with: its own choices over the project's over the design's
    {palette, colors, background, dim, photo_id, still_at, notes, picked, from}."""
    cat = _category(item)
    G = item.get("look") or {}
    P = look or {}
    src = {}
    if G.get("palette"):
        pal, src["palette"] = G["palette"], "graphic"
    elif (P.get("palettes") or {}).get(cat.key):
        pal, src["palette"] = P["palettes"][cat.key], "project"
    elif P.get("vary"):
        pal, src["palette"] = L.varied(cat, P.get("seed") or ""), "vary"
    else:
        pal, src["palette"] = None, "design"
    picks = {}
    for k in ("accent", "text"):
        if G.get(k):
            picks[k], src[k] = (None if G[k] == "own" else G[k]), "graphic"
        else:
            picks[k], src[k] = P.get(k), ("project" if P.get(k) else "design")
    if G.get("background"):
        bg, photo, still, src["background"] = G["background"], G.get("photo_id") or "", G.get("still_at"), "graphic"
    else:
        bg, photo, still, src["background"] = P.get("background") or "own", P.get("photo_id") or "", None, ("project" if P.get("background") else "design")
    dim = G.get("dim") if G.get("dim") is not None else P.get("dim")
    r = L.resolve(cat, pal, picks["accent"], picks["text"], bg, dim)
    # v0.4.64 type and layout: the graphic's own over the project's over the design
    ty = {}
    for k in ("font", "size", "mirror", "place"):
        if k in G:
            ty[k], src[k] = G[k], "graphic"
        elif k in P:
            ty[k], src[k] = P[k], "project"
        else:
            ty[k], src[k] = None, "design"
    rt = L.resolve_type(cat, ty["font"], ty["size"], ty["mirror"], ty["place"])
    if src["mirror"] == "project" and not (cat.looks or {}).get("mirror"):
        rt["notes"] = [n for n in rt["notes"] if "mirrored" not in n]  # "mirror where it can": no note on the ones that cannot
    out = {"palette": r["palette"], "colors": r["colors"], "background": r["backdrop"], "notes": r["notes"] + rt["notes"], "picked": r["picked"],
           "from": src, "type": {"font": rt["font"], "fonts": rt["fonts"], "size": rt["size"], "mirror": rt["mirror"], "place": rt["place"]}}
    if r["backdrop"] in L.PICTURE:
        out["dim"] = r["dim"]
    if r["backdrop"] == "photo":
        out["photo_id"] = photo
    if r["backdrop"] == "still":
        out["still_at"] = round(float(still if still is not None else item["start"]), 3)
    return out


def see_through(item):
    """Drawn over the footage itself (the darkened video shows through): it does not cover what is under it."""
    return (item.get("style") or {}).get("background") == "footage"


def describe(it):
    s = max(0, int(it.get("start") or 0))
    cat = _category(it)
    name = f"cinematic {(cat.label if cat else 'graphic').lower()}"
    lab = str(it.get("label") or "").strip()
    return f"{name}" + (f" \u201c{lab}\u201d" if lab else "") + f" at {s // 60}:{s % 60:02d}"


# ====================================================================== photos (slots)

_GENERIC = {"street", "st", "station", "avenue", "ave", "road", "boulevard", "park", "place", "court", "courthouse", "the", "east",
            "west", "north", "south", "of", "and", "criminal", "supreme", "family", "county", "city", "hall", "square"}
_TAGS = {"vigil": {"vigil", "candle", "candles", "candlelight", "memorial"}, "memorial": {"memorial", "vigil", "candles", "tribute"},
         "funeral": {"funeral", "service"}}


def slots(item):
    cat = _category(item)
    return cat.photo_slots(item.get("payload") or {}) if cat else []


def _tokens(name):
    return set(re.findall(r"[a-z0-9]+", Path(str(name)).stem.lower()))


def auto_photos(project, item, st=None, keep=None):
    """Fill the graphic's photo slots from the project's own pictures whose file name names that person,
    place or event ("kenny.jpg" -> Joseph Kenny). A person is matched only by a name that identifies one
    person in the story (a surname shared by father and son matches neither). Choices you made are kept."""
    keep = keep or {}
    images = [a for a in project.get("assets") or [] if a.get("kind") == "image"]
    if st is None:
        st = story_for(project)[0]
    out = {}
    for sl in slots(item):
        k = sl["key"]
        if k in keep and (keep[k].get("asset_id") or not keep[k].get("auto")):
            out[k] = dict(keep[k])
            continue
        want = set()
        if sl["kind"] == "person":
            p = st.people.get(sl["value"])
            want = {x.lower() for x in (p.aliases if p else set()) if len(x) > 2}  # aliases are unique to one person
        elif sl["kind"] == "place":
            want = {w for w in re.findall(r"[a-z0-9]+", sl["value"].lower()) if w not in _GENERIC and len(w) > 2}
        elif sl["kind"] == "tag":
            want = _TAGS.get(sl["value"], {sl["value"]})
        hit = next((a for a in images if want and want & _tokens(a.get("name"))), None)
        out[k] = {"asset_id": hit["id"] if hit else "", "credit": str(hit.get("license") or "").strip()[:120] if hit else "",
                  "month": "", "auto": True}
    return out


BACKDROP = "__backdrop__"   # v0.4.63: the picture behind the graphic (a project photo or a still), in `files`


def photo_files(project, item, asset_path, data=None):
    """{slot key: {file, credit, month}} for the slots with a photo whose file is on this machine (what the
    graphic is drawn with; part of its cache key). v0.4.63: plus BACKDROP: {file}, the photo or footage still
    its look puts behind it (motion.background_path: taken once with FFmpeg and cached), when found."""
    assets = {a["id"]: a for a in project.get("assets") or [] if a.get("kind") == "image"}
    out = {}
    for k, v in (item.get("photos") or {}).items():
        a = assets.get(v.get("asset_id"))
        if not a:
            continue
        try:
            path = Path(asset_path(a))
        except (OSError, ValueError, KeyError):
            continue
        if path.is_file():
            out[k] = {"file": str(path), "credit": v.get("credit") or "", "month": v.get("month") or ""}
    st = item.get("style") or {}
    if st.get("background") in ("photo", "still") and data is not None:
        src = {"background": st["background"], "photo_id": st.get("photo_id") or "", "still_at": st.get("still_at", item.get("start", 0)),
               "start": item.get("start", 0)}
        f = motion.background_path(project, src, data, asset_path)
        if f:
            out[BACKDROP] = {"file": str(f), "credit": "", "month": ""}
    return out


def backdrop_used(item, files):
    """What the graphic is actually drawn over: its own background, the footage, or the photo / still when
    its file was found (else its own background: nothing is made up)."""
    bg = (item.get("style") or {}).get("background") or "own"
    if bg in ("photo", "still") and BACKDROP not in (files or {}):
        return "own"
    return bg


def _assets(item, files):
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


def _photo_sig(files):
    sig = []
    for k in sorted(files or {}):
        f = files[k]
        try:
            stt = os.stat(f["file"])
            sig.append([k, f["file"], stt.st_size, stt.st_mtime_ns, f.get("credit"), f.get("month")])
        except OSError:
            continue
    return sig


def item_hash(item, W, H, files=None):
    keep = {k: v for k, v in item.items() if k not in ("status", "reason", "source", "id", "hide_captions", "label", "photos", "score")}
    return hashlib.sha1(json.dumps([ENGINE, motion.ENGINE, keep, W, H, _photo_sig(files)], sort_keys=True).encode()).hexdigest()[:20]


# ====================================================================== drawing

_GRAPHICS: "OrderedDict[str, object]" = OrderedDict()
_GRAPHICS_LOCK = threading.Lock()


def build(item, files=None):
    """The cinegfx Graphic for an item (cached: building lays out the type and reads the photos once)."""
    key = item_hash(item, 0, 0, files)
    with _GRAPHICS_LOCK:
        g = _GRAPHICS.get(key)
        if g is not None:
            _GRAPHICS.move_to_end(key)
            return g
    cat = _category(item)
    if not cat:
        raise ValueError("Unknown cinematic graphic.")
    beat = core.Beat(item["collection"], item["category"], *item["window"], item.get("score", 0.0), item["payload"], [])
    style = item.get("style") or {}
    g = cat.graphic(beat, L.theme_for(cat, style.get("colors"), style.get("type")), timeline(item), _assets(item, files))
    g.place = L.placement((style.get("type") or {}).get("place"), D.W, D.H) if (style.get("type") or {}).get("place") else None  # v0.4.64
    used = backdrop_used(item, files)
    dim = float(style.get("dim") or L.DIM[2])
    g.backdrop = None  # v0.4.63: None (its own background), ("footage", dim) or ("picture", darkened picture)
    if used == "footage":
        g.backdrop = ("footage", dim)
    elif used in ("photo", "still"):
        g.backdrop = ("picture", _picture(files[BACKDROP]["file"], dim))
    with _GRAPHICS_LOCK:
        _GRAPHICS[key] = g
        while len(_GRAPHICS) > 8:
            _GRAPHICS.popitem(last=False)
    return g


def _picture(path, dim):
    """A photo or still behind the graphic: covering the frame with room for a slow push-in, darkened."""
    from PIL import ImageOps
    with Image.open(path) as src:
        im = ImageOps.exif_transpose(src).convert("RGB")
    size = (round(D.W * PUSH), round(D.H * PUSH))
    im = ImageOps.fit(im, size, Image.LANCZOS)
    return Image.blend(im, Image.new("RGB", size, (8, 8, 10)), dim).convert("RGBA")


PUSH = 1.04   # v0.4.63: a picture behind a graphic pushes in this much over the graphic (like the classic templates)


def _canvas(g, t, total):
    """The graphic at time t over what its look puts behind it (1920x1080 RGBA)."""
    bd = getattr(g, "backdrop", None)
    place = getattr(g, "place", None)
    if place is not None:  # v0.4.64: made smaller / placed: the layout is drawn on its own layer, the background stays full-frame
        return _placed(g, t, total, bd, place)
    if bd is None:
        return g.frame(t)  # its own background (the approved path, unchanged)
    if bd[0] == "footage":  # see-through: the darkening only; the video shows through in the preview and the export
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
    """The layout at its size and position over the full-frame background (its own, the darkened footage, a picture).
    Downscaled with Lanczos (sharp, no blur filter); at full size only moved."""
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
    if cut_fade is not None:  # v0.4.63: fading out under a see-through graphic, over its fade-in
        a_out = min(a_out, A.out_cubic(A.clamp((cut_fade - t) / FADE_IN)))
    return min(a_in, a_out)


def frame(g, item, n, W, H):
    """Frame `n` (at the app's FPS) as RGBA at W x H. The composition is 16:9 at 1920x1080: other 16:9
    sizes are a sharp (Lanczos) resize of it; a tall or square video gets it as a full-width panel on the
    category's own background."""
    t = n / FPS
    total = full_frames(item) / FPS  # a covered graphic (`cut`) has no exit: the next one is over it by then
    im = _canvas(g, t, total)
    see = getattr(g, "backdrop", None) is not None and g.backdrop[0] == "footage"
    if (W, H) != (D.W, D.H):
        if abs(W / H - D.W / D.H) < 0.01:
            im = im.resize((W, H), Image.LANCZOS)
        else:
            h = round(W * D.H / D.W)
            if h > H:  # wider than 16:9: full height
                w = round(H * D.W / D.H)
                panel, pos = im.resize((w, H), Image.LANCZOS), ((W - w) // 2, 0)
            else:
                panel, pos = im.resize((W, h), Image.LANCZOS), (0, (H - h) // 2)
            bg = Image.new("RGBA", (W, H), (8, 8, 10, int(round(255 * g.backdrop[1]))) if see else g.th.c("bg"))
            bg.paste(panel, pos)
            im = bg
    a = _envelope(t, total, frames_of(item) / FPS if item.get("cut_fade") else None)
    if a < 0.999:
        if see:  # see-through: scale its own transparency
            im.putalpha(im.getchannel("A").point(lambda v: int(round(v * a))))
        else:
            im.putalpha(int(round(255 * a)))
    return im


# ====================================================================== preview (the editor)

def preview_plan(data, project, item, files=None):
    W, H = motion.preview_size(project)
    h = item_hash(item, W, H, files)
    folder = motion.cache_root(data) / h
    folder.mkdir(parents=True, exist_ok=True)
    spec = folder / "item.json"
    if not spec.exists():
        tmp = spec.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"engine": "cinematic", "item": item, "W": W, "H": H, "files": files or {}}))
        os.replace(tmp, spec)
    n = frames_of(item)
    sl = slots(item)
    st = item.get("style") or {}
    return {"hash": h, "width": W, "height": H, "fps": FPS, "frames": list(range(n)), "unique": n, "start": item["start"],
            "layout": "cinematic", "layouts": [], "background": "cinematic",
            "slots": [dict(s, filled=s["key"] in (files or {})) for s in sl],
            "style": st, "backdrop": backdrop_used(item, files)}


def preview_frame(folder, spec, k, out):
    """Draw unique frame `k` of a planned cinematic graphic into `out` (WebP), like motion.preview_frame."""
    item = spec["item"]
    n = frames_of(item)
    if not 0 <= int(k) < n:
        raise KeyError(k)
    g = build(item, spec.get("files"))
    tmp = out.with_suffix(f".{threading.get_ident()}.tmp")
    frame(g, item, int(k), spec["W"], spec["H"]).save(tmp, "WEBP", quality=88, method=0, alpha_quality=90)
    os.replace(tmp, out)
    return out


# ====================================================================== export

_W = {}


def _worker_init(item, files, W, H):
    _W.update(g=build(item, files), item=item, W=W, H=H)


def _worker_frame(n):
    return frame(_W["g"], _W["item"], n, _W["W"], _W["H"]).tobytes()


def workers_for(n_frames):
    """Frame-drawing processes for an export: all cores but one (each frame is independent), at most 6
    (memory: ~120 MB each), and in-process for short graphics or small machines, where starting the
    workers would cost more than it saves. CASEFILE_CINEMATIC_WORKERS overrides."""
    env = os.environ.get("CASEFILE_CINEMATIC_WORKERS")
    if env and env.isdigit():
        return max(1, int(env))
    cpus = os.cpu_count() or 2
    if cpus <= 2 or n_frames < 96:
        return 1
    return max(1, min(6, cpus - 1))


def encode(item, files, W, H, out, cancelled=lambda: False, workers=None):
    """Every frame of the graphic into one video with transparency (the same container the classic
    graphics use, so the export's overlay is unchanged). Returns the number of frames drawn."""
    import subprocess
    n = frames_of(item)
    out = Path(out)
    tmp = out.with_name(f"{out.stem}.{threading.get_ident()}.tmp.mov")
    log = out.with_name(f"{out.stem}.{threading.get_ident()}.log")
    with open(log, "wb") as err:
        proc = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
                                 "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "qtrle", "-pix_fmt", "argb",
                                 "-g", str(FPS), "-f", "mov", str(tmp)], stdin=subprocess.PIPE, stderr=err)
    ok = False
    workers = workers or workers_for(n)
    try:
        if workers <= 1:
            g = build(item, files)
            for k in range(n):
                if cancelled():
                    raise RuntimeError("Cancelled by you. No output was published.")
                proc.stdin.write(frame(g, item, k, W, H).tobytes())
        else:
            ctx = mp.get_context("spawn")  # the macOS default; also safe under Windows and inside the server
            with ctx.Pool(workers, initializer=_worker_init, initargs=(item, files, W, H)) as pool:
                for buf in pool.imap(_worker_frame, range(n), chunksize=4):
                    if cancelled():
                        pool.terminate()
                        raise RuntimeError("Cancelled by you. No output was published.")
                    proc.stdin.write(buf)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("FFmpeg could not write the cinematic graphic: " + log.read_text(errors="replace")[-300:])
        os.replace(tmp, out)
        ok = True
    except (BrokenPipeError, OSError) as e:
        raise RuntimeError(f"FFmpeg could not write the cinematic graphic: {e} {log.read_text(errors='replace')[-300:]}")
    finally:
        if not ok:
            proc.kill()
            proc.wait()
            tmp.unlink(missing_ok=True)
        log.unlink(missing_ok=True)
    return n


def prepare_one(item, files, width, height, data, cancelled=lambda: False):
    """One exported cinematic graphic as a transparent video at the export size, cached by content.
    Returns the layer dict motion.prepare returns for every graphic."""
    h = item_hash(item, width, height, files)
    cache = motion.cache_root(data) / h
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / "export.mov"
    drawn = 0
    if not out.exists():
        drawn = encode(item, files, width, height, out, cancelled)
    else:
        os.utime(cache)
    n = frames_of(item)
    s0 = round(item["start"] * FPS) / FPS
    return {"start": s0, "end": s0 + n / FPS, "file": out, "frames": n, "unique": n, "drawn": drawn, "id": item["id"]}


# ====================================================================== sound (the graphic's own design)

def cues(item, files=None):
    """The graphic's designed sound cues: [{t (seconds from its start), sfx, gain_db, why}]. Built from the
    same Graphic the frames come from, so every sync point lands on its visual event."""
    g = build(item, files)
    until = (frames_of(item) / FPS - FADE_IN) if item.get("cut") else float("inf")  # covered: the rest is not seen
    return [{"t": float(c.t), "sfx": c.sfx, "gain_db": float(c.gain_db), "why": c.why} for c in g.cues if c.t < until - 1e-6]
