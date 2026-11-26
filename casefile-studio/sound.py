"""v0.4.56 Intelligent sound design: an optional, non-destructive sound effects layer (A4).

How it decides (structured event analysis with conservative rules — it does not "understand" the
story, and does not pretend to):

1. Events are read from what is actually on the timeline: every animation event of each approved
   motion graphic (heading, title, divider, each line, each marker, connector and tag, typed
   characters, the exit — `motion.sound_events`), every transition (type, length, direction, and
   whether a chapter changes there), chapter starts, the subscribe animation's own keyframes
   (entrance, click, bell, exit), document-like pictures, and a few kinds of sentence in the
   narration (a legal outcome actually told, a discovery, a contradiction, a turning point).
2. Protected places get silence, on purpose: soundbites (original source audio: interviews,
   police briefings, court), chapters about the victim and family, and any sentence about grief,
   death or violence. Ordinary hard cuts get nothing.
3. Each event has a priority. Density decides how many are kept (a threshold, a per-minute cap
   and a minimum spacing per kind of sound); intensity decides how strong the chosen variation is
   and its level. Related events share a sound (all the bullets of one graphic click alike);
   across the episode the variations rotate so the same sound does not come back too soon.

A planned sound is stored by what it follows (its *anchor*: "the 2nd line of graphic X", "the
transition into scene Y"), not by a time. Its time is worked out again whenever it is played or
exported, so moving, shortening or replacing a transition or a graphic moves its sound with it;
when the thing it followed is gone, the sound is left out (and the export says so).

Mixing: the narration (A1) and soundbites (A2) are never changed. The effects are placed sample-
accurately into one stem (soft-limited, so it cannot clip), ducked under the voice with FFmpeg's
sidechaincompress, mixed with the music (A3) and limited (alimiter) at the end.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import subprocess
import threading
from pathlib import Path

import numpy as np

import effects
import motion
import sfxlib

SPEC = effects.SPEC["sound"]
D = SPEC["defaults"]
LIM = SPEC["limits"]
FPS = SPEC["fps"]
SR = sfxlib.SR
KINDS = [k for k, _ in SPEC["kinds"]]
PRESETS = {p["id"]: p for p in SPEC["presets"]}

# sentences that never get emphasis (and keep the sounds away): grief, death, violence, abuse
SENSITIVE = (
    motion.EMOTION
    + r"|\b(?:kill\w*|murder\w*|shot|shoot\w*|gun\w*|stabb\w*|strangl\w*|suffocat\w*|bod(?:y|ies)|death|died|dies|dead|dying|"
    r"blood\w*|wound\w*|injur\w*|beat(?:en|ing)|rap(?:e|ed)|assault\w*|abus\w*|tortur\w*|suffer\w*|scream\w*|pain|"
    r"victim'?s?|child(?:ren)?|baby|toddler|autopsy|remains)\b"
)
DISCOVERY = (r"\b(?:matched|match(?:es)?\s+(?:him|her|the)|identified|confirmed|discovered|uncovered|turned\s+up|came\s+back|"
             r"led\s+(?:police|detectives|investigators|them)\s+to|breakthrough|broke\s+the\s+case|for\s+the\s+first\s+time|"
             r"traced|linked)\b")
TURNING = r"\b(?:then|until|everything\s+changed|that\s+changed|would\s+change|changed\s+the\s+direction|turned|suddenly|but\s+then)\b"
DOCUMENT = (r"\b(?:document|record|report|letter|warrant|affidavit|filing|transcript|receipt|statement|screenshot|text\s+message|"
            r"email|e-mail|map|certificate|indictment|complaint|newspaper|article|headline|court\s+papers?|docket|form|log)s?\b")


# ====================================================================== settings

def _num(v, lo, hi, default):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return default if not math.isfinite(n) else max(lo, min(hi, n))


def _item(it):
    if not isinstance(it, dict):
        return None
    sid = str(it.get("sound") or "")
    if not (sid in sfxlib.BY_ID or re.fullmatch(r"a:[0-9a-f]{6,32}", sid)):
        return None
    anchor = str(it.get("anchor") or "")[:120]
    if not anchor:
        return None
    kind = it.get("kind") if it.get("kind") in KINDS else "manual"
    out = {
        "id": re.sub(r"[^a-z0-9]", "", str(it.get("id") or ""))[:24] or "sx" + hashlib.sha1(f"{anchor}|{sid}".encode()).hexdigest()[:10],
        "anchor": anchor,
        "kind": kind,
        "sound": sid,
        "gain": round(_num(it.get("gain"), *LIM["gain"], 0.0), 2),
        "offset": round(_num(it.get("offset"), *LIM["offset"], 0.0), 4),
        "fade_in": round(_num(it.get("fade_in"), *LIM["fade"], 0.0), 3),
        "fade_out": round(_num(it.get("fade_out"), *LIM["fade"], 0.0), 3),
        "length": round(_num(it.get("length"), 0.03, 30.0, 0.0), 3) or None,
        "status": it.get("status") if it.get("status") in ("approved", "suggested", "removed") else "approved",
        "source": "auto" if it.get("source") == "auto" else "manual",
        "edited": bool(it.get("edited")),
        "reason": str(it.get("reason") or "")[:240],
        "label": str(it.get("label") or "")[:120],
    }
    return out


def normalise(value):
    v = value if isinstance(value, dict) else {}
    out = {
        "enabled": bool(v.get("enabled", D["enabled"])),
        "mode": v.get("mode") if v.get("mode") in ("auto", "manual") else D["mode"],
        "preset": v.get("preset") if v.get("preset") in PRESETS else D["preset"],
        "master": round(_num(v.get("master"), *LIM["master"], D["master"]), 3),
        "intensity": round(_num(v.get("intensity"), *LIM["intensity"], D["intensity"]), 3),
        "density": round(_num(v.get("density"), *LIM["density"], D["density"]), 3),
        "lead": round(_num(v.get("lead"), *LIM["lead"], D["lead"]), 3),
        "duck": bool(v.get("duck", D["duck"])),
        "variation": bool(v.get("variation", D["variation"])),
        "kinds": {k: bool((v.get("kinds") or {}).get(k, D["kinds"].get(k, True))) for k in KINDS if k != "manual"},
    }
    items, seen = [], set()
    for it in (v.get("items") or [])[: LIM["items"]]:
        it = _item(it)
        if it and it["id"] not in seen:
            seen.add(it["id"])
            items.append(it)
    out["items"] = items
    return out


# ====================================================================== the timeline, read

def _offsets(scenes):
    out, t = [], 0.0
    for s in scenes:
        out.append(t)
        t += max(1, round(float(s.get("duration") or 0) * FPS)) / FPS
    return out, t


def _scene_len(s):
    return max(1, round(float(s.get("duration") or 0) * FPS)) / FPS


_EVENTS: dict = {}  # graphic content hash -> its animation events (laying out a graphic takes ~0.6 s)
_EVENTS_LOCK = threading.Lock()


def _motion_events(project):
    """{item id: (item, [events])} for the graphics that are exported (approved, layer on)."""
    out = {}
    W, H = motion.preview_size(project)  # the editor lays them out at this size too (shared cache)
    for it in motion.exported(project):
        key = motion.item_hash(it, W, H)
        with _EVENTS_LOCK:
            evs = _EVENTS.get(key)
        if evs is None:
            try:
                evs = motion.sound_events(motion._layout(it, W, H, None))
            except (OSError, ValueError, KeyError):  # pragma: no cover - a broken item is skipped
                continue
            with _EVENTS_LOCK:
                if len(_EVENTS) > 300:
                    _EVENTS.pop(next(iter(_EVENTS)))
                _EVENTS[key] = evs
        out[it["id"]] = (it, evs)
    return out


def _sentences(project):
    try:
        return motion.sentences(motion.timeline_words(project))
    except (KeyError, ValueError, TypeError):  # pragma: no cover
        return []


# ====================================================================== context (v0.4.57)
# What is sensitive is decided from the passage, not from one word: a sentence's own evidence
# (violence, death, grief and memory, the people in it), its neighbours, its chapter, the picture on
# screen, who it is about (the victim's family or the suspect's) and what it does in the story (a
# record, a discovery, a legal step). "The vehicle was registered to Jackson's mother" is evidence;
# "That was a mother remembering her son" is grief. One word alone never decides either way.

C_VIOLENT = re.compile(r"\b(?:kill(?:ed|ing|s)?|murder(?:ed|ing|s)?|shots?|shoot(?:ing|s)?|violen(?:ce|t)|stabb\w*|strangl\w*|suffocat\w*|bod(?:y|ies)|"
                       r"blood\w*|wound\w*|injur\w*|beat(?:en|ing)|rap(?:e|ed)|assault\w*|abus\w*|tortur\w*|scream\w*|remains|autopsy|"
                       r"bullet\s+(?:struck|hit|wound)|gunned\s+down|open(?:ed)?\s+fire)\b", re.I)
C_DEATH = re.compile(r"\b(?:death|died|dies|dead|dying|lost\s+(?:her|his|their|\w+)\s+(?:\w+\s+)?(?:sons?|daughters?|child(?:ren)?|li(?:fe|ves))|never\s+came\s+home|"
                     r"pronounced|passed\s+away)\b", re.I)
C_GRIEF = re.compile(r"\b(?:funeral|vigil|tribute|memorial|grave(?:side|s)?|mourn\w*|grie(?:f|v\w*)|tears?|wept|sobb\w*|cried|cry(?:ing)?|"
                     r"beloved|heartbr\w*|miss(?:es|ed)?\s+(?:him|her)|in\s+memory|memor(?:y|ies)|remember(?:ed|s|ing)?|recalled|"
                     r"(?:described|remembered)\s+(?:him|her)\s+as|suffer\w*|pain)\b", re.I)
C_PERSON = re.compile(r"\b(?:mother|father|mom|dad|grand(?:mother|father|ma|pa)|god(?:mother|father)|famil(?:y|ies)|loved\s+ones?|son|"
                      r"daughter|sister|brother|wife|husband|child(?:ren)?|baby|toddler|teen(?:ager)?|boy|girl|victim'?s?|relatives?|"
                      r"smil\w*|dream\w*|love[ds]?)\b", re.I)
# the language of the case: records, evidence, procedure (it is about the investigation, not grief)
C_CASE = re.compile(r"\b(?:registered|registration|records?|owned|licen[cs]e|plates?|vehicle|car|truck|phone|warrant|testif\w*|"
                    r"told\s+(?:police|detectives|investigators|officers)|police|detectives?|investigators?|officers?|marshals?|"
                    r"evidence|surveillance|footage|camera|address|according\s+to|court|filed|filing|docket|charged|arrest\w*|"
                    r"matched|traced|identified|recovered|casings?|ballistic\w*|forensic\w*|dna|prosecutors?|defen[cs]e|"
                    r"hearing|plea|indict\w*|submission|statement|sentenc\w*|guilty|convict\w*|access\s+to)\b", re.I)
# a violent word used as the name of a charge is a legal term ("pleaded guilty to murder")
C_CHARGE = re.compile(r"\b(?:charged\s+with|convicted\s+of|guilty\s+(?:to|of)|count(?:s)?\s+of|acquitted\s+of|plea\s+to|"
                      r"aggravated|(?:first|second|third)[-\s]degree|attempted|felonious)\s+(?:\w+\s+){0,2}"
                      r"(?:murder|manslaughter|assault|homicide|killing|felony)\b|"
                      r"\b(?:murder|manslaughter|homicide|assault)\s+(?:conviction|charges?|counts?|case|trial|indictment|statute)\b", re.I)
C_PICTURE = re.compile(r"\b(?:photo(?:graph)?s?|portraits?|pictures?|smiling|childhood|school\s+photo|selfie|wedding|graduation|"
                       r"memorial|candles?|flowers|cross(?:es)?)\b", re.I)
SENSITIVE_AT = 1.5  # the score at which a passage or picture is kept free of automatic sounds


def _people(project):
    """(victim name words, suspect name words) from the episode guide's project setup."""
    import basefill

    ep = project.get("episode")
    guide = ep.get("guide") if isinstance(ep, dict) else None
    setup = guide.get("setup") if isinstance(guide, dict) else None
    if not isinstance(setup, dict):
        return [], []
    names = lambda v: basefill.name_parts([n for n in v if isinstance(n, str)] if isinstance(v, list) else [])
    return names(setup.get("victims")), names(setup.get("suspects"))


