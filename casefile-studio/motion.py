"""Motion graphics (v0.4.52): cinematic, narration-synchronised kinetic typography.

`project["motion"] = {"enabled": False, "items": [item, ...]}`, an item:

    {id, template: findings|timeline|contrast|legal, status: suggested|draft|approved,
     start, end (seconds on the timeline), heading, title, layout,
     lines: [{text, label, kind, emphasis, at (seconds on the timeline)}],
     background: charcoal|footage|still|photo, photo_id, still_at, dim, font, size, accent, text_color,
     align, x, y, speed, enter, exit, hide_captions, source: auto|manual, reason}

* A separate layer over the picture: scenes, clips, narration and soundbites are never changed;
  removing a graphic (or switching motion graphics off) shows the original picture again.
* Every frame is drawn here with Pillow (bundled Oswald font), at 24 fps. The export overlays each
  graphic as one transparent video (QuickTime Animation, lossless; v0.4.53, before: PNG frames);
  the editor shows the same frames, smaller, as WebP. Frames that are identical (nothing moving)
  are drawn once; everything is cached by content.
* v0.4.53: more layouts per template (and a second graphic of a template gets another one), the
  case's legal outcome near the end (recapping the steps already told), chapter titles weigh in,
  a still from your own footage as the background.
* The text only comes from the narration (or what you type): nothing is invented. Each line
  appears when the narrator says the word it starts with (episode word timings, else captions).
* Only approved graphics are exported, and only while motion graphics are switched on.
"""
from __future__ import annotations

import copy
import bisect
import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import effects

SPEC = effects.SPEC["motion"]
FPS = SPEC["fps"]
TEMPLATES = {t["id"]: t for t in SPEC["templates"]}
LIM = SPEC["limits"]
DEF = SPEC["defaults"]
TIM = SPEC["timing"]
ENGINE = 3  # bump when the drawing changes: cached frames are made again
FONT_DIR = Path(__file__).resolve().parent / "web" / "assets" / "fonts"
FONTS = {
    "oswald": ("Oswald-Bold.ttf", "Oswald-Medium.ttf", "Oswald-Regular.ttf"),
    "inter": ("Inter-Black.otf", "Inter-Bold.otf", "Inter-Bold.otf"),
    "dejavu": ("DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"),
}
MUTED = 0.72  # body text that is not emphasised
RECAP_STEP = 0.7  # seconds between the legal steps a graphic recaps


# ====================================================================== the data

def _num(v, lo, hi, default):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return default if not math.isfinite(n) else max(lo, min(hi, n))


def _choice(v, options, default):
    ids = [o[0] if isinstance(o, list) else o for o in options]
    return v if v in ids else default


def _text(v, n):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _color(v, default):
    return v.lower() if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default


def normalise_item(it, n=0, image_assets=None):
    if not isinstance(it, dict) or it.get("template") not in TEMPLATES:
        return None
    start = round(_num(it.get("start"), 0.0, 86400.0, 0.0), 3)
    lo, hi = LIM["length"]
    end = round(_num(it.get("end"), start + lo, start + hi, start + 8.0), 3)
    tpl = it["template"]
    lines = []
    for ln in (it.get("lines") or [])[: TEMPLATES[tpl]["max_lines"]]:
        if not isinstance(ln, dict):
            continue
        text = _text(ln.get("text"), LIM["text"])
        if not text:
            continue
        lines.append({
            "text": text,
            "label": _text(ln.get("label"), LIM["label"]),
            "kind": _choice(ln.get("kind"), SPEC["contrast_kinds"], "statement") if tpl == "contrast" else "",
            "emphasis": ln.get("emphasis") is True,
            "at": round(_num(ln.get("at"), start, end, start), 3),
        })
    bg = _choice(it.get("background"), SPEC["backgrounds"], DEF["background"])
    photo = str(it.get("photo_id") or "")
    if bg == "photo" and (not photo or (image_assets is not None and photo not in image_assets)):
        bg, photo = "charcoal", ""
    return {
        "id": re.sub(r"[^\w-]", "", str(it.get("id") or ""))[:24] or f"mg{n + 1}",
        "template": tpl,
        "status": it.get("status") if it.get("status") in ("suggested", "draft", "approved") else "draft",
        "start": start,
        "end": end,
        "heading": _text(it.get("heading"), LIM["heading"]),
        "title": _text(it.get("title"), LIM["title"]),
        "layout": _choice(it.get("layout"), SPEC["layouts"][tpl], "auto"),
        "lines": lines,
        "background": bg,
        "photo_id": photo if bg == "photo" else "",
        "still_at": round(_num(it.get("still_at"), 0.0, 86400.0, start), 3),  # v0.4.53: the footage moment
        "dim": round(_num(it.get("dim"), *LIM["dim"], DEF["dim"]), 2),
        "font": _choice(it.get("font"), SPEC["fonts"], DEF["font"]),
        "size": round(_num(it.get("size"), *LIM["size"], DEF["size"]), 2),
        "accent": _color(it.get("accent"), DEF["accent"]),
        "text_color": _color(it.get("text_color"), DEF["text_color"]),
        "align": "center" if it.get("align") == "center" else "left",
        "x": round(_num(it.get("x"), *LIM["xy"], 0.0), 3),
        "y": round(_num(it.get("y"), *LIM["xy"], 0.0), 3),
        "speed": round(_num(it.get("speed"), *LIM["speed"], DEF["speed"]), 2),
        "enter": _choice(it.get("enter"), SPEC["enters"], DEF["enter"]),
        "exit": _choice(it.get("exit"), SPEC["exits"], DEF["exit"]),
        "hide_captions": it.get("hide_captions") is not False,
        "source": "auto" if it.get("source") == "auto" else "manual",
        "reason": _text(it.get("reason"), 240),
    }


def normalise(value, image_assets=None):
    value = value if isinstance(value, dict) else {}
    items = []
    seen = set()
    for n, it in enumerate((value.get("items") or [])[: LIM["items"]]):
        x = normalise_item(it, n, image_assets)
        if x and x["id"] not in seen:
            seen.add(x["id"])
            items.append(x)
    items.sort(key=lambda x: x["start"])
    return {"enabled": value.get("enabled") is True, "items": items}


def exported(project):
    """The graphics that go into the video: approved ones, while motion graphics are on."""
    m = normalise(project.get("motion"))
    return [x for x in m["items"] if x["status"] == "approved"] if m["enabled"] else []


def caption_gaps(project):
    """[(start, end)] on the timeline where an exported graphic hides the captions."""
    return [(x["start"], x["end"]) for x in exported(project) if x["hide_captions"]]


# ====================================================================== the narration on the timeline

def scene_offsets(scenes):
    out, t = [], 0.0
    for s in scenes:
        out.append(t)
        t += max(1, round(float(s.get("duration") or 0) * FPS)) / FPS
    return out, t


def _norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def timeline_words(project):
    """Every narrated word with its time on the timeline: [{w, t, e, scene}].
    Guide projects: the episode word clock (exact); otherwise each caption's words spread over
    the caption; otherwise the scene's narration spread over the scene."""
    import difflib

    scenes = project.get("scenes") or []
    offsets, _ = scene_offsets(scenes)
    timing = ((project.get("episode") or {}).get("timings") or {}).get("words") or []
    out = []
    for i, s in enumerate(scenes):
        if s.get("insert_audio"):
            continue  # a soundbite: not narration
        dur = max(1, round(float(s.get("duration") or 0) * FPS)) / FPS
        tokens = str(s.get("narration") or "").split()
        if not tokens:
            continue
        timed = []
        a0 = s.get("audio_start")
        if timing and a0 is not None:
            a0 = float(a0)
            a1 = a0 + float(s.get("audio_duration") or dur)
            timed = [w for w in timing if a0 - 1e-6 <= float(w["start"]) < a1 - 1e-6]
            timed = [(offsets[i] + float(w["start"]) - a0, offsets[i] + float(w["end"]) - a0, _norm(w.get("normalized") or w.get("word") or "")) for w in timed]
        if not timed and s.get("captions"):
            for c in s["captions"]:
                ws = str(c.get("text") or "").split()
                c0, c1 = float(c["start"]), float(c["end"])
                for j, w in enumerate(ws):
                    timed.append((offsets[i] + c0 + (c1 - c0) * j / len(ws), offsets[i] + c0 + (c1 - c0) * (j + 1) / len(ws), _norm(w)))
        if not timed:
            timed = [(offsets[i] + dur * j / len(tokens), offsets[i] + dur * (j + 1) / len(tokens), _norm(w)) for j, w in enumerate(tokens)]
        # the script's words (with punctuation) take the times of the timed words they match
        times = [None] * len(tokens)
        sm = difflib.SequenceMatcher(a=[_norm(w) for w in tokens], b=[x[2] for x in timed], autojunk=False)
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                times[blk.a + k] = timed[blk.b + k][:2]
        known = [k for k, v in enumerate(times) if v]
        for k in range(len(tokens)):
            if times[k] is None:
                prev = max((j for j in known if j < k), default=None)
                nxt = min((j for j in known if j > k), default=None)
                t0 = times[prev][1] if prev is not None else offsets[i]
                t1 = times[nxt][0] if nxt is not None else offsets[i] + dur
                span = (nxt if nxt is not None else len(tokens)) - (prev if prev is not None else -1)
                pos = k - (prev if prev is not None else -1)
                t = t0 + (t1 - t0) * (pos - 1) / max(1, span - 1) if span > 1 else t0
                times[k] = (t, t + 0.25)
        for w, (t0, t1) in zip(tokens, times):
            out.append({"w": w, "t": round(t0, 3), "e": round(t1, 3), "scene": i})
    return out


def sentences(words):
    """Group words into sentences: [{text, t, e, words}]."""
    out, cur = [], []
    for k, w in enumerate(words):
        cur.append(w)
        if not re.search(r"[.!?][\"'”’)]*$", w["w"]):
            continue
        nxt = words[k + 1]["w"] if k + 1 < len(words) else ""
        if re.fullmatch(r"(?i)(mr|mrs|ms|dr|st|jr|sr|no|vs|u\.s|[a-z])\.", w["w"]):
            continue
        if re.fullmatch(r"(?i)[ap]\.m\.", w["w"]) and not (nxt[:1].isupper() and not re.match(MONTH + r"$|(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day", nxt)):
            continue  # "at 3 p.m. on Friday" goes on; "at 3:27 p.m. Trial reporting said" is a new sentence
        out.append(cur)
        cur = []
    if cur:
        out.append(cur)
    return [{"text": " ".join(x["w"] for x in s), "t": s[0]["t"], "e": s[-1]["e"], "words": s, "scene": s[0]["scene"]} for s in out]


def passage(project, start, end):
    words = [w for w in timeline_words(project) if start - 1e-6 <= w["t"] < end]
    return sentences(words)


# ====================================================================== reading the narration

MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
DATE = re.compile(
    rf"\b(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?(?:{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+(?:19|20)\d\d)?|{MONTH}\s+(?:19|20)\d\d|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH}(?:,?\s+(?:19|20)\d\d)?|(?:in|by|until|since)\s+(?:19|20)\d\d|(?:early|late|mid)[- ]{MONTH}|{MONTH}(?=\s*,))"
    rf"|\b\d{{1,2}}(?::\d\d)?\s*[ap]\.m\.|\b\d{{1,2}}:\d\d\s*[ap]m\b|(?<=\b[Aa]t\s)\d{{1,2}}:\d\d\b|\b(?:about|around|by|until|before|after)\s+\d{{1,2}}:\d\d\b",
    re.I,
)
LEGAL = [  # (label, pattern), most specific first
    ("PLEA", r"plead(?:ed|s)?\s+(?:not\s+)?guilty|plea\s+(?:deal|agreement|of)|pleaded\s+no\s+contest"),
    ("ACQUITTED", r"acquitt|found\s+not\s+guilty|not\s+guilty\s+verdict"),
    ("CONVICTED", r"convict|found\s+(?:him|her|them|\w+)?\s*guilty|guilty\s+verdict|jury\s+(?:found|returned)"),
    ("SENTENCED", r"sentenc|life\s+in\s+prison|years\s+in\s+(?:state\s+)?prison|probation"),
    ("DISMISSED", r"dismiss|charges?\s+(?:were\s+)?dropped|dropped\s+(?:the\s+)?charges?"),
    ("CHARGED", r"charged|indict|faces?\s+(?:a\s+)?charges?|\bcounts?\s+of|booked\s+on"),
    ("ARRESTED", r"\barrest"),
    ("ALLEGED", r"alleg|accus|suspected\s+of"),
]
STATED = r"\b(?:told\s+(?:police|detectives|investigators|officers|deputies|reporters|a\s+\w+)|claimed|claims|insisted|maintained|denied|alibi|his\s+account|her\s+account|their\s+account|version\s+of\s+events|(?:he|she|they)\s+said)\b"
FOUND = r"\b(?:records?|footage|video|data|evidence|showed|shows|revealed|forensic\w*|dna|autopsy|phone|cell|gps|receipts?|timestamps?)\b"
CONTRADICT = r"\b(?:but|however|instead|in\s+fact|contradict\w*|inconsisten\w*|did\s+not\s+match|didn't\s+match|no\s+evidence|never|discrepanc\w*|conflict\w*)\b"
COURT = r"\b(?:argu\w*|prosecut\w*|defen[cs]e|jur(?:y|ors?)|testif\w*|testimony|closing|opening\s+statement|cross-exam\w*|attorney|lawyer|counsel|judge)\b"
FIND = r"\b(?:evidence|records?|video|footage|surveillance|phone|cell|data|dna|autopsy|report|detectives?|investigators?|found|discovered|revealed|showed|warrant|search(?:ed)?|forensic\w*|fingerprints?|ballistics?|camera|messages?|location|witness(?:es)?|tip)\b"
EMOTION = r"\b(?:mother|father|mom|dad|grandmother|grandfather|family|families|loved|love|remember\w*|funeral|vigil|tribute|heart\w*|tears?|grief|griev\w*|mourn\w*|smile|dream\w*|miss(?:es|ed)?\s+(?:him|her)|beloved|memorial|sobb\w*|wept|cried|cry)\b"
LEAD = re.compile(r"^(?:and|but|so|then|now|still|yet|also)\s+", re.I)

# v0.4.53: what a chapter is about, from its title (the order matters: the first match wins)
CHAPTER_KINDS = [
    ("opening", r"hook|cold\s+open|opening|setting\s+the\s+scene|teaser|prologue"),
    ("victim", r"remember|who\s+was|in\s+memory|tribute|legacy|life\s+of|people\s+around|famil(?:y|ies)|mother|father|childhood|growing\s+up"),
    ("closing", r"closing|epilogue|final\s+thoughts|conclusion|outro"),
    ("legal", r"trial|sentenc|verdict|court|plea|prosecut|charges?\b|hearing|detention|convict|appeal|justice"),
    ("statements", r"interrogat|interview|statement|alibi|accounts?\b|stor(?:y|ies)\b|confess|\blies\b|lying|version"),
    ("investigation", r"evidence|surveillance|digital|investigat|search|forensic|clue|records?\b|discover|autopsy|\bdna\b|phone|camera|video|footage|tips?\b|leads?\b|manhunt"),
    ("chronology", r"night|\bday\b|timeline|hours|last\s+seen|disappear|vanish|morning|evening|weekend|minutes|countdown"),
]
STAGES = ["ALLEGED", "ARRESTED", "CHARGED", "PLEA", "VERDICT", "CONVICTED", "ACQUITTED", "DISMISSED", "SENTENCED"]
# an outcome actually told (not asked for, faced or argued): these can anchor a legal graphic
OUTCOME = [
    ("PLEA", r"\bple(?:aded|d)\s+guilty|\bpleaded\s+no\s+contest|\baccepted\s+a\s+plea"),
    ("ACQUITTED", r"\bacquitted\b|\bfound\s+(?:\w+\s+){0,2}not\s+guilty"),
    ("CONVICTED", r"\bwas\s+convicted|\bwere\s+convicted|\bconvicted\s+(?!felon)\w+\s+of\b|\bfound\s+(?:\w+\s+){0,2}guilty|\bguilty\s+verdict"),
    ("SENTENCED", r"\bsentenced\s+(?:\w+[-\w]*\s+){0,3}to\b|\bwas\s+sentenced\b|\bwere\s+sentenced\b"),
    ("DISMISSED", r"\bcharges?\s+(?:were|was)\s+(?:dismissed|dropped)|\bdismissed\s+the\s+(?:case|charges?)|\bdropped\s+the\s+charges?"),
]
# the earlier steps a legal outcome recaps (strict: an arrest made, a charge brought)
MILESTONE = [
    ("CHARGED", r"\bcharged\s+(?:\w+\s+){0,3}(?:with|as\s+an\s+adult)\b|\bindicted\b|\bannounced\s+(?:a\s+|the\s+)?[\w\s-]{0,40}\bcharges?\b"),
    ("ARRESTED", r"\b(?:police|officers|deputies|detectives|marshals|authorities|agents|department)\b[^;]{0,140}?\barrested\s+\w|\b(?:was|were)\s+arrested\b"),
]
HYPOTHETICAL = r"\b(?:faced?|faces|facing|could|would|might|asked|sought|seek\w*|request\w*|recommend\w*|argu\w*|urged|hoped|expected|possible|possibility)\b|\?"


def chapter_kind(chapter):
    """opening | victim | closing | legal | statements | investigation | chronology | general."""
    c = str(chapter or "")
    c = re.sub(r"(?i)^\s*(?:chapter|part|act)\s+\w+\s*[—–:-]\s*", "", c)
    for kind, pat in CHAPTER_KINDS:
        if re.search(pat, c, re.I):
            return kind
    return "chronology" if DATE.search(c) else "general"


def _outcome(text):
    """(label, character index) of a legal outcome told in this sentence, else None."""
    if re.search(HYPOTHETICAL, text, re.I):
        return None
    for lab, pat in OUTCOME:
        m = re.search(pat, text, re.I)
        if m:
            return lab, m.start()
    return None


def _milestones(project, before, have):
    """Legal steps told earlier in the narration (outside the cold open): the latest earlier
    outcome of each kind, the first charge (or the first arrest when no charge was told)."""
    scenes = project.get("scenes") or []
    got = {}
    for s in sentences(timeline_words(project)):
        if s["e"] > before + 1e-6:
            break
        if scenes and chapter_kind(scenes[s["scene"]].get("chapter")) in ("opening", "victim"):
            continue
        if len(s["text"]) > LIM["text"] or re.search(EMOTION, s["text"], re.I):
            continue  # it would have to be cut; or it is about the family
        hit = _outcome(s["text"])
        if hit:
            got[hit[0]] = s  # the latest
            continue
        if re.search(HYPOTHETICAL, s["text"], re.I):
            continue
        for lab, pat in MILESTONE:
            if re.search(pat, s["text"], re.I):
                got.setdefault(lab, s)  # the first
                break
    if "CHARGED" in got or "CHARGED" in have:
        got.pop("ARRESTED", None)
    return {k: v for k, v in got.items() if k not in have}


def _clean_line(text, n=LIM["text"]):
    t = LEAD.sub("", text.strip())
    t = re.sub(r"\s*\[[^\]]*\]\([^)]*\)", "", t)  # source links
    t = t.rstrip(" ;:,")
    if t.endswith(".") and not re.search(r"(?i)\b(?:[ap]\.m|u\.s|jr|sr|st|[a-z])\.$", t):
        t = t[:-1]
    if t:
        t = t[0].upper() + t[1:]
    if len(t) > n:
        cut = max(t.rfind(", ", 0, n), t.rfind("; ", 0, n), t.rfind(" — ", 0, n))
        t = (t[:cut] if cut > n * 0.5 else t[:n].rsplit(" ", 1)[0]) + "…"
    return t


def _word_time(sent, char_index):
    """The time of the word at character `char_index` of the sentence text."""
    pos = 0
    for w in sent["words"]:
        if pos + len(w["w"]) >= char_index:
            return w["t"]
        pos += len(w["w"]) + 1
    return sent["t"]


def _chapter_parts(chapter):
    c = str(chapter or "").strip()
    m = re.match(r"(?i)^\s*(chapter\s+\d+|part\s+\d+|act\s+\w+)\s*[—–:-]\s*(.+)$", c)
    if m:
        return m[1].upper(), m[2].strip().upper()
    return "", c.upper() if c and not re.search(r"(?i)hook|opening|cold open", c) else ""


def draft(project, template, start, end, item_id=None, source="manual", reason=""):
    """An item for this passage, made only from the narration's own words. None when the
    passage has no narration."""
    sents = [s for s in passage(project, start, end) if s["text"].strip()]
    if not sents or template not in TEMPLATES:
        return None
    scenes = project.get("scenes") or []
    chapter = scenes[sents[0]["scene"]].get("chapter") if scenes else ""
    label, subtitle = _chapter_parts(chapter)
    tpl = TEMPLATES[template]
    lines = []
    if template == "timeline":
        for s in sents:
            m = DATE.search(s["text"])
            if not m:
                continue
            # the date is lifted out only when it opens the sentence ("On December 9, he escaped");
            # anywhere else the sentence stays word for word
            lead = s["text"][: m.start()]
            if re.fullmatch(r"\s*(?:(?:and|then|but|by|on|in|at|around|about|shortly\s+after|just\s+after|before|after)\s+)?", lead, re.I):
                rest = re.sub(r"^[\s,]+", "", s["text"][m.end():])
            else:
                rest = s["text"]
            when = re.sub(r"^(?:AT|ABOUT|AROUND|BY|UNTIL|BEFORE|AFTER|IN|SINCE)\s+", "", m[0].strip(" ,").upper())
            rng = re.search(r"(?i)\bbetween\s+(\d{1,2}(?::\d\d)?)\s*(?:[ap]\.m\.\s*)?and\s+(\d{1,2}(?::\d\d)?\s*[ap]\.m\.)", s["text"])
            if rng:
                when = f"{rng[1]}–{rng[2]}".upper()
            prev_ampm = re.search(r"[AP]\.M\.$", lines[-1]["label"]) if lines else None
            if re.fullmatch(r"\d{1,2}:\d\d", when) and prev_ampm:
                when += " " + prev_ampm[0]  # "At 3:36" after "3:33 p.m." is in the afternoon too
            lines.append({"label": when, "text": _clean_line(rest), "at": s["t"]})
        if len(lines) < 2:
            lines = [{"label": "", "text": _clean_line(s["text"]), "at": s["t"]} for s in sents]
    elif template == "legal":
        told = [(_outcome(s["text"]), s) for s in sents]
        if any(h for h, _ in told):
            # v0.4.53: a legal outcome: it is shown when it is said, after the steps that led to it
            # (already told earlier in the narration, so nothing is given away), each with its tag
            for h, s in told:
                if h:
                    lines.append({"label": h[0], "text": _clean_line(s["text"]), "at": _word_time(s, h[1])})
                    continue
                for lab, pat in MILESTONE:
                    m = re.search(pat, s["text"], re.I)
                    if m and not re.search(HYPOTHETICAL, s["text"], re.I):
                        lines.append({"label": lab, "text": _clean_line(s["text"]), "at": _word_time(s, m.start())})
                        break
            earlier = _milestones(project, sents[0]["t"], {x["label"] for x in lines})
            recap = [{"label": lab, "text": _clean_line(s["text"]), "at": None} for lab, s in earlier.items()]
            lines = sorted(recap, key=lambda x: STAGES.index(x["label"])) + lines
            lines = lines[-tpl["max_lines"]:]  # the outcome stays
        else:
            for s in sents:
                for lab, pat in LEGAL:
                    m = re.search(pat, s["text"], re.I)
                    if m:
                        lines.append({"label": lab, "text": _clean_line(s["text"]), "at": _word_time(s, m.start())})
                        break
        if not lines:
            lines = [{"label": "", "text": _clean_line(s["text"]), "at": s["t"]} for s in sents]
    elif template == "contrast":
        for s in sents:
            found = bool(re.search(FOUND, s["text"], re.I)) and not re.search(STATED, s["text"], re.I)
            lines.append({"kind": "finding" if found else "statement", "label": "",
                          "text": _clean_line(s["text"]), "at": s["t"],
                          "emphasis": bool(found and re.search(CONTRADICT, s["text"], re.I))})
    else:
        lines = [{"text": _clean_line(s["text"]), "at": s["t"]} for s in sents]
    lines = lines[: tpl["max_lines"]]
    recap = [x for x in lines if x["at"] is None]
    first = min(x["at"] for x in lines if x["at"] is not None)
    intro = TIM["intro_end"]
    begin = max(0.0, min(start, first - intro - RECAP_STEP * len(recap) - (0.6 if recap else 0)))
    for k, x in enumerate(recap):  # the steps already told come in one after another, then the outcome
        x["at"] = round(begin + intro + RECAP_STEP * k, 3)
    last_end = max(s["e"] for s in sents)
    item = {
        "id": item_id or "mg" + hashlib.sha1(f"{template}{start}{end}{time.time()}".encode()).hexdigest()[:10],
        "template": template,
        "status": "suggested" if source == "auto" else "draft",
        "start": round(begin, 3),
        "end": round(max(last_end + TIM["hold"], begin + LIM["length"][0]), 3),
        "heading": (label + " · " if label else "") + tpl["heading"] if template != "contrast" else tpl["heading"],
        "title": subtitle or _clean_line(sents[0]["text"], 70).upper(),
        "lines": lines,
        "source": source,
        "reason": reason,
    }
    return normalise_item(item)


