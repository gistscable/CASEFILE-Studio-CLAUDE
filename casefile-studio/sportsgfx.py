"""v0.4.79 The sports editorial graphics as motion graphics on the Edit page.

The Edit page builds the video (editing guide, fetched clips, renaming, crops, auto-fit). For football, boxing & MMA
and wrestling projects this module adds the sports engine's editorial graphics (cinegfx.sports) to that same
timeline, as ordinary motion graphics (`project["motion"]["items"]`, template "sports"):

    the narration on the timeline (motion.timeline_words: the script's words at their recorded times)
        -> cinegfx.sports.semantics.analyse: a name opening the story, dates and venues, numbered goals,
           single big numbers, stacked stats, defining headlines and quotes, flashback lines
        -> one item per graphic, placed on its words; the storytelling style keeps the screen from being
           overloaded (planner.thin)

Each item is then like any other graphic in the editor: it is on the timeline, can be moved, approved,
rejected or removed, previewed over the picture, and goes into the normal export (motion.prepare) when the
graphics are on. Words come only from the narration; nothing is fetched or made up.

Text behind the player: an item is drawn as two transparent layers, BEHIND (type the player passes in front
of) and FRONT. The export cuts the player out of the behind layer with the optional segmentation model, on
the picture of the scene it is over (renderer: `behind_step`), so the crop, fit, zoom and grade of the Edit
page are respected. Without the model, the behind layer is simply shown (the type is in front of the player).

Item: {id, template: "sports", status, start, end, family, label, text, data (the element's own data, times
from `start`), dur (graphic length, its exit is added), why, source, hide_captions}
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import threading
from pathlib import Path

import numpy as np

import motion

FPS = motion.FPS
ENGINE = "sports-gfx-1"   # bump when the drawing changes: cached layers are made again
EXIT = 0.45               # a family stays drawn until t_out + 0.4 (families.Family.active)
MAX_DATA = 20000          # characters of JSON per graphic
SPORTS = ("football", "boxing", "wrestling")
_TIME_KEYS = {"t", "t0", "t1", "end"}
_MATTE_LOCK = threading.Lock()


# ====================================================================== words and graphics

def eligible(project) -> bool:
    import niches
    return niches.key_of(project) in SPORTS


def words(project):
    """The narration on the timeline as cinegfx.sports.semantics.Word (script words, recorded times).
    A chapter of the edit is a segment of the narration (a player's name opening one is an intro)."""
    from cinegfx.sports import semantics as S
    scenes = project.get("scenes") or []
    out, sent, seg, last_chapter = [], 0, -1, object()
    for w in motion.timeline_words(project):
        ch = scenes[w["scene"]].get("chapter") if w["scene"] < len(scenes) else None
        if ch != last_chapter:
            last_chapter = ch
            seg += 1
            if out and not out[-1].ends_sentence:
                sent += 1
        out.append(S.Word(w["w"], float(w["t"]), max(float(w["e"]), float(w["t"]) + 0.02), max(0, seg), sent))
        if out[-1].ends_sentence:
            sent += 1
    return out


def elements(project):
    """(words, every graphic the narration supports)."""
    from cinegfx.sports import semantics as S
    ws = words(project)
    return ws, (S.analyse(ws) if ws else [])


def _shift(v, dt):
    """The element's times moved by dt (a graphic keeps its own times relative to where it starts)."""
    if isinstance(v, dict):
        return {k: (round(x + dt, 3) if (k in _TIME_KEYS or k.endswith("_t")) and isinstance(x, (int, float))
                    and not isinstance(x, bool) else _shift(x, dt)) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        if len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], (int, float)) and not isinstance(v[1], bool):
            return [v[0], round(v[1] + dt, 3)]
        return [_shift(x, dt) for x in v]
    return v


def frames_of(item):
    return max(1, int(math.ceil((float(item["dur"]) + EXIT) * FPS - 1e-6)))