def _whose(text, victims, suspects):
    """'victim' | 'suspect' | None: whose relative a family word is ("Maurco's mother", "Jackson's mother")."""
    low = text.lower()
    for kind, names in (("suspect", suspects), ("victim", victims)):
        for n in names:
            if re.search(rf"\b{re.escape(n)}(?:'s|’s|s')\s+(?:\w+\s+)?(?:mother|father|mom|dad|grand\w+|god\w+|famil\w+|sister|brother|"
                         rf"wife|husband|son|daughter|relatives?|loved)", low):
                return kind
    return None


def _evidence(text, victims, suspects):
    """(score, [why]) of one piece of text on its own: positive = grief, death, violence, the victim
    as a person; negative = the record, the evidence, the procedure. Cached: a re-plan after an edit
    only scores the sentences whose words changed."""
    score, why = _evidence_cached(text, tuple(victims), tuple(suspects))
    return score, list(why)


@functools.lru_cache(maxsize=16384)
def _evidence_cached(text, victims, suspects):
    why = []
    score = 0.0
    charge = C_CHARGE.search(text)
    violent = [m for m in C_VIOLENT.finditer(text) if not (charge and charge.start() <= m.start() < charge.end())]
    if violent:
        score += 2.0
        why.append(f"violence ({violent[0].group(0).lower()})")
    elif charge:
        score += 0.4
        why.append(f"a charge ({charge.group(0).lower()})")
    if C_DEATH.search(text):
        score += 1.8
        why.append("death")
    g = C_GRIEF.search(text)
    if g:
        score += 1.4
        why.append(f"grief or memory ({g.group(0).lower()})")
    persons = {m.group(0).lower() for m in C_PERSON.finditer(text)}
    whose = _whose(text, victims, suspects)
    low = text.lower()
    victim_named = any(re.search(rf"\b{re.escape(n)}\b", low) for n in victims)
    suspect_named = any(re.search(rf"\b{re.escape(n)}\b", low) for n in suspects)
    if persons:
        w = 0.0 if whose == "suspect" else min(1.0, 0.6 + 0.2 * (len(persons) - 1))
        if whose == "victim":
            w += 0.8
        score += w
        if w:
            why.append(f"family ({sorted(persons)[0]}{', the victim' + chr(39) + 's' if whose == 'victim' else ''})")
    if victim_named and not suspect_named:
        score += 0.5
        why.append("about the victim")
    case = {m.group(0).lower() for m in C_CASE.finditer(text)}
    if case:
        score -= min(1.4, 0.7 * len(case))
        why.append(f"the case ({', '.join(sorted(case)[:2])})")
    return score, tuple(why)


def context(project, sents):
    """{"sent": [score], "scene": [score], "why_sent": [..], "why_scene": [..]}: how sensitive each
    narration sentence and each scene's picture is, from all the context there is."""
    scenes = project.get("scenes") or []
    victims, suspects = _people(project)
    assets = {a.get("id"): a for a in project.get("assets") or []}
    base = [_evidence(snt["text"], victims, suspects) for snt in sents]
    out_s, why_s = [], []
    import basefill

    kinds = {}
    chapter_kind = lambda c: kinds[c] if c in kinds else kinds.setdefault(c, motion.chapter_kind(c))

    for i, snt in enumerate(sents):
        sc, why = base[i][0], list(base[i][1])
        # the passage: grief or violence next door colours a sentence (a neutral line between two
        # grief lines is still that passage); only within the same chapter
        ch = (scenes[snt["scene"]].get("chapter") if scenes else "") or ""
        near = [base[j][0] for j in (i - 1, i + 1) if 0 <= j < len(sents) and
                ((scenes[sents[j]["scene"]].get("chapter") if scenes else "") or "") == ch]
        spill = 0.4 * max([0.0] + near)
        if spill >= 0.4:
            sc += spill
            why.append("a sensitive passage around it")
        if len(near) == 2 and min(near) >= SENSITIVE_AT and sc < SENSITIVE_AT:
            sc = SENSITIVE_AT  # between two sensitive sentences: inside that passage
            why.append("inside a sensitive passage")
        ck = chapter_kind(ch)
        if ck == "victim":
            sc += 1.0
            why.append("a chapter about the victim")
        # what it does in the story: a legal step or an investigative finding is case progress
        if base[i][0] < 2.0 and (motion._outcome(snt["text"]) or (re.search(DISCOVERY, snt["text"], re.I) and re.search(motion.FIND, snt["text"], re.I))):
            sc -= 0.6
            why.append("case progress")
        out_s.append(round(sc, 2))
        why_s.append(why)
    out_c, why_c = [], []
    for k, s in enumerate(scenes):
        a = assets.get(s.get("asset_id")) or {}
        sc, why = 0.0, []
        b = basefill.parse_name(a.get("name"))
        if b:
            tags = set(b["tags"])
            if b["bucket"] == "V":
                sc += 1.5 + (0.5 if tags & {"memorial", "family", "portrait", "funeral", "vigil", "childhood"} else 0.0)
                why.append("a picture of the victim")
            elif tags & {"memorial", "funeral", "vigil", "family"}:
                sc += 1.5
                why.append("a memorial picture")
            else:
                sc -= 1.0
                why.append("a suspect or scene picture" if b["bucket"] in ("S", "C") else "a case picture")
        pic = f"{s.get('title', '')} {s.get('visual', '')} {s.get('visual_note', '')} {'' if b else a.get('name', '')}"
        if re.search(r"\bbase\s+image\s*·\s*victim\b", pic, re.I) and not b:
            sc += 1.5
            why.append("a picture of the victim")
        e, w = _evidence(pic, victims, suspects)
        if re.search(r"\bvictim'?s?\b", pic, re.I) and not b:
            e += 0.9  # "victim" in what the picture is: it shows the victim
        if C_PICTURE.search(pic) and (e > 0 or sc > 0):
            e += 0.9
            w.append("a personal photograph")
        sc += e
        why += w
        told = [out_s[i] for i, snt in enumerate(sents) if snt["scene"] == k]
        if told:
            sc += 0.5 * max(0.0, sum(told) / len(told))
        if chapter_kind(s.get("chapter")) == "victim":
            sc += 1.0
        out_c.append(round(sc, 2))
        why_c.append(why)
    return {"sent": out_s, "scene": out_c, "why_sent": why_s, "why_scene": why_c}