# ====================================================================== suggestions (the whole documentary)

def _flags(project):
    """Per scene: is it a place no graphic should go? (soundbites, CTA, cold open, closing)."""
    import cta

    scenes = project.get("scenes") or []
    offsets, total = scene_offsets(scenes)
    blocked = []
    for i, s in enumerate(scenes):
        a, b = offsets[i], offsets[i] + max(1, round(float(s.get("duration") or 0) * FPS)) / FPS
        if s.get("insert_audio") or s.get("audio_break"):
            blocked.append((a - 1.0, b + 1.0, "a soundbite"))
        kind = chapter_kind(s.get("chapter"))
        if kind == "opening":
            blocked.append((a, b, "the cold open"))
        elif kind == "victim":  # v0.4.53: who the victim was, the family, remembrance
            blocked.append((a, b, "a chapter about the victim and family"))
        elif kind == "closing":
            blocked.append((a, b, "the closing"))
    try:
        for ev in cta.events(project):
            blocked.append((ev[0] - 2.0, ev[1] + 2.0, "the subscribe animation"))
    except Exception:  # pragma: no cover - the CTA is optional
        pass
    sp = SPEC["suggest"]
    blocked.append((0.0, total * sp["edge_start"], "the opening"))
    blocked.append((total * (1 - sp["edge_end"]), total + 1, "the closing"))
    return blocked, total


def suggest(project, existing=()):
    """Read the whole narration chapter by chapter and propose graphics where they help the story:
    chronology (several dated events), the investigation (several findings), contradictions (what
    was said against what was found) and legal outcomes. What a chapter is about (its title) weighs
    in. Never in the cold open, soundbites, emotional passages, chapters about the victim and family,
    or CTA places; the closing only for the case's legal outcome. Returns [item]; can be empty."""
    words = timeline_words(project)
    if not words:
        return []
    sents = sentences(words)
    scenes = project.get("scenes") or []
    blocked, total = _flags(project)
    hard = [x for x in blocked if x[2] != "the closing"]  # the legal outcome may go near the end
    taken = [(x["start"], x["end"]) for x in existing]
    sp = SPEC["suggest"]
    lo, hi = sp["window"]

    def chapter(s):
        return str(scenes[s["scene"]].get("chapter") or "") if scenes else ""

    def free(a, b, rules=blocked):
        return not any(a < y and b > x for x, y, _ in rules)

    # consecutive narration with no soundbite between (a soundbite splits the narration)
    runs, cur = [], []
    for s in sents:
        if cur and (chapter(s) != chapter(cur[-1]) or s["t"] - cur[-1]["e"] > 1.2 or not free(cur[-1]["e"], s["t"])):
            runs.append(cur)
            cur = []
        cur.append(s)
    if cur:
        runs.append(cur)
    cands = []  # (score, template, start, end, chapter, why, ready item or None)
    for run in runs:
        for i in range(len(run)):
            for j in range(i + 2, min(len(run), i + 7) + 1):
                win = run[i:j]
                a, b = win[0]["t"], win[-1]["e"]
                if not (lo <= b - a <= hi) or not free(a - TIM["lead"], b + TIM["hold"]):
                    continue
                text = " ".join(s["text"] for s in win)
                if max(len(s["text"]) for s in win) > LIM["text"]:
                    continue  # a line would have to be cut: a graphic would change what was said
                if re.search(EMOTION, text, re.I) or text.rstrip().endswith(":"):
                    continue  # family, victims, tributes; or introducing someone who speaks next
                ch = chapter(win[0])
                kind = chapter_kind(ch)
                pos = a / max(1.0, total)
                dated = [s for s in win if DATE.search(s["text"])]
                legal = {lab for s in win for lab, pat in LEGAL if re.search(pat, s["text"], re.I)}
                stated = [s for s in win if re.search(STATED, s["text"], re.I)]
                found = [s for s in win if re.search(FOUND, s["text"], re.I) and s not in stated]
                courtroom = re.search(COURT, text, re.I)  # arguments in court are never shown as findings
                finds = [s for s in win if len(re.findall(FIND, s["text"], re.I)) >= 1]
                opts = []
                if len(dated) >= 3:
                    opts.append(("timeline", 2.2 * len(dated) + (1.5 if 0.2 <= pos <= 0.6 else 0) + (2.5 if kind == "chronology" else 0),
                                 f"{len(dated)} dated events in {b - a:.0f} s"))
                if len(legal - {"ARRESTED", "ALLEGED"}) >= 2 or (len(legal) >= 2 and kind == "legal"):
                    opts.append(("legal", 2.5 * len(legal) + (2 if pos >= 0.6 else 0) + (2 if kind == "legal" else 0),
                                 f"{', '.join(sorted(legal)).lower()} in the narration"))
                if stated and found and not courtroom and re.search(CONTRADICT, " ".join(s["text"] for s in found), re.I):
                    opts.append(("contrast", 6.0 + 1.5 * min(len(stated), len(found)) + (1.5 if 0.45 <= pos <= 0.85 else 0) + (2.5 if kind == "statements" else 0),
                                 f"{len(stated)} statement(s) set against {len(found)} finding(s)"))
                if len(finds) >= 3:
                    opts.append(("findings", 1.6 * len(finds) + (2 if kind == "investigation" else 0) + (1 if 0.35 <= pos <= 0.8 else 0) - (2 if kind == "legal" else 0),
                                 f"{len(finds)} investigative findings in {b - a:.0f} s"))
                for tpl, score, why in opts:
                    if score >= 6.0:
                        cands.append((score, tpl, a, b, ch, why, None))
    cands += _outcome_candidates(project, sents, scenes, hard, free, chapter)
    cands.sort(key=lambda c: -c[0])
    chosen = []
    for c in cands:
        score, tpl, a, b = c[:4]
        s0, s1 = a - TIM["lead"], b + TIM["hold"]
        if any(s0 < y + sp["min_gap"] and s1 > x - sp["min_gap"] for x, y in taken + [(o[2], o[3]) for o in chosen]):
            continue
        if sum(1 for o in chosen if o[1] == tpl) >= 2:
            continue  # vary the templates
        chosen.append(c)
        if len(chosen) >= sp["max"]:
            break
    out = []
    for score, tpl, a, b, ch, why, ready in sorted(chosen, key=lambda c: c[2]):
        where = (ch.split("—")[0].strip().title() + " — ") if ch else ""
        it = ready or draft(project, tpl, a, b + 0.01, source="auto", reason=f"{where}{why}; no soundbites or emotional passages.")
        if it and len(it["lines"]) >= 2:
            out.append(it)
    tall = _is_tall(project)
    return [vary_layout(it, list(existing) + out[:k], tall) for k, it in enumerate(out)]


def _outcome_candidates(project, sents, scenes, hard, free, chapter):
    """v0.4.53: the case's legal outcome (a verdict, a sentence, a plea told in the narration), as a
    graphic that recaps the steps before it. Allowed near the end, where outcomes are told; never
    over a soundbite, the CTA, an emotional sentence or a chapter about the victim. One for the
    final outcome (an earlier one only when it is told long before)."""
    anchors = []
    for k, s in enumerate(sents):
        if not _outcome(s["text"]) or len(s["text"]) > LIM["text"] or re.search(EMOTION, s["text"], re.I):
            continue
        if chapter_kind(chapter(s)) in ("opening", "victim") or not free(s["t"], s["e"], hard):
            continue
        anchors.append(k)
    keep, nxt = [], None
    for k in reversed(anchors):
        if nxt is None or sents[nxt]["t"] - sents[k]["e"] >= SPEC["suggest"]["recap_gap"]:
            keep.append(k)
            nxt = k
    out = []
    for k in keep:
        s = sents[k]
        it = draft(project, "legal", s["t"], s["e"] + 0.01, source="auto")
        if not it or len(it["lines"]) < 2:
            continue
        # back to the footage before the next emotional sentence, soundbite or CTA (still readable)
        end = it["end"]
        for x in sents[k + 1:]:
            if x["t"] >= end:
                break
            if re.search(EMOTION, x["text"], re.I) or not free(x["t"], x["e"], hard):
                end = max(s["e"] + 1.2, x["t"] + 1.0)
                break
        end = min(end, min((b[0] for b in hard if b[0] > s["e"]), default=end))
        it["end"] = round(max(end, it["start"] + LIM["length"][0]), 3)
        if not free(it["start"], it["end"], hard):
            continue
        steps = ", ".join(x["label"].lower() for x in it["lines"])
        ch = chapter(s)
        where = (ch.split("—")[0].strip().title() + " — ") if ch else ""
        it["reason"] = (f"{where}the legal outcome ({steps}); the earlier steps were already told, the last one appears "
                        f"when it is said. Allowed near the end because this is where the outcome is told.")
        out.append((12.0 + len(it["lines"]), "legal", it["start"], it["end"], ch, it["reason"], normalise_item(it)))
    return out


# ---------------------------------------------------------------------- layouts (v0.4.53)

def _is_tall(project):
    try:
        W, H = effects.frame_size("1080p", effects.aspect_of(project))
        return H > W
    except Exception:  # pragma: no cover
        return False


def resolve_layout(item, tall=False):
    """The layout an item is drawn with ("auto" resolved from its content; a layout made for wide
    frames becomes its upright counterpart in a tall frame)."""
    lines = item["lines"]
    lay = item["layout"]
    tpl = item["template"]
    if lay == "auto":
        if tpl == "findings":
            lay = "split" if (len(lines) >= 3 and len(item["title"]) > 18) else "stack"
        elif tpl == "timeline":
            lay = "horizontal" if len(lines) <= 5 else "vertical"
        elif tpl == "contrast":
            kinds = {l["kind"] for l in lines}
            lay = "columns" if {"statement", "finding"} <= kinds else "rows"
        else:
            lay = "verdict" if (len(lines) >= 2 and lines[-1]["label"] in ("CONVICTED", "ACQUITTED", "SENTENCED", "PLEA", "DISMISSED")
                                and len(lines[-1]["text"]) <= 120) else "list"
    if tall:
        lay = SPEC["layouts_tall"].get(lay, lay)
    return lay


def layout_options(item, tall=False):
    """The layouts that look different for this item, in order (no duplicates once resolved)."""
    seen, out = set(), []
    for lid, _ in SPEC["layouts"][item["template"]]:
        if lid == "auto":
            continue
        r = resolve_layout(dict(item, layout=lid), tall)
        if r in seen or not _fits(item, r):
            continue
        seen.add(r)
        out.append(r)
    return out


