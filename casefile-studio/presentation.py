"""v0.4.65 Automatic presentation (optional; off unless the producer ticks it in Motion).

For each cinematic graphic it proposes how it is shown: full screen on its own background, over the footage
(the darkened video shows through), or partial (the layout made smaller beside the footage). It only reads:

  * what the collection says each design suits (cinegfx category ``looks["present"]``: a design preference,
    and whether its layout needs its own screen),
  * the shots under the graphic on the timeline (video or picture, how many cuts, whether a whole shot of
    the production script would be hidden),
  * the production script's chapter and shot notes for those shots (the footage guide's Show / Care lines).

Nothing is applied here: the editor shows the proposals and applies the ones the producer approves, as the
graphic's own look (so each can be changed back afterwards). It never decides content or wording; it holds
no rules about what may be named or shown (the script decides that).
"""
from __future__ import annotations

import motion

FULL, FOOTAGE, PARTIAL = "own", "footage", "partial"
PARTIAL_SCALE = 0.86     # the layout's size when it sits beside the footage (inside the 0.8-1.0 place range)
BUSY_CUTS = 4            # this many shots under one graphic: the footage behind it would flicker
LONG = 9.0               # seconds: a graphic this long hiding a whole scripted shot is worth showing the shot
OPENS = 3.0              # seconds: a graphic this close to a chapter's first shot opens the chapter


def _shots(project, start, end):
    """The timeline shots under [start, end]: [{i, a, b, kind, chapter, cue, show, care, whole, share}]."""
    scenes = project.get("scenes") or []
    offsets, _ = motion.scene_offsets(scenes)
    assets = {a["id"]: a for a in project.get("assets") or []}
    cues = {c.get("id"): c for c in ((project.get("episode") or {}).get("guide") or {}).get("cues") or []}
    out = []
    for i, s in enumerate(scenes):
        a = offsets[i]
        b = a + max(1, round(float(s.get("duration") or 0) * motion.FPS)) / motion.FPS
        ov = min(b, end) - max(a, start)
        if ov <= 0.02:
            continue
        cue = cues.get(s.get("guide_cue_id")) or {}
        asset = assets.get(s.get("asset_id")) or {}
        prev = out[-1] if out else None
        if prev and prev["asset"] == s.get("asset_id") and prev["cue"] == (cue.get("id") or "") and abs(prev["b"] - a) < 0.05:
            # the same shot continuing (a scene split on the same footage and script line): not a cut
            prev["b"] = b
            prev["whole"] = prev["whole"] and b <= end + 0.05
            prev["share"] += ov / max(0.01, end - start)
            continue
        out.append({"i": i, "a": a, "b": b, "asset": s.get("asset_id"), "kind": asset.get("kind") or "",
                    "chapter": str(s.get("chapter") or "").strip(),
                    "cue": cue.get("id") or "", "number": cue.get("number"), "show": str(cue.get("show") or "").strip(),
                    "care": str(cue.get("care") or "").split("**Source ID", 1)[0].strip(),
                    "whole": a >= start - 0.05 and b <= end + 0.05, "share": ov / max(0.01, end - start)})
    return out


def _chapter_starts(project):
    scenes = project.get("scenes") or []
    offsets, _ = motion.scene_offsets(scenes)
    seen, out = set(), {}
    for i, s in enumerate(scenes):
        ch = str(s.get("chapter") or "").strip()
        if ch and ch not in seen:
            seen.add(ch)
            out[ch] = offsets[i]
    return out