SOUNDBITE = "original source audio (a soundbite)"
VICTIM = "a chapter about the victim and family"
PICTURE = "a picture of the victim or family"
SENSITIVE_TEXT = "a sensitive passage (grief, death or violence)"


def protected(project, sents=None, ctx=None):
    """[(start, end, why)] where no automatic sound goes: original source audio, the victim and
    family (chapters and pictures), grief and violence in the narration (by context: `context`)."""
    scenes = project.get("scenes") or []
    offsets, total = _offsets(scenes)
    sents = _sentences(project) if sents is None else sents
    ctx = context(project, sents) if ctx is None else ctx
    zones = []
    for i, s in enumerate(scenes):
        a, b = offsets[i], offsets[i] + _scene_len(s)
        if s.get("insert_audio") or s.get("audio_break"):
            zones.append((a - 0.6, b + 0.6, SOUNDBITE))
        elif motion.chapter_kind(s.get("chapter")) == "victim":
            zones.append((a, b, VICTIM))
        elif ctx["scene"][i] >= SENSITIVE_AT:
            zones.append((a - 0.3, b - 0.001, PICTURE))  # up to the cut (a sound on the cut belongs to the next picture)
    for k, snt in enumerate(sents):
        if ctx["sent"][k] >= SENSITIVE_AT:
            zones.append((snt["t"] - 0.8, snt["e"] + 0.8, SENSITIVE_TEXT))
    zones.sort()
    merged = []
    for z in zones:
        if merged and z[0] <= merged[-1][1] and z[2] == merged[-1][2]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], z[1]), z[2])
        else:
            merged.append(z)
    return merged


def _quiet(t, zones):
    return next((z[2] for z in zones if z[0] <= t <= z[1]), None)


# v0.4.58 Each motion graphics template has its own sound identity: one coherent family per template,
# shaped by what the graphic actually does (its entrance and exit animation, its layout, the kind of
# line). Within a family, the least recently used variation is chosen, so two graphics of the same
# template sound related but not identical. (category, hint): hint picks variations by id.
PALETTES = {
    # investigative findings: neutral air, a rising divider, crisp mechanical clicks ("logged")
    "findings": {"enter": [("whoosh", ("short", "mid"))], "divider": [("tonal-sweep", "up")],
                 "line": [("click", ("mech-1", "mech-2"))], "cards": ["pop"], "typing": "typewriter"},
    # chronological timeline: travel along the time axis, small precise ticks on each date
    "timeline": {"enter": [("whoosh", ("short", "mid"))], "enter_horizontal": [("whoosh", "dir-r")],
                 "divider": [("tonal-sweep", "up")], "marker": ["tick"], "connector": ["scan"],
                 "line": ["tick"], "typing": "typewriter"},
    # contradictory statements: an intake of breath, a falling divider; what was said is a soft muted
    # click, the record a firmer felt one, and the first piece of the record that contradicts it a low pulse
    "contrast": {"enter": ["reverse-whoosh", ("whoosh", "mid")], "divider": [("tonal-sweep", "down")],
                 "statement": [("click-muted", ("muted-1", "muted-2"))], "finding": [("click-muted", "muted-3")], "contradiction": [("pulse", "low")],
                 "typing": "typewriter"},
    # legal outcome: the record itself (a document), a falling divider, the heavy click on every step
    # (the same weight each time), the outcome lands. Typed entrances keep the typewriter everywhere:
    # the animation is called "Typewriter" (soft keys only at a low intensity, as before)
    "legal": {"enter": [("document", ""), "paper"], "divider": [("tonal-sweep", "down")],
              "tag": [("click", "mech-3")], "marker": [("click", "mech-3")],
              "connector": ["scan"], "verdict": ["thump", "bass-impact"], "typing": "typewriter"},
}
# the entrance / exit animation decides the movement of the air
ENTER_MOVES = {"slide": [("whoosh", "dir-l")]}  # slides in from the right: a leftward whoosh
EXIT_MOVES = {"slide": [("whoosh", "dir-r")]}   # slides out to the right


def palette(template):
    return PALETTES.get(template, PALETTES["findings"])