def _fits(item, lay):
    n = len(item["lines"])
    if lay in ("focus", "cards", "steps", "horizontal"):
        return 1 <= n <= (4 if lay == "cards" else 5)
    if lay == "columns":
        return {"statement", "finding"} <= {l["kind"] for l in item["lines"]}
    if lay == "quote":
        return any(l["kind"] == "statement" for l in item["lines"])
    if lay == "verdict":
        return n >= 1
    return True


def vary_layout(item, others, tall=False):
    """A graphic of a template already used looks different: the first layout that suits it and
    that the others of the same template do not use."""
    same = {resolve_layout(o, tall) for o in others if o is not item and o["template"] == item["template"]}
    if not same or resolve_layout(item, tall) not in same:
        return item
    for lid in layout_options(item, tall):
        if resolve_layout(dict(item, layout=lid), tall) not in same:
            return dict(item, layout=lid)
    return item


# ====================================================================== drawing

def _font_file(name, weight):
    fam = FONTS.get(name, FONTS["oswald"])
    f = FONT_DIR / fam[{"bold": 0, "medium": 1, "regular": 2}[weight]]
    if f.exists():
        return str(f)
    import renderer
    return renderer.BOLD


@lru_cache(maxsize=256)
def font(name, weight, px):
    try:
        return ImageFont.truetype(_font_file(name, weight), max(6, int(round(px))))
    except OSError:
        return ImageFont.load_default()


def _rgb(hexcolor):
    return tuple(int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))


_CUT = threading.local()  # how many texts wrap() had to cut while building a layout


