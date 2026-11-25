"""Picture cutaways on long Re-cut clips (v0.4.38).

While a real clip plays with its own sound, the picture may leave the speaker
for a few seconds to show what they are talking about (her photo, the court,
the place), then come back to their face. The sound never changes.

Two ways to get them:
- planned, from the re-cut list's cutaway table (``| RC | From | To | Show |``,
  times inside the clip), written by the Guide-Writer from the script's
  cutaway points; these always win;
- automatic, for long clips (12 s or more) that have none planned: Casefile
  shows what the clip is ABOUT, never the room the speaker is already in
  (v0.4.46). From the clip's words when the list has them (the victim's or the
  suspect's name, "my son", "the house", "the vigil", "police"...), else from
  who speaks: family, judge, prosecutor and lawyers -> the victim (V); the
  defendant, police, witnesses -> the place (C / location); a defence lawyer
  -> the suspect (S). Automatic cutaways never show a courtroom picture (most
  soundbites are filmed in one) and never a suspect picture under a family
  speaker or under the defendant himself. When a bucket has no pictures the
  next sensible one is used (victim -> place, place -> victim).

Rules (both ways): the face shows for the first 2.5 s at least (longer when a
name card is on) and the last 1.5 s; one cutaway is 1 to 8 s; cutaways cover
at most 60 % of the clip; never a suspect picture under a family speaker.
"""
from __future__ import annotations

import re

import basefill

AUTO_MIN = 12.0  # clips at least this long get automatic cutaways
HEAD, HEAD_CARD = 3.0, 4.5  # automatic: face first (longer when a name card shows)
MIN_HEAD, MIN_TAIL = 2.5, 1.5  # any cutaway: face at the start and the end
SHOT, FACE_GAP = 4.5, 3.0  # automatic: cutaway length, face between cutaways
MIN_SHOT, MAX_SHOT = 1.0, 8.0
AUTO_SHARE, MAX_SHARE = 0.5, 0.6

FAMILY = re.compile(r"\b(father|mother|mom|mum|dad|parent|grand\w*|sister|brother|aunt|uncle|cousin|son|daughter|wife|husband|"
                    r"fianc\w*|family|friend|stepfather|stepmother|godmother|godfather)\b", re.I)
DEFENDANT = re.compile(r"\b(defendant|accused|suspect|shooter|gunman|convicted|inmate|allocution)\b", re.I)
DEFENCE = re.compile(r"\b(defen[cs]e|public defender)\b", re.I)
COURT = re.compile(r"\b(judge|solicitor|prosecut\w*|attorney|counsel|lawyer|clerk|magistrate|court)\b", re.I)
POLICE = re.compile(r"\b(police|chief|sheriff|detective|officer|investigator|coroner|deputy|agent|spokes\w*)\b", re.I)

# v0.4.46 What the words of a clip are about (only used when the list gives the words, not a count).
TOPIC_WORDS = {
    "memorial": r"vigil|funeral|memorial|grave|graveside|cemetery|candles?|balloons?|buried|burial|casket|tribute",
    "victim": r"son|daughter|child|children|kids?|boy|girl|baby|grandson|granddaughter|grandbaby|nephew|niece|"
              r"victim|his life|her life|loved|miss (?:him|her)",
    "suspect": r"defendant|shooter|gunman|killer|murderer|accused|suspect",
    "place": r"house|home|apartment|street|road|block|neighbou?rhood|scene|car|vehicle|suv|truck|parking|store|"
             r"park|school|yard|porch|driveway|window|door|outside|corner|gas station",
    "police": r"police|officers?|cops?|detectives?|arrest\w*|911|investigat\w*|handcuff\w*|squad|patrol",
}
SHOWS = {
    "victim": ("V", [], []), "memorial": ("V", ["memorial"], []), "suspect": ("S", [], []),
    "place": ("C", ["location"], ["court"]), "police": ("C", ["police"], ["court"]),
}
ABOUT = {"victim": "the victim", "memorial": "the memorial", "suspect": "the suspect", "place": "the place",
         "police": "the police work"}
_T = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"


def _sec(text):
    text = str(text or "").strip()
    m = re.search(_T, text)
    if m:
        total = 0.0
        for part in m.group(0).replace(",", ".").split(":"):
            total = total * 60 + float(part)
        return total
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    return float(m.group(0).replace(",", ".")) if m else None


def speaker(who, suspect=""):
    """family | defendant | defence | court | police | other."""
    who = str(who or "")
    if FAMILY.search(who):
        return "family"
    named = bool(suspect) and any(re.search(rf"\b{re.escape(n)}\b", who.lower()) for n in _names(suspect))
    if DEFENCE.search(who) or (named and COURT.search(who)):
        return "defence"
    if DEFENDANT.search(who) or named:
        return "defendant"
    if COURT.search(who):
        return "court"
    if POLICE.search(who):
        return "police"
    return "other"


def _names(full):
    return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'’-]{2,}", full or "")]


