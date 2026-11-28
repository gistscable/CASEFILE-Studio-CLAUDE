"""v0.4.78 Sports edit: cut the producer's own footage together with the editorial graphics.

For sports projects (football, boxing & MMA, wrestling) the app can make the whole edit, not only lay graphics
over a finished episode:

    narration audio + script + word timings  ->  graphics (cinegfx.sports.semantics)
    the project's own videos and photos      ->  shots (cinegfx.sports.shots: cuts found, each shot described)
    storytelling style                        ->  pace, grade, music arc (cinegfx.sports.planner)
    review (graphics on/off, cuts moved, shots swapped)  ->  overrides saved on the project
    render                                    ->  cinegfx.sports.edit (cached chunks: a change re-renders only
                                                  the chunks it touches)

Nothing is fetched or invented: every word on screen is from the narration, every picture from the project.
A project without the setting, and every true-crime project, is untouched.

Saved on the project as `sports_edit`: {enabled, style, crop, overrides: {graphics, moves, shots}}
(crop: footage is reframed 14% so a broadcaster's corner logo stays out of shot).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import niches
from cinegfx.sports import matte as M
from cinegfx.sports import planner as P
from cinegfx.sports import semantics as S
from cinegfx.sports import shots as SH

SPORTS = ("football", "boxing", "wrestling")
LEAD = 0.8            # a shot before the first word
TAIL = 1.6            # and after the last
W, H, FPS = 1920, 1080, 25
MAX_OVERRIDES = 400
CROP = (0.5, 0.56, 1.14)      # "crop in": a corner logo leaves the frame, the action stays centred


def eligible(project) -> bool:
    return niches.key_of(project) in SPORTS


def default():
    return {"enabled": False, "style": "auto", "crop": False, "overrides": {"graphics": {}, "moves": {}, "shots": {}}}


def _num(v, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a number.")
    if not (0 <= x < 36000):
        raise ValueError(f"{what} is out of range.")
    return round(x, 3)


def _key(k):
    if not isinstance(k, str) or not re.fullmatch(r"\d{1,5}\.\d{2}", k):
        raise ValueError("Unknown cut or graphic.")
    return k


def normalise(raw, asset_ids=None) -> dict:
    """Settings from the editor (ValueError on anything malformed)."""
    out = default()
    if raw is None:
        return out
    if not isinstance(raw, dict):
        raise ValueError("Sports edit settings must be an object.")
    out["enabled"] = bool(raw.get("enabled", False))
    style = raw.get("style", "auto")
    if style not in P.STYLES:
        raise ValueError("Unknown storytelling style.")
    out["style"] = style
    out["crop"] = bool(raw.get("crop", False))
    ov = raw.get("overrides") or {}
    if not isinstance(ov, dict):
        raise ValueError("Overrides must be an object.")
    g, mv, sh = ov.get("graphics") or {}, ov.get("moves") or {}, ov.get("shots") or {}
    if not all(isinstance(x, dict) for x in (g, mv, sh)) or len(g) + len(mv) + len(sh) > MAX_OVERRIDES:
        raise ValueError("Too many or malformed review changes.")
    out["overrides"]["graphics"] = {_key(k): bool(v) for k, v in g.items()}
    out["overrides"]["moves"] = {_key(k): _num(v, "A cut time") for k, v in mv.items()}
    shots = {}
    for k, v in sh.items():
        if not isinstance(v, dict) or not isinstance(v.get("asset_id"), str):
            raise ValueError("A swapped shot needs a file from the project.")
        if asset_ids is not None and v["asset_id"] not in asset_ids:
            raise ValueError("A swapped shot uses a file that is not in this project.")
        shots[_key(k)] = {"asset_id": v["asset_id"], "in": _num(v.get("in", 0), "A shot's start")}
    out["overrides"]["shots"] = shots
    return out


def settings(project) -> dict:
    try:
        return normalise(project.get("sports_edit"))
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
                "Restart the app. Without it the edit still renders: the type goes in front of the player.",
            ],
            "license": "Robust Video Matting is GPL-3.0; it runs as a separate optional model file."}


def media_assets(project):
    """The project's own footage and photos the edit may use (not the narration, music or logo)."""
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
        item = {"id": a["id"], "name": a.get("name") or a["id"], "kind": a["kind"],
                "duration": a.get("duration"), "has_audio": bool(a.get("has_audio", a["kind"] == "video")), "shots": (info or {}).get("shots") or [], "analysed": bool(info),
                "path": path}
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