def events(project, mg=None, sents=None, ctx=None):
    """Every candidate moment for a sound: [{anchor, kind, t, prio, cats, group, reason, label,
    gain, typed}] in timeline seconds (where the sound's sync point goes)."""
    scenes = project.get("scenes") or []
    offsets, total = _offsets(scenes)
    out = []

    def add(anchor, kind, t, prio, cats, reason, label, group=None, gain=0.0, typed=None):
        if 0 <= t <= total + 0.5:
            out.append({"anchor": anchor, "kind": kind, "t": round(t, 4), "prio": prio, "cats": cats, "reason": reason,
                        "label": label, "group": group or anchor, "gain": gain, "typed": typed})

    # --- motion graphics and their diagrams
    mg = _motion_events(project) if mg is None else mg
    for gid, (it, evs) in mg.items():
        tpl = it["template"]
        start = round(it["start"] * FPS) / FPS  # the graphic's first frame (motion.prepare does the same)

        def on_frame(local):  # the first frame on which something at `local` is drawn
            return math.ceil(local * FPS - 1e-6) / FPS
        layout = motion.resolve_layout(it, motion._is_tall(project))
        diagram = tpl == "timeline" or (tpl == "legal" and layout == "steps")
        name = f"{tpl} graphic at {int(start // 60)}:{int(start % 60):02d}"
        photo = it.get("background") in ("photo", "still")
        counts = {}
        last_t = -1.0
        # a typed piece is its own sound: no click or whoosh on top of the first keys
        typed_at = [start + on_frame(e["t"]) for e in evs if e["chars"]]
        pal = palette(tpl)
        enter_kind = it.get("enter") or "mask"
        exit_kind = it.get("exit") or "fade"
        starts = motion.line_starts(it) if tpl == "contrast" else []
        first_finding = next((k for k, (_, ln) in enumerate(starts) if ln["kind"] == "finding"), None)
        contradicts = bool(first_finding) and any(ln["kind"] != "finding" for _, ln in starts[:first_finding])

        def line_of(local):  # the line (of a contradiction graphic) a drawn element belongs to
            k = max((j for j, (t0, _) in enumerate(starts) if t0 <= local + 1e-3), default=0)
            return k, starts[k][1] if starts else None
        for e in evs:
            role = e["role"]
            k = counts.get(role, 0)
            counts[role] = k + 1
            anchor = f"mg:{gid}:{role}:{k}"
            t = start + on_frame(e["t"])
            if e["chars"]:
                fam = pal["typing"]
                add(anchor, "typing", t, 0.8, [fam], f"{'typing' if fam == 'typewriter' else 'keys'}, key by key, as the {role} is typed",
                    f"Typing — {name}", group=f"mg:{gid}:type", gain=-5.0,
                    typed=[[round(start + on_frame(c[0]), 4), bool(c[1])] for c in e["chars"]])
                if tpl == "contrast" and role == "line" and contradicts and line_of(e["t"])[0] == first_finding \
                        and not any(x["anchor"].endswith(":x") and x["group"] == f"mg:{gid}:contradiction" for x in out):
                    # v0.4.59 a typed contradiction keeps its low pulse (typed legal outcomes keep their thump):
                    # the keys are the line's sound, the pulse marks the record contradicting the statement
                    add(f"{anchor}:x", "motion", t, 0.72, pal["contradiction"], "the record contradicts the statement",
                        f"Contradiction — {name}", group=f"mg:{gid}:contradiction", gain=-9.0)
                continue
            if role != "exit" and any(abs(t - ta) < 0.35 for ta in typed_at):
                continue
            if typed_at and role in ("divider", "title"):
                continue  # a typed graphic: the keys are its sound (a sweep would ring over them)
            if role == "background":
                if tpl == "legal" or photo:
                    add(anchor, "documents", t + 0.25, 0.75, ["document", "paper"], "an official record / picture comes up", f"Document reveal — {name}", gain=-2.0)
                else:
                    cats = ENTER_MOVES.get(enter_kind) or pal.get(f"enter_{layout}") or pal["enter"]
                    how = {"slide": "slides in", "fade": "fades in", "type": "comes in to be typed"}.get(enter_kind, "rises in")
                    add(anchor, "motion", t + 0.3, 0.75, cats, f"the {tpl} graphic {how}", f"Entrance — {name}",
                        gain=-8.0 if enter_kind == "fade" else -5.0)
            elif role == "heading" and k == 0:
                add(anchor, "motion", t, 0.3, ["click-muted"], "heading entrance", f"Heading — {name}", group=f"mg:{gid}:click", gain=-4.0)
            elif role == "title" and k == 0:
                add(anchor, "motion", t, 0.35, ["tonal-sweep"], "masked title reveal", f"Title — {name}", gain=-3.0)
            elif role == "divider":
                add(anchor, "motion", t + 0.15, 0.55, pal["divider"], "animated divider", f"Divider — {name}", gain=-2.0)
            elif role in ("marker", "tag") and diagram:
                add(anchor, "diagrams", t, 0.68, pal.get(role) or pal.get("marker") or ["tick"],
                    f"diagram {'marker' if role == 'marker' else 'step label'} appears",
                    f"Diagram {role} {k + 1} — {name}", group=f"mg:{gid}:{role}", gain=-1.0)
            elif role == "connector" and diagram:
                add(anchor, "diagrams", t + 0.1, 0.42, pal.get("connector", ["scan"]), "connecting line draws to the next point",
                    f"Connector {k + 1} — {name}", group=f"mg:{gid}:connector", gain=-6.0)
            elif role == "tag":
                add(anchor, "motion", t, 0.7, pal.get("tag", ["click"]), "legal step appears", f"Legal step {k + 1} — {name}",
                    group=f"mg:{gid}:tag", gain=-1.0)
            elif role == "verdict" and k == 0:
                add(anchor, "moments", t, 0.86, pal.get("verdict", ["thump", "bass-impact"]), "the legal outcome lands", f"Outcome — {name}", gain=-8.0)
            elif role in ("line", "marker", "date") and not diagram:
                if t - last_t < 0.3:  # a bullet marker and its line (or a wrapped line) come together: one sound
                    continue
                last_t = t
                if tpl == "contrast":
                    j, ln = line_of(e["t"])
                    kind = ln["kind"] if ln else "statement"
                    if kind == "finding" and contradicts and j == first_finding:
                        # the record contradicts what was said: a low pulse, or the firm click if it cannot be placed
                        add(f"{anchor}:x", "motion", t, 0.72, pal["contradiction"], "the record contradicts the statement",
                            f"Contradiction — {name}", gain=-9.0)
                    add(anchor, "motion", t, 0.7, pal[kind], "what the record shows" if kind == "finding" else "what was said",
                        f"{'Record' if kind == 'finding' else 'Statement'} {sum(1 for _, x in starts[:j + 1] if x['kind'] == kind)} — {name}", group=f"mg:{gid}:{kind}",
                        gain=-1.0 if kind == "finding" else -3.0)
                    continue
                cats = pal["cards"] if (layout == "cards" and "cards" in pal) else (pal.get("line") or pal.get("tag") or ["click"])
                add(anchor, "motion", t, 0.7, cats, "an information line is revealed", f"Line {counts[role]} — {name}",
                    group=f"mg:{gid}:line", gain=-2.0)
            elif role == "exit":
                add(anchor, "motion", t, 0.35, EXIT_MOVES.get(exit_kind) or [("whoosh", "short")], "the graphic leaves", f"Exit — {name}", gain=-10.0)

    # --- transitions and chapter starts
    for i in range(1, len(scenes)):
        s, prev = scenes[i], scenes[i - 1]
        new_chapter = (s.get("chapter") or "") != (prev.get("chapter") or "") and bool(s.get("chapter"))
        ck = motion.chapter_kind(s.get("chapter"))
        tid = effects.transition_id(s.get("transition"))
        d = effects.transition_length(s, float(s.get("duration") or 0)) if tid != "none" else 0.0
        at = offsets[i]
        title = s.get("title") or f"scene {i + 1}"
        if tid != "none" and d > 0:
            mid = at + d / 2
            size = "short" if d < 0.5 else ("long" if d > 1.0 else "mid")
            anchor = f"tr:{s.get('id') or i}"
            what = f"{tid} transition ({d:.1f} s)"
            if tid in ("slide-left", "wipe-left"):
                add(anchor, "transitions", mid, 0.7, [("whoosh", "dir-l" if tid == "slide-left" else size)], f"{what}: a restrained directional whoosh",
                    f"Transition into {title}", gain=-4.0)
            elif tid == "slide-up":
                add(anchor, "transitions", mid, 0.7, [("whoosh", "dir-up")], f"{what}: a rising whoosh", f"Transition into {title}", gain=-4.0)
            elif tid == "zoom":
                add(anchor, "transitions", mid, 0.68, [("whoosh", size)], f"{what}: a short, controlled whoosh", f"Transition into {title}", gain=-4.0)
            elif tid == "circle":
                add(anchor, "transitions", mid, 0.62, ["tonal-sweep"], f"{what} (a masked reveal): a soft tonal sweep", f"Transition into {title}", gain=-2.0)
            elif tid == "pixelize":
                add(anchor, "transitions", mid, 0.6, ["scan"], f"{what}: a digital scan", f"Transition into {title}", gain=-2.0)
            elif tid in ("dip-black", "dip-white"):
                if new_chapter:  # a chapter change: a swell that crests on the black (or white) frame
                    add(anchor, "transitions", mid, 0.8, ["swell"], f"{what} at a new chapter: an atmospheric swell",
                        f"Chapter: {s.get('chapter')}", gain=-4.0)
                else:
                    add(anchor, "transitions", mid, 0.5, ["pulse"], f"{what}: a quiet low pulse", f"Transition into {title}", gain=-8.0)
            elif tid == "dissolve":
                if new_chapter and d >= 0.6:
                    add(anchor, "transitions", at, 0.65, ["swell"], f"slow {what} at a new chapter: an atmospheric swell", f"Chapter: {s.get('chapter')}", gain=-5.0)
                # an ordinary dissolve: silence
        elif new_chapter and ck in ("investigation", "legal", "statements", "chronology"):
            add(f"ch:{s.get('id') or i}", "transitions", at, 0.55, ["swell"], f"a new chapter ({ck}) begins on a cut: a subtle swell",
                f"Chapter: {s.get('chapter')}", gain=-6.0)
        # documents and photographs (never a camera shutter: it would suggest a real camera)
        asset = next((a for a in project.get("assets") or [] if a.get("id") == s.get("asset_id")), None)
        if asset and asset.get("kind") == "image" and not s.get("insert_audio"):
            text = f"{asset.get('name', '')} {title} {s.get('visual', '')} {s.get('visual_note', '')}"
            if re.search(DOCUMENT, text, re.I):
                add(f"doc:{s.get('id') or i}", "documents", at + (d / 2 if d else 0.05), 0.6, ["document", "paper"],
                    "a document is presented", f"Document — {title}", gain=-3.0)
            else:
                add(f"doc:{s.get('id') or i}", "documents", at + (d / 2 if d else 0.05), 0.3, ["paper"],
                    "a photograph is shown", f"Photograph — {title}", gain=-8.0)

    # --- the narration: legal outcomes told, discoveries, contradictions, turning points
    sents = _sentences(project) if sents is None else sents
    ctx = context(project, sents) if ctx is None else ctx
    for k_s, snt in enumerate(sents):
        text = snt["text"]
        sc = scenes[snt["scene"]] if scenes else {}
        ck = motion.chapter_kind(sc.get("chapter"))
        if ctx["sent"][k_s] >= SENSITIVE_AT or ck in ("victim", "opening", "closing"):
            continue
        local = round(snt["t"] - offsets[snt["scene"]], 3)
        anchor = f"mo:{sc.get('id') or snt['scene']}:{local}"
        short = (text[:70] + "…") if len(text) > 72 else text
        out_ = motion._outcome(text)
        if out_:
            t = motion._word_time(snt, out_[1])
            add(anchor, "moments", t, 0.85, ["bass-impact", "thump"], f"a legal development told in the narration ({out_[0].lower()})",
                f"\u201c{short}\u201d", gain=-10.0)
            continue
        if re.search(motion.COURT, text, re.I):
            continue  # arguments in court are not discoveries
        m = re.search(DISCOVERY, text, re.I)
        if m and re.search(motion.FIND, text, re.I):
            add(anchor, "moments", motion._word_time(snt, m.start()), 0.72, ["thump", "pulse"], "an investigative discovery",
                f"\u201c{short}\u201d", gain=-9.0)
            continue
        if re.search(motion.STATED, text, re.I) and re.search(motion.CONTRADICT, text, re.I) and re.search(motion.FOUND, text, re.I):
            add(anchor, "moments", snt["t"], 0.6, ["pulse"], "a contradiction: what was said against what was found", f"\u201c{short}\u201d", gain=-9.0)
            continue
        m = re.search(TURNING, text, re.I)
        if m and m.start() < 12 and len(text) > 25:
            add(anchor, "moments", snt["t"], 0.45, ["reverse-whoosh"], "a turning point in the story", f"\u201c{short}\u201d", gain=-9.0)

    # --- the subscribe animation, on its own keyframes
    try:
        import cta

        c = cta.normalise(project.get("cta"))
        for r in cta.spots(project):
            if not r["shown"]:
                continue
            a, b = r["start"], r["end"]
            key = r["key"]
            add(f"cta:{key}:enter", "cta", a + cta.SPEC["fade_in"] * 0.5, 0.9, [("whoosh", "short")], "the subscribe banner comes in",
                "Subscribe — entrance", group="cta:whoosh", gain=-8.0)
            if c.get("source", "casefile") != "file":  # our own animation: we know its keyframes
                if a + cta.SPEC["click"] < b - 0.2:
                    add(f"cta:{key}:click", "cta", a + cta.SPEC["click"], 0.9, ["cta-click"], "the cursor clicks SUBSCRIBE", "Subscribe — click", gain=-2.0)
                if a + cta.SPEC["wiggle"][0] < b - 0.3:
                    add(f"cta:{key}:bell", "cta", a + cta.SPEC["wiggle"][0], 0.9, ["bell"], "the notification bell rings", "Subscribe — bell", gain=-4.0)
            add(f"cta:{key}:exit", "cta", max(a, b - cta.fade_out_seconds(a, b)), 0.6, [("whoosh", "short")], "the banner leaves",
                "Subscribe — exit", group="cta:whoosh", gain=-14.0)
    except Exception:  # pragma: no cover - the CTA is optional
        pass
    out.sort(key=lambda e: e["t"])
    return out


