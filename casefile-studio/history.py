"""v0.4.51 Undo and redo for every edit.

Before (v0.4.50) undo kept up to 8 full copies of 13 project fields inside the project file (a
guide project: 1.2 MB a copy, 85% of an 18 MB file that was written on every save and sent to the
browser after every edit), had no redo, and only script/scene changes and a few actions made a step:
CTA, stickers, crop, effects, watermark… could not be undone.

Now:
- `begin(project, label)` (storage.checkpoint) notes the state before an edit; `finish(project)`
  (called by storage.save_project) stores only what changed: whole fields, scenes and assets by id,
  guide (episode) data by key. Nothing changed: no step.
- Steps live in DATA/history/<id>.json (not in the project file): up to LIMIT undo steps and the
  redo steps. The project keeps only their names, `project["history"] = {"undo": [...], "redo": [...]}`,
  so the page can say "Undo: Move sticker".
- A new edit clears redo. The same edit repeated within MERGE_SECONDS (−/+ clicks on one control,
  typing in one field, one drag saved in parts) is one step.
- `undo(project)` / `redo(project)` apply a step and keep its opposite on the other list.
"""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid

import storage

LIMIT = 50  # undo steps kept
MAX_BYTES = 40_000_000  # and at most this much history per project (oldest steps go first)
MERGE_SECONDS = 1.5
OPEN_SECONDS = 300  # a begun step whose save never came (the edit failed) is forgotten

# Everything an edit can change. Sources, exports, messages and research are not undone (their
# review/approval state must not come back with an undo).
FIELDS = (
    "title", "topic", "target_minutes",
    "script", "script_dirty", "script_origin", "script_approved_hash",
    "scenes", "assets", "look", "captions", "narration_id", "music_id", "music_volume", "narration_volume", "review",
    "episode", "caption_style", "effects", "aspect", "vertical_fit", "cta", "name_cards",
    "watermark", "stickers", "motion", "sound", "music", "niche",
)
MISSING = "__casefile_missing__"
# Of a media file only what you edit is undone; its preview stills, codec, thumbnail… are made by
# Casefile (and remade, e.g. sharper stills in v0.4.50) and must never be put back to an old copy.
ASSET_KEYS = ("name", "license", "crop", "sticker")
_OPEN: dict[str, dict] = {}
_LOCK = threading.RLock()


# ------------------------------------------------------------------ the file

def path(project_id):
    return storage.DATA / "history" / f"{project_id}.json"


def load(project_id):
    try:
        h = json.loads(path(project_id).read_text())
        if isinstance(h, dict) and isinstance(h.get("undo"), list) and isinstance(h.get("redo"), list):
            return h
    except (OSError, ValueError):
        pass
    return {"undo": [], "redo": []}