def _short(text, n=110):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def propose_one(project, item, cat, chapters=None):
    """{mode, look, reasons, shots} for one cinematic graphic (cat: its cinegfx Category)."""
    import cinegfx.look as L
    lk = cat.looks or {}
    pref = lk.get("present") or {}
    can = set(L.backdrops(cat))
    prefer = pref.get("prefer") or FULL
    if prefer == PARTIAL and not lk.get("place"):
        prefer = FOOTAGE
    if prefer != FULL and FOOTAGE not in can:
        prefer = FULL
    start, end = float(item["start"]), float(item["end"])
    shots = _shots(project, start, end)
    main = max(shots, key=lambda s: s["share"]) if shots else None
    pictures = [s for s in shots if s["kind"] in ("video", "image")]
    reasons = [f"{cat.label}: {pref['why']}." if pref.get("why") else f"{cat.label}."]
    mode = prefer

    if pref.get("lock") or FOOTAGE not in can:
        mode = FULL
        reasons.append("Its layout needs its own screen, so it stays full screen.")
    elif not pictures or (main and main["kind"] not in ("video", "image")):
        mode = FULL
        reasons.append("There is no footage or picture under it on the timeline.")
    else:
        busy = len(shots) >= BUSY_CUTS
        if busy:
            reasons.append(f"{len(shots)} shots under it: footage behind the text would keep cutting, so full screen.")
            mode = FULL
        opens = next((ch for ch, t0 in (chapters or {}).items() if abs(start - t0) <= OPENS), None)
        hidden = [s for s in pictures if s["whole"] and s["show"]]
        hid = (f"the scripted shot {hidden[0]['cue'] or hidden[0]['i'] + 1} (\u201c{_short(hidden[0]['show'], 80)}\u201d)"
               if hidden else "")
        if opens and prefer == FULL:
            mode = FULL
            name = opens.title() if opens.isupper() else opens
            reasons.append(f"It opens {name}: full screen marks the new chapter."
                           + (f" It hides {hid}; choose Over the footage to keep that shot visible." if hid else ""))
        elif mode == FULL and hid and end - start >= LONG and not busy:
            mode = FOOTAGE
            reasons.append(f"Full screen would hide all of {hid}, so it goes over that footage.")
        if mode == PARTIAL and main and main["kind"] == "image":
            mode = FOOTAGE  # a still picture under it: over it whole (a small layout beside a photo looks unplanned)
            reasons.append("The shot under it is a still picture: over it, full size.")
    look = {"background": FULL if mode == FULL else FOOTAGE}
    if mode == PARTIAL:
        look["place"] = {"scale": PARTIAL_SCALE, "x": float(pref.get("anchor", 0.0)), "y": 0.0}
        reasons.append("Made smaller to one side so the footage stays visible beside it.")
    elif mode == FOOTAGE:
        reasons.append("The footage shows through, darkened.")
    notes = [{"cue": s["cue"], "chapter": s["chapter"], "show": _short(s["show"]), "care": _short(s["care"]),
              "kind": s["kind"] or "none", "seconds": round(s["b"] - s["a"], 2), "whole": s["whole"]} for s in shots[:6]]
    return {"mode": mode, "look": look, "reasons": reasons, "shots": notes}


def propose(project):
    """Proposals for every cinematic graphic: [{id, label, category, start, mode, look, current, same, reasons, shots}]."""
    import cinematic
    m = motion.normalise(project.get("motion"))
    chapters = _chapter_starts(project)
    out = []
    for it in m["items"]:
        if it["template"] != "cinematic":
            continue
        cat = cinematic._category(it)
        if not cat:
            continue
        p = propose_one(project, it, cat, chapters)
        st = it.get("style") or {}
        cur_bg = st.get("background") or "own"
        cur_place = (it.get("look") or {}).get("place")
        current = PARTIAL if (cur_bg == FOOTAGE and cur_place and cur_place.get("scale", 1) < 1) else (FOOTAGE if cur_bg == FOOTAGE else
                                                                                                       cur_bg)
        out.append({"id": it["id"], "label": it.get("label") or cat.label, "category": cat.label, "start": it["start"],
                    "end": it["end"], "current": current, "same": current == p["mode"], **p})
    return out


def apply(look, proposal):
    """The graphic's own look with an approved proposal applied (the rest of its look kept)."""
    out = dict(look or {})
    out["background"] = proposal["look"]["background"]
    out.pop("photo_id", None)
    out.pop("still_at", None)
    if proposal["mode"] == PARTIAL:
        out["place"] = dict(proposal["look"]["place"])
    elif "place" in out and (out["place"] or {}).get("scale", 1) == PARTIAL_SCALE:
        out.pop("place")  # undo a partial this tool made; a size you chose yourself is kept
    return out
