"""v0.4.78 Edit planner: the narration's graphics + a footage library -> a cut list with a reason for every choice.

    plan(words, elements, library, style, duration, locked=()) -> {"cuts", "graphics", "music", "style"}

* Cuts land on words. Candidate cut points are sentence starts, each graphic's entrance and each numbered point;
  long stretches are split at the word nearest the style's shot length and short ones merged. A graphic that
  sits behind the player (name, stats, impact) holds its close-up instead of cutting under it.
* Each piece of the edit says what it needs from the story: a close-up of a person for type behind him,
  action for numbered goals, a dark or archive picture for a step back in time, a wide for a date and venue.
  Shots are chosen from the analysed footage (shots.py) by that need, by the file name matching the words
  spoken over it (a photo named "ballon_dor_2009" comes up when the narration says "Ballon d'Or"), and by
  variety (a shot isn't reused while unused ones fit; a re-used shot continues from where it stopped).
* Photos are only used when their name matches the narration: nothing is placed as decoration.
* Grade, speed and transitions follow the style and the story (monochrome goals, low-key flashback, warm
  archive, slow motion on emotional close-ups when the shot is short).
* `overrides` (the review step in the app) win over every automatic choice:
      {"graphics": {"40.50": false, "56.60": true},       graphic on/off, keyed by its entrance (s, 2 decimals)
       "moves": {"12.94": 13.40},                          a cut moved by hand (planned time -> new time)
       "shots": {"12.94": {"asset_id", "in"}}}             the footage for the piece starting at a planned cut
  Keys are the cut's *planned* time, so a hand choice survives a re-plan that leaves that cut where it was;
  one that no longer matches a cut is reported in `stale`.

Pure function of its inputs: no I/O.
"""
from __future__ import annotations

import re

from . import semantics as S

# ------------------------------------------------------------------ storytelling styles
STYLES = {
    "auto": {"label": "Automatic", "about": "Chosen from the story: stats-heavy narration is cut analytically, a story "
             "that steps back in time as a historical retrospective, otherwise emotional cinematic."},
    "emotional": {"label": "Emotional cinematic", "about": "Held close-ups, slow motion on the big moments, warm grade, "
                  "music from nostalgic to triumphant.", "min": 2.4, "max": 4.8, "grade": "warm", "close_grade": "warm",
                  "slow": 0.8, "nat": -16, "gap": 0.3, "intro": "nostalgic", "mid": "build", "peak": "peak",
                  "end": "triumph", "rhythm": ["close", "wide", "crowd", "action"]},
    "investigative": {"label": "Investigative", "about": "Cooler, desaturated picture, steady cutting, tension under the "
                      "voice; the numbers and dates do the work.", "min": 2.0, "max": 4.2, "grade": "cool_desat",
                      "close_grade": "cool_desat", "slow": 1.0, "nat": -20, "gap": 0.3, "intro": "tension",
                      "mid": "tension", "peak": "build", "end": "minimal", "rhythm": ["wide", "close", "action", "crowd"]},
    "historical": {"label": "Historical retrospective", "about": "Longer shots, warm archive grade, dissolves between "
                   "chapters, nostalgic music.", "min": 3.0, "max": 6.0, "grade": "warm", "close_grade": "archive",
                   "slow": 0.85, "nat": -20, "gap": 0.5, "intro": "nostalgic", "mid": "nostalgic", "peak": "build",
                   "end": "triumph", "rhythm": ["wide", "close", "crowd", "action"], "dissolve_chapters": True},
    "high_energy": {"label": "High-energy", "about": "Fast cutting on action, punchy grade, loud crowd, building to the "
                    "peak.", "min": 1.2, "max": 2.6, "grade": "punch", "close_grade": "punch", "slow": 1.0, "nat": -12,
                    "gap": 0.2, "intro": "build", "mid": "build", "peak": "peak", "end": "triumph",
                    "rhythm": ["action", "close", "crowd", "action", "wide"]},
    "analytical": {"label": "Analytical", "about": "Clean natural picture, every statistic shown, minimal music, "
                   "footage sound low.", "min": 2.2, "max": 4.5, "grade": "natural", "close_grade": "natural",
                   "slow": 1.0, "nat": -22, "gap": 0.0, "intro": "minimal", "mid": "build", "peak": "build",
                   "end": "minimal", "rhythm": ["wide", "action", "close", "crowd"]},
}
STYLE_KEYS = list(STYLES)