def make_item(el, source="auto", status="suggested", item_id=None):
    from cinegfx.sports import planner as P
    data = _shift(json.loads(json.dumps(el.data, default=str)), -el.t_in)
    start = round(max(0.0, el.t_in), 3)
    it = {"id": item_id or "sp" + hashlib.sha1(f"{el.family}|{el.t_in:.2f}|{json.dumps(data, sort_keys=True)}".encode()).hexdigest()[:10],
          "template": "sports", "status": status, "start": start, "end": 0.0, "family": el.family,
          "label": P.S_LABEL.get(el.family, el.family).capitalize(), "text": P._text_of(el)[:200],
          "data": data, "dur": round(max(0.3, el.t_out - el.t_in), 3), "why": (el.why or "")[:240],
          "source": source, "hide_captions": True}
    return normalise_item(it)


def element(item):
    """The cinegfx Element the item is drawn from, at its place on the timeline."""
    from cinegfx.sports.semantics import Element
    s = float(item["start"])
    return Element(item["family"], s, s + float(item["dur"]), _shift(item["data"], s), item.get("why") or "")


def _num(v, lo, hi, d):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return d if not math.isfinite(x) else max(lo, min(hi, x))


def _clean(v, depth=0):
    """Only JSON data (strings, numbers, lists, objects), a few levels deep."""
    if depth > 5:
        raise ValueError("too deep")
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        if not math.isfinite(float(v)):
            raise ValueError("not a number")
        return v
    if isinstance(v, str):
        return v[:200]
    if isinstance(v, (list, tuple)):
        return [_clean(x, depth + 1) for x in list(v)[:40]]
    if isinstance(v, dict):
        return {str(k)[:40]: _clean(x, depth + 1) for k, x in list(v.items())[:40]}
    raise ValueError("not JSON")


def normalise_item(it, n=0, image_assets=None):
    from cinegfx.sports.families import FAMILIES
    if not isinstance(it, dict) or it.get("template") != "sports" or it.get("family") not in FAMILIES:
        return None
    try:
        data = _clean(it.get("data"))
    except ValueError:
        return None
    if not isinstance(data, dict) or not data or len(json.dumps(data)) > MAX_DATA:
        return None
    start = round(_num(it.get("start"), 0.0, 86400.0, 0.0), 3)
    out = {
        "id": re.sub(r"[^\w-]", "", str(it.get("id") or ""))[:24] or f"sp{n + 1}",
        "template": "sports",
        "status": it.get("status") if it.get("status") in ("suggested", "draft", "approved") else "draft",
        "start": start,
        "end": 0.0,
        "family": it["family"],
        "label": str(it.get("label") or "")[:120],
        "text": str(it.get("text") or "")[:200],
        "data": data,
        "dur": round(_num(it.get("dur"), 0.3, 120.0, 4.0), 3),
        "why": str(it.get("why") or "")[:240],
        "source": "auto" if it.get("source") == "auto" else "manual",
        "hide_captions": it.get("hide_captions") is not False,
    }
    out["end"] = round(start + frames_of(out) / FPS, 3)
    return out


def _soundbites(project):
    scenes = project.get("scenes") or []
    offsets, _ = motion.scene_offsets(scenes)
    return [(offsets[i], offsets[i] + max(1, round(float(s.get("duration") or 0) * FPS)) / FPS)
            for i, s in enumerate(scenes) if s.get("insert_audio")]


def suggest(project, existing=(), style="auto"):
    """Place the graphics the narration supports: the storytelling style keeps the strongest ones with room
    between them (planner.thin); never over a graphic you keep, never across a soundbite."""
    from cinegfx.sports import planner as P
    _, els = elements(project)
    if not els:
        return []
    _, params = P.resolve_style(style, els)
    taken = [(float(x["start"]), float(x["end"])) for x in existing]
    bites = _soundbites(project)
    out = []
    for el in P.thin(els, params["gap"]):
        a, b = el.t_in, el.t_out + EXIT
        if any(a < e and s < b for s, e in taken) or any(a < e and s < b for s, e in bites):
            continue
        it = make_item(el)
        if it:
            out.append(it)
    return out