def inputs(project, sources: dict, asset_path):
    """What the edit is made from, and what is still missing (in the producer's words)."""
    problems = []
    narration = next((a for a in project.get("assets") or [] if a.get("id") == project.get("narration_id")), None)
    npath = None
    if not narration:
        problems.append("Add the narration audio (Voice tab): the edit is cut to it.")
    else:
        try:
            npath = str(asset_path(narration))
        except ValueError as e:
            problems.append(str(e))
    script = (sources.get("script") or sources.get("locked") or "").strip()
    timings = (((project.get("episode") or {}).get("timings") or {}).get("words")) or []
    if not timings:
        problems.append("Make the word timing first (Voice tab, Timing): graphics and cuts land on spoken words.")
    if not script:
        problems.append("Add the script: every word on screen comes from it.")
    return {"narration": {"id": narration["id"], "name": narration.get("name"), "duration": narration.get("duration")}
            if narration else None, "narration_path": npath, "script": script, "timings": len(timings),
            "problems": problems}


def words(project, script: str):
    """Script words on the edit's timeline (narration starts at LEAD), with number-aware alignment."""
    heard = [{"word": w.get("word") or w.get("text") or "", "start": float(w["start"]), "end": float(w["end"])}
             for w in (((project.get("episode") or {}).get("timings") or {}).get("words") or [])
             if w.get("start") is not None and w.get("end") is not None]
    if not heard:
        return []
    import autotiming
    script = script or " ".join(h["word"] for h in heard)
    aligned = S.align_words(script, heard)
    # the script's paragraphs are the narration's segments (a player's name opening one is an intro)
    sizes = [len(autotiming.script_words(x)) for x in re.split(r"\n\s*\n", script) if x.strip()]
    if sum(sizes) != len(aligned):
        sizes = [len(aligned)]
    out, sent, k = [], 0, 0
    for seg, n in enumerate(sizes):
        for w in aligned[k:k + n]:
            out.append(S.Word(w["word"], round(LEAD + w["start"], 3), round(LEAD + w["end"], 3), seg, sent))
            if out[-1].ends_sentence:
                sent += 1
        k += n
        if out and not out[-1].ends_sentence:
            sent += 1
    return out


def make_plan(project, sources, data_dir, asset_path, lib=None):
    """Everything the review step shows. {inputs, plan | None, library}."""
    info = inputs(project, sources, asset_path)
    cfg = settings(project)
    lib = lib if lib is not None else library(project, data_dir, asset_path)
    public_lib = [{k: v for k, v in x.items() if k != "path"} for x in lib]
    out = {"inputs": {k: v for k, v in info.items() if k not in ("narration_path", "script")} |
           {"script": bool(info["script"])}, "library": public_lib, "plan": None}
    if info["problems"]:
        return out
    ws = words(project, info["script"])
    if not ws:
        info["problems"].append("The word timing has no words. Make it again in the Voice tab.")
        return out
    els = S.analyse(ws)
    nd = float((info["narration"] or {}).get("duration") or 0)
    duration = max(ws[-1].e + TAIL, (LEAD + nd) if nd else 0)
    pl = P.plan(ws, els, [x for x in lib if x["analysed"]], cfg["style"], duration, LEAD, cfg["overrides"])
    pl.pop("on")
    waiting = [x["name"] for x in lib if not x["analysed"] and not x.get("missing")]
    pl["waiting"] = waiting
    pl["problems"] = (["No footage or photos in the project yet: add your own clips (Setup, media) to cut with."]
                      if not lib else []) + ([f"{len(waiting)} file{'s' if len(waiting) != 1 else ''} not analysed yet "
                                              "(Analyse footage, or Render analyses them first)."] if waiting else [])
    pl["empty"] = sum(1 for c in pl["cuts"] if not c["asset_id"])
    out["plan"] = pl
    return out