# what each graphic needs from the picture: (kinds in order of preference, person matte, grade key, slow-mo ok)
NEEDS = {
    "name": (["close"], True, "close", True),
    "cumulative": (["close", "crowd", "wide"], True, "close", False),
    "impact": (["close", "crowd"], True, "close", True),
    "headline": (["close", "action", "crowd"], False, "punch", False),
    "numbered": (["action", "wide"], False, "mono_cool", False),
    "minimal": (["dark", "close"], False, "low_key", True),
    "label": (["wide", "crowd"], False, "base", False),
}
PRIORITY = {"impact": 5, "numbered": 5, "name": 5, "cumulative": 4, "headline": 4, "label": 3, "minimal": 3}
STOP = set("the a an and of to in on at for by with from his her their its was were is are be been it this that "
           "then than as but or into over out up one two who what when where which mp4 mov jpg jpeg png webp clip "
           "video photo image final copy edit hd".split())


def resolve_style(key: str, elements) -> tuple[str, dict]:
    """(style key, params); 'auto' picks from the story."""
    key = key if key in STYLES else "auto"
    if key != "auto":
        return key, STYLES[key]
    fams = [e.family for e in elements]
    stats = sum(f in ("cumulative", "impact", "numbered") for f in fams)
    if stats >= max(3, len(fams) * 0.5):
        return "analytical", STYLES["analytical"]
    back = sum(f in ("minimal", "label") for f in fams)
    if back >= 3 and back >= len(fams) * 0.4:
        return "historical", STYLES["historical"]
    return "emotional", STYLES["emotional"]


def thin(elements, gap: float):
    """Don't overload: keep the strongest graphics with at least `gap` seconds between them. Returns the elements
    that stay on, in time order (the rest are offered in the app, switched off)."""
    order = sorted(range(len(elements)), key=lambda i: (-PRIORITY.get(elements[i].family, 1), elements[i].t_in))
    kept = []
    for i in order:
        e = elements[i]
        if all(e.t_out + gap <= k.t_in or k.t_out + gap <= e.t_in for k in kept):
            kept.append(e)
    return sorted(kept, key=lambda e: e.t_in)


def tokens(text: str) -> set:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower().replace("'", "")):
        if len(w) >= 3 and w not in STOP and not (w.isdigit() and len(w) < 4):
            out.add(w)
    return out


def _cut_points(words, elements, duration, lead, p):
    hard, soft = {0.0}, set()
    for i, w in enumerate(words):
        if i == 0 or w.sent != words[i - 1].sent:
            soft.add(round(w.s, 3))
    for e in elements:
        hard.add(round(e.t_in, 3))
        if e.family == "numbered":
            for it in e.data.get("items", []):
                hard.add(round(it["t"], 3))
        if e.family == "minimal":
            hard.add(round(e.t_out, 3))
    if words and lead > 0.3:
        hard.add(round(words[0].s, 3))
    pts = sorted(t for t in hard | soft if 0 <= t < duration - 0.5)
    # no cuts under the first seconds of a behind-the-player graphic: its close-up is held
    held = [(e.t_in + 0.05, min(e.t_out, e.t_in + 3.2)) for e in elements if NEEDS.get(e.family, ([], False))[1]]
    pts = [t for t in pts if t in hard or not any(a < t < b for a, b in held)]
    # merge pieces shorter than the style's minimum (a hard point wins over a soft one)
    out = []
    for t in pts:
        if out and t - out[-1] < p["min"]:
            if t in hard and out[-1] not in hard and len(out) > 1:
                out[-1] = t
            elif t in hard and t - out[-1] >= 0.8:
                out.append(t)
            continue
        out.append(t)
    # split pieces longer than the maximum at the word start nearest the target length
    starts = [w.s for w in words]
    final = []
    for a, b in zip(out, out[1:] + [duration]):
        final.append(a)
        cur = a
        while b - cur > p["max"]:
            target = cur + (p["min"] + p["max"]) / 2
            cands = [s for s in starts if cur + p["min"] <= s <= b - p["min"] and not any(x < s < y for x, y in held)]
            if not cands:
                break
            cur = min(cands, key=lambda s: abs(s - target))
            final.append(round(cur, 3))
    return final


def _context(elements, a):
    for e in elements:
        if e.t_in - 0.3 <= a < e.t_out:
            return e
    return None