def draft(project, start, end, family="auto", item_id=None):
    """A graphic from a passage you chose: the strongest one the passage supports, or the family asked for."""
    from cinegfx.sports import planner as P
    from cinegfx.sports.families import FAMILIES
    _, els = elements(project)
    inside = [e for e in els if e.t_in >= start - 0.3 and e.t_in < end]
    if family != "auto":
        if family not in FAMILIES:
            raise ValueError("Unknown kind of sports graphic.")
        inside = [e for e in inside if e.family == family]
    if not inside:
        what = "this kind of graphic" if family != "auto" else "a sports graphic"
        raise ValueError(f"Nothing in this passage calls for {what}: names opening a story, dates and venues, numbered "
                         "goals, a single big number, stacked figures, a short defining line or quote, a step back in time.")
    best = max(inside, key=lambda e: (P.PRIORITY.get(e.family, 1), -e.t_in))
    return make_item(best, source="manual", status="draft", item_id=item_id)


def describe(it):
    s = max(0, int(it.get("start") or 0))
    return f"sports graphic ({it.get('label') or it.get('family')}) at {s // 60}:{s % 60:02d}"


# ====================================================================== what is under a graphic

class _Shot:
    def __init__(self, start, end):
        self.start, self.end = start, end


class TimelineCtx:
    """What the graphics ask of the picture (cinegfx.sports.families): where the player's head is (the name
    is placed so the head overlaps it) and how much of a box he covers (a big number goes behind him only if
    he hides little of it). Read from the footage on the Edit timeline at that moment, with the optional
    segmentation model; without it, there is no player to avoid (centred name, number behind)."""

    def __init__(self, project, W, H, data_dir=None, asset_path=None, use_matte=None):
        from cinegfx.sports import matte as M
        self.project, self.W, self.H, self.fps = project, W, H, FPS
        scenes = project.get("scenes") or []
        offsets, total = motion.scene_offsets(scenes)
        self.shots = [_Shot(offsets[i], offsets[i + 1] if i + 1 < len(offsets) else total) for i in range(len(scenes))] \
            or [_Shot(0.0, 1e9)]
        self.data_dir, self.asset_path = data_dir, asset_path
        self.use_matte = M.available() if use_matte is None else use_matte
        self._memo = {}

    def shot_at(self, t):
        k = 0
        for i, s in enumerate(self.shots):
            if s.start <= t + 1e-9:
                k = i
        return k

    def _alpha(self, t):
        if not self.use_matte or not self.asset_path:
            return None
        got = motion.footage_at(self.project, t)
        if not got:
            return None
        a, sec = got
        key = (a["id"], None if sec is None else round(sec, 2))
        if key not in self._memo:
            try:
                self._memo[key] = still_matte(self.asset_path(a), sec, self.W, self.H, self.data_dir)
            except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
                self._memo[key] = None
        return self._memo[key]

    def occlusion(self, t, box):
        a = self._alpha(t)
        if a is None:
            return 0.0
        h, w = a.shape[:2]
        x0, y0, x1, y1 = box
        sub = np.asarray(a[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))],
                         np.float32)
        return float(sub.mean()) / 255 if sub.size else 0.0

    def subject(self, t):
        a = self._alpha(t)
        if a is None:
            return None
        return subject_of(a)


def subject_of(a):
    """{"head_x", "head_x0", "head_x1", "head_y", "cover"} of the matted person (normalised), or None."""
    a = np.asarray(a, np.float32) / 255
    cover = float(a.mean())
    if cover < 0.02:
        return None
    rows = np.nonzero(a.max(axis=1) > 0.5)[0]
    if not len(rows):
        return None
    top = rows[0]
    band = a[top: top + max(4, int(a.shape[0] * 0.18))]
    xs = np.nonzero(band.max(axis=0) > 0.5)[0]
    hx = float(xs.mean()) / a.shape[1] if len(xs) else 0.5
    x0 = float(xs.min()) / a.shape[1] if len(xs) else hx
    x1 = float(xs.max()) / a.shape[1] if len(xs) else hx
    return {"head_x": round(hx, 4), "head_x0": round(x0, 4), "head_x1": round(x1, 4), "head_y": round(top / a.shape[0], 4),
            "cover": round(cover, 4)}


def matte_size(W, H):
    from cinegfx.sports import matte as M
    mw = M.MATTE_W if W >= H else round(M.MATTE_W * W / H / 2) * 2
    return mw, round(mw * H / W / 2) * 2


