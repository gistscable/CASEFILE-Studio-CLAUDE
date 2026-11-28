"""v0.4.75 Your saved presets: set something up once, use it again in any project.

Kinds
  sticker   a sticker or text template as you set it up: its kind, size, place, opacity, words,
            strength, length and its keyframes (the move, with its speeds). Your own uploaded images
            belong to one project, so they are not saved as presets.
  move      a picture move (the scene's zoom/position keyframes with their speeds), from its first key.
  caption   a caption style.

Stored in <data>/presets.json (one file for the whole app, not inside a project), cleaned with the
same rules as the things themselves, so a preset can never hold anything a project could not.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid

import captionstyle
import picture
import stickers
import storage
from storage import atomic_json

KINDS = ("sticker", "move", "caption")
MAX = 300
NAME = 40
_LOCK = threading.Lock()


def path():
    return storage.DATA / "presets.json"  # read each time (tests point DATA elsewhere)


def clean_name(v, fallback="My preset"):
    s = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(v or ""))).strip()[:NAME]
    return s or fallback


def clean_data(kind, data):
    """The preset's settings, cleaned; None when there is nothing usable."""
    if not isinstance(data, dict):
        return None
    if kind == "sticker":
        if data.get("kind") == "image":
            return None
        got = stickers.normalise([{**data, "id": "p", "start": 0}])
        if not got:
            return None
        st = got[0]
        st.pop("id", None)
        st.pop("start", None)
        return st
    if kind == "move":
        keys = picture.normalise_keyframes(data.get("keyframes"), 600.0)
        if len(keys) < 2:
            return None
        t0 = keys[0]["t"]
        return {"keyframes": [{**k, "t": round(k["t"] - t0, 3)} for k in keys]}
    if kind == "caption":
        return captionstyle.normalise(data)
    return None


def normalise(value):
    items = value.get("presets") if isinstance(value, dict) else None
    out, seen = [], set()
    for p in items if isinstance(items, list) else []:
        if not isinstance(p, dict) or p.get("kind") not in KINDS:
            continue
        data = clean_data(p["kind"], p.get("data"))
        pid = re.sub(r"[^\w-]", "", str(p.get("id") or ""))[:24]
        if data is None or not pid or pid in seen:
            continue
        seen.add(pid)
        out.append({"id": pid, "kind": p["kind"], "name": clean_name(p.get("name")),
                    "created": round(float(p.get("created") or 0), 3) if isinstance(p.get("created"), (int, float)) else 0.0,
                    "data": data})
    return out[:MAX]


def load():
    try:
        return normalise(json.loads(path().read_text()))
    except (OSError, ValueError):
        return []


def _save(items):
    atomic_json(path(), {"version": 1, "presets": items})


def add(kind, name, data):
    if kind not in KINDS:
        raise ValueError("Unknown kind of preset.")
    clean = clean_data(kind, data)
    if clean is None:
        raise ValueError("There is nothing to save in this preset." if kind != "sticker" or (data or {}).get("kind") != "image"
                         else "Your own images belong to one project, so they cannot be saved as presets.")
    with _LOCK:
        items = load()
        if len(items) >= MAX:
            raise ValueError(f"You can keep up to {MAX} presets. Delete some first.")
        p = {"id": uuid.uuid4().hex[:12], "kind": kind, "name": clean_name(name), "created": round(time.time(), 3), "data": clean}
        items.append(p)
        _save(items)
    return p


def rename(pid, name):
    with _LOCK:
        items = load()
        for p in items:
            if p["id"] == pid:
                p["name"] = clean_name(name, p["name"])
                _save(items)
                return p
    raise KeyError(pid)


def remove(pid):
    with _LOCK:
        items = load()
        rest = [p for p in items if p["id"] != pid]
        if len(rest) == len(items):
            raise KeyError(pid)
        _save(rest)