def _words_in(words, a, b):
    return " ".join(w.text for w in words if a - 0.6 <= w.s < b + 0.3)


def key(t: float) -> str:
    return f"{float(t):.2f}"


def plan(words, elements, library, style="auto", duration=None, lead=0.0, overrides=None):
    """words: semantics.Word (timeline seconds); elements: semantics.Element (all detected); library:
    [{id, name, kind: video|image, duration, shots: [{t0, t1, kind, why, person, ...}]}]; overrides: see above."""
    ov = overrides or {}
    g_ov = {key(k): bool(v) for k, v in (ov.get("graphics") or {}).items()}
    moves = {key(k): float(v) for k, v in (ov.get("moves") or {}).items()}
    picks = {key(k): v for k, v in (ov.get("shots") or {}).items() if isinstance(v, dict)}
    style_key, p = resolve_style(style, elements)
    duration = duration or ((words[-1].e + 1.6) if words else 10.0)
    auto_on = {id(e) for e in thin(elements, p["gap"])}
    graphics, on = [], []
    for e in elements:
        k = key(e.t_in)
        is_on = g_ov.get(k, id(e) in auto_on)
        reason = None
        if not is_on:
            reason = "switched off by hand" if k in g_ov else \
                "too close to a stronger graphic (keeps the screen from being overloaded)"
        elif k in g_ov and id(e) not in auto_on:
            reason = "switched on by hand"
        if is_on:
            on.append(e)
        graphics.append({"key": k, "family": e.family, "label": S_LABEL.get(e.family, e.family),
                         "t_in": round(e.t_in, 3), "t_out": round(e.t_out, 3), "text": _text_of(e), "why": e.why,
                         "on": is_on, "note": reason, "hand": k in g_ov})
    for g in graphics:   # two graphics on screen at once: say so (the producer chose it)
        if g["on"]:
            clash = [h for h in graphics if h is not g and h["on"] and h["t_in"] < g["t_out"] and g["t_in"] < h["t_out"]]
            if clash:
                g["warning"] = f"on screen at the same time as the {clash[0]['label']}"

    planned = _cut_points(words, on, duration, lead, p)
    stale = [k for k in list(moves) + list(picks) if k not in {key(t) for t in planned}]
    # moved cuts: stay between their neighbours (0.4 s at least each side)
    pts = list(planned)
    for i, t in enumerate(planned):
        if key(t) in moves and i > 0:
            lo = pts[i - 1] + 0.4
            hi = (planned[i + 1] if i + 1 < len(planned) else duration) - 0.4
            pts[i] = round(min(max(moves[key(t)], lo), hi), 3)
    origin = {round(b, 3): key(a) for a, b in zip(planned, pts)}
    video_shots = []
    for clip in library:
        if clip["kind"] == "video":
            for j, s in enumerate(clip.get("shots") or []):
                video_shots.append((clip, j, s))
    photos = [c for c in library if c["kind"] == "image"]
    name_tok = {c["id"]: tokens(c["name"]) for c in library}
    # a video file's name only helps choose between files: words every video name shares say nothing
    vids = [c["id"] for c in library if c["kind"] == "video"]
    if len(vids) < 2:
        for v in vids:
            name_tok[v] = set()
    else:
        common = set.intersection(*(name_tok[v] for v in vids))
        for v in vids:
            name_tok[v] = name_tok[v] - common
    photo_uses = {}
    used = {}            # (clip id, shot index) -> seconds of source already used
    by_id = {c["id"]: c for c in library}
    cuts = []
    rhythm = p["rhythm"]
    prev_key = None
    for n, (a, b) in enumerate(zip(pts, pts[1:] + [duration])):
        L = b - a
        ctx = _context(on, a)
        fam = ctx.family if ctx else None
        kinds, want_matte, grade_key, slow_ok = NEEDS.get(fam, (None, False, "base", False))
        if kinds is None:
            kinds = [rhythm[n % len(rhythm)]] + [k for k in rhythm if k != rhythm[n % len(rhythm)]][:2]
        spoken = _words_in(words, a, b) + (" " + " ".join(str(v) for v in _flat(ctx.data)) if ctx else "")
        spoken_tok = tokens(spoken)
        grade = {"base": p["grade"], "close": p["close_grade"]}.get(grade_key, grade_key)
        why_need = (f"{S_LABEL.get(fam, fam)} on screen: needs {' / '.join(kinds)}" if fam else
                    f"narration only: {kinds[0]} for rhythm")
        k = origin.get(round(a, 3), key(a))
        base = {"key": k, "t": round(a, 3), "end": round(b, 3), "moved": k in moves, "need": why_need,
                "graphic": S_LABEL.get(fam) if fam else None}
        pick = picks.get(k)
        if pick and pick.get("asset_id") in by_id:
            c = by_id[pick["asset_id"]]
            is_photo = c["kind"] == "image"
            t_in = 0.0 if is_photo else max(0.0, float(pick.get("in") or 0.0))
            sk = None
            if not is_photo:
                for j, s_ in enumerate(c.get("shots") or []):
                    if s_["t0"] <= t_in < s_["t1"]:
                        sk = s_
                        used[(c["id"], j)] = used.get((c["id"], j), 0.0) + L + 0.2
                        break
            cuts.append({**base, "asset_id": c["id"], "name": c["name"], "in": round(t_in, 3), "speed": 1.0,
                         "grade": "archive" if is_photo else grade, "matte": bool(want_matte), "photo": is_photo,
                         "kind": "photo" if is_photo else (sk["kind"] if sk else None), "why": "chosen by hand",
                         "hand": True})
            prev_key = (c["id"], None)
            continue
        # a photo whose name matches the words spoken over it
        best_photo = None
        # a photo matches what is said inside its own piece; under a graphic that wants a person (name,
        # stats) only the graphic's own words count (lionel_messi.jpg under LIONEL MESSI, not a stadium photo)
        photo_tok = tokens(_text_of(ctx)) if (ctx and want_matte) else \
            tokens(" ".join(w.text for w in words if a - 0.2 <= w.s < b))
        for c in photos:
            if prev_key == (c["id"], None) or photo_uses.get(c["id"], 0) >= 2:
                continue
            hit = name_tok[c["id"]] & photo_tok
            if hit and (best_photo is None or len(hit) > best_photo[1]):
                best_photo = (c, len(hit), sorted(hit))
        if best_photo and (fam in (None, "label", "minimal", "headline") or best_photo[1] >= 2):
            c, _, hit = best_photo
            photo_uses[c["id"]] = photo_uses.get(c["id"], 0) + 1
            cuts.append({**base, "asset_id": c["id"], "name": c["name"], "in": 0.0,
                         "speed": 1.0, "grade": "archive", "matte": bool(want_matte), "photo": True,
                         "kind": "photo", "why": f"photo named for what is said here ({', '.join(hit)})", "hand": False})
            prev_key = (c["id"], None)
            continue
        if not video_shots:
            cuts.append({**base, "asset_id": None, "name": None, "in": 0.0, "speed": 1.0,
                         "grade": grade, "matte": False, "photo": False, "kind": None,
                         "why": "no footage in the project", "hand": False})
            continue
        scored = []
        for clip, j, s in video_shots:
            avail = (s["t1"] - s["t0"]) - used.get((clip["id"], j), 0.0) - 0.15
            score = 0.0
            reasons = []
            if s["kind"] in kinds:
                r = kinds.index(s["kind"])
                score += 3 - r
                reasons.append(f"{s['kind']} ({s['why']})")
            elif s["kind"] == "dark":
                score -= 2
            hit = name_tok[clip["id"]] & spoken_tok
            if hit:
                score += 2.5 * len(hit)
                reasons.append(f"file named for what is said ({', '.join(sorted(hit))})")
            n_used = 1 if (clip["id"], j) in used else 0
            score -= 3.5 * n_used
            if prev_key == (clip["id"], j):
                score -= 20
            speed = 1.0
            if avail < L:
                need_speed = max(0.0, avail) / L
                if slow_ok and need_speed >= 0.5:
                    speed = round(max(0.5, need_speed), 2)
                    if speed < 0.95:
                        reasons.append(f"slowed to {speed}× to fill the line")
                elif need_speed >= 0.85:
                    speed = round(need_speed, 2)
                else:
                    score -= 4 + 4 * (1 - need_speed)
            elif slow_ok and p["slow"] < 1 and s["kind"] == "close" and avail >= L * p["slow"] * 1.05:
                speed = p["slow"]
                reasons.append(f"slow motion ({speed}×) on the emotional beat")
            if want_matte and s.get("person") is not None:
                score += 1.5 * min(1.0, s["person"] / 0.2)
            scored.append((score, -s["t0"], clip, j, s, speed, reasons, avail))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        score, _, clip, j, s, speed, reasons, avail = scored[0]
        start = s["t0"] + 0.15 + used.get((clip["id"], j), 0.0)
        need_src = L * speed
        if start + need_src > s["t1"]:          # not enough left: from the shot's start (re-use)
            start = s["t0"] + 0.15
        used[(clip["id"], j)] = used.get((clip["id"], j), 0.0) + need_src + 0.2
        prev_key = (clip["id"], j)
        cuts.append({**base, "asset_id": clip["id"], "name": clip["name"],
                     "in": round(start, 3), "speed": speed, "grade": grade,
                     "matte": bool(want_matte), "photo": False, "kind": s["kind"],
                     "why": "; ".join(reasons) or f"{s['kind']} shot, best available fit", "hand": False})
    return {"style": style_key, "style_label": p["label"], "duration": round(duration, 3), "cuts": cuts,
            "graphics": graphics, "music": [list(m) for m in music_sections(on, duration, p, lead)],
            "dissolve_chapters": bool(p.get("dissolve_chapters")), "stale": stale,
            "natural_db": p["nat"], "on": on}