def still_matte(path, sec, W, H, data_dir=None):
    """The player's matte (uint8, network size) in one frame of the footage, framed to fill the picture."""
    from cinegfx.sports import matte as M
    mw, mh = matte_size(W, H)
    path = str(path)
    st = os.stat(path)
    key = M.cache_key("still", path, st.st_size, int(st.st_mtime), sec, mw, mh, M.net().id)
    cache = (Path(data_dir) / "cache" / "sportsmatte") if data_dir else None
    f = cache / f"still-{key}.npy" if cache else None
    if f and f.exists():
        return np.load(f)
    seek = ["-ss", f"{sec:.3f}"] if sec is not None else []
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", *seek, "-i", path, "-frames:v", "1", "-vf",
                          f"scale={mw}:{mh}:force_original_aspect_ratio=increase,crop={mw}:{mh}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True, timeout=60).stdout
    if len(raw) < mw * mh * 3:
        raise ValueError("no frame")
    rgb = np.frombuffer(raw[:mw * mh * 3], np.uint8).reshape(mh, mw, 3)
    with _MATTE_LOCK:
        a = M.still(rgb)
    if f:
        cache.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.stem + f".{threading.get_ident()}.tmp.npy")
        np.save(tmp, a)
        os.replace(tmp, f)
    return a


class _HintCtx:
    """The preview's stand-in for TimelineCtx: the head position measured once when the preview was planned."""

    def __init__(self, hints, W, H):
        self.W, self.H, self.fps = W, H, FPS
        self.hints = hints or {}
        self.shots = [_Shot(a, b) for a, b in self.hints.get("shots") or [[0.0, 1e9]]]

    def shot_at(self, t):
        k = 0
        for i, s in enumerate(self.shots):
            if s.start <= t + 1e-9:
                k = i
        return k

    def subject(self, t):
        return self.hints.get("subject")

    def occlusion(self, t, box):
        return 0.0


def _hints(project, item, W, H, data_dir=None, asset_path=None):
    """What the layout of the graphic depends on in the picture: the head position at its start, the footage
    under it (so a changed picture redraws it) and whether the player can be cut out."""
    from cinegfx.sports import matte as M
    s, e = float(item["start"]), float(item["end"])
    scenes = project.get("scenes") or []
    offsets, total = motion.scene_offsets(scenes)
    under, shots = [], []
    for i, sc in enumerate(scenes):
        a, b = offsets[i], (offsets[i + 1] if i + 1 < len(offsets) else total)
        if a < e and s < b:
            under.append([sc.get("asset_id"), round(float(sc.get("trim_start") or 0), 3), round(a, 3), round(b, 3),
                          sc.get("fit"), sc.get("motion")])
            shots.append([a, b])
    ok = M.available()
    sub = None
    if ok and item["family"] in ("name", "cumulative"):
        ctx = TimelineCtx(project, W, H, data_dir, asset_path, use_matte=True)
        sub = ctx.subject(s + (0.3 if item["family"] == "name" else 0.2))
    return {"under": under, "shots": shots, "matte": ok, "subject": sub}


def item_hash(item, W, H, hints):
    keep = {k: v for k, v in item.items() if k not in ("status", "source", "id", "hide_captions", "why", "label", "text")}
    return hashlib.sha1(json.dumps([ENGINE, keep, W, H, hints], sort_keys=True, default=str).encode()).hexdigest()[:20]


# ====================================================================== drawing

def draw(item, n, W, H, ctx, fam=None):
    """Frame n of the graphic: (behind RGBA, front RGBA) as PIL images, at W x H."""
    from PIL import Image
    from cinegfx.sports import families as F
    from cinegfx.sports import fx as FX
    f = fam or F.make(element(item), W, H, FPS)
    t = float(item["start"]) + n / FPS
    behind = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    front = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if f.active(t):
        f.draw(t, behind, front, ctx)
        r = f.fx(t)
        if r.get("rgb"):
            px = max(1, int(round(r["rgb"] * W / 1920)))
            behind = Image.fromarray(FX.rgb_split(np.asarray(behind).copy(), px, 0), "RGBA")
            front = Image.fromarray(FX.rgb_split(np.asarray(front).copy(), px, 0), "RGBA")
        ta = r.get("type_alpha", 1.0)
        if ta < 1.0:
            arr = np.asarray(front).copy()
            arr[..., 3] = (arr[..., 3].astype(np.float32) * max(0.0, ta)).astype(np.uint8)
            front = Image.fromarray(arr, "RGBA")
    return behind, front


