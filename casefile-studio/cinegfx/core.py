"""Core of the cinematic graphics engine: niche-agnostic.

  Story (story.py) -> Collection.detect (per category) -> select() -> Beat -> Graphic (per category)
  -> frames (render.py) + Cues (sfx.py)

A Collection is a niche (true crime, football, boxing, history ...). It registers Categories; each
Category bundles a detector (does this stretch of script call for me, and with what content?), a
Theme, and a Graphic class (how to draw it, given the narration timeline). The core never imports a
collection, so new niches are added by dropping a module in collections/ and calling register()."""
from __future__ import annotations

import importlib
import json
import pkgutil
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import anim
from .draw import H, W


@dataclass
class Cue:
    t: float            # when the sound's sync point should land (s, graphic-local)
    sfx: str            # sfxlib id
    gain_db: float = 0.0
    why: str = ""


@dataclass
class Beat:
    collection: str
    category: str
    a: int              # sentence window [a, b) in the story
    b: int
    score: float
    payload: dict
    reasons: list = field(default_factory=list)

    def text(self, story) -> str:
        return story.window_text(self.a, self.b)


class Graphic:
    """Base class: subclasses implement build() (times, cues, layout from payload+timeline) and draw(canvas, t)."""
    fps = 30

    def __init__(self, beat: Beat, theme, timeline, assets: "Assets", story_meta: dict | None = None):
        self.beat, self.p, self.th, self.tl, self.assets = beat, beat.payload, theme, timeline, assets
        self.meta = story_meta or {}
        self.cues: list[Cue] = []
        self.duration = timeline.duration + 0.6
        self.out = self.duration - anim.EXIT - 0.05
        self.build()

    # timing helpers -------------------------------------------------
    def at(self, phrase: str, after: int = 0, default: float | None = None, end: bool = False) -> float:
        hit = self.tl.phrase(phrase, after) if phrase else None
        if not hit:
            return default if default is not None else 0.0
        return hit[1] if end else hit[0]

    def span(self, phrase: str, after: int = 0):
        hit = self.tl.phrase(phrase, after) if phrase else None
        return (hit[0], hit[1]) if hit else (None, None)

    def cue(self, t, sfx, gain_db=0.0, why=""):
        self.cues.append(Cue(round(max(0.0, t), 3), sfx, gain_db, why))

    def build(self):
        raise NotImplementedError

    def draw(self, canvas, t: float):
        raise NotImplementedError

    def frame(self, t: float):
        from PIL import Image
        canvas = Image.new("RGBA", (W, H), self.th.c("bg"))
        self.draw(canvas, t)
        return canvas


@dataclass
class Category:
    key: str
    label: str
    theme: object
    detect: callable           # (story, a, b) -> (score, payload, reasons) | None
    graphic: type
    max_window: int = 3
    min_window: int = 1
    cross_chapter: bool = False   # e.g. a chapter-ending question answered by the next chapter's first line
    slots: callable = None        # (payload) -> [{key, kind: person|place|tag, value, label}]: photos it can show
    about: str = ""               # one line for the editor: what this graphic is for

    def photo_slots(self, payload) -> list:
        return list(self.slots(payload)) if self.slots else []


class Collection:
    key = ""
    label = ""
    categories: dict

    def __init__(self):
        self.categories = {}

    def add(self, cat: Category):
        self.categories[cat.key] = cat


REGISTRY: dict[str, Collection] = {}


def register(c: Collection):
    REGISTRY[c.key] = c
    return c


def load_collections():
    from . import collections as pkg
    for m in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{m.name}")
    return REGISTRY


# ------------------------------------------------------------------ selection

def candidates(story, collection: Collection, categories=None):
    """Every (window, category) the detectors find meaningful: [Beat], unsorted. `categories`: only these."""
    cands = []
    for cat in collection.categories.values():
        if categories and cat.key not in categories:
            continue
        for a in range(len(story.sentences)):
            for n in range(cat.min_window, cat.max_window + 1):
                b = a + n
                if b > len(story.sentences) or (not cat.cross_chapter and story.sentences[b - 1].chapter != story.sentences[a].chapter):
                    break
                r = cat.detect(story, a, b)
                if r:
                    score, payload, reasons = r
                    cands.append(Beat(collection.key, cat.key, a, b, round(score, 3), payload, reasons))
    return cands