def _text_of(e) -> str:
    """The words a graphic shows (all from the narration), for the review list."""
    d = e.data
    f = e.family
    if f == "name":
        return " ".join(x[0] for x in d.get("lines", []))
    if f in ("label", "minimal"):
        return " / ".join(x["text"] for x in d.get("lines", []))
    if f == "headline":
        return d.get("text", "") + ((" " + " ".join(w for w, _ in d.get("sub", []))) if d.get("sub") else "")
    if f == "numbered":
        return " / ".join(f"{it['n']}. {it.get('label', '')}".strip() for it in d.get("items", []))
    if f == "impact":
        return f"{d.get('value', '')} {d.get('label', '')} {d.get('sub', '')}".strip()
    if f == "cumulative":
        return " / ".join(f"{it['value']} {it['label']}" for it in d.get("items", []))
    return ""


S_LABEL = {"name": "player name (behind the player)", "headline": "headline", "numbered": "numbered points",
           "minimal": "flashback line", "label": "date / place label", "cumulative": "stacked stats (behind the player)",
           "impact": "single big number"}


def _flat(d):
    if isinstance(d, dict):
        for v in d.values():
            yield from _flat(v)
    elif isinstance(d, (list, tuple)):
        for v in d:
            yield from _flat(v)
    elif isinstance(d, str):
        yield d