def cues(item):
    """The graphic's designed sound cues: [{t (seconds from its start), sfx, gain_db, why}] (the same family
    the frames come from, so a sound lands on its visual event)."""
    from cinegfx.sports import families as F
    f = F.make(element(item), 1920, 1080, FPS)
    s = float(item["start"])
    return [{"t": round(float(c.t) - s, 4), "sfx": c.sfx, "gain_db": float(c.gain_db), "why": c.why}
            for c in f.cues() if float(c.t) - s >= -1e-6]


# ---------------------------------------------------------------------- preview (the Edit page player)

def preview_plan(data, project, item):
    from renderer import asset_path
    W, H = motion.preview_size(project)
    hints = _hints(project, item, W, H, data, asset_path)
    h = item_hash(item, W, H, hints)
    folder = motion.cache_root(data) / h
    folder.mkdir(parents=True, exist_ok=True)
    spec = folder / "item.json"
    if not spec.exists():
        tmp = spec.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"engine": "sports", "item": item, "W": W, "H": H, "hints": hints}))
        os.replace(tmp, spec)
    n = frames_of(item)
    return {"hash": h, "width": W, "height": H, "fps": FPS, "frames": list(range(n)), "unique": n, "start": item["start"],
            "layout": "sports", "layouts": [], "background": "sports", "behind": item["family"] in ("name", "cumulative", "impact"),
            "matte": bool(hints["matte"])}


def preview_frame(folder, spec, k, out):
    from PIL import Image
    item = spec["item"]
    if not 0 <= int(k) < frames_of(item):
        raise KeyError(k)
    b, f = draw(item, int(k), spec["W"], spec["H"], _HintCtx(spec.get("hints"), spec["W"], spec["H"]))
    img = Image.alpha_composite(b, f)
    tmp = out.with_suffix(f".{threading.get_ident()}.tmp")
    img.save(tmp, "WEBP", quality=88, method=0, alpha_quality=90)
    os.replace(tmp, out)
    return out


# ---------------------------------------------------------------------- export

def _writer(path, W, H):
    return subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-c:v", "qtrle", "-pix_fmt", "argb", "-g", str(FPS), "-f", "mov",
                             str(path)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)


def _close(proc, what):
    proc.stdin.close()
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"FFmpeg could not write the {what}: {err[-300:]}")


def encode(item, W, H, ctx, behind_out, front_out, cancelled=lambda: False):
    """Every frame into two transparent videos (behind, front). Returns (frames, behind has any type)."""
    from cinegfx.sports import families as F
    n = frames_of(item)
    fam = F.make(element(item), W, H, FPS)
    tb, tf = Path(behind_out).with_suffix(f".{threading.get_ident()}.tmp.mov"), Path(front_out).with_suffix(f".{threading.get_ident()}.tmp.mov")
    pb, pf = _writer(tb, W, H), _writer(tf, W, H)
    any_b, ok = False, False
    try:
        for k in range(n):
            if cancelled():
                raise RuntimeError("Cancelled by you. No output was published.")
            b, f = draw(item, k, W, H, ctx, fam)
            bb = b.tobytes()
            any_b = any_b or b.getbbox() is not None
            pb.stdin.write(bb)
            pf.stdin.write(f.tobytes())
        _close(pb, "sports graphic")
        _close(pf, "sports graphic")
        os.replace(tb, behind_out)
        os.replace(tf, front_out)
        ok = True
    except (BrokenPipeError, OSError) as e:
        raise RuntimeError(f"FFmpeg could not write the sports graphic: {e}")
    finally:
        if not ok:
            for p in (pb, pf):
                p.kill()
                p.wait()
            tb.unlink(missing_ok=True)
            tf.unlink(missing_ok=True)
    return n, any_b