# ====================================================================== choosing

def _candidates(cat, intensity):
    """Library sounds for a category (or (category, hint)), best first for this intensity."""
    hint = None
    if isinstance(cat, (list, tuple)):
        cat, hint = cat
    pool = [c for c in sfxlib.CATALOG if c[1] == cat and not c[0].startswith("shutter") and "-seq" not in c[0]]
    if cat == "typewriter":
        pool = [c for c in pool if "space" not in c[0]]
    if hint:
        hints = (hint,) if isinstance(hint, str) else tuple(hint)
        hinted = [c for c in pool if any(h in c[0] for h in hints)]
        pool = hinted or pool
    want = 1 + round(intensity * 2)  # 1..3
    pool.sort(key=lambda c: (abs(c[3] - want), c[0]))
    best = abs(pool[0][3] - want) if pool else 0
    return [c[0] for c in pool if abs(c[3] - want) <= best + (1 if len(pool) > 3 else 0)]


def _family(cat):
    """v0.4.58 Every variation of a palette entry (category, hint), whatever the intensity: the
    siblings a graphic's repeated element alternates between."""
    hint = None
    if isinstance(cat, (list, tuple)):
        cat, hint = cat
    pool = [c[0] for c in sfxlib.CATALOG if c[1] == cat and not c[0].startswith("shutter") and "-seq" not in c[0] and "space" not in c[0]]
    if hint:
        hints = (hint,) if isinstance(hint, str) else tuple(hint)
        pool = [c for c in pool if any(h in c for h in hints)] or pool
    return sorted(pool)


# a repeated element of one graphic is humanised: the same family, alternating variations and a
# small accent pattern (dB) — related, never the identical sample at the identical level
ACCENTS = (0.0, -1.2, -0.5, -1.6)


def plan(project, settings=None, keep=(), held=()):
    """The automatic plan: [item] (source "auto"), and the decisions taken: {kept, silenced:
    [{t, label, why}], dropped: count}. `keep`: anchors already decided by you (not planned again)."""
    st = normalise(settings if settings is not None else project.get("sound"))
    sents = _sentences(project)
    ctx = context(project, sents)
    zones = protected(project, sents, ctx)
    evs = [e for e in events(project, sents=sents, ctx=ctx) if st["kinds"].get(e["kind"], True) and e["anchor"] not in keep]
    lo, hi = SPEC["keep_above"]  # the priority a moment needs at density 0 and at density 1
    threshold = lo - (lo - hi) * st["density"]
    per_min = SPEC["per_minute"][0] + SPEC["per_minute"][1] * st["density"]
    silenced, chosen = [], []
    for e in evs:
        why = _quiet(e["t"], zones)
        if why in (SENSITIVE_TEXT, PICTURE) and e["kind"] in ("motion", "diagrams", "typing") and e["prio"] >= 0.6 and \
                any(c in ("click", "click-muted", "tick", "pop", "typewriter") for c in e["cats"]):
            # a graphic already on screen over a sensitive sentence (or drawn over such a picture): its reveals stay, softened
            # (muted clicks, quieter keys), so the graphic sounds the same from line to line
            e = {**e, "cats": ["keyboard"] if e["typed"] else ["click-muted"], "gain": e["gain"] - 5.0,
                 "reason": e["reason"] + f"; softened: {why}"}
        elif why and e["kind"] != "cta":
            silenced.append({"t": e["t"], "label": e["label"], "why": f"Silence: {why}."})
            continue
        if e["prio"] < threshold and e["kind"] != "cta":  # the subscribe animation has its own switch
            continue
        chosen.append(e)
    # one graphic sounds the same from line to line: softened in one place, softened throughout
    soft = {e["group"] for e in chosen if "softened" in e["reason"]}
    chosen = [e if (e["group"] not in soft or "softened" in e["reason"]) else
              {**e, "cats": ["keyboard"] if e["typed"] else ["click-muted"], "gain": e["gain"] - 5.0,
               "reason": e["reason"] + "; softened with the rest of this graphic"} for e in chosen]
    # spacing and overlaps, most important first
    chosen.sort(key=lambda e: -e["prio"])
    # v0.4.56: the sounds you already decided (edited, added or removed) are not planned again, but
    # they are there: nothing planned may crowd them (a removed sound leaves its moment silent)
    kept = [{"t": t, "typed": None, "kind": "held", "prio": 1.0, "_cat": cat, "_held": True, "_removed": removed}
            for t, cat, removed in held]
    seed = int(hashlib.sha1(str(project.get("id") or "").encode()).hexdigest()[:6], 16)
    last_used = {}  # sound id -> time last used
    group_sound = {}
    for e in chosen:
        if e["typed"]:
            kept.append(e)
            continue
        near = [k for k in kept if not k["typed"] and abs(k["t"] - e["t"]) < SPEC["spacing"]["any"]]
        if near:
            continue  # one sound at a time: the more important one is already there
        cat0 = e["cats"][0][0] if isinstance(e["cats"][0], (list, tuple)) else e["cats"][0]
        gap = SPEC["spacing"].get(cat0, 0.25)
        if gap > 0.5 and e["kind"] != "cta" and any(k.get("_cat") == cat0 and abs(k["t"] - e["t"]) < gap for k in kept):
            continue  # the same kind of sound too soon again
        window = [k for k in kept if not k["typed"] and k["kind"] != "cta" and not k.get("_removed") and abs(k["t"] - e["t"]) < 30]
        if e["kind"] != "cta" and len(window) >= per_min:
            continue  # density: at most this many a minute
        e["_cat"] = cat0
        kept.append(e)
    kept = sorted((k for k in kept if not k.get("_held")), key=lambda e: e["t"])
    # variations: related events share a sound; otherwise the least recently used one
    items = []
    for e in kept:
        if e["typed"]:
            fam = "keyboard" if (e["cats"] == ["keyboard"] or st["intensity"] < 0.3) else "typewriter"
            sid = _candidates(fam, st["intensity"])[0]
        elif e["group"] in group_sound:
            g = group_sound[e["group"]]
            g["n"] += 1
            sid = g["sids"][g["n"] % len(g["sids"])]
        else:
            pool = []
            for cat in e["cats"]:
                pool = _candidates(cat, st["intensity"])
                if pool:
                    break
            if not pool:
                continue
            if st["variation"]:
                rot = seed % len(pool)
                pool = pool[rot:] + pool[:rot]
                sid = min(pool, key=lambda s: last_used.get(s, -1e9))
            else:
                sid = pool[0]
            sibs = [x for x in _family(next((c for c in e["cats"] if _candidates(c, st["intensity"])), e["cats"][0])) if x != sid]
            group_sound[e["group"]] = {"sids": [sid] + (sibs if st["variation"] else []), "n": 0}
        last_used[sid] = e["t"]
        level = e["gain"] + (st["intensity"] - 0.4) * 8.0  # +-~5 dB around the designed level
        if not e["typed"] and e["group"] in group_sound and e["group"] != e["anchor"]:
            level += ACCENTS[group_sound[e["group"]]["n"] % len(ACCENTS)]
        items.append(_item({
            "anchor": e["anchor"], "kind": e["kind"], "sound": sid, "gain": round(level, 1), "source": "auto",
            "status": "approved" if st["mode"] == "auto" else "suggested", "reason": e["reason"], "label": e["label"],
        }))
    return items, {"kept": len(items), "silenced": silenced, "considered": len(evs)}


