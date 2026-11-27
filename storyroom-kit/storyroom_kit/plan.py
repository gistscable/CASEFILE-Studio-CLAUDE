"""The plan: which graphics go where, as one JSON file Storyroom (or a person) can read and edit before rendering.

    {
      "kit": "storyroom-kit", "version": ..., "fps": 24, "width": 1920, "height": 1080,
      "script": {"title", "subject", "sentences", "reference_date"},
      "timing": {"source": srt|words|audio|estimated, "matched", "notes", "offset"},
      "photos": {"folder": "photos" | null, "sources": true|false},
      "look": {...plan-wide look, optional...},
      "graphics": [ item, ... ]       # graphics.py: the same item format Casefile stores
    }

Edit freely: set a graphic's "status" to "skipped" to leave it out, give it a "look", fill its "photos", or
move its "start" (the reveals stay on its words because they are timed from the graphic's own start; move it
only if the narration moved by the same amount).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from . import graphics as G
from . import photos as P
from . import script as SC
from .cinegfx import draw as D


def make(raw_script: str, srt: str | None = None, words_json=None, audio: str | None = None, photos: str | None = None,
         look: dict | None = None, collection: str = G.DEFAULT_COLLECTION, categories=None, subject: str = "",
         offset: float = 0.0, wpm: float = 150.0, fps: int = 24) -> dict:
    """Read the script, time it, and place the graphics where the story calls for them (at `fps` frames a second)."""
    G.set_fps(fps)
    narr = SC.narration(raw_script, srt=srt, words_json=words_json, audio=audio, subject=subject, offset=offset, wpm=wpm)
    items = G.suggest(narr, collection=collection, categories=categories)
    sources = P.has_sources(photos)
    for it in items:
        it["slots"] = G.slots(it)
        it["photos"] = {} if sources else P.auto(narr.story, it, photos)
        it["sentences"] = [it["window"][0] + 1, it["window"][1]]  # 1-based, inclusive, for people reading the plan
    plan = {
        "kit": "storyroom-kit", "version": __version__, "fps": G.FPS, "width": D.W, "height": D.H,
        "collection": collection,
        "script": {"title": narr.story.title, "subject": narr.story.subject, "sentences": len(narr.story.sentences),
                   "reference_date": narr.story.reference.isoformat()},
        "timing": dict(narr.timing, offset=offset),
        "photos": {"folder": photos, "sources": sources},
        "look": G.normalise_look(look or {}, project=True),
        "graphics": items,
    }
    refresh(plan)
    return plan


def refresh(plan: dict) -> dict:
    """Resolve every graphic's look into its `style` and recompute where back-to-back graphics cover each other."""
    G.set_fps(plan.get("fps") or 24)
    for it in plan["graphics"]:
        it["style"] = G.style_of(it, plan.get("look"))
    G.handoffs(plan["graphics"])
    return plan


def relocate(plan: dict, to_dir, from_dir=None) -> dict:
    """Rewrite the photo paths (relative to `from_dir`, default the current folder) relative to `to_dir`, the
    folder the plan is saved in, so the plan still finds them when it is moved together with its photos."""
    import os
    src = Path(from_dir or Path.cwd()).resolve()
    to = Path(to_dir).resolve()

    def rel(p):
        if not p:
            return p
        q = Path(p)
        q = q if q.is_absolute() else src / q
        try:
            r = os.path.relpath(q.resolve(), to)
        except ValueError:  # another drive (Windows)
            return str(q.resolve())
        return str(q.resolve()) if r.split(os.sep)[:2] == ["..", ".."] else r  # far away: keep it absolute
    ph = plan.get("photos") or {}
    if ph.get("folder"):
        ph["folder"] = rel(ph["folder"])
    for it in plan["graphics"]:
        for v in (it.get("photos") or {}).values():
            if v.get("file"):
                v["file"] = rel(v["file"])
    if (plan.get("look") or {}).get("photo"):
        plan["look"]["photo"] = rel(plan["look"]["photo"])
    return plan


def save(plan: dict, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load(path) -> dict:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("kit") != "storyroom-kit" or not isinstance(plan.get("graphics"), list):
        raise ValueError(f"{path} is not a storyroom-kit plan.")
    for it in plan["graphics"]:
        if not G.category_of(it):
            raise ValueError(f"Graphic {it.get('id')}: unknown category {it.get('collection')}/{it.get('category')}.")
    return refresh(plan)


def summary(plan: dict) -> str:
    lines = [f"{plan['script']['title'] or 'Untitled'}: {len(plan['graphics'])} graphics "
             f"(timing: {plan['timing']['source']}, {round(plan['timing']['matched'] * 100)}% of words matched)"]
    for n, it in enumerate(plan["graphics"], 1):
        s, e = it["start"], it["end"]
        flag = " [skipped]" if it.get("status") == "skipped" else ""
        lines.append(f"  {n}. {it['category']:<13} {_tc(s)}–{_tc(e)}  {it['label']}{flag}")
    for note in plan["timing"].get("notes") or []:
        lines.append("  note: " + note)
    return "\n".join(lines)


def _tc(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"
