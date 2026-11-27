"""Photos a graphic may show: only real pictures you give it, never generated or stock.

Each graphic lists its photo *slots* (a person, a place or an event it can show). Two ways to fill them:

* A folder with `sources.json` (file, subject, credit, month, people, places, tags per photo): the graphic finds
  the person / place / tag it needs, with the credit you wrote. This is how the approved Javits demos work.
* A plain folder: a photo fills a slot when its file name names that person, place or event ("kenny.jpg" ->
  Joseph Kenny). A person is matched only by a name that identifies one person in the story (a surname shared
  by father and son matches neither). No credit is made up: add one in the plan (`photos.<slot>.credit`).

A slot left empty is simply not drawn.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import graphics as G

IMAGE = {".jpg", ".jpeg", ".png", ".webp"}
_GENERIC = {"street", "st", "station", "avenue", "ave", "road", "boulevard", "park", "place", "court", "courthouse", "the", "east",
            "west", "north", "south", "of", "and", "criminal", "supreme", "family", "county", "city", "hall", "square"}
_TAGS = {"vigil": {"vigil", "candle", "candles", "candlelight", "memorial"}, "memorial": {"memorial", "vigil", "candles", "tribute"},
         "funeral": {"funeral", "service"}}


def _tokens(name):
    return set(re.findall(r"[a-z0-9]+", Path(str(name)).stem.lower()))


def has_sources(folder) -> bool:
    return bool(folder) and (Path(folder) / "sources.json").is_file()


def images(folder):
    if not folder or not Path(folder).is_dir():
        return []
    return sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in IMAGE)


def auto(story, item, folder):
    """{slot key: {file, credit, month, auto: true}} for the slots a file in `folder` names (Casefile:
    cinematic.auto_photos). File paths are as found (absolute or relative to where you ran the kit)."""
    pics = images(folder)
    out = {}
    for sl in G.slots(item):
        want = set()
        if sl["kind"] == "person":
            p = story.people.get(sl["value"])
            want = {x.lower() for x in (p.aliases if p else set()) if len(x) > 2}
        elif sl["kind"] == "place":
            want = {w for w in re.findall(r"[a-z0-9]+", sl["value"].lower()) if w not in _GENERIC and len(w) > 2}
        elif sl["kind"] == "tag":
            want = _TAGS.get(sl["value"], {sl["value"]})
        hit = next((p for p in pics if want and want & _tokens(p.name)), None)
        if hit:
            out[sl["key"]] = {"file": str(hit), "credit": "", "month": "", "auto": True}
    return out


def files_for(item, base: Path):
    """The files a graphic is drawn with: {slot key: {file, credit, month}} (+ the photo behind it), resolved
    against the plan's folder; a missing file is left out."""
    out = {}
    for k, v in (item.get("photos") or {}).items():
        f = _resolve(v.get("file"), base)
        if f:
            out[k] = {"file": str(f), "credit": v.get("credit") or "", "month": v.get("month") or ""}
    st = item.get("style") or {}
    if st.get("background") == "photo":
        f = _resolve(st.get("photo"), base)
        if f:
            out[G.BACKDROP] = {"file": str(f), "credit": "", "month": ""}
    return out


def _resolve(path, base: Path):
    if not path:
        return None
    p = Path(path)
    for cand in ([p] if p.is_absolute() else [base / p, Path.cwd() / p]):
        if cand.is_file():
            return cand.resolve()
    return None
