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

def select(story, collection: Collection, threshold: float = 0.6, min_gap: int = 2, repeat_decay: float = 0.7,
           max_per_chapter: int = 2):
    """Choose where graphics are meaningful. Every window of every chapter is offered to every category;
    candidates are taken best-first, never overlapping, spaced by `min_gap` sentences, at most
    `max_per_chapter` per chapter, and each re-use of a category decays its later scores so the edit
    doesn't repeat one composition. Returns beats in story order."""
    cands = []
    for cat in collection.categories.values():
        for a in range(len(story.sentences)):
            for n in range(cat.min_window, cat.max_window + 1):
                b = a + n
                if b > len(story.sentences) or (not cat.cross_chapter and story.sentences[b - 1].chapter != story.sentences[a].chapter):
                    break
                r = cat.detect(story, a, b)
                if r:
                    score, payload, reasons = r
                    cands.append(Beat(collection.key, cat.key, a, b, round(score, 3), payload, reasons))
    chosen, used = [], {}
    per_chapter = {}
    pool = sorted(cands, key=lambda c: -c.score)
    while pool:
        # re-score with the repetition decay, then take the best
        best = max(pool, key=lambda c: c.score * repeat_decay ** used.get(c.category, 0))
        eff = best.score * repeat_decay ** used.get(best.category, 0)
        if eff < threshold:
            break
        pool.remove(best)
        ch = story.sentences[best.a].chapter
        if per_chapter.get(ch, 0) >= max_per_chapter:
            continue
        if any(best.a < c.b + min_gap and c.a < best.b + min_gap for c in chosen):
            continue
        chosen.append(best)
        used[best.category] = used.get(best.category, 0) + 1
        per_chapter[ch] = per_chapter.get(ch, 0) + 1
    return sorted(chosen, key=lambda c: c.a)


# ------------------------------------------------------------------ assets

class Assets:
    """Authentic imagery with provenance (sources.json: file, subject, credit, month, people, places, tags).
    Graphics ask for a person/place/tag; nothing is ever generated or substituted with stock."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
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
        it = self.items[key]
        month = it.get("month", "")
        short = re.sub(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b",
                       lambda m: m.group(1)[:3], month)
        return ("PHOTO: " + it["credit"] + (" · " + short if short else "")).upper()