def prepare_layers(project, item, width, height, data, cancelled=lambda: False):
    """The exported graphic as transparent videos at the export size, cached by content: the behind layer
    (flagged `behind`, cut around the player per scene by the renderer) first, then the front layer."""
    from renderer import asset_path
    hints = _hints(project, item, width, height, data, asset_path)
    h = item_hash(item, width, height, hints)
    cache = motion.cache_root(data) / h
    cache.mkdir(parents=True, exist_ok=True)
    bo, fo, meta = cache / "behind.mov", cache / "front.mov", cache / "layers.json"
    drawn = 0
    if not (fo.exists() and bo.exists() and meta.exists()):
        ctx = TimelineCtx(project, width, height, data, asset_path)
        drawn, any_b = encode(item, width, height, ctx, bo, fo, cancelled)
        meta.write_text(json.dumps({"behind": any_b}))
    else:
        os.utime(cache)
    any_b = json.loads(meta.read_text()).get("behind", True)
    n = frames_of(item)
    s0 = round(item["start"] * FPS) / FPS
    base = {"start": s0, "end": s0 + n / FPS, "frames": n, "unique": n, "id": item["id"]}
    out = []
    if any_b:
        out.append({**base, "file": bo, "drawn": 0, "behind": True})
    out.append({**base, "file": fo, "drawn": drawn})
    return out


# ---------------------------------------------------------------------- the export: type behind the player

def behind_step(layer, a, b, scene_start, pic_cmd, pic_raw, key, out, W, H, data, warnings):
    """A step of a scene's render (renderer.run_scenes runs it before the scene's own FFmpeg command): the
    part [a, b) (timeline seconds) of a behind layer, with the player cut out of it. The player is found in
    the scene's own picture (`pic_cmd` writes it, small, to `pic_raw`: the same crop, fit, zoom and look as
    the export); the mattes are cached by `key`. If anything fails, the layer is used as it is."""
    def run(stopped):
        from cinegfx.sports import matte as M
        mw, mh = matte_size(W, H)
        n = max(1, round((b - a) * FPS))
        cache = Path(data) / "cache" / "sportsmatte"
        cache.mkdir(parents=True, exist_ok=True)
        mf = cache / f"scene-{key}.npy"
        mattes = None
        try:
            if mf.exists():
                mattes = np.load(mf)
            elif M.available():
                from renderer import run as run_cmd
                run_cmd(pic_cmd, stopped)
                raw = Path(pic_raw).read_bytes()
                count = len(raw) // (mw * mh * 3)
                if not count:
                    raise ValueError("no picture")
                frames = np.frombuffer(raw[:count * mw * mh * 3], np.uint8).reshape(count, mh, mw, 3)
                with _MATTE_LOCK:
                    mattes = np.stack(M.matte_frames(list(frames)))
                tmp = mf.with_name(mf.stem + f".{threading.get_ident()}.tmp.npy")
                np.save(tmp, mattes)
                os.replace(tmp, mf)
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as e:
            if stopped():
                raise
            warnings.append(f"The player could not be cut out of a sports graphic at {int(a // 60)}:{int(a % 60):02d} "
                            f"(the type is in front of him there): {e}")
            mattes = None
        finally:
            Path(pic_raw).unlink(missing_ok=True)
        first = round((a - layer["start"]) * FPS)
        src = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, (first - 0.5) / FPS):.4f}", "-i",
                                str(layer["file"]), "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        tmp = Path(out).with_suffix(f".{threading.get_ident()}.tmp.mov")
        dst = _writer(tmp, W, H)
        size = W * H * 4
        ok = False
        try:
            for k in range(n):
                if stopped():
                    raise RuntimeError("Cancelled by you. No output was published.")
                buf = src.stdout.read(size)
                if len(buf) < size:
                    buf = bytes(size)
                if mattes is not None and len(mattes):
                    fr = np.frombuffer(buf, np.uint8).reshape(H, W, 4).copy()
                    if fr[..., 3].any():
                        m = M.refine(mattes[min(k, len(mattes) - 1)], W, H)
                        fr[..., 3] = (fr[..., 3].astype(np.float32) * (1.0 - m)).astype(np.uint8)
                    buf = fr.tobytes()
                dst.stdin.write(buf)
            _close(dst, "sports graphic")
            os.replace(tmp, out)
            ok = True
        finally:
            src.kill()
            src.wait()
            if not ok:
                dst.kill()
                dst.wait()
                tmp.unlink(missing_ok=True)
    return run