def build_edit(project, sources, data_dir, asset_path, lib, log=print, compute_mattes=True, matte_progress=None):
    """The Edit to render (graphics, shots, transitions, music, natural sound)."""
    from cinegfx.core import Cue
    from cinegfx.sports import edit as E
    from cinegfx.sports.footage import Shot
    info = inputs(project, sources, asset_path)
    if info["problems"]:
        raise ValueError(" ".join(info["problems"]))
    cfg = settings(project)
    ws = words(project, info["script"])
    if not ws:
        raise ValueError("The word timing has no words. Make it again in the Voice tab.")
    els = S.analyse(ws)
    nd = float((info["narration"] or {}).get("duration") or 0)
    duration = max(ws[-1].e + TAIL, (LEAD + nd) if nd else 0)
    pl = P.plan(ws, els, [x for x in lib if x["analysed"]], cfg["style"], duration, LEAD, cfg["overrides"])
    by_id = {x["id"]: x for x in lib}
    empty = [c for c in pl["cuts"] if not c["asset_id"] or c["asset_id"] not in by_id]
    if empty:
        raise ValueError(f"{len(empty)} part{'s' if len(empty) != 1 else ''} of the edit "
                         "have no footage. Add your own clips or photos to the project first.")
    e = E.Edit(W, H, FPS, cache_dir=cache_dir(data_dir, project["id"]))
    e.narration.append((info["narration_path"], LEAD))
    e.set_elements(pl["on"])
    nat = []
    for c in pl["cuts"]:
        a = by_id[c["asset_id"]]
        if c["photo"]:
            shot = Shot(a["path"], 0.0, 1.0, grade=c["grade"], photo=True, matte=c["matte"],
                        parallax=0.035 if c["matte"] else 0.0, move=((0.5, 0.55, 1.06), (0.5, 0.45, 1.2)),
                        tag=f"photo: {a['name']}")
        else:
            shot = Shot(a["path"], c["in"], 1.0, speed=c["speed"], grade=c["grade"], matte=c["matte"],
                        frame=CROP if cfg["crop"] else (0.5, 0.5, 1.0),
                        tag=f"{c['kind'] or 'shot'}: {a['name']} @ {c['in']:.1f}s")
        e.add(shot, at=c["t"])
        e.cut_at(c["end"])
        if not c["photo"] and c["speed"] >= 0.95 and a.get("has_audio"):
            nat.append(E.Natural(a["path"], c["in"], c["t"], (c["end"] - c["t"]) * c["speed"], pl["natural_db"]))
    e.natural = nat
    if pl["dissolve_chapters"]:   # historical: dissolve where the story moves on without a graphic entrance
        starts = {round(x.t_in, 2) for x in pl["on"]}
        sent_starts = {round(w.s, 2) for i, w in enumerate(ws) if i and w.sent != ws[i - 1].sent}
        for i in range(1, len(e.shots)):
            t = round(e.shots[i].start, 2)
            if t in sent_starts and t not in starts:
                e.trans[i] = E.Transition("dissolve", 0.5, why="historical: a dissolve between chapters")
    e.auto_transitions()
    e.music = [tuple(m) for m in pl["music"]]
    for x in pl["on"]:
        if x.family in ("numbered", "impact"):
            e.cues.append(Cue(x.t_in, "riser-1", -12, f"rise into the {x.family} graphic"))
    if compute_mattes:
        e.prepare_mattes(log, compute=True, progress=matte_progress)
    return e, pl


def renders(data_dir, pid):
    f = folder(data_dir, pid) / "renders.json"
    try:
        items = json.loads(f.read_text())
    except (OSError, ValueError):
        return []
    return [r for r in items if (folder(data_dir, pid) / f"{r['id']}.mp4").is_file()]


def add_render(data_dir, pid, record, keep=6):
    """Newest first; keeps the last `keep` renders on disk."""
    d = folder(data_dir, pid)
    d.mkdir(parents=True, exist_ok=True)
    items = [record] + renders(data_dir, pid)
    for old in items[keep:]:
        (d / f"{old['id']}.mp4").unlink(missing_ok=True)
    items = items[:keep]
    tmp = d / "renders.json.tmp"
    tmp.write_text(json.dumps(items, indent=1))
    os.replace(tmp, d / "renders.json")
    return items