def topic(kind, words="", victim="", suspect=""):
    """(topic, reason) for an automatic cutaway: what the clip is about."""
    text = f" {words or ''} ".lower()
    real = len(re.findall(r"[a-z]{2,}", text)) >= 3  # a word count like "39" says nothing
    allowed = [t for t in TOPIC_WORDS if not (t == "suspect" and kind in ("family", "defendant"))]
    if real:
        score = {}
        for t in allowed:
            pattern = TOPIC_WORDS[t]
            names = _names(victim if t == "victim" else suspect if t == "suspect" else "")
            if names:
                pattern += "|" + "|".join(re.escape(n) for n in names)
            score[t] = len(re.findall(rf"\b(?:{pattern})\b", text))
        best = max(allowed, key=lambda t: (score[t], -allowed.index(t)))
        if score[best]:
            return best, f"the words are about {ABOUT[best]}"
    default = {"family": "victim", "court": "victim", "defence": "suspect", "defendant": "place",
               "police": "place", "other": "place"}[kind]
    who = {"family": "the family's side", "court": "the court or a lawyer", "defence": "the defence",
           "defendant": "the defendant", "police": "the police", "other": "a witness"}[kind]
    return default, f"{who} is speaking" + ("" if real else " (the list gives no words to go on)")


def parse_show(text):
    """What a cutaway shows: footage window, a BASE- file, or a base hint."""
    raw = re.sub(r"[*_`]", "", str(text or "")).strip()
    low = raw.lower()
    if not raw or re.fullmatch(r"(?:stay on |back to )?(?:the )?(?:face|speaker|on camera|on-camera)\.?", low):
        return {"kind": "face"}
    m = re.search(r"BASE-[VSC][^\s|`\"'<>()\[\]]*?\.(?:jpe?g|png|webp|mp4|mov|webm|mkv)", raw, re.I)
    if m:
        return {"kind": "file", "name": m.group(0)}
    sid = re.match(r"\(?([A-Z]{1,3}\d{1,3})\)?\b", raw)
    span = re.findall(_T, raw)
    if sid and len(span) >= 2:
        return {"kind": "footage", "source_id": sid.group(1), "start": _sec(span[0]), "end": _sec(span[1])}
    hint = basefill.parse_hint(re.sub(r"^\s*fill\s*:?", "", raw, flags=re.I))
    if hint:
        return {"kind": "base", "bucket": hint["bucket"], "tags": hint["tags"], "exclude": hint["exclude"]}
    return None


def show_label(show):
    if not show:
        return "?"
    k = show["kind"]
    if k == "footage":
        return f"{show['source_id']} {_clock(show['start'])}–{_clock(show['end'])}"
    if k == "file":
        return show["name"]
    if k == "asset":
        return show.get("name") or "chosen picture"
    if k == "base":
        tags = "+".join(show.get("tags") or [])
        bits = [show.get("bucket") or "any"] + ([tags] if tags else []) + ["!" + t for t in show.get("exclude") or []]
        return " / ".join(bits)
    return "face"


def _clock(s):
    m, sec = divmod(max(0.0, float(s or 0)), 60)
    return f"{int(m)}:{sec:04.1f}"


def parse_row(frm, to, show):
    a, b = _sec(frm), _sec(to)
    parsed = parse_show(show)
    if a is None or b is None or parsed is None or parsed["kind"] == "face":
        return None
    return {"from": a, "to": b, "show": parsed, "label": show_label(parsed)}


def _base(t):
    bucket, tags, exclude = SHOWS[t]
    return {"kind": "base", "bucket": bucket, "tags": list(tags), "exclude": list(exclude)}


def auto_plan(length, who="", words="", victim="", suspect="", card=False):
    """Base-image cutaways for a long clip with none planned: what the clip is about."""
    if length < AUTO_MIN:
        return []
    kind = speaker(who, suspect)
    t, why = topic(kind, words, victim, suspect)
    # Next best when a bucket has no pictures; never the suspect under family or the defendant himself.
    order = [t] + {"victim": ["place"], "memorial": ["victim", "place"], "suspect": ["place"],
                   "place": ["victim"], "police": ["place", "victim"]}[t]
    show, alts = _base(order[0]), [_base(x) for x in order[1:]]
    out, at = [], HEAD_CARD if card else HEAD
    budget = length * AUTO_SHARE
    while at + 2.5 <= length - max(MIN_TAIL, 2.0) and budget >= 2.5:
        d = min(SHOT, length - max(MIN_TAIL, 2.0) - at, budget)
        if d < 2.5:
            break
        out.append({"from": round(at, 2), "to": round(at + d, 2), "show": dict(show), "alts": alts, "label": show_label(show),
                    "auto": True, "why": f"Shows {ABOUT[t]}: {why}."})
        budget -= d
        at += d + FACE_GAP
    return out