def effective(project):
    """The sounds that play: auto mode = a fresh plan, with your own sounds and edits kept and the
    ones you removed left out; manual mode = only the stored ones. ([item], decisions)."""
    st = normalise(project.get("sound"))
    stored = st["items"]
    if st["mode"] == "manual":
        return stored, {"kept": len(stored), "silenced": [], "considered": 0}
    mine = [it for it in stored if it["source"] == "manual" or it["edited"] or it["status"] == "removed"]
    fresh, info = plan(project, st, keep={it["anchor"] for it in mine}, held=_held(project, mine))
    return sorted(mine + fresh, key=lambda it: it["anchor"]), info


# ====================================================================== resolving times

def _anchor_times(project, mg=None):
    """{anchor: time} for every anchor that exists on the current timeline, and typed keys."""
    scenes = project.get("scenes") or []
    offsets, total = _offsets(scenes)
    times, typed = {}, {}
    for e in events(project, mg):
        times.setdefault(e["anchor"], e["t"])
        if e["typed"]:
            typed[e["anchor"]] = e["typed"]
    by_id = {str(s.get("id") or i): (i, s) for i, s in enumerate(scenes)}
    return times, typed, by_id, offsets, total


def _anchor_time(a, times, by_id, offsets):
    t = times.get(a)
    if t is None:
        m = re.fullmatch(r"(?:sc|mo):([^:]+):(-?[\d.]+)", a)
        if m and m[1] in by_id:
            t = offsets[by_id[m[1]][0]] + float(m[2])
        elif re.fullmatch(r"t:-?[\d.]+", a):
            t = float(a[2:])
    return t


def _held(project, items):
    """[(time, category, removed)] of decided sounds, for the planner's spacing. A planned sound you
    edited, moved or removed holds its original moment as the plan had it, so editing one sound never
    adds, drops or moves another: no second sound appears where it was, none disappears where it went."""
    if not items:
        return []
    times, _typed, by_id, offsets, _total = _anchor_times(project)
    cats = {}
    for e in events(project):
        cats.setdefault(e["anchor"], e["cats"][0])
    out = []
    for it in items:
        t = _anchor_time(it["anchor"], times, by_id, offsets)
        if t is None or it["kind"] == "typing":
            continue
        if it["source"] == "manual":
            cat = sfxlib.BY_ID[it["sound"]][1] if it["sound"] in sfxlib.BY_ID else "custom"
            out.append((t + it["offset"], cat, it["status"] == "removed"))
        else:
            # the category the plan chose for this moment (a replacement from another family changes nothing)
            c0 = cats.get(it["anchor"])
            cat = (c0[0] if isinstance(c0, (list, tuple)) else c0) or "custom"
            out.append((t, cat, False))
    return out


def resolve(project, data, items=None):
    """[{id, t, start, sound, file, sync, gain (linear, with the master), fade_in, fade_out, length,
    kind, label, keys}] for the sounds that play, and [(item, why)] for the ones left out."""
    st = normalise(project.get("sound"))
    if items is None:
        items, _ = effective(project)
    times, typed, by_id, offsets, total = _anchor_times(project)
    manifest = sfxlib.ensure(data, sorted({it["sound"] for it in items if it["sound"] in sfxlib.BY_ID}) or ["click-mech-1"])
    out, gone = [], []
    for it in items:
        if it["status"] != "approved":
            continue
        a = it["anchor"]
        t = _anchor_time(a, times, by_id, offsets)
        if t is None:
            gone.append((it, "what it followed is no longer on the timeline"))
            continue
        t = t + it["offset"] + st["lead"]
        if not (0 <= t <= total):
            gone.append((it, "it would fall outside the video"))
            continue
        info = custom_info(project, data, it["sound"]) if it["sound"].startswith("a:") else manifest.get(it["sound"])
        if not info:
            gone.append((it, "its sound file is missing"))
            continue
        gain = st["master"] * 10 ** (it["gain"] / 20)
        keys = None
        if a in typed:
            keys = _typing_keys(typed[a], it["sound"], it["offset"] + st["lead"], manifest, data)
        out.append({
            "id": it["id"], "t": round(t, 4), "start": round(t - info["sync"], 4), "sound": it["sound"],
            "sync": info["sync"], "seconds": info["seconds"], "gain": round(gain, 4), "fade_in": it["fade_in"],
            "fade_out": it["fade_out"], "length": it["length"], "kind": it["kind"], "label": it["label"], "keys": keys,
        })
    out.sort(key=lambda r: r["t"])
    return out, gone


def _typing_keys(chars, sound, shift, manifest, data):
    """Each typed character gets a key: the variations of the chosen family in turn (a space has
    its own), slightly different levels — like a real machine, never one loop."""
    fam = sfxlib.BY_ID[sound][1] if sound in sfxlib.BY_ID else "typewriter"
    keys = [c[0] for c in sfxlib.CATALOG if c[1] == fam and "space" not in c[0]] or [sound]
    space = next((c[0] for c in sfxlib.CATALOG if c[1] == fam and "space" in c[0]), keys[0])
    sfxlib.ensure(data, keys + [space])
    start = int(round((chars[0][0] if chars else 0) * 7)) % len(keys)  # v0.4.58 not every line the same keys
    out = []
    for k, (t, is_space) in enumerate(chars):
        sid = space if is_space else keys[(k * 5 + 2 + start) % len(keys)]
        out.append([round(t + shift, 4), sid, round(0.8 + 0.2 * (((k * 37) % 7) / 6), 3)])
    return out


# ====================================================================== your own sounds

_CUSTOM_LOCK = threading.Lock()


def custom_path(project, sound):
    import renderer

    aid = sound[2:]
    a = next((x for x in project.get("assets") or [] if x.get("id") == aid and (x.get("kind") == "audio" or x.get("has_audio"))), None)
    if not a:
        return None
    try:
        return renderer.asset_path(a)
    except (ValueError, OSError):
        return None


def custom_file(project, data, sound):
    """Your own sound decoded once to a 48 kHz stereo WAV (first 30 s), or None."""
    src = custom_path(project, sound)
    if not src:
        return None
    st = Path(src).stat()
    key = hashlib.sha1(f"{src}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:20]
    folder = Path(data) / "cache" / "sfx" / "custom"
    path = folder / f"{key}.wav"
    with _CUSTOM_LOCK:
        if not path.exists():
            folder.mkdir(parents=True, exist_ok=True)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(src), "-t", "30", "-ac", "2", "-ar", str(SR),
                                  "-f", "f32le", "-"], capture_output=True, check=True).stdout
            x = np.frombuffer(raw, dtype="<f4").reshape(-1, 2).T
            if not x.size:
                raise ValueError("this file has no sound")
            sfxlib._write(path, x)
    return path


def custom_audio(project, data, sound):
    """Your own sound decoded to 48 kHz stereo (cached by file), and its sync point; or (None, 0)."""
    path = custom_file(project, data, sound)
    if not path:
        return None, 0.0
    x = sfxlib.read_wav(path)
    env = np.convolve(np.max(np.abs(x), axis=0), np.ones(480) / 480, mode="same")
    sync = float(np.argmax(env > env.max() * 0.5)) / SR if env.size and env.max() > 0 else 0.0
    return x, round(sync, 4)


def custom_info(project, data, sound):
    try:
        x, sync = custom_audio(project, data, sound)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None
    if x is None:
        return None
    return {"sync": sync, "seconds": round(x.shape[1] / SR, 3)}


# ====================================================================== for the editor

