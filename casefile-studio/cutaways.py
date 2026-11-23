"""Picture cutaways on long Re-cut clips (v0.4.38).

While a real clip plays with its own sound, the picture may leave the speaker
for a few seconds to show what they are talking about (her photo, the court,
the place), then come back to their face. The sound never changes.

Two ways to get them:
- planned, from the re-cut list's cutaway table (``| RC | From | To | Show |``,
  times inside the clip), written by the Guide-Writer from the script's
  cutaway points; these always win;
- automatic, for long clips (12 s or more) that have none planned: Casefile
  picks matching base images from the speaker (family -> V, court -> C/court,
  police -> C/police; S only when the words name the suspect and the speaker
  is not family).

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
COURT = re.compile(r"\b(judge|solicitor|prosecutor|attorney|counsel|defen[cs]e|lawyer|clerk|magistrate|court)\b", re.I)
POLICE = re.compile(r"\b(police|chief|sheriff|detective|officer|investigator|coroner|deputy|agent|spokes\w*)\b", re.I)
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


def speaker(who):
    who = str(who or "")
    if FAMILY.search(who):
        return "family"
    if COURT.search(who):
        return "court"
    if POLICE.search(who):
        return "police"
    return "other"


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


def auto_plan(length, who="", words="", victim="", suspect="", card=False):
    """Base-image cutaways for a long clip with none planned."""
    if length < AUTO_MIN:
        return []
    kind = speaker(who)
    text = f" {words} ".lower()
    names = lambda full: [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'’-]{2,}", full or "")]
    hits = lambda full: any(re.search(rf"\b{re.escape(n)}\b", text) for n in names(full))
    if kind != "family" and suspect and hits(suspect):
        show = {"kind": "base", "bucket": "S", "tags": ["court"] if kind == "court" else [], "exclude": []}
    elif kind == "family" or (victim and hits(victim)):
        show = {"kind": "base", "bucket": "V", "tags": [], "exclude": []}
    elif kind == "court":
        show = {"kind": "base", "bucket": "C", "tags": ["court"], "exclude": []}
    elif kind == "police":
        show = {"kind": "base", "bucket": "C", "tags": ["police"], "exclude": []}
    else:
        show = {"kind": "base", "bucket": "C", "tags": [], "exclude": []}
    out, t = [], HEAD_CARD if card else HEAD
    budget = length * AUTO_SHARE
    while t + 2.5 <= length - max(MIN_TAIL, 2.0) and budget >= 2.5:
        d = min(SHOT, length - max(MIN_TAIL, 2.0) - t, budget)
        if d < 2.5:
            break
        out.append({"from": round(t, 2), "to": round(t + d, 2), "show": dict(show), "label": show_label(show), "auto": True})
        budget -= d
        t += d + FACE_GAP
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
            def fits(i, with_tags=True):
                if show.get("bucket") and i["bucket"] != show["bucket"]:
                    return False
                if any(t in i["tags"] for t in show.get("exclude") or []):
                    return False
                return not with_tags or all(t in i["tags"] for t in show.get("tags") or [])
            options = [i for i in pool if fits(i)] or [i for i in pool if fits(i, False)]
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
