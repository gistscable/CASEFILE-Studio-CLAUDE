"""v0.4.79 Sports on the Edit page (football, boxing & MMA, wrestling).

The Edit page builds the video: the editing guide places the shots, the clips are fetched (yt-dlp), renamed,
cropped as directed and fitted to the narration. The sports engine (cinegfx.sports) adds to that same timeline,
and everything it adds is visible and adjustable there:

    graphics        the narration's editorial graphics as motion graphics (sportsgfx.py): on the timeline,
                    previewed over the picture, approved or removed one by one, exported with the video
    empty scenes    only scenes with no clip from the guide: a shot chosen from the project's own footage for
                    what is said there (cinegfx.sports.shots finds the shots, the planner picks one); proposed
                    first, applied when you say so, then an ordinary scene you can change
    style           the storytelling style's grade (the project look), transitions where a chapter changes
                    (only where you have not chosen one) and an original music bed that follows the story's arc
                    (cinegfx.sports.score); proposed first, applied when you say so, undoable

Nothing is fetched or made up: every word on screen is from the narration, every picture from the project.
A true-crime project never sees any of this.

Saved on the project as `sports_edit`: {"style": "auto" | one of the six}.
"""
from __future__ import annotations

import re
from pathlib import Path

import niches
from cinegfx.sports import matte as M
from cinegfx.sports import planner as P
from cinegfx.sports import shots as SH

SPORTS = ("football", "boxing", "wrestling")

# the storytelling style on the Edit page: the project look (effects.LOOKS) and the transition where a chapter
# changes (effects.TRANSITIONS; None = a cut)
LOOK = {"emotional": "warm", "investigative": "cold", "historical": "archive", "high_energy": "punchy",
        "analytical": "natural"}
CHAPTER_TRANSITION = {"emotional": ("dissolve", 0.5), "investigative": ("dip-black", 0.6),
                      "historical": ("dissolve", 0.8), "high_energy": None, "analytical": None}


def eligible(project) -> bool:
    return niches.key_of(project) in SPORTS


def default():
    return {"style": "auto"}


def normalise(raw) -> dict:
    """Settings from the editor (ValueError on anything malformed)."""
    out = default()
    if raw is None:
        return out
    if not isinstance(raw, dict):
        raise ValueError("Sports settings must be an object.")
    style = raw.get("style", "auto")
    if style not in P.STYLES:
        raise ValueError("Unknown storytelling style.")
    out["style"] = style
    return out


def settings(project) -> dict:
    raw = project.get("sports_edit")
    try:
        return normalise({"style": raw.get("style", "auto")} if isinstance(raw, dict) else None)
    except ValueError:
        return default()


def folder(data_dir, pid) -> Path:
    return Path(data_dir) / "media" / pid / "sportsedit"


def cache_dir(data_dir, pid) -> Path:
    return folder(data_dir, pid) / "cache"


def segmentation() -> dict:
    """Is text-behind-the-player available, and how to switch it on."""
    ok = M.available()
    return {"available": ok, "reason": None if ok else M.unavailable_reason(),
            "model": str(M.model_path()) if ok else None,
            "how": [
                "Install the optional runtime: pip install onnxruntime (inside the app's Python environment).",
                "Put the Robust Video Matting model (rvm_mobilenetv3_fp32.onnx, converted from the official "
                "PeterL1n/RobustVideoMatting release) in casefile-studio/models/.",
                "Restart the app. Without it the graphics still export: the type goes in front of the player.",
            ],
            "license": "Robust Video Matting is GPL-3.0; it runs as a separate optional model file."}


# ====================================================================== the project's own footage

def media_assets(project):
    """The project's own footage and photos the engine may use (not the narration, music or logo)."""
    skip = {project.get("narration_id"), project.get("music_id"),
            ((project.get("watermark") or {}).get("asset_id"))}
    return [a for a in project.get("assets") or [] if a.get("kind") in ("video", "image") and a.get("id") not in skip]


def library(project, data_dir, asset_path, analyse_missing=False, progress=None, cancelled=None):
    """[{id, name, kind, duration, shots, analysed}] from cached analyses (analyse_missing: decode what is missing)."""
    out, todo = [], []
    cdir = cache_dir(data_dir, project["id"])
    for a in media_assets(project):
        try:
            path = str(asset_path(a))
        except ValueError:
            out.append({"id": a["id"], "name": a.get("name") or a["id"], "kind": a["kind"], "duration": None,
                        "shots": [], "analysed": False, "missing": True})
            continue
        info = SH.cached(path, cdir)
        item = {"id": a["id"], "name": a.get("name") or a["id"], "kind": a["kind"], "duration": a.get("duration"),
                "shots": (info or {}).get("shots") or [], "analysed": bool(info), "path": path}
        out.append(item)
        if not info:
            todo.append(item)
    if analyse_missing:
        for n, item in enumerate(todo):
            if cancelled and cancelled():
                break

            def step(pct, n=n, item=item):
                if progress:
                    progress(n, len(todo), pct, item["name"])
            step(0)
            info = SH.analyse(item["path"], cdir, step, float(item.get("duration") or 0) or None)
            item.update(shots=info["shots"], analysed=True)
    return out