def overview(project, data):
    """Everything the editor shows: the settings, each sound (including the ones you removed and
    the suggestions) with where it falls now, the moments left silent and why, and the protected
    passages. Cheap after the first call (the graphics' timings are cached)."""
    st = normalise(project.get("sound"))
    items, info = effective(project)
    trial = [dict(it, status="approved") for it in items]
    placed, gone = resolve(project, data, trial)
    at = {p["id"]: p for p in placed}
    why = {it["id"]: w for it, w in gone}
    out = []
    for it in items:
        p = at.get(it["id"])
        out.append({**it, "t": p["t"] if p else None, "start": p["start"] if p else None, "seconds": p["seconds"] if p else None,
                    "keys": p["keys"] if p else None, "level": round(20 * math.log10(max(1e-6, p["gain"])), 1) if p else None,
                    "gone": why.get(it["id"])})
    out.sort(key=lambda r: (r["t"] is None, r["t"] or 0))
    _, total = _offsets(project.get("scenes") or [])
    zones = [{"start": round(max(0.0, a), 3), "end": round(min(total, b), 3), "why": w} for a, b, w in protected(project)]
    return {"settings": {k: v for k, v in st.items() if k != "items"}, "items": out, "silenced": info["silenced"],
            "considered": info["considered"], "zones": zones, "total": round(total, 3)}


# ====================================================================== the stem

def _clip(x, knee=0.6):
    """Soft limit: untouched below the knee, never above 1 (no clipping, however many overlap)."""
    a = np.abs(x)
    over = a > knee
    if over.any():
        x = x.copy()
        x[over] = np.sign(x[over]) * (knee + (1 - knee) * np.tanh((a[over] - knee) / (1 - knee)))
    return x


def stem_hash(placed, total):
    return hashlib.sha1(json.dumps([sfxlib.LIB_VERSION, placed, round(total, 4)], sort_keys=True).encode()).hexdigest()[:20]