def clean(cuts, length, who=""):
    """Apply the rules; returns (cutaways, warnings)."""
    family = speaker(who) == "family"
    out, warnings = [], []
    for c in sorted(cuts or [], key=lambda x: x["from"]):
        a, b = max(MIN_HEAD, float(c["from"])), min(length - MIN_TAIL, float(c["to"]))
        if b - a > MAX_SHOT:
            warnings.append(f"Cutaway at {_clock(c['from'])} was longer than {MAX_SHOT:.0f} s; it was shortened.")
            b = a + MAX_SHOT
        if out and a < out[-1]["to"]:
            a = out[-1]["to"]
        if b - a < MIN_SHOT:
            warnings.append(f"Cutaway at {_clock(c['from'])} was left out: it needs at least {MIN_SHOT:.0f} s of picture between "
                            f"{MIN_HEAD:g} s from the start and {MIN_TAIL:g} s from the end of the clip.")
            continue
        show = c["show"]
        if family and show["kind"] == "base" and show.get("bucket") == "S":
            warnings.append(f"Cutaway at {_clock(c['from'])} was left out: no suspect picture while a family member speaks.")
            continue
        if family and show["kind"] in ("file", "asset") and re.match(r"BASE-S", show.get("name") or "", re.I):
            warnings.append(f"Cutaway at {_clock(c['from'])} was left out: no suspect picture while a family member speaks.")
            continue
        out.append({**c, "from": round(a, 3), "to": round(b, 3)})
    total = sum(c["to"] - c["from"] for c in out)
    while out and total > length * MAX_SHARE + 1e-6:
        last = out.pop()
        total -= last["to"] - last["from"]
        warnings.append(f"Cutaway at {_clock(last['from'])} was left out: cutaways may cover at most {int(MAX_SHARE * 100)}% of a clip.")
    return out, warnings


def resolve(cuts, pool, sources, used, file_path):
    """Give every cutaway a real file.

    pool: basefill.pool(project); sources: S-ID -> asset; used: {asset id: uses}
    shared across all clips so pictures rotate; file_path(asset) -> path.
    Returns (resolved, warnings). Each resolved cutaway has asset_id, name,
    kind ("image" | "video"), path and start (seconds into that file)."""
    out, warnings = [], []
    by_name = {i["name"].lower(): i for i in pool}
    for c in cuts:
        show, length = c["show"], c["to"] - c["from"]
        pick, start = None, 0.0
        if show["kind"] == "footage":
            a = sources.get(show["source_id"])
            if not a:
                warnings.append(f"Cutaway at {_clock(c['from'])}: no file for {show['source_id']} in the project.")
                continue
            pick = {"id": a["id"], "name": a["name"], "kind": "video", "duration": float(a.get("duration") or 0)}
            start = show["start"]
            length = min(length, max(0.0, show["end"] - show["start"]))
        elif show["kind"] == "asset":  # the producer picked this picture on the Re-cut page
            pick = next((i for i in pool if i["id"] == show["asset_id"]), None)
            if not pick:
                warnings.append(f"Cutaway at {_clock(c['from'])}: that picture is no longer in the project.")
                continue
        elif show["kind"] == "file":
            pick = by_name.get(show["name"].lower())
            if not pick:
                warnings.append(f"Cutaway at {_clock(c['from'])}: {show['name']} is not uploaded.")
                continue
        else:
            def fits_want(i, want, with_tags=True):
                if want.get("bucket") and i["bucket"] != want["bucket"]:
                    return False
                if any(t in i["tags"] for t in want.get("exclude") or []):
                    return False
                return not with_tags or all(t in i["tags"] for t in want.get("tags") or [])
            options = []
            for k, want in enumerate([show] + [a for a in c.get("alts") or [] if a.get("kind") == "base"]):
                fits_tags = lambda i, w=want: fits_want(i, w)
                options = [i for i in pool if fits_tags(i)] or [i for i in pool if fits_want(i, want, False)]
                if options:
                    if k:
                        warnings.append(f"Cutaway at {_clock(c['from'])}: no {show_label(show)} picture, so {show_label(want)} instead.")
                        show = want
                        c = {**c, "show": want, "label": show_label(want)}
                    break
            if not options:
                warnings.append(f"Cutaway at {_clock(c['from'])}: no base image for {show_label(show)}; the speaker stays on screen.")
                continue
            pick = min(options, key=lambda i: (used.get(i["id"], 0), pool.index(i)))
        if pick["kind"] == "video" and show["kind"] != "footage":
            if pick.get("window"):
                start = pick["window"][0]
                length = min(length, pick["window"][1] - pick["window"][0])
            else:
                length = min(length, pick["duration"])
        if length < MIN_SHOT:
            warnings.append(f"Cutaway at {_clock(c['from'])}: the picture is too short; the speaker stays on screen.")
            continue
        used[pick["id"]] = used.get(pick["id"], 0) + 1
        asset = {"id": pick["id"], "name": pick["name"], "kind": pick["kind"]}
        out.append({**c, "to": round(c["from"] + length, 3), "asset_id": pick["id"], "name": pick["name"], "kind": pick["kind"],
                    "path": file_path(asset), "start": round(start, 3)})
    return out, warnings