def wrap(text, fnt, max_w, max_lines=4):
    """Lines of at most max_w pixels; past max_lines the text ends with "…" (build() makes the
    text smaller first, so this only happens when even the smallest size cannot hold it)."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if fnt.getlength(test) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        _CUT.n = getattr(_CUT, "n", 0) + 1
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;") + "…"
    return lines


def text_sprite(text, fnt, color, tracking=0.0, alpha=255):
    asc, desc = fnt.getmetrics()
    pad = max(2, int(asc * 0.08))
    if tracking:
        widths = [fnt.getlength(ch) for ch in text]
        width = sum(widths) + tracking * max(0, len(text) - 1)
    else:
        width = fnt.getlength(text)
    im = Image.new("RGBA", (int(math.ceil(width)) + pad * 2, asc + desc + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fill = (*color, alpha)
    if tracking:
        x = pad
        for ch, w in zip(text, widths):
            d.text((x, pad), ch, font=fnt, fill=fill)
            x += w + tracking
    else:
        d.text((pad, pad), text, font=fnt, fill=fill)
    return im, pad


def type_chars(text, fnt, pad, tracking=0.0, cps=17.0):
    """v0.4.56 The typewriter entrance of one line of text: [(seconds after it starts, width shown)]
    (and whether it is a space) per character. A slightly uneven, repeatable rhythm (a steady machine gun of keys sounds fake):
    spaces and punctuation take a little longer."""
    out, t, x = [], 0.0, float(pad)
    for i, ch in enumerate(text):
        x += fnt.getlength(ch) + (tracking if i else 0.0)
        out.append((round(t, 4), int(math.ceil(x)), ch.isspace()))
        jitter = ((i * 7919 + len(text) * 31) % 11) / 10.0 - 0.5  # -0.5..0.5, the same every time
        step = (1.0 + 0.28 * jitter) / cps
        if ch in " ,.;:!?\u2014-":
            step *= 1.6
        t += step
    return out


def rect_sprite(w, h, color, alpha=255, radius=0):
    im = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if radius:
        d.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius, fill=(*color, alpha))
    else:
        d.rectangle((0, 0, im.width, im.height), fill=(*color, alpha))
    return im


def ring_sprite(r, color, fill, width):
    s = 4
    im = Image.new("RGBA", (int(r * 2 * s) + 4, int(r * 2 * s) + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((2, 2, im.width - 3, im.height - 3), fill=(*fill, 255), outline=(*color, 255), width=int(width * s))
    return im.resize((im.width // s, im.height // s), Image.LANCZOS)


def tag_sprite(label, fnt, style, accent, text_color):
    """A legal tag: ALLEGED (outline, grey), CHARGED/ARRESTED (outline, off-white),
    PLEA/VERDICT/CONVICTED (solid accent), SENTENCED (solid off-white), ACQUITTED/DISMISSED (solid grey)."""
    asc, desc = fnt.getmetrics()
    tw = fnt.getlength(label) + len(label) * asc * 0.12
    padx, pady = asc * 0.55, asc * 0.32
    w, h = int(tw + padx * 2), int(asc + desc * 0.4 + pady * 2)
    s = 3
    im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    grey = (150, 146, 140)
    if style == "outline-grey":
        d.rounded_rectangle((s, s, w * s - s, h * s - s), 4 * s, outline=(*grey, 255), width=2 * s)
        tc = grey
    elif style == "outline":
        d.rounded_rectangle((s, s, w * s - s, h * s - s), 4 * s, outline=(*text_color, 255), width=2 * s)
        tc = text_color
    elif style == "solid-accent":
        d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), 4 * s, fill=(*accent, 255))
        tc = (255, 255, 255)
    elif style == "solid-light":
        d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), 4 * s, fill=(*text_color, 255))
        tc = (18, 18, 20)
    else:
        d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), 4 * s, fill=(*grey, 255))
        tc = (18, 18, 20)
    im = im.resize((w, h), Image.LANCZOS)
    t, pad = text_sprite(label, fnt, tc, tracking=asc * 0.12)
    im.alpha_composite(t, (int(padx - pad), int(pady - pad - desc * 0.15)))
    return im


TAG_STYLE = {"ALLEGED": "outline-grey", "ARRESTED": "outline", "CHARGED": "outline", "PLEA": "solid-accent",
             "VERDICT": "solid-accent", "CONVICTED": "solid-accent", "SENTENCED": "solid-light",
             "ACQUITTED": "solid-grey", "DISMISSED": "solid-grey"}


@dataclass
class El:
    img: Image.Image
    x: int
    y: int
    t_in: float
    d_in: float
    enter: str  # mask | slide | fade | settle | wipe | wipe_v | pop
    t_out: float = 1e9
    d_out: float = 0.5
    exit: str = "fade"
    lut: dict = field(default_factory=dict, repr=False)
    early: bool = False  # v0.4.53: leaves on its own (one line at a time), not with the rest
    # v0.4.56: what the element is (heading, title, divider, line, marker, connector, tag, rule,
    # label): the sound design follows these events. `chars`: for the typewriter entrance, the
    # [(seconds after t_in, visible width in px, is a space)] of each typed character.
    role: str = ""
    chars: list | None = None


def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 4


def ease_in(x):
    x = max(0.0, min(1.0, x))
    return x ** 3


def ease_io(x):
    x = max(0.0, min(1.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


@dataclass
class Layout:
    item: dict
    W: int
    H: int
    els: list
    length: float
    frames: int
    bg: str
    photo: Image.Image | None = None
    plan: tuple | None = None
    layout: str = ""


def build(item, W, H, photo_path=None):
    """Place every element of the graphic (the drawing is done per frame by `frame`); long text is
    made smaller until it fits inside the frame (never cut)."""
    fit = 1.0
    for _ in range(7):
        _CUT.n = 0
        lay = _build(item, W, H, photo_path, fit)
        bottom = max((el.y + el.img.height for el in lay.els), default=0)
        right = max((el.x + el.img.width for el in lay.els), default=0)
        if bottom <= H * 0.94 and right <= W * 0.97 and not _CUT.n:
            break
        fit *= 0.9
    return lay


def _build(item, W, H, photo_path, fit):
    it = item
    sp = it["speed"]
    length = it["end"] - it["start"]
    frames = max(1, round(it["end"] * FPS) - round(it["start"] * FPS))
    tall = H > W
    U = min(H, W * 9 / 16) if not tall else W * 1.25  # text unit
    U *= it["size"] * fit
    fam = it["font"]
    tc, ac = _rgb(it["text_color"]), _rgb(it["accent"])
    muted = tuple(int(c * MUTED + 30 * (1 - MUTED)) for c in tc)
    ac_text = tuple(min(255, int(c + (255 - c) * 0.22)) for c in ac)  # small red text: a little lighter to read
    enter = it["enter"]
    d_in = TIM["enter"] / sp
    exit_len = TIM["exit"] / sp
    margin = W * (0.075 if not tall else 0.08)
    shift_x, shift_y = it["x"] * W, it["y"] * H
    els: list[El] = []

    def t_line(at):
        return max(TIM["intro_end"] / sp * 0.9, at - it["start"])

    cps = TIM.get("type_cps", 17) * sp

    def add(img, x, y, t_in, kind=None, d=None, role=None, chars=None):
        kind = kind or enter
        if kind == "type" and not chars:
            kind = "fade"  # only plain lines of text are typed
        if kind == "type":
            d = chars[-1][0] + 1.0 / cps
        role = role or {"pop": "marker", "wipe": "rule", "wipe_v": "rule"}.get(kind, "label")
        el = El(img, int(round(x + shift_x)), int(round(y + shift_y)), t_in, d or d_in, kind, role=role, chars=chars)
        els.append(el)
        return el

    def typed(text, fnt, pad, tracking=0.0):
        return type_chars(text, fnt, pad, tracking, cps) if enter == "type" else None

    def leave(group, t_next):
        """One at a time: these elements leave just before the next line comes in."""
        for el in group:
            el.early = True
            el.d_out = 0.35 / sp
            el.t_out = max(el.t_in + el.d_in, t_next - 0.4 / sp)
            el.exit = "fade"

    heading_f = font(fam, "medium", U * 0.027)
    title_f = font(fam, "bold", U * (0.074 if not tall else 0.062))
    body_f = font(fam, "regular", U * 0.041)
    small_f = font(fam, "medium", U * 0.026)

    def intro(x, y, max_w, center=False):
        """Heading, title, divider; returns the y below them."""
        y0 = y
        if it["heading"]:
            img, pad = text_sprite(it["heading"].upper(), heading_f, ac_text, tracking=U * 0.006)
            bar = rect_sprite(U * 0.03, max(2, U * 0.004), ac)
            hx = x if not center else x + (max_w - img.width) / 2
            if not center:
                add(bar, hx, y + img.height / 2 - bar.height / 2, TIM["heading"] / sp, "wipe", 0.5 / sp, role="heading")
                hx += bar.width + U * 0.016
            add(img, hx - pad, y - pad, TIM["heading"] / sp + 0.08 / sp, role="heading",
                chars=typed(it["heading"].upper(), heading_f, pad, U * 0.006))
            y += img.height - pad + U * 0.012
        if it["title"]:
            lines = wrap(it["title"].upper(), title_f, max_w, 3)  # never cut: the fit makes it smaller
            for k, ln in enumerate(lines):
                img, pad = text_sprite(ln, title_f, tc)
                lx = x if not center else x + (max_w - img.width) / 2
                add(img, lx - pad, y - pad, TIM["title"] / sp + k * TIM["line_stagger"] / sp, "settle" if enter == "fade" else "mask", 0.8 / sp, role="title")
                y += title_f.getmetrics()[0] * 1.08
        y += U * 0.022
        dw = min(max_w, U * 0.32)
        div = rect_sprite(dw, max(2, U * 0.0045), ac)
        add(div, x if not center else x + (max_w - dw) / 2, y, TIM["divider"] / sp, "wipe", 0.75 / sp, role="divider")
        y += U * 0.05
        return y, y - y0

    def body_block(text, fnt, color, x, y, max_w, t_in, max_lines=4, center=False):
        """Wrapped text, line by line; returns the height used."""
        lh = fnt.getmetrics()[0] * 1.32
        lines = wrap(text, fnt, max_w, max_lines)
        t = t_in
        for k, ln in enumerate(lines):
            img, pad = text_sprite(ln, fnt, color)
            lx = x if not center else x + (max_w - img.width) / 2
            el = add(img, lx - pad, y + k * lh - pad, t if enter == "type" else t_in + k * TIM["line_stagger"] / sp,
                     role="line", chars=typed(ln, fnt, pad))
            t = el.t_in + el.d_in + 0.04 / sp  # typed rows follow one another
        return len(lines) * lh

    lines = it["lines"]
    tpl = it["template"]
    layout = resolve_layout(it, tall)

    if tpl == "findings" and layout == "cards":  # v0.4.53: numbered cards, two columns when wide
        x, mw = margin, W - margin * 2
        cols = 2 if (not tall and len(lines) >= 2) else 1
        gap = U * 0.07
        cw = (mw - gap * (cols - 1)) / cols
        num_f = font(fam, "bold", U * 0.066)
        card_f = font(fam, "regular", U * 0.036)
        num_w = num_f.getlength("00") + U * 0.03
        lh = card_f.getmetrics()[0] * 1.32
        tw = cw - num_w
        hs = [max(len(wrap(l["text"], card_f, tw, 4)) * lh, num_f.getmetrics()[0] * 1.05) + U * 0.035 for l in lines]
        row_h = [max(hs[r * cols:(r + 1) * cols]) + U * 0.045 for r in range(math.ceil(len(lines) / cols))]
        head_h = U * (0.05 + 0.08 * min(3, len(wrap(it["title"].upper(), title_f, mw, 3))) + 0.1)
        y = max(H * 0.08, (H - head_h - sum(row_h)) / 2)
        y, _ = intro(x, y, mw)
        for k, l in enumerate(lines):
            r, c = divmod(k, cols)
            cx, cy = x + c * (cw + gap), y + sum(row_h[:r])
            t = t_line(l["at"])
            rule = rect_sprite(cw, max(2, U * 0.003), (120, 116, 110), 150)
            add(rule, cx, cy, max(TIM["divider"] / sp, t - 0.2 / sp), "wipe", 0.6 / sp)
            red = rect_sprite(U * 0.06, max(3, U * 0.006), ac)
            add(red, cx, cy - (red.height - rule.height) / 2, t, "wipe", 0.4 / sp)
            img, pad = text_sprite(f"{k + 1:02d}", num_f, ac_text)
            add(img, cx - pad, cy + U * 0.022 - pad, t, "mask", 0.6 / sp)
            body_block(l["text"], card_f, tc, cx + num_w, cy + U * 0.035, tw, t + 0.12 / sp, 4)

    elif tpl == "findings" and layout == "focus":  # v0.4.53: one finding at a time, large
        center = it["align"] == "center"
        x, mw = margin, W - margin * 2
        y, _ = intro(x, H * (0.1 if not tall else 0.12), mw, center)
        big_f = font(fam, "medium", U * 0.058)
        cnt_f = font(fam, "medium", U * 0.026)
        lh = big_f.getmetrics()[0] * 1.22
        bw = mw * (0.86 if not tall else 1.0)
        n = len(lines)
        bar_y = H * 0.86
        top, bottom = y + U * 0.02, bar_y - U * 0.06
        seg_w = min(U * 0.09, (mw * 0.5) / max(1, n))
        times = [t_line(l["at"]) for l in lines]
        for k, (l, t) in enumerate(zip(lines, times)):
            rows = wrap(l["text"], big_f, bw, 4)
            cnt, cpad = text_sprite(f"{k + 1:02d} / {n:02d}", cnt_f, ac_text, tracking=U * 0.004)
            block = cnt.height + U * 0.02 + len(rows) * lh
            yy = max(top, top + (bottom - top - block) / 2)
            group = [add(cnt, (x if not center else x + (mw - cnt.width) / 2) - cpad, yy - cpad, t, "fade", 0.4 / sp)]
            yy += cnt.height + U * 0.02
            for j, ln in enumerate(rows):
                img, pad = text_sprite(ln, big_f, tc)
                lx = x if not center else x + (mw - img.width) / 2
                group.append(add(img, lx - pad, yy + j * lh - pad, t + j * TIM["line_stagger"] / sp, "settle" if enter == "fade" else enter, 0.75 / sp, role="line"))
            if k + 1 < n:
                leave(group, times[k + 1])
            sx = x + k * (seg_w + U * 0.01) if not center else x + (mw - n * (seg_w + U * 0.01)) / 2 + k * (seg_w + U * 0.01)
            add(rect_sprite(seg_w, max(3, U * 0.005), (90, 88, 84)), sx, bar_y, TIM["divider"] / sp, "wipe", 0.5 / sp)
            add(rect_sprite(seg_w, max(3, U * 0.005), ac), sx, bar_y, t, "wipe", 0.45 / sp)

    elif tpl == "findings":
        if layout == "split" and not tall:
            lx, lw = margin, W * 0.33
            rx, rw = W * 0.45, W - margin - W * 0.45
            # measure the bullets to centre both columns vertically
            heights = [len(wrap(l["text"], body_f, rw - U * 0.05, 4)) * body_f.getmetrics()[0] * 1.32 for l in lines]
            total = sum(heights) + U * 0.045 * max(0, len(lines) - 1)
            y = (H - total) / 2
            ly = H / 2 - U * 0.16
            intro(lx, ly, lw)
            rule = rect_sprite(max(2, U * 0.003), total + U * 0.04, ac, 200)
            add(rule, rx - U * 0.04, y - U * 0.02, TIM["divider"] / sp, "wipe_v", 0.9 / sp)
            for l, h in zip(lines, heights):
                body_block(l["text"], body_f, tc, rx, y, rw, t_line(l["at"]))
                y += h + U * 0.045
        else:
            center = layout == "center" or it["align"] == "center"
            x, mw = margin, W - margin * 2
            heights = [len(wrap(l["text"], body_f, mw - U * 0.05, 3)) * body_f.getmetrics()[0] * 1.32 for l in lines]
            head_h = U * (0.05 + 0.08 * min(2, len(wrap(it["title"].upper(), title_f, mw, 2))) + 0.1)
            total = head_h + sum(heights) + U * 0.035 * max(0, len(lines) - 1)
            y = max(H * 0.08, (H - total) / 2)
            y, _ = intro(x, y, mw, center)
            for l, h in zip(lines, heights):
                t = t_line(l["at"])
                if not center:
                    sq = rect_sprite(U * 0.013, U * 0.013, ac)
                    add(sq, x, y + body_f.getmetrics()[0] * 0.42, t, "pop", 0.4 / sp)
                    body_block(l["text"], body_f, tc, x + U * 0.04, y, mw - U * 0.05, t + 0.05 / sp, 3)
                else:
                    body_block(l["text"], body_f, tc, x, y, mw, t, 3, center=True)
                y += h + U * 0.035

    elif tpl == "timeline" and layout == "focus":  # v0.4.53: one date at a time, a strip below
        x, mw = margin, W - margin * 2
        y, _ = intro(x, H * (0.1 if not tall else 0.12), mw)
        date_f = font(fam, "bold", U * (0.11 if not tall else 0.09))
        txt_f = font(fam, "regular", U * 0.046)
        small = font(fam, "medium", U * 0.022)
        lh = txt_f.getmetrics()[0] * 1.3
        tw = mw * (0.8 if not tall else 1.0)
        n = len(lines)
        axis_y = H * 0.85
        top, bottom = y + U * 0.01, axis_y - U * 0.1
        times = [t_line(l["at"]) for l in lines]
        col = mw / max(1, n)
        pts = [x + col * (k + 0.5) for k in range(n)]
        base = rect_sprite(mw, max(2, U * 0.003), (120, 116, 110), 150)
        add(base, x, axis_y, TIM["divider"] / sp, "wipe", 1.0 / sp)
        prev = x
        for l, px, t in zip(lines, pts, times):
            seg = rect_sprite(max(2, px - prev), max(3, U * 0.005), ac)
            add(seg, prev, axis_y - (seg.height - base.height) / 2, max(TIM["divider"] / sp, t - 0.45 / sp), "wipe", 0.5 / sp, role="connector")
            prev = px
        for k, (l, px, t) in enumerate(zip(lines, pts, times)):
            dot = ring_sprite(U * 0.011, ac, (18, 18, 20), max(2, U * 0.0035))
            add(dot, px - dot.width / 2, axis_y + base.height / 2 - dot.height / 2, t, "pop", 0.35 / sp)
            if l["label"]:
                for j, ln in enumerate(wrap(l["label"], small, col - U * 0.02, 2)):
                    img, pad = text_sprite(ln, small, muted)
                    add(img, px - img.width / 2, axis_y + U * 0.03 + j * small.getmetrics()[0] * 1.2 - pad, t + 0.05 / sp)
            rows = wrap(l["text"], txt_f, tw, 4)
            dates = wrap(l["label"], date_f, mw, 2) if l["label"] else []
            dh = len(dates) * date_f.getmetrics()[0] * 1.05
            block = dh + (U * 0.025 if dates else 0) + len(rows) * lh
            yy = max(top, top + (bottom - top - block) / 2)
            group = []
            for j, ln in enumerate(dates):
                img, pad = text_sprite(ln, date_f, tc)
                group.append(add(img, x - pad, yy + j * date_f.getmetrics()[0] * 1.05 - pad, t, "mask", 0.7 / sp, role="date"))
            yy += dh + (U * 0.025 if dates else 0)
            if dates:
                group.append(add(rect_sprite(U * 0.12, max(3, U * 0.006), ac), x, yy - U * 0.016, t + 0.15 / sp, "wipe", 0.5 / sp))
            for j, ln in enumerate(rows):
                img, pad = text_sprite(ln, txt_f, tc)
                group.append(add(img, x - pad, yy + j * lh - pad, t + (0.2 + j * TIM["line_stagger"]) / sp, role="line"))
            if k + 1 < n:
                leave(group, times[k + 1])

    elif tpl == "timeline":
        if layout == "horizontal" and not tall:
            x, mw = margin, W - margin * 2
            y, _ = intro(x, H * 0.16, mw)
            axis_y = max(y + U * 0.16, H * 0.52)
            n = max(1, len(lines))
            col = mw / n
            pts = [x + col * (k + 0.5) for k in range(n)]
            base = rect_sprite(mw, max(2, U * 0.003), (120, 116, 110), 150)
            add(base, x, axis_y, TIM["divider"] / sp, "wipe", 1.0 / sp)
            date_f = font(fam, "bold", U * 0.036)
            txt_f = font(fam, "regular", U * 0.03)
            prev = x
            for l, px in zip(lines, pts):  # the red line grows to each event first; the dots go on top
                t = t_line(l["at"])
                seg = rect_sprite(max(2, px - prev), max(3, U * 0.005), ac)
                add(seg, prev, axis_y - (seg.height - base.height) / 2, max(TIM["divider"] / sp, t - 0.45 / sp), "wipe", 0.5 / sp, role="connector")
                prev = px
            for k, (l, px) in enumerate(zip(lines, pts)):
                t = t_line(l["at"])
                r = U * 0.014
                dot = ring_sprite(r, ac, (18, 18, 20), max(2, U * 0.004))
                add(dot, px - dot.width / 2, axis_y + base.height / 2 - dot.height / 2, t, "pop", 0.35 / sp)
                if l["label"]:
                    img, pad = text_sprite(l["label"], date_f, tc)
                    add(img, px - img.width / 2, axis_y - U * 0.035 - img.height + pad, t + 0.05 / sp, "mask")
                lh = txt_f.getmetrics()[0] * 1.3
                for j, ln in enumerate(wrap(l["text"], txt_f, col - U * 0.04, 4)):
                    img, pad = text_sprite(ln, txt_f, muted)
                    add(img, px - img.width / 2, axis_y + U * 0.045 + j * lh - pad, t + (0.15 + 0.08 * j) / sp, role="line")
        else:
            x, mw = margin, W - margin * 2
            date_f = font(fam, "bold", U * 0.034)
            txt_f = font(fam, "regular", U * 0.034)
            date_w = U * 0.36 if not tall else U * 0.3
            tx = x + date_w + U * 0.06
            tw = W - margin - tx
            lh = txt_f.getmetrics()[0] * 1.3
            heights = [max(len(wrap(l["text"], txt_f, tw, 3)) * lh, date_f.getmetrics()[0] * 1.3) for l in lines]
            head_h = U * 0.3
            total = head_h + sum(heights) + U * 0.03 * max(0, len(lines) - 1)
            y = max(H * 0.07, (H - total) / 2)
            y, _ = intro(x, y, mw)
            line_x = x + date_w + U * 0.025
            prev, yy = y, y
            for l, h in zip(lines, heights):  # the line first, dots on top
                t = t_line(l["at"])
                cy = yy + date_f.getmetrics()[0] * 0.6
                seg = rect_sprite(max(3, U * 0.004), max(2, cy - prev), ac)
                add(seg, line_x - seg.width / 2, prev, max(TIM["divider"] / sp, t - 0.4 / sp), "wipe_v", 0.45 / sp, role="connector")
                prev = cy
                yy += h + U * 0.03
            for l, h in zip(lines, heights):
                t = t_line(l["at"])
                cy = y + date_f.getmetrics()[0] * 0.6
                dot = ring_sprite(U * 0.012, ac, (18, 18, 20), max(2, U * 0.004))
                add(dot, line_x - dot.width / 2, cy - dot.height / 2, t, "pop", 0.35 / sp)
                if l["label"]:
                    img, pad = text_sprite(l["label"], date_f, tc)
                    add(img, line_x - U * 0.03 - img.width + pad, y - pad, t + 0.05 / sp, "slide")
                body_block(l["text"], txt_f, muted, tx, y, tw, t + 0.12 / sp, 3)
                y += h + U * 0.03

    elif tpl == "contrast" and layout == "quote":  # v0.4.53: what was said as a quote, then the record
        x, mw = margin, W - margin * 2
        y, _ = intro(x, H * (0.1 if not tall else 0.1), mw)
        q_f = font(fam, "bold", U * 0.15)
        say_f = font(fam, "regular", U * 0.044)
        rec_f = font(fam, "medium", U * 0.041)
        who_f = font(fam, "medium", U * 0.024)
        indent = U * 0.085
        said = [l for l in lines if l["kind"] != "finding"]
        found = [l for l in lines if l["kind"] == "finding"]
        if said:
            qm, qpad = text_sprite("\u201c", q_f, ac)
            add(qm, x - qpad - U * 0.005, y - qpad - U * 0.035, t_line(said[0]["at"]), "pop", 0.45 / sp)
        for l in said:
            t = t_line(l["at"])
            h = body_block(l["text"], say_f, tc if l["emphasis"] else muted, x + indent, y, mw - indent, t + 0.05 / sp, 3)
            y += h
            if l["label"]:
                img, pad = text_sprite("— " + l["label"].upper(), who_f, (150, 146, 140), tracking=U * 0.004)
                add(img, x + indent - pad, y - pad, t + 0.3 / sp)
                y += img.height
            y += U * 0.03
        if found:
            y += U * 0.02
            t0 = t_line(found[0]["at"])
            hdr, hpad = text_sprite("THE RECORD", who_f, ac_text, tracking=U * 0.006)
            add(rect_sprite(min(mw, U * 0.5), max(2, U * 0.003), (120, 116, 110), 150), x, y + hdr.height / 2, t0 - 0.1 / sp, "wipe", 0.6 / sp)
            add(hdr, x + min(mw, U * 0.5) + U * 0.02 - hpad, y - hpad, t0)
            y += hdr.height + U * 0.025
            for l in found:
                t = t_line(l["at"])
                lh = rec_f.getmetrics()[0] * 1.32
                n = len(wrap(l["text"], rec_f, mw - indent, 3))
                add(rect_sprite(max(3, U * 0.006), n * lh, ac), x + indent - U * 0.035, y, t, "wipe_v", 0.4 / sp)
                body_block(l["text"], rec_f, tc, x + indent, y, mw - indent, t + 0.08 / sp, 3)
                y += n * lh + U * 0.03

    elif tpl == "contrast":
        x, mw = margin, W - margin * 2
        if layout == "columns" and not tall:
            y, _ = intro(x, H * 0.12, mw)
            gap = U * 0.08
            cw = (mw - gap) / 2
            cols = {"statement": x, "finding": x + cw + gap}
            hdr_f = font(fam, "medium", U * 0.026)
            divider = rect_sprite(max(2, U * 0.003), H * 0.8 - y, (140, 136, 130), 170)
            add(divider, x + cw + gap / 2, y, TIM["divider"] / sp + 0.2 / sp, "wipe_v", 1.0 / sp)
            heads = {"statement": "WHAT WAS SAID", "finding": "WHAT WAS FOUND"}
            ys = {}
            for kind in ("statement", "finding"):
                img, pad = text_sprite(heads[kind], hdr_f, (150, 146, 140) if kind == "statement" else ac_text, tracking=U * 0.005)
                add(img, cols[kind] - pad, y - pad, TIM["divider"] / sp + 0.3 / sp)
                ys[kind] = y + img.height + U * 0.03
            for l in lines:
                k = l["kind"]
                t = t_line(l["at"])
                cx = cols[k]
                yy = ys[k]
                if l["label"] and l["label"] not in ("STATED", "FOUND"):
                    img, pad = text_sprite(l["label"].upper(), small_f, (150, 146, 140), tracking=U * 0.004)
                    add(img, cx - pad, yy - pad, t)
                    yy += img.height + U * 0.004
                f = body_f if l["emphasis"] else font(fam, "regular", U * 0.037)
                color = tc if (k == "finding" or l["emphasis"]) else muted
                h = body_block(l["text"], f, color, cx, yy, cw, t + 0.05 / sp, 4)
                if l["emphasis"]:
                    bar = rect_sprite(min(cw, U * 0.22), max(3, U * 0.006), ac)
                    add(bar, cx, yy + h + U * 0.008, t + 0.55 / sp, "wipe", 0.6 / sp)
                    h += U * 0.02
                ys[k] = yy + h + U * 0.04
        else:
            y, _ = intro(x, H * (0.12 if not tall else 0.1), mw)
            for l in lines:
                t = t_line(l["at"])
                finding = l["kind"] == "finding"
                f = body_f if (finding or l["emphasis"]) else font(fam, "regular", U * 0.037)
                lh = f.getmetrics()[0] * 1.32
                n = len(wrap(l["text"], f, mw - U * 0.06, 3))
                lab = l["label"] or ("FOUND" if finding else "STATED")
                img, pad = text_sprite(lab.upper(), small_f, ac_text if finding else (150, 146, 140), tracking=U * 0.004)
                bar = rect_sprite(max(3, U * 0.005), img.height + n * lh, ac if finding else (110, 106, 100))
                add(bar, x, y, t, "wipe_v", 0.4 / sp)
                add(img, x + U * 0.03 - pad, y - pad, t + 0.05 / sp)
                body_block(l["text"], f, tc if finding or l["emphasis"] else muted, x + U * 0.03, y + img.height, mw - U * 0.06, t + 0.1 / sp, 3)
                y += img.height + n * lh + U * 0.04

    elif layout == "steps":  # v0.4.53 legal: the steps across, a tag on the line for each
        x, mw = margin, W - margin * 2
        y, _ = intro(x, H * 0.14, mw)
        tag_f = font(fam, "bold", U * 0.026)
        txt_f = font(fam, "regular", U * 0.031)
        axis_y = max(y + U * 0.1, H * 0.46)
        n = max(1, len(lines))
        col = mw / n
        pts = [x + col * (k + 0.5) for k in range(n)]
        base = rect_sprite(mw, max(2, U * 0.003), (120, 116, 110), 150)
        add(base, x, axis_y, TIM["divider"] / sp, "wipe", 1.0 / sp)
        prev = x
        for l, px in zip(lines, pts):
            t = t_line(l["at"])
            seg = rect_sprite(max(2, px - prev), max(3, U * 0.005), ac)
            add(seg, prev, axis_y - (seg.height - base.height) / 2, max(TIM["divider"] / sp, t - 0.45 / sp), "wipe", 0.5 / sp, role="connector")
            prev = px
        lh = txt_f.getmetrics()[0] * 1.3
        for l, px in zip(lines, pts):
            t = t_line(l["at"])
            tag = tag_sprite(l["label"] or "—", tag_f, TAG_STYLE.get(l["label"].upper(), "outline"), ac, tc)
            add(tag, px - tag.width / 2, axis_y + base.height / 2 - tag.height / 2, t, "pop", 0.4 / sp, role="tag")
            strong = l["label"].upper() in ("CONVICTED", "VERDICT", "SENTENCED", "PLEA", "ACQUITTED") or l["emphasis"]
            for j, ln in enumerate(wrap(l["text"], txt_f, col - U * 0.04, 5)):
                img, pad = text_sprite(ln, txt_f, tc if strong else muted)
                add(img, px - img.width / 2, axis_y + tag.height / 2 + U * 0.03 + j * lh - pad, t + (0.15 + 0.08 * j) / sp, role="line")

    elif layout == "verdict":  # v0.4.53 legal: the steps small, the outcome in large type
        x, mw = margin, W - margin * 2
        tag_f = font(fam, "bold", U * 0.021)
        small_txt = font(fam, "regular", U * 0.03)
        big_tag_f = font(fam, "bold", U * 0.03)
        big_f = font(fam, "bold", U * (0.062 if not tall else 0.056))
        earlier, last = lines[:-1], lines[-1]
        tag_w = max([tag_sprite(l["label"] or "—", tag_f, "outline", ac, tc).width for l in earlier] + [U * 0.1])
        slh = small_txt.getmetrics()[0] * 1.28
        blh = big_f.getmetrics()[0] * 1.12
        e_h = [max(len(wrap(l["text"], small_txt, mw - tag_w - U * 0.03, 2)) * slh, U * 0.04) + U * 0.018 for l in earlier]
        big_rows = wrap(last["text"].upper(), big_f, mw, 4)
        total = U * 0.3 + sum(e_h) + U * 0.07 + U * 0.06 + len(big_rows) * blh
        y = max(H * 0.07, (H - total) / 2)
        y, _ = intro(x, y, mw)
        for l, h in zip(earlier, e_h):
            t = t_line(l["at"])
            if l["label"]:
                tag = tag_sprite(l["label"], tag_f, TAG_STYLE.get(l["label"].upper(), "outline"), ac, tc)
                add(tag, x, y + (slh - tag.height) / 2, t, "wipe", 0.4 / sp, role="tag")
            body_block(l["text"], small_txt, muted, x + tag_w + U * 0.03, y, mw - tag_w - U * 0.03, t + 0.1 / sp, 2)
            y += h
        y += U * 0.05
        t = t_line(last["at"])
        if last["label"]:
            tag = tag_sprite(last["label"], big_tag_f, TAG_STYLE.get(last["label"].upper(), "outline"), ac, tc)
            add(tag, x, y, t, "wipe", 0.45 / sp, role="tag")
            y += tag.height + U * 0.022
        for j, ln in enumerate(big_rows):
            img, pad = text_sprite(ln, big_f, tc)
            add(img, x - pad, y + j * blh - pad, t + (0.15 + j * TIM["line_stagger"]) / sp, "mask" if enter != "fade" else "settle", 0.8 / sp, role="verdict")
        y += len(big_rows) * blh + U * 0.012
        add(rect_sprite(min(mw, U * 0.32), max(3, U * 0.006), ac), x, y, t + 0.7 / sp, "wipe", 0.7 / sp)

    else:  # legal: a list
        x, mw = margin, W - margin * 2
        tag_f = font(fam, "bold", U * 0.024)
        txt_f = font(fam, "regular", U * 0.038)
        tag_w = max([tag_sprite(l["label"] or "—", tag_f, "outline", ac, tc).width for l in lines] + [U * 0.12])
        tx = x + tag_w + U * 0.035
        tw = W - margin - tx
        lh = txt_f.getmetrics()[0] * 1.3
        heights = [max(len(wrap(l["text"], txt_f, tw, 3)) * lh, U * 0.05) for l in lines]
        total = U * 0.3 + sum(heights) + U * 0.035 * max(0, len(lines) - 1)
        y = max(H * 0.07, (H - total) / 2)
        y, _ = intro(x, y, mw)
        for l, h in zip(lines, heights):
            t = t_line(l["at"])
            if l["label"]:
                tag = tag_sprite(l["label"], tag_f, TAG_STYLE.get(l["label"].upper(), "outline"), ac, tc)
                add(tag, x, y + (txt_f.getmetrics()[0] * 1.3 - tag.height) / 2, t, "wipe", 0.45 / sp, role="tag")
            strong = l["label"].upper() in ("CONVICTED", "VERDICT", "SENTENCED", "PLEA") or l["emphasis"]
            body_block(l["text"], txt_f, tc if strong else muted, tx, y, tw, t + 0.12 / sp, 3)
            y += h + U * 0.035

    # exit: every element leaves, last in first out, before the background fades
    out_start = length - exit_len - TIM["background_out"] * 0.5
    rest = [e for e in els if not e.early]
    # the stagger fits in a fixed time however many pieces there are, and every piece has gone
    # before the end (v0.4.53: with many wrapped lines the last ones were still on screen)
    step = min(TIM["exit_stagger"] / sp * 0.5, TIM["background_out"] * 0.3 / max(1, len(rest)))
    last_out = length - exit_len - 1.0 / FPS
    for k, el in enumerate(reversed(rest)):
        el.t_out = min(max(el.t_in + el.d_in, out_start + k * step), max(last_out, el.t_in))
        el.d_out = exit_len
        el.exit = it["exit"]
    for el in els:  # one at a time: never after the rest
        if el.early:
            el.t_out = min(el.t_out, max(el.t_in + el.d_in, out_start))
    photo = None
    if it["background"] in ("photo", "still") and photo_path:
        try:
            with Image.open(photo_path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                cw, ch = int(W * 1.08), int(H * 1.08)
                im = ImageOps.fit(im, (cw, ch), Image.LANCZOS)
                im = im.filter(ImageFilter.GaussianBlur(max(2, W / 320)))
                photo = im
        except OSError:
            photo = None
    bg = it["background"]
    if bg in ("photo", "still"):
        bg = "photo" if photo is not None else "charcoal"  # a still from the footage is drawn like a photo
    return Layout(it, W, H, els, length, frames, bg, photo, layout=layout)


def _state(el, tau):
    if tau < el.t_in:
        return None
    p = (tau - el.t_in) / el.d_in
    q = (tau - el.t_out) / el.d_out if tau > el.t_out else 0.0
    if q >= 1:
        return None
    return (min(1.0, round(p, 3)), round(max(0.0, q), 3))


def sound_events(lay):
    """v0.4.56 Every animation event of a built graphic, for the sound design, in seconds from its
    start: [{t, role, enter, d, chars}] (`chars`: when each typed character appears), with the
    background coming in at 0 and the exit (when the first piece starts to leave)."""
    out = [{"t": 0.0, "role": "background", "enter": "fade", "d": TIM["background_in"], "chars": None}]
    for el in lay.els:
        out.append({"t": round(el.t_in, 4), "role": el.role or "label", "enter": el.enter, "d": round(el.d_in, 4),
                    "chars": [[round(el.t_in + c[0], 4), c[2]] for c in el.chars] if el.chars else None})
    rest = [el.t_out for el in lay.els if not el.early and el.t_out < 1e8]
    if rest:
        out.append({"t": round(min(rest), 4), "role": "exit", "enter": lay.item.get("exit", "fade"), "d": TIM["exit"], "chars": None})
    out.sort(key=lambda e: e["t"])
    return out


def bg_alpha(lay, tau):
    a_in = ease_io(tau / TIM["background_in"])
    a_out = 1 - ease_io((tau - (lay.length - TIM["background_out"])) / TIM["background_out"])
    return max(0.0, min(a_in, a_out))


def bg_phase(tau):
    return math.floor(tau * 6) / 6  # the background drifts in steps of 1/6 s: invisible, but frames repeat


def frame_key(lay, n):
    tau = n / FPS
    states = tuple(_state(el, tau) for el in lay.els)
    a = round(bg_alpha(lay, tau), 3)
    phase = bg_phase(tau) if lay.bg in ("charcoal", "photo") else 0
    return (a, phase, states)


@lru_cache(maxsize=8)
def _charcoal(W, H, accent):
    """The dark background: charcoal, a soft light from the upper left, a vignette, faint smoke."""
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(0, 1, W)[None, :]
    base = 14 + 8 * (1 - y) + 0 * x
    light = np.exp(-(((x - 0.18) / 0.55) ** 2 + ((y - 0.1) / 0.6) ** 2)) * 16
    vig = 1 - 0.55 * np.clip(((x - 0.5) ** 2 + (y - 0.5) ** 2 * 1.4) / 0.45, 0, 1) ** 1.6
    rng = np.random.default_rng(7)
    smoke = Image.fromarray((rng.random((max(8, H // 24), max(8, W // 24))) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    smoke = np.asarray(smoke.filter(ImageFilter.GaussianBlur(W / 60)), dtype=np.float32) / 255 - 0.5
    lum = (base + light + smoke * 7) * vig
    rgb = np.stack([lum * 1.0, lum * 1.0, lum * 1.08], axis=-1)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


@lru_cache(maxsize=8)
def _glow(W, H, accent):
    """A soft, slow light in the accent colour (drifts behind the text)."""
    gw, gh = int(W * 0.9), int(H * 1.1)
    y = np.linspace(-1, 1, gh)[:, None]
    x = np.linspace(-1, 1, gw)[None, :]
    a = np.exp(-(x ** 2 + y ** 2) * 2.6) * 0.16
    r, g, b = _rgb(accent)
    arr = np.zeros((gh, gw, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = r, g, b
    arr[..., 3] = np.clip(a * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _alpha(img, a, cache=None):
    if a >= 0.999:
        return img
    if a <= 0.001:
        return None
    q = round(a * 64)
    if cache is not None and q in cache:
        return cache[q]
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda v: v * q // 64))
    if cache is not None:
        cache[q] = out
    return out


def _paste(canvas, img, x, y):
    """alpha_composite that accepts sprites partly outside the canvas."""
    W, H = canvas.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + img.width), min(H, y + img.height)
    if x1 <= x0 or y1 <= y0:
        return
    canvas.alpha_composite(img.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def _motion_blur(img, px):
    """Horizontal motion blur over `px` pixels (premultiplied, so edges stay clean)."""
    k = int(px)
    if k < 2:
        return img
    a = np.asarray(img, dtype=np.float32)
    pm = a.copy()
    pm[..., :3] *= a[..., 3:4] / 255
    pad = np.pad(pm, ((0, 0), (k, k), (0, 0)))
    cs = np.cumsum(pad, axis=1)
    out = (cs[:, k * 2:] - cs[:, :-k * 2]) / (2 * k)
    out = out[:, : a.shape[1]]
    al = np.maximum(out[..., 3:4], 1e-3)
    out[..., :3] = out[..., :3] * 255 / al
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def frame(lay, n):
    """Frame `n` of the graphic, RGBA at lay.W x lay.H."""
    W, H = lay.W, lay.H
    tau = n / FPS
    a = bg_alpha(lay, tau)
    it = lay.item
    if lay.bg == "footage":
        canvas = Image.new("RGBA", (W, H), (8, 8, 10, int(255 * it["dim"] * a)))
        if it["align"] != "center":  # deeper on the side the text is
            g = np.linspace(1, 0, W)[None, :] ** 1.5 * 0.35 * a
            ga = Image.fromarray(np.repeat((g * 255).astype(np.uint8), H, axis=0), "L")
            shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            shade.putalpha(ga)
            canvas.alpha_composite(shade)
    else:
        ph = bg_phase(tau)
        if lay.bg == "photo" and lay.photo is not None:
            z = 1.0 + 0.04 * min(1.0, ph / max(1.0, lay.length))  # a slow push-in
            pw, phh = lay.photo.size
            # v0.4.55: the crop comes from the photo's real size. It was W*1.08 wide, but the photo
            # is int(W*1.08) wide, so at the first frames the box was a fraction of a pixel larger
            # than the photo and Pillow refused it ("box offset can't be negative").
            cw, ch = pw / z, phh / z
            box = (max(0.0, (pw - cw) / 2), max(0.0, (phh - ch) / 2), min(pw, (pw + cw) / 2), min(phh, (phh + ch) / 2))
            canvas = lay.photo.resize((W, H), Image.BILINEAR, box=box).convert("RGBA")
            dark = Image.new("RGBA", (W, H), (8, 8, 10, int(255 * it["dim"])))
            canvas.alpha_composite(dark)
        else:
            canvas = _charcoal(W, H, it["accent"]).copy()
        glow = _glow(W, H, it["accent"])
        gx = int(W * (0.62 + 0.07 * math.sin(2 * math.pi * ph / 14.0)) - glow.width / 2)
        gy = int(H * (0.42 + 0.05 * math.cos(2 * math.pi * ph / 17.0)) - glow.height / 2)
        _paste(canvas, glow, gx, gy)
        if a < 0.999:
            canvas.putalpha(canvas.getchannel("A").point(lambda v: int(v * a)))
    for el in lay.els:
        st = _state(el, tau)
        if st is None:
            continue
        p, q = ease_out(st[0]), st[1]
        img = el.img
        x, y = el.x, el.y
        alpha = 1.0
        kind = el.enter
        if kind == "mask":
            dy = int(round((1 - p) * img.height * 0.9))
            if dy:
                img = img.crop((0, 0, img.width, max(1, img.height - dy)))
                y += dy
            alpha = min(1.0, st[0] * 2.2)
        elif kind == "slide":
            dx = (1 - p) * W * 0.03
            vel = abs(W * 0.03 * 4 * (1 - min(1, st[0])) ** 3 / (el.d_in * FPS))  # px per frame
            if vel > 2 and st[0] < 0.9:
                img = _motion_blur(img, vel * 0.6)
            x -= int(round(dx))
            alpha = p
        elif kind == "settle":
            s = 1.0 + 0.04 * (1 - p)
            if s > 1.001:
                nw, nh = int(img.width * s), int(img.height * s)
                img = img.resize((nw, nh), Image.BICUBIC)
                x -= (nw - el.img.width) // 2
                y -= (nh - el.img.height) // 2
            alpha = p
        elif kind == "pop":
            s = 0.6 + 0.4 * p
            if s < 0.999:
                nw, nh = max(1, int(img.width * s)), max(1, int(img.height * s))
                img = img.resize((nw, nh), Image.BICUBIC)
                x += (el.img.width - nw) // 2
                y += (el.img.height - nh) // 2
            alpha = min(1.0, st[0] * 2)
        elif kind == "wipe":
            w = int(round(img.width * ease_io(st[0])))
            if w < 1:
                continue
            img = img.crop((0, 0, w, img.height))
        elif kind == "wipe_v":
            h = int(round(img.height * ease_io(st[0])))
            if h < 1:
                continue
            img = img.crop((0, 0, img.width, h))
        elif kind == "type" and el.chars:  # v0.4.56: character by character, a cursor while typing
            local = tau - el.t_in
            shown = bisect.bisect_right([c[0] for c in el.chars], local + 1e-6)
            if shown < 1:
                continue
            w = min(img.width, el.chars[shown - 1][1])
            img = img.crop((0, 0, max(1, w), img.height))
            if shown < len(el.chars) and q <= 0:
                cw_, ch_ = max(2, int(img.height * 0.07)), int(img.height * 0.62)
                _paste(canvas, rect_sprite(cw_, ch_, _rgb(it["accent"])), x + w + 2, y + int(img.height * 0.2))
        else:  # fade
            alpha = p
        if q > 0:
            qe = ease_in(q)
            if el.exit == "slide":
                x += int(round(qe * W * 0.02))
                alpha *= 1 - qe
            elif el.exit == "mask":
                dy = int(round(qe * img.height))
                img = img.crop((0, 0, img.width, max(1, img.height - dy)))
                y += 0  # sinks behind its own baseline
                alpha *= 1 - qe * 0.3
            else:
                alpha *= 1 - qe
        img = _alpha(img, alpha, el.lut if img is el.img else None)
        if img is not None:
            _paste(canvas, img, x, y)
    return canvas


# ====================================================================== cache, preview, export

def item_hash(item, W, H, background=""):
    keep = {k: v for k, v in item.items() if k not in ("status", "reason", "source", "id", "hide_captions")}
    if keep.get("background") != "still":
        keep.pop("still_at", None)
    return hashlib.sha1(json.dumps([ENGINE, keep, W, H, str(background or "")], sort_keys=True).encode()).hexdigest()[:20]


def footage_at(project, t):
    """(asset, seconds into it, or None for a picture) of the footage on the timeline at `t`,
    the same way the export cuts it (trim, crop, looped crop). None when there is no footage."""
    scenes = project.get("scenes") or []
    if not scenes:
        return None
    assets = {a["id"]: a for a in project.get("assets") or []}
    offsets, total = scene_offsets(scenes)
    t = max(0.0, min(float(t), total - 1e-3))
    i = max(k for k in range(len(scenes)) if offsets[k] <= t + 1e-9)
    sc = scenes[i]
    a = assets.get(sc.get("asset_id"))
    if not a or a.get("kind") not in ("image", "video"):
        return None
    if a["kind"] == "image":
        return a, None
    dur = float(sc.get("duration") or 0)
    trim = max(0.0, float(sc.get("trim_start", 0) or 0))
    crop_end = float(sc["source_crop_end"]) if sc.get("source_crop_end") is not None else trim + dur
    crop_end = min(max(trim, crop_end), float(a.get("duration", 0) or 0) or crop_end)
    crop = crop_end - trim
    if crop <= 0:
        return None
    return a, round(trim + (t - offsets[i]) % crop, 3)


def background_path(project, item, data, asset_path):
    """The picture behind a graphic: one of your photos, or a still from your own footage at
    `still_at` (taken once with FFmpeg and cached). None: the charcoal (nothing is made up)."""
    bg = item.get("background")
    if bg == "photo":
        a = next((x for x in project.get("assets") or [] if x["id"] == item.get("photo_id") and x.get("kind") == "image"), None)
        src = (a, None) if a else None
    elif bg == "still":
        src = footage_at(project, item.get("still_at", item.get("start", 0)))
    else:
        return None
    if not src:
        return None
    a, sec = src
    try:
        path = Path(asset_path(a))
    except (OSError, ValueError, KeyError):
        return None
    if sec is None:
        return str(path)
    st = path.stat()
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}|{sec:.3f}".encode()).hexdigest()[:20]
    out = cache_root(data) / "stills" / f"{key}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(f".{threading.get_ident()}.tmp.jpg")
        import subprocess
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{sec:.3f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale='min(1920,iw)':-2", "-q:v", "3", str(tmp)], capture_output=True, timeout=60)
        if tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, out)
        else:
            tmp.unlink(missing_ok=True)
            return None
    return str(out)


def cache_root(data):
    return Path(data) / "cache" / "motion"


def plan(lay):
    """For every frame, the index of its unique drawing: identical frames share one."""
    if lay.plan:
        return lay.plan
    keys, frames = {}, []
    for n in range(lay.frames):
        k = frame_key(lay, n)
        if k not in keys:
            keys[k] = len(keys)
        frames.append(keys[k])
    lay.plan = (frames, len(keys))
    return lay.plan


def preview_size(project):
    W, H = effects.frame_size("1080p", effects.aspect_of(project))
    pw = SPEC["preview_width"] if W >= H else round(SPEC["preview_width"] * W / H / 2) * 2
    return pw, round(pw * H / W / 2) * 2


_LAYOUTS: dict = {}
_LAYOUT_LOCK = threading.Lock()


def _layout(item, W, H, photo_path):
    key = (item_hash(item, W, H), photo_path)
    with _LAYOUT_LOCK:
        lay = _LAYOUTS.get(key)
    if lay is None:
        lay = build(item, W, H, photo_path)
        with _LAYOUT_LOCK:
            if len(_LAYOUTS) > 12:
                _LAYOUTS.pop(next(iter(_LAYOUTS)))
            _LAYOUTS[key] = lay
    return lay


def preview_plan(data, project, item, photo_path=None):
    """{hash, width, height, fps, frames: [unique index per frame], unique} for the editor; the
    item is kept so its frames can be drawn when asked for."""
    W, H = preview_size(project)
    h = item_hash(item, W, H, photo_path)
    folder = cache_root(data) / h
    folder.mkdir(parents=True, exist_ok=True)
    spec = folder / "item.json"
    if not spec.exists():
        spec.write_text(json.dumps({"item": item, "W": W, "H": H, "photo": str(photo_path or "")}))
    lay = _layout(item, W, H, photo_path)
    frames, unique = plan(lay)
    return {"hash": h, "width": W, "height": H, "fps": FPS, "frames": frames, "unique": unique, "start": item["start"],
            "layout": lay.layout, "layouts": layout_options(item, H > W), "background": lay.bg}


_DRAWING = threading.BoundedSemaphore(2)  # preview drawings at a time (the editor stays responsive)


def preview_frame(data, h, k):
    """The unique drawing `k` of a planned graphic (cached WebP)."""
    if not re.fullmatch(r"[0-9a-f]{20}", h):
        raise KeyError(h)
    folder = cache_root(data) / h
    out = folder / f"{int(k):05d}.webp"
    if out.exists():
        return out
    spec = json.loads((folder / "item.json").read_text())
    lay = _layout(spec["item"], spec["W"], spec["H"], spec["photo"] or None)
    frames, unique = plan(lay)
    if not 0 <= int(k) < unique:
        raise KeyError(k)
    n = frames.index(int(k))
    with _DRAWING:
        if out.exists():
            return out
        tmp = out.with_suffix(f".{threading.get_ident()}.tmp")
        frame(lay, n).save(tmp, "WEBP", quality=86, method=0, alpha_quality=90)
        os.replace(tmp, out)
    return out


_WARM = {"queue": [], "busy": False}
_WARM_LOCK = threading.Lock()


def warm(data, h, unique, paused=lambda: False):
    """Draw a planned graphic's frames in the background (one at a time, never during an export)."""
    with _WARM_LOCK:
        if h in _WARM["queue"]:
            return
        _WARM["queue"].append(h)
        if _WARM["busy"]:
            return
        _WARM["busy"] = True

    def run():
        while True:
            with _WARM_LOCK:
                if not _WARM["queue"]:
                    _WARM["busy"] = False
                    return
                cur = _WARM["queue"][0]
            for k in range(unique if cur == h else 10 ** 6):
                while paused():
                    time.sleep(0.5)
                try:
                    preview_frame(data, cur, k)
                except (KeyError, OSError, ValueError):
                    break
            with _WARM_LOCK:
                if cur in _WARM["queue"]:
                    _WARM["queue"].remove(cur)

    threading.Thread(target=run, daemon=True, name="motion-warm").start()