def stem(project, data, total, out_dir, cancelled=lambda: False):
    """Write the effects stem (FLAC, 48 kHz stereo) for the whole timeline. Returns
    (path or None, placed sounds, [(item, why)] left out). Cached by content."""
    placed, gone = resolve(project, data)
    if not placed:
        return None, placed, gone
    h = stem_hash(placed, total)
    cache = Path(data) / "cache" / "sfx" / "stems"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{h}.flac"
    if out.exists():
        out.touch()
        return out, placed, gone
    sounds = {}

    def audio(sid):
        if sid not in sounds:
            if sid.startswith("a:"):
                sounds[sid] = custom_audio(project, data, sid)[0]
            else:
                sounds[sid] = sfxlib.read_wav(sfxlib.path_of(data, sid))
        return sounds[sid]

    events_ = []  # (start sample, array [2, n] already with gain and fades)
    sync_of = {}
    for p in placed:
        if p["keys"]:
            for t, sid, g in p["keys"]:
                x = audio(sid)
                if sid not in sync_of:
                    sync_of[sid] = sfxlib.ensure(data, [sid])[sid]["sync"]
                events_.append((int(round((t - sync_of[sid]) * SR)), x * (p["gain"] * g)))
            continue
        x = audio(p["sound"])
        if x is None:
            continue
        if p["length"]:
            x = x[:, : max(1, int(p["length"] * SR))]
        x = x * p["gain"]
        n = x.shape[1]
        fi, fo = min(n, int(p["fade_in"] * SR)), min(n, int(p["fade_out"] * SR))
        if fi or fo or p["length"]:
            x = x.copy()
            if fi:
                x[:, :fi] *= np.linspace(0, 1, fi) ** 2
            fo = fo or (min(n, int(0.015 * SR)) if p["length"] else 0)
            if fo:
                x[:, n - fo:] *= np.linspace(1, 0, fo) ** 2
        events_.append((int(round(p["start"] * SR)), x))
    events_.sort(key=lambda e: e[0])
    N = int(math.ceil(total * SR))
    block = SR * 10
    tmp = out.with_suffix(f".{threading.get_ident()}.tmp.flac")
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                             "-c:a", "flac", "-compression_level", "1", str(tmp)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    ok = False
    try:
        first = 0
        for b0 in range(0, N, block):
            if cancelled():
                raise RuntimeError("Cancelled by you. No output was published.")
            b1 = min(N, b0 + block)
            buf = np.zeros((2, b1 - b0), dtype=np.float32)
            while first < len(events_) and events_[first][0] + events_[first][1].shape[1] < b0:
                first += 1
            for s, x in events_[first:]:
                if s >= b1:
                    break
                a, b = max(s, b0), min(s + x.shape[1], b1)
                if b > a:
                    buf[:, a - b0:b - b0] += x[:, a - s:b - s]
            proc.stdin.write(np.ascontiguousarray(_clip(buf).T, dtype="<f4").tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("FFmpeg could not write the sound effects: " + proc.stderr.read().decode(errors="replace")[-300:])
        tmp.replace(out)
        ok = True
    finally:
        if not ok:
            proc.kill()
            proc.wait()
            tmp.unlink(missing_ok=True)
    return out, placed, gone


def prune(data, keep=40):
    root = Path(data) / "cache" / "sfx" / "stems"
    if root.exists():
        files = sorted(root.glob("*.flac"), key=lambda f: f.stat().st_mtime)
        for f in files[:-keep]:
            f.unlink(missing_ok=True)


# ====================================================================== the preview's ducking

DUCK_RATE = 200  # values per second sent to the editor (5 ms, the compressor's attack time)
_DUCK_BUSY: dict = {}
_DUCK_FAILED: set = set()  # keys whose job failed: answered "none" instead of retried on every poll
_DUCK_LOCK = threading.Lock()
_DUCK_LATEST: dict = {}  # project id -> the key of its newest curve: an older job still running is stopped
_DUCK_PROC: dict = {}  # project id -> (key, the FFmpeg process making it)


def _low_priority():  # pragma: no cover - runs in the child
    try:
        os.nice(10)  # background work: the editor and an export come first
    except OSError:
        pass


VOICE_LEVEL = "aeval=(abs(val(0))+abs(val(1)))/2:c=mono"  # what the compressors detect (link=average)


def _duck_job(project):
    """v0.4.59 ({"bus": [...], "bus_key": .., "curve": [...]}, key): how the effects' (and music's)
    gain over time is computed exactly as the export applies it — FFmpeg's sidechaincompress with
    the export's settings, keyed by the export's own voice bus (renderer.voice_graph), compressing a
    constant 1.0, so its output IS the gain. None when the export would not duck.

    In two steps, so only a change of the timeline pays for the expensive one:
      bus   - the voice bus at narration level 100% (the export's loudnorm, scene cuts, soundbites),
              reduced to what a compressor with link=average detects, (|L| + |R|) / 2, and kept on
              disk (16-bit FLAC; two channels — narration, soundbites — when there are soundbites);
              keyed by the timeline and the source files only
      curve - the two compressors on that level, the narration volume applied to it (an exact
              scaling: the export applies the volume after the loudnorm, and to the narration
              only), a few seconds; keyed by the bus, the narration volume and the settings.
    The "{BUS}" in both commands is the cached file's path (duck_curve fills it in)."""
    import renderer

    import music as musiclib

    st = normalise(project.get("sound"))
    scenes = project.get("scenes") or []
    assets = {a.get("id"): a for a in project.get("assets") or []}
    narration = assets.get(project.get("narration_id"))
    # v0.4.58: the music's dip too (the export's music compressor), made in the same pass
    fx_ducks = st["enabled"] and st["duck"]
    music_ducks = bool(assets.get(project.get("music_id"))) and musiclib.normalise(project.get("music"))["duck"]
    if not (fx_ducks or music_ducks) or not scenes or not narration or not narration.get("has_audio", narration.get("kind") == "audio"):
        return None, None
    total = sum(round(float(sc["duration"]) * FPS) / FPS for sc in scenes)
    paths = [renderer.asset_path(narration)]
    inserts = {}
    for i, sc in enumerate(scenes):
        if sc.get("insert_audio"):
            clip = assets.get(sc.get("asset_id"))
            if not clip or not clip.get("has_audio"):
                return None, None  # the export refuses this project anyway
            inserts[i] = len(paths)
            paths.append(renderer.asset_path(clip))
    level = renderer.narration_volume(project)
    # the bus at 100% narration: the volume is not part of the timeline's analysis
    unit = {**project, "narration_volume": 1.0}
    graph = renderer.voice_graph(unit, scenes, total, 0, inserts, stems=True)
    two = any(g.endswith("[voicei]") for g in graph)
    fmt = "aformat=sample_fmts=flt:sample_rates=48000:channel_layouts=mono"
    if two:
        graph += [f"[voice]aresample=48000,{VOICE_LEVEL},{fmt}[ln]", f"[voicei]aresample=48000,{VOICE_LEVEL},{fmt}[li]",
                  "[ln][li]amerge=inputs=2[bus]"]
    else:
        graph += [f"[voice]aresample=48000,{VOICE_LEVEL},{fmt}[bus]"]
    bus = ["ffmpeg", "-v", "error", "-nostdin", "-y"]
    for path in paths:
        bus += ["-i", str(path)]
    bus += ["-filter_complex", ";".join(graph), "-map", "[bus]", "-c:a", "flac", "-sample_fmt", "s16",
            "-compression_level", "0", "-f", "flac", "{BUS}"]
    stamp = [(str(pth), pth.stat().st_size, int(pth.stat().st_mtime)) for pth in paths]
    bus_key = hashlib.sha1(json.dumps([graph, stamp, 2], sort_keys=True).encode()).hexdigest()[:20]
    d = SPEC["duck"]
    # the narration level scales the narration's part of the level (and the soundbites keep theirs)
    key_in = f"[0:a]pan=mono|c0={level:.6f}*c0+c1" if two else f"[0:a]volume={level:.6f}"
    curve = [
        f"{key_in},{fmt},asplit=2[k1][k2]",
        # a constant 1.0 (the compressors' output is then their gain): one 0.1 s block, looped
        f"aevalsrc=1:s=48000:d=0.1,aloop=loop=-1:size=4800,atrim=end_sample={round(total * 48000)},asplit=2[one][one2]",
        f"[one][k1]sidechaincompress=threshold={d['threshold']}:ratio={d['ratio']}:attack={d['attack']}:"
        f"release={d['release']}:makeup={d['makeup']},aresample=1000,{fmt.replace('48000', '1000')}[gf]",
        f"[one2][k2]{renderer.MUSIC_DUCK},aresample=1000,{fmt.replace('48000', '1000')}[gm]",
        "[gf][gm]amerge=inputs=2[g]",
    ]
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", "{BUS}", "-filter_complex", ";".join(curve), "-map", "[g]",
           "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    key = hashlib.sha1(json.dumps([bus_key, curve, DUCK_RATE], sort_keys=True).encode()).hexdigest()[:20]
    return {"bus": bus, "bus_key": bus_key, "curve": cmd}, key


BUS_KEEP = 4  # voice-bus analyses kept on disk (the latest used; a 25-minute one is ~50-100 MB)
_BUS_BUSY: dict = {}  # bus key -> threading.Event, set when that analysis is made (or given up)


def _register(pid, key, proc):
    """Make `proc` the project's running analysis and stop an obsolete one. False (and `proc`
    stopped) when this job is itself obsolete."""
    with _DUCK_LOCK:
        if _DUCK_LATEST.get(pid, key) != key:
            proc.kill()
            return False
        old = _DUCK_PROC.get(pid)
        if old and old[0] != key and old[1] is not proc:
            old[1].kill()
        _DUCK_PROC[pid] = (key, proc)
        return True


def _run(cmd, pid, key):
    """Run one FFmpeg step of the analysis: (stdout or None if it did not finish, superseded)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            preexec_fn=_low_priority if os.name == "posix" else None)
    if not _register(pid, key, proc):
        proc.communicate()
        return None, True
    try:
        raw, _ = proc.communicate(timeout=1800)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    with _DUCK_LOCK:
        superseded = _DUCK_LATEST.get(pid, key) != key
        if _DUCK_PROC.get(pid, (None, None))[1] is proc:
            _DUCK_PROC.pop(pid, None)
    if proc.returncode and not superseded:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return (raw if not proc.returncode else None), superseded


def _bus(job, folder, pid, key):
    """The voice-bus analysis of `job` on disk (made now, or by the job already making it): its
    path, or None when this job became obsolete meanwhile."""
    path = folder / f"bus-{job['bus_key']}.flac"
    while True:
        if path.exists():
            os.utime(path)  # recently used: kept
            return path
        with _DUCK_LOCK:
            ev = _BUS_BUSY.get(job["bus_key"])
            mine = ev is None
            if mine:
                ev = _BUS_BUSY[job["bus_key"]] = threading.Event()
        if not mine:  # e.g. the narration level moved while the timeline is analysed: wait for it
            while not ev.wait(0.25):
                with _DUCK_LOCK:
                    if _DUCK_LATEST.get(pid, key) != key:
                        return None
            if not path.exists():
                with _DUCK_LOCK:
                    if _DUCK_LATEST.get(pid, key) != key:
                        return None
            continue
        superseded = False
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / f"bus-{job['bus_key']}.{threading.get_ident()}.tmp"
            try:
                done, superseded = _run([str(tmp) if c == "{BUS}" else c for c in job["bus"]], pid, key)
                if done is not None and tmp.exists():
                    tmp.replace(path)  # finished (even if obsolete now: kept for an undo)
            finally:
                tmp.unlink(missing_ok=True)
            buses = sorted(folder.glob("bus-*.flac"), key=lambda q: q.stat().st_mtime)
            for q in buses[:-BUS_KEEP]:
                q.unlink(missing_ok=True)
        finally:
            with _DUCK_LOCK:
                _BUS_BUSY.pop(job["bus_key"], None)
            ev.set()
        if superseded:
            return None


def duck_curve(project, data, wait=False):
    """{"status": "none"} (no ducking: the effects play at their level), {"status": "working"}, or
    {"status": "ready", "rate": 200, "gain": [uint8 0..255 = gain 0..1, base64]}. Made in the background
    and cached: the voice bus by the timeline and its sources (narration file, scenes, soundbites),
    the curve by that and the narration volume and settings (see _duck_job)."""
    import base64

    try:
        job, key = _duck_job(project)
    except (ValueError, OSError, KeyError):
        return {"status": "none"}
    if not job:
        return {"status": "none"}
    folder = Path(data) / "cache" / "sfx" / "duck"
    path = folder / f"{key}.u8"
    mpath = folder / f"{key}.m.u8"  # v0.4.58: the music's dip
    if key in _DUCK_FAILED:
        return {"status": "none"}
    pid = str(project.get("id") or "")
    if path.exists() and mpath.exists():
        with _DUCK_LOCK:  # back to a timeline already made (undo): a job for another version is obsolete
            _DUCK_LATEST[pid] = key
            old = _DUCK_PROC.get(pid)
            if old and old[0] != key:
                old[1].kill()
        return {"status": "ready", "rate": DUCK_RATE, "key": key, "gain": base64.b64encode(path.read_bytes()).decode(),
                "music": base64.b64encode(mpath.read_bytes()).decode()}

    def run():
        superseded = False
        try:
            if isinstance(job, dict):
                bus = _bus(job, folder, pid, key)
                if bus is None:
                    superseded = True
                    return
                cmd = [str(bus) if c == "{BUS}" else c for c in job["curve"]]
            else:
                cmd = job  # one command writing the curve (tests)
            raw, superseded = _run(cmd, pid, key)
            if superseded:
                return
            both = np.frombuffer(raw, dtype="<f4")
            both = both[: len(both) // 2 * 2].reshape(-1, 2)
            step = 1000 // DUCK_RATE
            folder.mkdir(parents=True, exist_ok=True)
            for col, dest in ((0, path), (1, mpath)):
                g = both[:, col]
                g = g[: len(g) // step * step].reshape(-1, step).mean(axis=1) if len(g) >= step else g
                tmp = dest.with_suffix(".tmp")
                tmp.write_bytes(np.clip(np.round(g * 255), 0, 255).astype(np.uint8).tobytes())
                tmp.replace(dest)
            olds = sorted(folder.glob("*.u8"), key=lambda q: q.stat().st_mtime)
            for q in olds[:-40]:  # keep the latest 20 (two files each)
                q.unlink(missing_ok=True)
        except (subprocess.SubprocessError, OSError, ValueError):
            with _DUCK_LOCK:
                if not superseded:
                    _DUCK_FAILED.add(key)
        finally:
            with _DUCK_LOCK:
                _DUCK_BUSY.pop(key, None)

    with _DUCK_LOCK:
        _DUCK_LATEST[pid] = key
        thread = _DUCK_BUSY.get(key)
        if thread is None:
            thread = threading.Thread(target=run, daemon=True, name="sfx-duck")
            _DUCK_BUSY[key] = thread
            thread.start()
    if wait:
        thread.join()
        return duck_curve(project, data) if path.exists() and mpath.exists() else {"status": "none"}
    return {"status": "working", "key": key}


def mix_filters(sfx_index, total, voice_label, duck):
    """FFmpeg filters for the effects: [fx] at full timeline length, ducked under `voice_label` (a
    copy of the voice made for this) when there is a voice and ducking is on."""
    d = SPEC["duck"]
    f = [f"[{sfx_index}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,apad,atrim=duration={total}[fxr]"]
    if voice_label and duck:
        f.append(f"[fxr]{voice_label}sidechaincompress=threshold={d['threshold']}:ratio={d['ratio']}:attack={d['attack']}:"
                 f"release={d['release']}:makeup={d['makeup']}[fx]")
    else:
        f.append("[fxr]anull[fx]")
    return f