# ====================================================================== the story

def resolved_style(project, style=None):
    """(style key, label) the storytelling style resolves to (Automatic reads the story)."""
    import sportsgfx
    _, els = sportsgfx.elements(project)
    key, p = P.resolve_style(style or settings(project)["style"], els)
    return key, p["label"]


def _offsets(project):
    import motion
    return motion.scene_offsets(project.get("scenes") or [])


# ====================================================================== empty scenes

def gaps(project):
    """Scenes the guide left without a clip: [(index, start, end)] on the timeline (soundbites excluded)."""
    scenes = project.get("scenes") or []
    offsets, total = _offsets(project)
    out = []
    for i, s in enumerate(scenes):
        if s.get("asset_id") or s.get("insert_audio"):
            continue
        out.append((i, offsets[i], offsets[i + 1] if i + 1 < len(offsets) else total))
    return out


def fill_proposals(project, data_dir, asset_path, lib=None):
    """A shot from the project's own footage for each scene without a clip, chosen for what is said there.
    {proposals: [{scene_id, index, start, end, asset_id, name, in, kind, photo, why, need}], waiting, problems}."""
    import sportsgfx
    holes = gaps(project)
    lib = lib if lib is not None else library(project, data_dir, asset_path)
    waiting = [x["name"] for x in lib if not x["analysed"] and not x.get("missing")]
    out = {"proposals": [], "waiting": waiting, "problems": [], "gaps": len(holes)}
    if not holes:
        return out
    usable = [x for x in lib if x["analysed"] and (x["kind"] == "image" or x["shots"])]
    if not usable:
        out["problems"].append("No analysed footage to choose from: add your own clips (or let the guide fetch "
                               "them), then Analyse footage.")
        return out
    ws, els = sportsgfx.elements(project)
    scenes = project["scenes"]
    offsets, total = _offsets(project)
    taken = []
    for i, s in enumerate(scenes):
        if s.get("asset_id"):
            t0 = float(s.get("trim_start") or 0)
            taken.append((s["asset_id"], t0, t0 + float(s.get("duration") or 0)))
    pl = P.plan(ws, els, usable, settings(project)["style"], total, 0.0, None,
                pieces=[(a, b) for _, a, b in holes], taken=taken)
    by_id = {x["id"]: x for x in usable}
    for (i, a, b), c in zip(holes, pl["cuts"]):
        if not c.get("asset_id"):
            continue
        clip = by_id[c["asset_id"]]
        t_in = 0.0 if c["photo"] else float(c["in"])
        dur = float(clip.get("duration") or 0)
        if not c["photo"] and dur and t_in + (b - a) > dur:  # play on rather than loop when the clip allows it
            t_in = max(0.0, min(t_in, dur - (b - a)))
        out["proposals"].append({"scene_id": scenes[i].get("id"), "index": i, "start": round(a, 3), "end": round(b, 3),
                                 "asset_id": c["asset_id"], "name": c["name"], "in": round(t_in, 3), "kind": c["kind"],
                                 "photo": bool(c["photo"]), "why": re.sub(r";? ?slowed to [0-9.]+× to fill the line", "", c["why"]),
                                 "need": c["need"]})
    return out


def apply_fill(project, proposals, ids=None):
    """Put the proposed shots on their scenes (only scenes still without a clip). Guide projects keep them as
    the producer's picture choice for that scene (episode overrides), so a rebuild keeps them, and a clip the
    guide supplies later wins. Returns how many scenes were filled."""
    import episode
    scenes = project.get("scenes") or []
    by_id = {s.get("id"): s for s in scenes}
    assets = {a["id"] for a in project.get("assets") or []}
    guide = bool((project.get("episode") or {}).get("guide"))
    ov = project["episode"].setdefault("overrides", {}) if guide else None
    n = 0
    for pr in proposals:
        if ids is not None and pr["scene_id"] not in ids:
            continue
        s = by_id.get(pr["scene_id"])
        if not s or s.get("asset_id") or s.get("insert_audio") or pr["asset_id"] not in assets:
            continue
        mark = {"asset_id": pr["asset_id"], "why": str(pr.get("why") or "")[:160], "kind": str(pr.get("kind") or "")[:20]}
        fields = {"asset_id": pr["asset_id"], "trim_start": float(pr["in"]),
                  "motion": "slow-zoom" if pr["photo"] else "none",
                  "sports_fill": mark}
        s.update(fields)
        s.pop("source_crop_end", None)
        if guide:
            ov.setdefault(episode.scene_key(s), {}).update(fields)
        n += 1
    return n