def music_sections(elements, duration, p, lead=0.0):
    """[(t0, t1, mood)] from the story's shape: intro until the first big graphic, minimal under a flashback, the
    peak under numbered goals and single big numbers, the ending mood for the last stretch."""
    marks = []
    for e in elements:
        if e.family == "minimal":
            marks.append((e.t_in - 0.3, e.t_out + 0.2, "minimal"))
        elif e.family in ("numbered", "impact"):
            marks.append((e.t_in - 0.5, e.t_out + 0.3, p["peak"]))
    end_at = max(duration * 0.84, duration - 14)
    first_big = min([e.t_in for e in elements if e.family not in ("name", "label")] or [duration * 0.2])
    out = []
    t = 0.0
    base = [(0.0, max(lead + 1, first_big - 0.5), p["intro"])]
    for a, b, m in sorted(marks):
        base.append((a, b, m))
    base.append((end_at, duration + 1, p["end"]))
    base.sort()
    for a, b, m in base:
        a = max(a, t)
        if a > t + 0.05:
            out.append((round(t, 2), round(a, 2), p["mid"]))
        if b > a:
            out.append((round(a, 2), round(min(b, duration + 1), 2), m))
            t = min(b, duration + 1)
    if t < duration:
        out.append((round(t, 2), round(duration + 1, 2), p["end"]))
    merged = []
    for a, b, m in out:
        if merged and merged[-1][2] == m and abs(merged[-1][1] - a) < 0.05:
            merged[-1] = (merged[-1][0], b, m)
        elif b - a > 0.3:
            merged.append((a, b, m))
    return merged


def words_from(segments):
    """Convenience re-export: segments [{text, at, heard}] -> Words (number-aware alignment)."""
    return S.timeline(segments)