def prune(data, keep_bytes=2_000_000_000):
    """Keep the motion cache under ~2 GB (oldest graphics go first)."""
    root = cache_root(data)
    if not root.exists():
        return
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
    sizes = {d: sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) for d in dirs}
    total = sum(sizes.values())
    for d in dirs:
        if total <= keep_bytes:
            break
        shutil.rmtree(d, ignore_errors=True)
        total -= sizes[d]


def encode(lay, out, workers=2, cancelled=lambda: False):
    """v0.4.53: every frame of a graphic into one video with transparency (QuickTime Animation,
    lossless; quick to seek). The unique drawings are made by `workers` threads, in order, and
    piped to FFmpeg as they are ready: no image files (writing PNGs took 3x longer than drawing).
    Returns the number of drawings made."""
    import subprocess
    frames, unique = plan(lay)
    first, last = {}, {}
    for n, k in enumerate(frames):
        first.setdefault(k, n)
        last[k] = n
    out = Path(out)
    tmp = out.with_name(f"{out.stem}.{threading.get_ident()}.tmp.mov")
    log = out.with_name(f"{out.stem}.{threading.get_ident()}.log")
    with open(log, "wb") as err:
        proc = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
                                 "-s", f"{lay.W}x{lay.H}", "-r", str(FPS), "-i", "-", "-c:v", "qtrle", "-pix_fmt", "argb",
                                 "-g", str(FPS), "-f", "mov", str(tmp)], stdin=subprocess.PIPE, stderr=err)
    ok = False
    try:
        with ThreadPoolExecutor(max(1, workers)) as pool:
            pending, live, nxt = {}, {}, 0

            def draw(k):
                return frame(lay, first[k]).tobytes()

            for n, k in enumerate(frames):
                if k not in live:
                    while nxt < unique and len(pending) < max(1, workers) + 1:
                        pending[nxt] = pool.submit(draw, nxt)
                        nxt += 1
                    live[k] = pending.pop(k).result()
                    if cancelled():
                        raise RuntimeError("Cancelled by you. No output was published.")
                proc.stdin.write(live[k])
                if last[k] == n:
                    del live[k]
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("FFmpeg could not write the motion graphic: " + log.read_text(errors="replace")[-300:])
        os.replace(tmp, out)
        ok = True
    except (BrokenPipeError, OSError) as e:
        raise RuntimeError(f"FFmpeg could not write the motion graphic: {e} {log.read_text(errors='replace')[-300:]}")
    finally:
        if not ok:
            proc.kill()
            proc.wait()
            tmp.unlink(missing_ok=True)
        log.unlink(missing_ok=True)
    return unique