def select(story, collection: Collection, threshold: float = 0.6, min_gap: int = 2, repeat_decay: float = 0.7,
           max_per_chapter: int = 2, strong: float = 0.85, max_run: int = 3, cost: float = 0.55, allowed=None, cands=None):
    """Choose where graphics are meaningful, as a whole plan (best total value, not best-first).

    * Every window of every chapter is offered to every category (`candidates`).
    * Windows never overlap; between two graphics there are at least `min_gap` sentences of picture,
      except that two *strong* matches (>= `strong`) of *different* categories may follow each other
      directly as one sequence (a timeline, the arrest it leads to, then the docket). Never more than `max_run`
      graphics in a row.
    * At most `max_per_chapter` per chapter, never the same category twice in one chapter; each re-use of a category decays its value (x`repeat_decay`),
      so the edit doesn't repeat one composition; a beat worth less than `threshold` is left out.
    * Each graphic costs `cost` (it covers the picture): a plan is worth the sum of (value - cost), so two
      weak graphics never displace one strong one just to show more.
    * `allowed(beat) -> bool`: the caller's own veto (the app: no soundbite inside, not over another graphic).
    Returns beats in story order."""
    pool = [c for c in (cands if cands is not None else candidates(story, collection)) if c.score >= threshold and (allowed is None or allowed(c))]
    # the best few windows per category are enough: a weaker overlapping variant never beats its stronger sibling
    by_cat = {}
    for c in sorted(pool, key=lambda c: (-c.score, c.a, c.b)):
        lst = by_cat.setdefault(c.category, [])
        if len(lst) < 8:
            lst.append(c)
    pool = sorted((c for lst in by_cat.values() for c in lst), key=lambda c: (c.a, c.b))
    chapter = lambda c: story.sentences[c.a].chapter

    def gap_ok(x, y):  # x before y
        g = y.a - x.b
        if g < 0:
            return False
        if g >= min_gap:
            return True
        return g == 0 and x.score >= strong and y.score >= strong and x.category != y.category

    def value(chosen):
        tot, used = 0.0, {}
        for c in sorted(chosen, key=lambda c: -c.score):
            k = used.get(c.category, 0)
            v = c.score * repeat_decay ** k
            if v < threshold:
                return None
            tot += v - cost
            used[c.category] = k + 1
        return tot

    best = {"v": 0.0, "set": []}

    def run_length(chosen, nxt):
        n, cur = 1, nxt
        for c in reversed(chosen):
            if cur.a - c.b == 0:
                n, cur = n + 1, c
            else:
                break
        return n

    def dfs(i, chosen, per_ch, bound):
        v = value(chosen)
        if v is not None and v > best["v"] + 1e-9:
            best["v"], best["set"] = v, list(chosen)
        if v is None or (v + bound[i] if i < len(pool) else v) <= best["v"] + 1e-9:
            return
        for j in range(i, len(pool)):
            c = pool[j]
            if chosen and not gap_ok(chosen[-1], c):
                continue
            ch = chapter(c)
            if per_ch.get(ch, 0) >= max_per_chapter or (chosen and run_length(chosen, c) > max_run):
                continue
            if any(x.category == c.category and chapter(x) == ch for x in chosen):
                continue
            chosen.append(c)
            per_ch[ch] = per_ch.get(ch, 0) + 1
            dfs(j + 1, chosen, per_ch, bound)
            per_ch[ch] -= 1
            chosen.pop()

    # optimistic bound on what candidates i.. can still add: the best `max_per_chapter` scores of each chapter
    bound = [0.0] * (len(pool) + 1)
    for i in range(len(pool)):
        per = {}
        for c in pool[i:]:
            per.setdefault(chapter(c), []).append(c.score)
        bound[i] = sum(sum(max(0.0, x - cost) for x in sorted(v, reverse=True)[:max_per_chapter]) for v in per.values())
    dfs(0, [], {}, bound)
    return sorted(best["set"], key=lambda c: c.a)


# ------------------------------------------------------------------ assets

class Assets:
    """Authentic imagery with provenance (sources.json: file, subject, credit, month, people, places, tags).
    Graphics ask for a person/place/tag; nothing is ever generated or substituted with stock."""

    def __init__(self, folder: str | Path | None = None, items: dict | None = None):
        """From a folder with sources.json (the demos), or from `items` directly (the app: the photos the
        producer assigned to a graphic, `file` an absolute path)."""
        self.folder = Path(folder) if folder else Path("/")
        if items is not None:
            self.items = items
        else:
            f = self.folder / "sources.json"
            self.items = json.loads(f.read_text()) if f.exists() else {}

    def find(self, person: str = "", place: str = "", tag: str = ""):
        for key, it in self.items.items():
            if person and person in it.get("people", []):
                return key, it
            if place and any(place.lower() in p.lower() or p.lower() in place.lower() for p in it.get("places", [])):
                return key, it
            if tag and tag in it.get("tags", []):
                return key, it
        return None, None

    def path(self, key: str) -> str:
        return str(self.folder / self.items[key]["file"])

    def credit(self, key: str) -> str:
        """"PHOTO: <credit> · <Mon YYYY>", or "" when nobody gave a credit (never made up)."""
        it = self.items[key]
        if not str(it.get("credit") or "").strip():
            return ""
        month = it.get("month", "")
        short = re.sub(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b",
                       lambda m: m.group(1)[:3], month)
        return ("PHOTO: " + it["credit"] + (" · " + short if short else "")).upper()