# ====================================================================== storytelling style

def style_changes(project, style=None):
    """What applying the style would change on the Edit page: {style, label, look: [old, new], transitions:
    [{scene_id, index, at, to, duration}], music: {sections, current}}. Transitions only where a chapter
    changes and the scene has none of its own."""
    import effects
    key, label = resolved_style(project, style)
    scenes = project.get("scenes") or []
    offsets, total = _offsets(project)
    trans = []
    want = CHAPTER_TRANSITION.get(key)
    if want:
        for i in range(1, len(scenes)):
            s = scenes[i]
            if s.get("chapter") == scenes[i - 1].get("chapter") or s.get("insert_audio") or scenes[i - 1].get("insert_audio"):
                continue
            if effects.transition_id(s.get("transition")) != "none":
                continue
            trans.append({"scene_id": s.get("id"), "index": i, "at": round(offsets[i], 3), "to": want[0],
                          "duration": want[1]})
    music = project.get("music_id")
    current = next((a.get("name") for a in project.get("assets") or [] if a.get("id") == music), None)
    return {"style": key, "label": label, "look": [project.get("look", "noir"), LOOK.get(key, "natural")],
            "transitions": trans, "music": {"sections": music_sections(project, key), "current": current}}


def apply_style(project, parts, style=None):
    """Apply the look and/or the chapter transitions (parts: {"look", "transitions"}). Returns what changed."""
    import episode
    ch = style_changes(project, style)
    done = {"look": False, "transitions": 0}
    if "look" in parts and project.get("look") != ch["look"][1]:
        project["look"] = ch["look"][1]
        done["look"] = True
    if "transitions" in parts and ch["transitions"]:
        before = [dict(s) for s in project["scenes"]]
        by_id = {s.get("id"): s for s in project["scenes"]}
        for t in ch["transitions"]:
            s = by_id.get(t["scene_id"])
            if s:
                s["transition"], s["transition_duration"] = t["to"], t["duration"]
                done["transitions"] += 1
        if (project.get("episode") or {}).get("guide"):
            episode.record_overrides(project, before, project["scenes"])
    return done


def music_sections(project, style_key=None):
    """The music's arc over the timeline: [(t0, t1, mood)] from where the graphics fall in the story."""
    import sportsgfx
    _, els = sportsgfx.elements(project)
    key, p = P.resolve_style(style_key or settings(project)["style"], els)
    _, total = _offsets(project)
    if total <= 0:
        return []
    return [list(m) for m in P.music_sections(P.thin(els, p["gap"]), total, p, 0.0)]


def make_music(project, data_dir, progress=None, cancelled=None):
    """An original music bed for the whole timeline (cinegfx.sports.score, nothing sampled), written into the
    project's media. Returns the new asset (the caller adds it and makes it the music)."""
    import storage
    from cinegfx.sports import score
    key, label = resolved_style(project)
    sections = music_sections(project, key)
    _, total = _offsets(project)
    if total < 2 or not sections:
        raise ValueError("The timeline is empty: build the edit first.")
    d = Path(data_dir) / "media" / project["id"]
    d.mkdir(parents=True, exist_ok=True)
    name = storage.uid() + ".wav"
    path = d / name
    score.bed_wav(path, total + 1.0, [tuple(s) for s in sections], level_db=-1.0, progress=progress, cancelled=cancelled)
    return {"id": storage.uid(), "name": f"Sports score - {label}.wav", "path": storage.asset_reference(path),
            "url": f"/media/{project['id']}/{name}", "size": path.stat().st_size, "generated": True,
            "license": "Original music made by Casefile Studio for this project (no samples).", "thumbnail": None,
            "kind": "audio", "duration": round(total + 1.0, 3), "has_audio": True, "has_video": False,
            "audio_role": "music", "sports_score": {"style": key, "sections": sections}}


def is_fill(scene) -> bool:
    """A scene whose picture the sports engine chose (and still has)."""
    f = scene.get("sports_fill")
    return isinstance(f, dict) and f.get("asset_id") == scene.get("asset_id") and bool(scene.get("asset_id"))


def clean_fill(value):
    if not isinstance(value, dict):
        return None
    return {"asset_id": str(value.get("asset_id") or "")[:40], "why": str(value.get("why") or "")[:160],
            "kind": re.sub(r"[^a-z_]", "", str(value.get("kind") or ""))[:20]}