def describe(it):
    """A graphic named for a message: its template, title and time in the video."""
    s = max(0, int(it.get("start") or 0))
    title = str(it.get("title") or "").strip()
    name = f"{it.get('template', 'motion')} graphic" + (f" \u201c{title}\u201d" if title else "")
    return f"{name} at {s // 60}:{s % 60:02d}"


def prepare(project, width, height, data, folder, background=None, workers=None, cancelled=lambda: False, failed=None):
    """Every exported graphic as one transparent video at the export size, cached by content (an
    unchanged graphic is not drawn again). `background(item)` gives its photo or footage still.
    Returns [{start, end, file, frames, unique, drawn, id}].
    v0.4.55: with a `failed` list, a graphic that cannot be drawn is left out on its own (its item
    and the error are added to the list) and the others are still made; without it, it raises."""
    layers = []
    items = exported(project)
    if not items:
        return layers
    # measured (v0.4.53, 2 vCPUs): one drawing thread while FFmpeg encodes on the other core was the
    # quickest; a second thread added ~180 MB and no speed. Bigger machines get two.
    workers = workers or (1 if (os.cpu_count() or 2) <= 4 else 2)
    for it in items:
        if cancelled():
            raise RuntimeError("Cancelled by you. No output was published.")
        try:
            pp = background(it) if (background and it["background"] in ("photo", "still")) else None
            h = item_hash(it, width, height, pp)
            cache = cache_root(data) / h
            cache.mkdir(parents=True, exist_ok=True)
            out = cache / "export.mov"
            lay = build(it, width, height, pp)
            frames, unique = plan(lay)
            drawn = 0
            if not out.exists():
                drawn = encode(lay, out, workers, cancelled)
            else:
                os.utime(cache)  # recently used: kept by prune
        except (ValueError, OSError, KeyError, TypeError, ZeroDivisionError, RuntimeError) as e:
            if failed is None or cancelled():
                raise
            failed.append((it, e))
            continue
        s0 = round(it["start"] * FPS) / FPS
        layers.append({"start": s0, "end": s0 + len(frames) / FPS, "file": out, "frames": len(frames),
                       "unique": unique, "drawn": drawn, "id": it["id"]})
    return layers


def overlay_filters(layer, k, scene_start, scene_len):
    """(input args, filter text) to overlay a prepared graphic on a scene, or None. Continues a
    filter chain like stickers.overlay_filters. The graphic's video is read from the frame the scene
    needs (seeking half a frame early keeps it exact to the frame)."""
    a, b = max(layer["start"], scene_start), min(layer["end"], scene_start + scene_len)
    if b - a < 1 / FPS:
        return None
    first = round((a - layer["start"]) * FPS)
    ra, rb = a - scene_start, b - scene_start
    args = ["-ss", f"{max(0.0, (first - 0.5) / FPS):.4f}", "-t", f"{b - a + 2 / FPS:.4f}", "-i", str(layer["file"])]
    text = (
        f"[mgb{k}];[{k}:v]format=rgba,setpts=PTS-STARTPTS+{ra:.4f}/TB[mgv{k}];"
        f"[mgb{k}][mgv{k}]overlay=0:0:eof_action=pass:enable='between(t,{ra:.4f},{rb - 0.0001:.4f})':format=auto"
    )
    return args, text