def _save(project, h):
    while len(h["undo"]) > LIMIT:
        h["undo"].pop(0)
    data = json.dumps(h, ensure_ascii=False)
    while len(data) > MAX_BYTES and len(h["undo"]) + len(h["redo"]) > 1:
        (h["undo"] or h["redo"]).pop(0)
        data = json.dumps(h, ensure_ascii=False)
    p = path(project["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(data)
    tmp.replace(p)
    project["history"] = summary(h)


def summary(h):
    return {"undo": [e.get("label", "Edit") for e in h["undo"]], "redo": [e.get("label", "Edit") for e in h["redo"]]}


def adopt(project):
    """On load: the step names from the history file; a v0.4.50 project's own copies (`undo`)
    become history once, without rewriting the project file here (that happens on its next save)."""
    legacy = project.pop("undo", None)
    if project.get("id") is None:
        return project
    exists = path(project["id"]).exists()
    if not exists and isinstance(legacy, list) and legacy:
        with _LOCK:
            h = {"undo": _from_legacy(project, legacy), "redo": []}
            _save(project, h)
    elif not exists:
        project["history"] = {"undo": [], "redo": []}
    elif not isinstance(project.get("history"), dict):
        project["history"] = summary(load(project["id"]))
    return project


def _from_legacy(project, legacy):
    """v0.4.50 kept whole copies; keep only what each changed (same result when undone)."""
    after = take(project)
    out = []
    for snap in reversed([s for s in legacy if isinstance(s, dict)]):
        before = {**after, **{k: copy.deepcopy(v) for k, v in snap.items() if k in FIELDS}}
        patch = diff(before, after)
        if patch:
            out.append({"label": "Earlier edit", "t": 0, "group": None, "patch": patch})
        after = before
    return list(reversed(out))


# ------------------------------------------------------------------ states and patches

def take(project):
    return {k: copy.deepcopy(project[k]) if k in project else MISSING for k in FIELDS}


def _ids(items):
    ids = [x.get("id") for x in items] if isinstance(items, list) and all(isinstance(x, dict) for x in items) else None
    return ids if ids is not None and None not in ids and len(set(ids)) == len(ids) else None


def diff(before, after):
    """The patch that turns `after` back into `before` (only what differs), or {}."""
    patch = {}
    for k in FIELDS:
        b, a = before.get(k, MISSING), after.get(k, MISSING)
        if b == a:
            continue
        if k == "scenes" and _ids(b) is not None and _ids(a) is not None:
            now = {x["id"]: x for x in a}
            patch["scenes"] = {"order": _ids(b), "items": {x["id"]: x for x in b if now.get(x["id"]) != x}}
        elif k == "assets" and _ids(b) is not None and _ids(a) is not None:
            was = {x["id"]: x for x in b}
            now = {x["id"]: x for x in a}
            keys = {}
            for i in was.keys() & now.keys():
                d = {f: was[i].get(f, MISSING) for f in ASSET_KEYS if was[i].get(f, MISSING) != now[i].get(f, MISSING)}
                if d:
                    keys[i] = d
            put = {i: x for i, x in was.items() if i not in now}
            remove = [i for i in now if i not in was]
            if keys or put or remove:
                patch["assets"] = {"put": put, "remove": remove, "keys": keys}
        elif k == "episode" and isinstance(b, dict) and isinstance(a, dict):
            patch["episode"] = {"set": {i: v for i, v in b.items() if a.get(i, MISSING) != v}, "remove": [i for i in a if i not in b]}
        else:
            patch.setdefault("fields", {})[k] = b
    return patch


def apply(project, patch):
    """Apply `patch` to the project; return the patch that undoes this."""
    back = {}
    for k, v in (patch.get("fields") or {}).items():
        back.setdefault("fields", {})[k] = copy.deepcopy(project[k]) if k in project else MISSING
        if v == MISSING:
            project.pop(k, None)
        else:
            project[k] = copy.deepcopy(v)
    if "scenes" in patch:
        cur = project.get("scenes") or []
        by = {x.get("id"): x for x in cur if isinstance(x, dict)}
        sp = patch["scenes"]
        keep = set(sp["order"])
        back["scenes"] = {"order": [x.get("id") for x in cur],
                          "items": {i: copy.deepcopy(x) for i, x in by.items() if i in sp["items"] or i not in keep}}
        project["scenes"] = [copy.deepcopy(sp["items"][i]) if i in sp["items"] else by[i]
                             for i in sp["order"] if i in sp["items"] or i in by]
    if "assets" in patch:
        cur = project.setdefault("assets", [])
        at = {x.get("id"): n for n, x in enumerate(cur)}
        ap = patch["assets"]
        back["assets"] = {"put": {}, "remove": [], "keys": {}}
        for i, d in (ap.get("keys") or {}).items():
            if i not in at:
                continue
            x = cur[at[i]]
            back["assets"]["keys"][i] = {f: copy.deepcopy(x.get(f, MISSING)) for f in d}
            for f, v in d.items():
                if v == MISSING:
                    x.pop(f, None)
                else:
                    x[f] = copy.deepcopy(v)
        for i, x in ap["put"].items():
            if i in at:
                back["assets"]["put"][i] = copy.deepcopy(cur[at[i]])
                cur[at[i]] = copy.deepcopy(x)
            else:
                back["assets"]["remove"].append(i)
                cur.append(copy.deepcopy(x))
        gone = set(ap["remove"])
        for x in cur:
            if x.get("id") in gone:
                back["assets"]["put"][x["id"]] = copy.deepcopy(x)
        project["assets"] = [x for x in cur if x.get("id") not in gone]
    if "episode" in patch:
        e = project.get("episode")
        if not isinstance(e, dict):
            e = project["episode"] = {}
        ep = patch["episode"]
        back["episode"] = {"set": {}, "remove": []}
        for i, v in ep["set"].items():
            if i in e:
                back["episode"]["set"][i] = copy.deepcopy(e[i])
            else:
                back["episode"]["remove"].append(i)
            e[i] = copy.deepcopy(v)
        for i in ep["remove"]:
            if i in e:
                back["episode"]["set"][i] = e.pop(i)
    return back


# ------------------------------------------------------------------ names

SCENE_WORDS = {
    "duration": "length", "narration": "narration", "asset_id": "picture", "motion": "movement",
    "keyframes": "keyframes", "fit": "fill", "transition": "transition", "title": "title",
    "show_title": "title card", "captions": "captions", "trim_start": "clip start", "source_ids": "sources",
    "chapter": "chapter", "lower_third": "name card", "cta": "CTA", "audio_break": "audio break",
}
FIELD_WORDS = {
    "title": "Project title", "topic": "Topic", "target_minutes": "Target length", "script": "Script edit",
    "look": "Look", "captions": "Captions on/off", "narration_id": "Narration track", "music_id": "Music track",
    "music_volume": "Music volume", "music": "Music placement", "narration_volume": "Narration volume", "review": "Review checklist", "episode": "Episode setup",
    "caption_style": "Caption style", "effects": "Effects", "aspect": "Format", "vertical_fit": "Vertical fill",
    "name_cards": "Name cards", "watermark": "Watermark", "niche": "Documentary niche",
}
SIDE_EFFECTS = {"script", "script_dirty", "script_origin", "script_approved_hash", "review", "episode", "narration_id"}


def _changed_items(b, a):
    b = b if isinstance(b, list) else []
    a = a if isinstance(a, list) else []
    was = {x.get("id"): x for x in b if isinstance(x, dict)}
    now = {x.get("id"): x for x in a if isinstance(x, dict)}
    added = [i for i in now if i not in was]
    removed = [i for i in was if i not in now]
    changed = [i for i in now if i in was and now[i] != was[i]]
    # A setting saved for the first time with its default (fill "cover", 0, off…) is not what you
    # changed: name the step after the real change.
    real = lambda i: {k for k in set(was[i]) | set(now[i])
                      if was[i].get(k) != now[i].get(k) and not (k not in was[i] and not now[i].get(k))}
    if any(real(i) for i in changed):
        changed = [i for i in changed if real(i)]
        keys = sorted({k for i in changed for k in real(i)})
    else:
        keys = sorted({k for i in changed for k in set(was[i]) | set(now[i]) if was[i].get(k) != now[i].get(k)})
    return was, now, added, removed, changed, keys


def _guide_keyed(items):
    """Guide scenes get new ids when the timeline is rebuilt after an edit: match them by their
    place in the narration instead (as episode.scene_key does)."""
    out = []
    for x in items or []:
        if not isinstance(x, dict) or not x.get("guide_cue_id"):
            return None
        k = f'{x.get("guide_cue_id")}|{round(float(x.get("audio_start") or 0) * 24)}|{bool(x.get("insert_audio"))}'
        out.append({**{f: v for f, v in x.items() if f not in ("id", "media_url", "media_kind")}, "id": k})
    return out if len({x["id"] for x in out}) == len(out) else None


def _scenes_name(b, a):
    was, now, added, removed, changed, keys = _changed_items(b, a)
    if added and removed:
        kb, ka = _guide_keyed(b), _guide_keyed(a)
        if kb is not None and ka is not None:
            b, a = kb, ka
            was, now, added, removed, changed, keys = _changed_items(b, a)
    order = [x.get("id") for x in (a or [])]
    num = lambda i: order.index(i) + 1 if i in order else [x.get("id") for x in b].index(i) + 1
    if added and len(added) == 1 and len(changed) == 1 and not removed:
        return f"Split scene {num(changed[0])}", None
    if added:
        return ("Add scene" if len(added) == 1 else f"Add {len(added)} scenes"), None
    if removed:
        return (f"Delete scene {num(removed[0])}" if len(removed) == 1 else f"Delete {len(removed)} scenes"), None
    if not changed:
        return "Reorder scenes", None
    # Side effects of a guide rebuild (review flags on every scene) are not what you edited.
    named = [i for i in changed if any(k in SCENE_WORDS and was[i].get(k) != now[i].get(k) for k in keys)]
    if named and len(named) < len(changed):
        changed = named
        keys = sorted({k for i in named for k in keys if k in SCENE_WORDS and was[i].get(k) != now[i].get(k)})
    words = []
    for k in keys:
        w = SCENE_WORDS.get(k)
        if w and w not in words:
            words.append(w)
    what = " + ".join(words[:2]) if words else "edit"
    group = "scenes:" + ",".join(changed) + ":" + ",".join(keys)
    if len(changed) == 1:
        return f"Scene {num(changed[0])} · {what}", group
    return f"{len(changed)} scenes · {what}", group


def _stickers_name(b, a):
    was, now, added, removed, changed, keys = _changed_items(b, a)
    try:
        import stickers
        label = lambda x: stickers.CATALOG.get(x.get("kind"), {}).get("label") or "your image"
    except Exception:  # pragma: no cover
        label = lambda x: "sticker"
    if added:
        return (f"Add sticker · {label(now[added[0]])}" if len(added) == 1 else f"Add {len(added)} stickers"), None
    if removed:
        return ("Remove sticker" if len(removed) == 1 else f"Remove {len(removed)} stickers"), None
    if not changed:
        return "Reorder stickers", None
    k = set(keys)
    what = ("Move sticker" if k <= {"x", "y"} else "Resize sticker" if k <= {"size"} else
            "Sticker opacity" if k <= {"opacity"} else "Sticker timing" if k <= {"start", "length"} else
            "Sticker keyframes" if k <= {"keyframes"} else "Edit sticker")
    return what, "stickers:" + ",".join(changed) + ":" + ",".join(keys)


def _motion_name(b, a):
    b, a = b if isinstance(b, dict) else {}, a if isinstance(a, dict) else {}
    if bool(b.get("enabled")) != bool(a.get("enabled")) and b.get("items") == a.get("items"):
        return ("Motion graphics on" if a.get("enabled") else "Motion graphics off"), None
    was, now, added, removed, changed, keys = _changed_items(b.get("items"), a.get("items"))
    if added and all(now[i].get("status") == "suggested" for i in added):
        return (f"Suggest {len(added)} motion graphic{'s' if len(added) != 1 else ''}"), None
    if added:
        return ("Add motion graphic" if len(added) == 1 else f"Add {len(added)} motion graphics"), None
    if removed:
        return ("Remove motion graphic" if len(removed) == 1 else f"Remove {len(removed)} motion graphics"), None
    if not changed:
        return "Motion graphics", None
    k = set(keys)
    if k == {"status"}:
        st = {now[i].get("status") for i in changed}
        return ("Approve motion graphic" if st == {"approved"} else "Unapprove motion graphic"), None
    what = ("Motion graphic text" if k <= {"heading", "title", "lines"} else
            "Motion graphic timing" if k <= {"start", "end", "lines"} else
            "Motion graphic style" if k <= {"font", "size", "accent", "text_color", "align", "x", "y", "speed",
                                             "enter", "exit", "background", "photo_id", "dim", "layout", "hide_captions"} else
            "Edit motion graphic")
    return what, "motion:" + ",".join(changed) + ":" + ",".join(keys)


def _sound_name(b, a):
    """v0.4.56 The sound design: settings, or one sound placed, moved, changed or removed."""
    try:  # a project that never had sound design has the defaults
        import sound

        b, a = sound.normalise(b), sound.normalise(a)
    except Exception:  # pragma: no cover
        b, a = b if isinstance(b, dict) else {}, a if isinstance(a, dict) else {}
    keys = sorted(k for k in set(b) | set(a) if k != "items" and b.get(k) != a.get(k))
    if keys and b.get("items") == a.get("items"):
        if keys == ["enabled"]:
            return ("Sound design on" if a.get("enabled") else "Sound design off"), None
        words = {"preset": "Sound preset", "master": "Sound effects volume", "intensity": "Sound intensity", "density": "Sound density",
                 "mode": "Sound design mode", "duck": "Dialogue protection", "kinds": "Sound design switches", "lead": "Sound timing"}
        return (words.get(keys[0], "Sound design") if len(keys) == 1 else "Sound design settings"), "sound:" + ",".join(keys)
    was, now, added, removed, changed, ikeys = _changed_items(b.get("items"), a.get("items"))
    if len(added) == 1 and not removed and not changed and now[added[0]].get("source") == "auto":
        # in automatic mode a planned sound is stored only once you change it
        x = now[added[0]]
        return ("Remove sound effect" if x.get("status") == "removed" else "Edit sound effect"), None
    if added and not removed and all(now[i].get("source") == "auto" and now[i].get("edited") for i in added):
        # v0.4.57 several planned sounds changed at once ("every line in this graphic", "the whole
        # graphic"): stored the first time they are changed, so they arrive as additions
        n = len(added) + len(changed)
        if all(now[i].get("status") == "removed" for i in added + changed):
            return f"Remove {n} sound effects", None
        return f"Edit {n} sound effects", None
    if added and len(added) > 1:
        return f"Plan {len(added)} sound effects", None
    if added:
        return "Add sound effect", None
    if removed:
        return ("Remove sound effect" if len(removed) == 1 else f"Remove {len(removed)} sound effects"), None
    if not changed:
        return "Sound design", None
    k = set(ikeys) - {"edited"}
    if k == {"status"}:
        st = {now[i].get("status") for i in changed}
        return ("Mute sound effect" if st == {"removed"} else "Restore sound effect"), None
    what = ("Move sound effect" if k <= {"offset"} else "Sound effect volume" if k <= {"gain"} else
            "Sound effect fades" if k <= {"fade_in", "fade_out", "length"} else "Replace sound effect" if k <= {"sound", "label"} else
            "Edit sound effect")
    return what, "sound:" + ",".join(changed) + ":" + ",".join(sorted(k))


def _cta_name(b, a):
    b, a = b if isinstance(b, dict) else {}, a if isinstance(a, dict) else {}
    keys = sorted(k for k in set(b) | set(a) if b.get(k) != a.get(k))
    k = set(keys)
    if k <= {"spots", "extra"}:
        what = "CTA places"
    elif k <= {"size", "x", "y"}:
        what = "Move CTA" if k <= {"x", "y"} else "Resize CTA"
    elif k <= {"opacity"}:
        what = "CTA opacity"
    elif k <= {"enabled"}:
        what = "CTA on" if a.get("enabled") else "CTA off"
    else:
        what = "CTA settings"
    return what, "cta:" + ",".join(keys)


def _assets_name(b, a):
    was, now, added, removed, changed, keys = _changed_items(b, a)
    name = lambda x: x.get("name") or "file"
    if added:
        return (f"Add media · {name(now[added[0]])}" if len(added) == 1 else f"Add {len(added)} files"), None
    if removed:
        return (f"Delete media · {name(was[removed[0]])}" if len(removed) == 1 else f"Delete {len(removed)} files"), None
    if keys == ["crop"]:
        x = now[changed[0]]
        return (f"Crop · {name(x)}" if x.get("crop") else f"Whole picture · {name(x)}"), "assets:" + ",".join(changed) + ":crop"
    if keys == ["sticker"]:
        return "Sticker image", None
    return "Media details", "assets:" + ",".join(changed) + ":" + ",".join(keys)


def _view(k, v):
    if k == "assets" and isinstance(v, list):
        return [{f: x.get(f) for f in ("id",) + ASSET_KEYS} for x in v if isinstance(x, dict)]
    return v


def describe(before, after):
    """(name, merge group) of the change from `before` to `after`."""
    changed = [k for k in FIELDS if _view(k, before.get(k, MISSING)) != _view(k, after.get(k, MISSING))]
    if not changed:
        return "Edit", None
    main = [k for k in changed if k not in SIDE_EFFECTS] or changed
    if "script" in changed and "scenes" not in changed:
        main = ["script"] + [k for k in main if k != "script"]
    parts = []
    for k in main:
        b, a = before.get(k), after.get(k)
        if k == "scenes":
            parts.append(_scenes_name(b, a))
        elif k == "stickers":
            parts.append(_stickers_name(b, a))
        elif k == "cta":
            parts.append(_cta_name(b, a))
        elif k == "motion":
            parts.append(_motion_name(b, a))
        elif k == "sound":
            parts.append(_sound_name(b, a))
        elif k == "assets":
            parts.append(_assets_name(_view(k, b), _view(k, a)))
        elif k in FIELD_WORDS:
            parts.append((FIELD_WORDS[k], "field:" + k if k != "episode" else None))
        elif k in ("script_dirty", "script_origin", "script_approved_hash"):
            continue
        else:
            parts.append(("Edit", None))
    if not parts:
        return "Edit", None
    if len(parts) == 1:
        return parts[0]
    return " + ".join(p[0] for p in parts[:2]), None


# ------------------------------------------------------------------ steps

def begin(project, label=None):
    """Note the state before an edit (the first call wins until the project is saved)."""
    if not isinstance(project, dict) or not project.get("id"):
        return
    with _LOCK:
        now = time.time()
        for k in [k for k, v in _OPEN.items() if now - v["t"] > OPEN_SECONDS]:
            _OPEN.pop(k, None)
        token = project.get("_history_token")
        if token in _OPEN:
            if label and not _OPEN[token]["label"]:
                _OPEN[token]["label"] = label
            return
        token = uuid.uuid4().hex
        project["_history_token"] = token
        _OPEN[token] = {"before": take(project), "label": label, "t": now}


def finish(project):
    """Called on save: store the begun step if anything changed."""
    token = project.pop("_history_token", None)
    with _LOCK:
        open_step = _OPEN.pop(token, None) if token else None
        if not open_step:
            return
        record(project, open_step["before"], open_step["label"])


def _without_clock(state):
    """A guide rebuild stamps the time it was built; that alone is not an edit."""
    e = state.get("episode")
    if isinstance(e, dict) and isinstance(e.get("plan"), dict):
        return {**state, "episode": {**e, "plan": {k: v for k, v in e["plan"].items() if k != "built_at"}}}
    return state


def record(project, before, label=None):
    """Store the step from `before` to the project as it is now (if anything changed)."""
    after = take(project)
    patch = diff(before, after)
    if not patch or _without_clock(before) == _without_clock(after):
        return False
    name, group = describe(before, after)
    if label:
        name, group = label, None
    with _LOCK:
        h = load(project["id"])
        now = time.time()
        top = h["undo"][-1] if h["undo"] else None
        if group and top and top.get("group") == group and now - top.get("t", 0) < MERGE_SECONDS and not h["redo"]:
            # the same control again: one step, from before the first change to now
            state = copy.deepcopy(after)
            scratch = {k: v for k, v in state.items() if v != MISSING}
            apply(scratch, patch)
            apply(scratch, top["patch"])
            first = {k: scratch.get(k, MISSING) for k in FIELDS}
            merged = diff(first, after)
            if merged:
                top.update(patch=merged, t=now)
            else:
                h["undo"].pop()
        else:
            h["undo"].append({"label": name, "group": group, "t": now, "patch": patch})
        h["redo"] = []
        _save(project, h)
    return True


def _step(project, src, dst):
    with _LOCK:
        h = load(project["id"])
        if not h[src]:
            project["history"] = summary(h)
            return None
        entry = h[src].pop()
        back = apply(project, entry["patch"])
        h[dst].append({"label": entry.get("label", "Edit"), "group": None, "t": 0, "patch": back})
        _save(project, h)
        return entry.get("label", "Edit")


def undo(project):
    """Undo the last step; returns its name, or None when there is nothing to undo."""
    project.pop("_history_token", None)
    return _step(project, "undo", "redo")


def redo(project):
    project.pop("_history_token", None)
    return _step(project, "redo", "undo")


def forget(project_id):
    path(project_id).unlink(missing_ok=True)
