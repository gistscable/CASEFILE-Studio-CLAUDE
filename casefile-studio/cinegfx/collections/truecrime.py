"""True-crime collection — the first niche. Six categories, each with its own detector (reads the story
model), its own identity (Theme) and its own composition (Graphic). All on-screen words come from the
script itself (verbatim or trimmed), attributed to the speaker the script attributes them to."""
from __future__ import annotations

import datetime as dt
import re

from PIL import Image

from .. import anim as A
from .. import draw as D
from .. import text as T
from ..core import Category, Collection, Graphic, register
from ..theme import Theme

INVESTIGATORS = re.compile(r"detective|police|investigator|prosecutor|district attorney|sheriff|officer|fbi|nypd", re.I)
FAMILY_ROLES = {"father", "mother", "sister", "brother", "uncle", "aunt", "son", "daughter", "wife", "husband", "family"}
STOP = set("the a an and or of to in on at by for with was were is are be been had has have that this those these it its "
           "he she they his her their them him who which did does not no never would could should said says told".split())


def short_date(d: dt.date) -> str:
    return f"{T.MONTH_ABBR[d.month]} {d.day}"


def long_date(d: dt.date) -> str:
    return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")


def headline(s: str) -> str:
    s = T.tidy(s).rstrip(".;,")
    return T.cap_first(s)


INCIDENT_NOUN = [(r"\bstabb(?:ed|ing)\b", "stabbing"), (r"\b(?:shot|shooting)\b", "shooting"), (r"\b(?:killed|killing|murder(?:ed)?)\b", "killing"),
                 (r"\bdied\b", "death")]


def incident_noun(story) -> str:
    """What the story's incident was called ("shooting", "stabbing" ...), from the sentence that dates it."""
    for s in story.sentences:
        if s.dates and re.search(r"\b(shot|shooting|killed|murder|stabbed|died)\b", s.text, re.I):
            for pat, noun in INCIDENT_NOUN:
                if re.search(pat, s.text, re.I):
                    return noun
    return "incident"


NYC = re.compile(r"\b(?:NYPD|New York|Bronx|Manhattan|Brooklyn|Queens|MTA)\b")
MTA_COLORS = {"1": "#EE352E", "2": "#EE352E", "3": "#EE352E", "4": "#00933C", "5": "#00933C", "6": "#00933C", "7": "#B933AD",
              "A": "#0039A6", "C": "#0039A6", "E": "#0039A6", "B": "#FF6319", "D": "#FF6319", "F": "#FF6319", "M": "#FF6319",
              "G": "#6CBE45", "J": "#996633", "Z": "#996633", "L": "#A7A9AC", "N": "#FCCC0A", "Q": "#FCCC0A", "R": "#FCCC0A", "W": "#FCCC0A"}


def named_in(story, text: str, exclude=()):
    """People named in `text` as actors (not only in a possessive like "Javits's mother"), in order."""
    out = []
    for p in story.people.values():
        if p.name in exclude:
            continue
        for alias in [p.name] + sorted(p.aliases, key=len, reverse=True):
            for m in re.finditer(rf"\b{re.escape(alias)}\b(?!['’]s)", text):
                out.append((m.start(), p.name))
                break
            else:
                continue
            break
    return [n for _, n in sorted(out)]


def content_words(s: str):
    return {w for w in (x.lower().rstrip("s") for x in T.tokens(s)) if w not in STOP and len(w) > 2}


# ============================================================ 1. INVESTIGATIVE FINDINGS

STATUS_PATTERNS = [
    (r"(?P<items>.+?)\s+(?:were|was|are|is)\s+(?:among the\s+)?possibilit(?:y|ies)", "POSSIBLE", "possible"),
    (r"(?:found|had found|have found)\s+no\s+(?:indication|evidence|sign)\s+(?:that\s+)?(?:\w+\s){0,3}?(?:was|were|is)\s+involved in\s+(?P<items>[\w\s-]+)", "NO INDICATION", "ruled"),
    (r"ruled out\s+(?P<items>[\w\s-]+)", "RULED OUT", "ruled"),
    (r"(?P<items>[\w\s-]+?)\s+(?:was|were|is|are)\s+(?:being\s+)?(?:examined|investigated|looked at)", "UNDER REVIEW", "open"),
]


def _finding_items(story, s):
    out = []
    for c in s.claims:
        src_role = story.role_of(c.source) or c.source
        if not INVESTIGATORS.search(src_role) and not INVESTIGATORS.search(c.source):
            continue
        for pat, status, kind in STATUS_PATTERNS:
            m = re.search(pat, c.content, re.I)
            if m:
                for it in re.split(r",\s*|\s+and\s+", m.group("items")):
                    it = it.strip()
                    if it and len(it.split()) <= 4:
                        out.append({"label": it.upper(), "status": status, "kind": kind, "phrase": it, "source": c.source,
                                    "evidence": c.content})
    # unattributed status lines: "No motive had been publicly announced as of November 13."
    m = re.match(r"No\s+(\w+)\s+had\s+been\s+(?:publicly\s+)?(\w+)", s.text)
    if m:
        note = f"AS OF {short_date(s.dates[0].date)}" if s.dates else ""
        out.append({"label": m.group(1).upper(), "status": "NOT " + m.group(2).upper(), "kind": "open", "phrase": m.group(0)[:len("No " + m.group(1))],
                    "note": note, "source": ""})
    return out


def detect_findings(story, a, b):
    items, sources, quotes = [], [], []
    for s in story.sentences[a:b]:
        got = _finding_items(story, s)
        items += got
        sources += [g["source"] for g in got if g["source"]]
        for c in s.claims:  # a reported characterisation by the same investigator becomes the pull-quote
            m = re.search(r"characterized\s+\w+\s+as\s+(the [^,.;]+)", c.content)
            if m:
                quotes.append({"quote": m.group(1), "by": c.content.split()[0], "via": c.source})
    if len(items) < 3 or not sources:
        return None
    lead = max(set(sources), key=sources.count)
    briefing = None
    for s in story.sentences:
        if lead in s.people and re.search(r"briefing|press conference|news conference", s.text) and s.dates:
            briefing = s.dates[0].date
            break
    score = 0.45 + 0.12 * len(items) + (0.1 if quotes else 0)
    agency = "NYPD" if any(lead in s.people and "NYPD" in s.text for s in story.sentences) else "POLICE"
    payload = {"source": lead, "role": story.role_of(lead), "items": items[:5], "quote": quotes[0] if quotes else None,
               "briefing": briefing.isoformat() if briefing else None, "agency": agency, "chapter": story.chapters[story.sentences[a].chapter].title,
               "chapter_no": story.chapters[story.sentences[a].chapter].number}
    return score, payload, [f"{len(items)} investigator findings with explicit status from {lead}"]


class FindingsGraphic(Graphic):
    def build(self):
        p = self.p
        self.photo_key, _ = self.assets.find(person=p["source"])
        last = 0
        self.rows = []
        for it in p["items"]:
            t0, t1 = self.span(it["phrase"], last)
            if t0 is None:
                continue
            hit = self.tl.phrase(it["phrase"], last)
            last = hit[3]
            self.rows.append(dict(it, t=max(0.35, t0 - 0.08), t_end=t1))
        q = p.get("quote")
        if q:
            self.q0, self.q1 = self.span(q["quote"])
        self.cue(0.0, "whoosh-mid-1", -6, "panel in")
        for i, r in enumerate(self.rows):
            self.cue(r["t"], f"click-mech-{i % 3 + 1}", -5, "finding row")
            self.cue(r["t"] + 0.14, "thump-deep-1" if r["kind"] == "open" and r["status"].startswith("NOT") else f"pop-soft-{i % 3 + 1}",
                     -10 if r["status"].startswith("NOT") else -8, "status chip")
        if q and self.q0 is not None:
            self.cue(self.q0 - 0.1, "paper-1", -8, "quote card")
        self.cue(self.out, "rwhoosh-1", -8, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        # faint case-board grid
        D.blit(c, _grid(th.c("ink", 9), 64), 0, 0, e_out)
        # --- photo panel (v0.4.64: "mirror" puts it on the right, the findings on the left)
        flip = th.traits.get("mirror")
        px0, py0, pw, ph = (1144 if flip else 96), 96, 680, 888
        if self.photo_key:
            e = A.ease(t, 0.0, 0.5, A.out_smooth)
            img = D.photo(self.assets.path(self.photo_key), pw, ph, focus=(0.77, 0.42), zoom=A.drift(t, self.duration, 0.07), sat=0.92, contrast=1.06)
            reveal = py0 + ph * (1 - e)
            D.blit(c, img, px0, py0, e_out, clip=(px0, reveal, px0 + pw, py0 + ph))
            D.blit(c, D.gradient(pw, 360, th.c("bg", 0), th.c("bg", 245)), px0, py0 + ph - 360, e * e_out)  # v0.4.63: was the navy (11, 17, 32) = the approved bg
            ax = px0 if flip else px0 + pw - 6  # the accent edge faces the findings
            D.rect(c, ax, reveal, ax + 6, py0 + ph, th.accent, e_out)
            en = A.ease(t, 0.3, A.FAST)
            name = p["source"].upper()
            ns = D.fit_size(name, th.display, pw - 80, 64, 36)  # v0.4.64: a long name (or a wider font) fits the panel
            D.text(c, name, th.display, ns, th.ink, px0 + 40 - 30 * (1 - en), py0 + ph - 170 + (64 - ns) * 0.6, en * e_out)
            D.text(c, (p["role"] or "").upper(), th.label, 22, th.accent, px0 + 42, py0 + ph - 88, en * e_out, tracking=0.14)
            cr = self.assets.credit(self.photo_key)
            if cr:
                D.rect(c, px0, py0, px0 + D.measure(cr, "mono", 14)[0] + 28, py0 + 34, "#000000", 0.55 * en * e_out)
                D.text(c, cr, "mono", 14, "#FFFFFF", px0 + 14, py0 + 9, 0.85 * en * e_out)
        # --- heading
        x0 = 96 if flip else 856
        ek = A.ease(t, 0.12, A.FAST)
        kicker = f"CHAPTER {p['chapter_no']} · {p['chapter'].upper()}" if p.get("chapter_no") else p["chapter"].upper()
        D.text(c, kicker, th.label, 20, th.muted, x0 + 30 * (1 - ek), 112, ek * e_out, tracking=0.16)
        eh = A.ease(t, 0.2, 0.34)
        surname = p["source"].split()[-1].upper()
        title = f"WHAT {surname} SAID"
        ts = D.fit_size(title, th.display, 960, 92, 56)  # v0.4.64: fits its 960 px (a long surname, a wider font)
        D.text(c, title, th.display, ts, th.ink, x0, 140 + (92 - ts) * 0.5, e_out, clip=(x0, 140, x0 + 960 * eh, 280))
        if p.get("briefing"):
            b = dt.date.fromisoformat(p["briefing"])
            D.text(c, f"{p.get('agency') or 'POLICE'} BRIEFING · {long_date(b).upper()}", "mono", 20, th.accent, x0 + 2, 268, A.ease(t, 0.45, A.FAST) * e_out)
        D.rect(c, x0, 312, x0 + 968 * A.ease(t, 0.3, 0.5), 315, th.ink, 0.25 * e_out)
        # --- finding rows
        y = 340
        for i, r in enumerate(self.rows):
            er = A.ease(t, r["t"], A.FAST)
            if er <= 0:
                y += D.lead(th.heading, 74) + D.lead(th.body, 30) + 8
                continue
            D.text(c, f"{i + 1:02d}", "mono", 22, th.accent, x0, y + 22, er * e_out)
            lx = x0 + 70 + 40 * (1 - er)
            D.text(c, r["label"], th.heading, 56, th.ink, lx, y, e_out, clip=(x0 + 60, y - 10, x0 + 70 + 700 * er, y + D.lead(th.heading, 90)))
            sub = r.get("note") or (f"{r['source'].split()[-1]} said" if r.get("source") else "")
            if r["kind"] == "ruled" and r.get("evidence"):
                sub = "“" + r["evidence"] + "”"
            sub = sub if len(sub) < 70 else sub[:67].rsplit(" ", 1)[0] + "…”"
            D.text(c, sub, th.body, 20, th.muted, x0 + 72, y + D.lead(th.heading, 74), A.ease(t, r["t"] + 0.2, A.FAST) * e_out)
            # status chip
            ec = A.prog(t, r["t"] + 0.14, A.SNAP)
            if ec > 0:
                chip = _chip(r["status"], th, r["kind"])
                s = A.out_back(ec, 1.6)
                cw, ch = max(1, int(chip.width * s)), max(1, int(chip.height * s))
                ci = chip.resize((cw, ch), Image.BICUBIC) if s != 1 else chip
                D.blit(c, ci, x0 + 968 - chip.width + (chip.width - cw) / 2, y + 14 + (chip.height - ch) / 2, min(1, ec * 3) * e_out)
            rule = y + D.lead(th.heading, 74) + D.lead(th.body, 30)
            D.rect(c, x0, rule, x0 + 968 * A.ease(t, r["t"], 0.5), rule + 1, th.ink, 0.12 * e_out)
            y = rule + 8
        # --- pull quote, typed in time with the narration
        q = p.get("quote")
        if q and self.q0 is not None:
            eq = A.ease(t, self.q0 - 0.1, A.FAST)
            qy = max(812, y + 24)  # v0.4.64: under the rows when a larger text size makes them taller
            D.rect(c, x0, qy, x0 + 8, qy + (60 + 54 * len(D.wrap("“" + q["quote"] + "”", "caladea", 44, 900))) * eq, th.accent, e_out)
            shown = A.typed_until("“" + q["quote"] + "”", t, self.q0, self.q1)
            for j, line in enumerate(D.wrap("“" + q["quote"] + "”", "caladea", 44, 900)):
                start = sum(len(l) + 1 for l in D.wrap("“" + q["quote"] + "”", "caladea", 44, 900)[:j])
                part = shown[start:start + len(line)]
                D.text(c, part, "caladea", 44, th.ink, x0 + 34, qy + 4 + j * 54, e_out)
            nl = len(D.wrap("“" + q["quote"] + "”", "caladea", 44, 900))
            D.text(c, f"{q['by'].upper()}, AS REPORTED BY {q['via'].upper()}", th.label, 18, th.muted,
                   x0 + 36, qy + 22 + nl * 54, A.ease(t, self.q1 or 0, A.FAST) * e_out, tracking=0.12)


def _chip(status, th, kind):
    key = ("chip", status, th.name, kind)
    if key not in _CACHE:
        f, size = th.label, 22
        w, _ = D.measure(status, f, size, 0.1)
        cw, ch = w + 40, 46
        if kind == "possible":
            box = D.rounded(cw, ch, 6, th.c("accent"))
            fg = th.bg
        elif kind == "ruled":
            box = D.rounded(cw, ch, 6, th.c("bg2"), th.c("muted"), 2)
            fg = th.muted
        else:
            box = D.rounded(cw, ch, 6, th.c("bg2"), th.c("accent2"), 2)
            fg = th.accent2
        im = box.copy()
        im.alpha_composite(D.sprite(status, f, size, D.col(fg), 0.1), (20, 9))
        _CACHE[key] = im
    return _CACHE[key]


_CACHE = {}


def _grid(color, step):
    key = ("grid", color, step)
    if key not in _CACHE:
        im = Image.new("RGBA", (D.W, D.H), (0, 0, 0, 0))
        for x in range(0, D.W, step):
            im.paste(color, (x, 0, x + 1, D.H))
        for y in range(0, D.H, step):
            im.paste(color, (0, y, D.W, y + 1))
        _CACHE[key] = im
    return _CACHE[key]


# ============================================================ 2. CHRONOLOGICAL TIMELINE

EVENT_SPLIT = re.compile(r"\b(came|took place|was held|were held|ended|began|happened)\b")


def _events(story, a, b):
    evs = []
    for s in story.sentences[a:b]:
        if not s.dates:
            continue
        # clause boundaries: ; and ", and" and ", the"
        cuts = list(re.finditer(r";\s*|,\s+and\s+(?=the\b)", s.text))
        starts = [0] + [m.end() for m in cuts]
        ends = [m.start() for m in cuts] + [len(s.text)]
        for i in range(len(starts)):
            ca, cb = starts[i], ends[i]
            clause = s.text[ca:cb]
            ds = [d for d in s.dates if ca <= d.start < cb and not d.back]
            if not ds:
                continue
            main = ds[0]
            rel = None
            label = clause
            for d in ds[1:]:
                # "one week after the October 29 shooting": a relation to an earlier anchor event
                m = re.search(r"(one week|\w+ days?|a day|\w+ weeks?)\s+(after|before)\s+the\s+" + re.escape(d.text) + r"\s+(\w+)", clause)
                if m:
                    rel = {"date": d.date.isoformat(), "span": m.group(1), "dir": m.group(2), "event": m.group(3),
                           "phrase_span": m.group(1) + " " + m.group(2), "phrase_anchor": d.text + " " + m.group(3)}
            label = label.replace(main.text, "")
            label = re.sub(r"^\s*(?:and\s+)?(?:on\s*,?\s*)?", "", label)
            label = re.sub(r"\s+on\s*$", "", label.strip(" ,;."))
            label = re.sub(r"^(?:The|the)\s+(?=\w)", "The ", label)
            label = re.sub(r"\s{2,}", " ", label).strip(" ,")
            sub = ""
            m = EVENT_SPLIT.search(label)
            if m and m.start() > 3:
                sub = label[m.start():]
                label = label[:m.start()].strip()
                if rel:
                    sub = ""
            label = re.sub(r"^(?:The|the)\s+", "", label) if len(label.split()) > 2 and main.relative else label
            m = re.search(r"\b(vigil|memorial|funeral)\b", label, re.I)
            evs.append({"date": main.date.isoformat(), "label": headline(label), "sub": sub.strip(" ,."), "phrase_date": main.text,
                        "phrase_clause": clause.strip(" ,;")[:40], "rel": rel, "sent": s.i,
                        "people": named_in(story, label, exclude={story.subject}), "tag": m.group(1).lower() if m else ""})
    return evs


CLOCK = re.compile(r"\b(?:between\s+)?(\d{1,2}):(\d{2})(?:\s*(a\.m\.|p\.m\.|am|pm))?(?:\s+and\s+(\d{1,2}):(\d{2})(?:\s*(a\.m\.|p\.m\.|am|pm))?)?")


def _clock_events(story, a, b):
    """One day, minute by minute: sentences that give an exact clock time ("At 3:33 p.m., ...", "between 2:41 and
    3:27 p.m."), on the day the chapter has dated. Approximate times ("shortly after 3:30") are not events."""
    ch = story.sentences[a].chapter
    day = None
    for s in story.sentences[:b]:
        if s.chapter == ch:
            day = next((d for d in s.dates if not d.back), None) or day
    if not day:
        return []
    evs, half = [], ""
    for s in story.sentences[a:b]:
        m = CLOCK.search(s.text)
        if not m or re.search(r"\b(?:shortly|about|around|approximately|just)\s+(?:after|before)?\s*$", s.text[:m.start()]):
            continue
        h1 = (m.group(3) or m.group(6) or half or "").lower()
        half = h1 or half
        ampm = "AM" if h1.startswith("a") else "PM" if h1.startswith("p") else ""
        t1 = f"{int(m.group(1))}:{m.group(2)}"
        clock = t1 + (f"–{int(m.group(4))}:{m.group(5)}" if m.group(4) else "")
        # the clause around the time, without the time and the attribution
        label = (s.text[:m.start()] + s.text[m.end():]).strip()
        label = re.sub(r"^(?:At|at|By|Around)\s*,?\s*", "", label)
        label = re.sub(r",?\s*(?:police|prosecutors|investigators|detectives|officials)\s+said,?", "", label)
        label = re.sub(r"^(?:According to [^,]+,\s*)", "", label)
        label = re.sub(r"\s+(?:toward|towards|near)\b.*$", "", label.strip(" ,.;"))
        label = re.sub(r"\s{2,}", " ", label).strip(" ,.;")
        evs.append({"date": day.date.isoformat(), "clock": clock, "ampm": ampm, "label": headline(label), "sub": "", "phrase_date": m.group(0).replace("between ", ""),
                    "phrase_clause": s.text.strip(" ,;")[:40], "rel": None, "sent": s.i, "people": [], "tag": ""})
    return evs


def detect_timeline(story, a, b):
    evs = _events(story, a, b)
    dates = {e["date"] for e in evs}
    if len(dates) < 3 or b - a > 3:
        evs = _clock_events(story, a, b)
        if len({e["clock"] for e in evs}) < 3 or story.sentences[a].i not in [e["sent"] for e in evs]:
            return None
        ch = story.chapters[story.sentences[a].chapter]
        return 0.6 + 0.1 * len(evs), {"events": evs, "chapter": ch.title, "chapter_no": ch.number, "incident": None, "clock": True}, \
            [f"{len(evs)} clock times on {evs[0]['date']}"]
    ch = story.chapters[story.sentences[a].chapter]
    return 0.5 + 0.12 * len(dates), {"events": evs, "chapter": ch.title, "chapter_no": ch.number,
                                      "incident": story.incident_date().isoformat() if story.incident_date() else None}, [f"{len(dates)} dated events"]


class TimelineGraphic(Graphic):
    def build(self):
        evs = self.p["events"]
        self.events = []
        last = 0
        for e in evs:
            ca = self.tl.phrase(e["phrase_clause"][:24], last)
            dp = self.tl.phrase(e["phrase_date"], ca[2] if ca else last)
            t_clause = ca[0] if ca else 0.4
            t_date = dp[0] if dp else t_clause
            last = (dp or ca)[3] if (dp or ca) else last
            ev = dict(e, t=max(0.45, min(t_clause, t_date) - 0.05), td=max(0.5, t_date))
            if e.get("rel"):
                ev["t_rel"] = self.at(e["rel"]["phrase_span"], default=ev["t"] + 1)
                ev["t_anchor"] = self.at(e["rel"]["phrase_anchor"], default=ev["t_rel"] + 0.6)
            self.events.append(ev)
        # positions: a broken axis — the anchor event (incident) at left, then the run of events evenly
        self.xs = [640 + i * (1690 - 640) / max(1, len(self.events) - 1) for i in range(len(self.events))]
        # v0.4.64: five or more events are closer than a 330 px card: the cards, their labels and the big dates narrow to
        # the spacing (with a gap), so neighbouring labels never run into each other. Up to four events: as designed.
        step = (self.xs[1] - self.xs[0]) if len(self.xs) > 1 else 1050
        self.crowded = step < 330 + 16
        self.card_w = 330 if not self.crowded else int(step - 32)
        # a card shows a photo of a person it names (assigned by the producer), or of the vigil / memorial it is
        # about when it is the last card; never the subject's own photo on someone else's card
        self.card_photo = {}
        for i, e in enumerate(self.events):
            key = next((k for k in (self.assets.find(person=n)[0] for n in e.get("people") or []) if k), None)
            if not key and e.get("tag") and i == len(self.events) - 1:
                key, _ = self.assets.find(tag=e["tag"])
            if key:
                self.card_photo[i] = (key, (0.55, 0.32) if e.get("people") else (0.62, 0.6))
        self.cue(0.05, "whoosh-dir-r", -7, "rail")
        for i, e in enumerate(self.events):
            self.cue(e["t"], f"click-muted-{i % 3 + 1}", -6, "event card")
            self.cue(e["td"], "tick-1", -6, "date lands")
            if e.get("rel"):
                self.cue(e["t_rel"], "sweep-down-1", -12, "reach back in time")
                self.cue(e["t_anchor"], "thump-deep-1", -9, "anchor event")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        ek = A.ease(t, 0.05, A.FAST)
        D.text(c, f"CHAPTER {p['chapter_no']}" if p.get("chapter_no") else "", th.label, 20, th.accent, 120, 96, ek * e_out, tracking=0.2)
        eh = A.ease(t, 0.12, 0.4)
        chap = p["chapter"].upper()
        cs = D.fit_size(chap, th.display, 1680, 72, 44)  # v0.4.64: a long chapter title (or a wider font) fits the width
        D.text(c, chap, th.display, cs, th.ink, 120, 124 + (72 - cs) * 0.5, e_out, clip=(120, 120, 120 + 1700 * eh, 240))
        first = dt.date.fromisoformat(p["incident"]) if p.get("incident") else dt.date.fromisoformat(self.events[0]["date"])
        lastd = dt.date.fromisoformat(self.events[-1]["date"])
        if p.get("clock"):  # one day: the date once, then the clock span
            e0, e1 = self.events[0], self.events[-1]
            span = f"{e0['clock'].split('–')[0]} {e0.get('ampm', '')} — {e1['clock'].split('–')[-1]} {e1.get('ampm', '')}".replace("  ", " ")
            D.text(c, f"{short_date(lastd)}, {lastd.year} · {span}".upper().strip(), "mono", 22, th.muted, 1800, 108, ek * e_out, anchor="r")
        else:
            D.text(c, f"{short_date(first)} — {short_date(lastd)}, {lastd.year}".upper(), "mono", 22, th.muted, 1800, 108, ek * e_out, anchor="r")
        # rail
        ry = 560
        er = A.ease(t, 0.05, 0.6, A.out_quint)
        D.rect(c, 520, ry - 2, 520 + (1800 - 520) * er, ry + 2, th.ink, 0.55 * e_out)
        # anchor (incident) region left of the axis break
        ax = 220
        for e in self.events:
            if e.get("rel") and t >= e["t_rel"]:
                # bracket reaching back from this event to the anchor
                i = self.events.index(e)
                ex = self.xs[i]
                pb = A.ease(t, e["t_rel"], 0.55, A.out_quint)
                bx = ex + (ax - ex) * pb
                by = ry - 196
                D.rect(c, bx, by, ex, by + 3, th.accent, e_out)
                D.rect(c, ex - 1, by, ex + 2, by + 34, th.accent, e_out)
                if pb > 0.98:
                    D.rect(c, ax - 1, by, ax + 2, ry - 24, th.accent, e_out)
                span = e["rel"]["span"].upper() + " " + e["rel"]["dir"].upper()
                D.text(c, span, th.label, 22, th.accent, (ax + ex) / 2, by - 40, A.ease(t, e["t_rel"] + 0.2, A.FAST) * e_out, tracking=0.16, anchor="c")
                # axis break marks + anchor node
                ea = A.prog(t, e["t_anchor"], A.SNAP)
                if ea > 0:
                    D.rect(c, ax - 100, ry - 2, ax + 160, ry + 2, th.ink, 0.55 * e_out)
                    for k in (0, 18):
                        D.polyline(c, [(ax + 200 + k, ry + 16), (ax + 216 + k, ry - 16)], th.ink, 3, 0.6 * e_out)
                    s = A.out_back(ea, 1.8)
                    dsz = max(2, int(34 * s))
                    D.blit(c, D.disc(dsz, th.c("bg"), th.c("accent"), 5), ax - dsz / 2, ry - dsz / 2, e_out)
                    ad = dt.date.fromisoformat(e["rel"]["date"])
                    D.text(c, short_date(ad), th.display, 64, th.accent, ax, ry + 40, min(1, ea * 2) * e_out, anchor="c")
                    D.text(c, ("THE " + e["rel"]["event"]).upper(), th.label, 22, th.muted, ax, ry + 126, min(1, ea * 2) * e_out, tracking=0.16, anchor="c")
        # events
        for i, e in enumerate(self.events):
            x = self.xs[i]
            ee = A.ease(t, e["t"], A.FAST)
            if ee <= 0:
                continue
            ed = A.prog(t, e["td"], A.SNAP)
            dsz = max(2, int(26 * A.out_back(ed, 1.8))) if ed > 0 else 0
            if dsz:
                D.blit(c, D.disc(dsz, th.c("ink")), x - dsz / 2, ry - dsz / 2, e_out)
            d = dt.date.fromisoformat(e["date"])
            # big date above the rail, rises into place when spoken
            if ed > 0:
                dy = ry - 120 + 30 * (1 - A.out_smooth(ed))
                big = e.get("clock") or short_date(d)
                if self.crowded:  # v0.4.64: the date fits its narrower column
                    size = D.fit_size(big, th.display, self.card_w, 92, 40)
                    half = self.card_w / 2 + 8
                else:
                    size = D.fit_size(big, th.display, 390, 92, 48) if e.get("clock") else 92
                    half = 200
                D.text(c, big, th.display, size, th.ink, x, dy - 20 + (92 - size) * 0.5, e_out, anchor="c", clip=(x - half, ry - 150, x + half, ry - 12))
                if e.get("ampm"):
                    D.text(c, e["ampm"], th.label, 20, th.accent, x, ry - 150 - 8, min(1, ed * 2) * e_out, anchor="c", tracking=0.2)
            # card below the rail
            cy = ry + 40
            card_w = self.card_w
            cx0 = x - card_w / 2
            D.rect(c, cx0, cy, cx0 + card_w * ee, cy + 4, th.accent if e.get("rel") else th.ink, e_out)
            yy = cy + 24
            photo_key, focus = self.card_photo.get(i, (None, None))
            if photo_key:
                ph = 150
                img = D.photo(self.assets.path(photo_key), card_w, ph, focus=focus,
                              zoom=1 + 0.05 * A.out_cubic(A.prog(t, e["t"], 3.0)), sat=0.95)  # v0.4.65: settles as it is read
                D.blit(c, img, cx0, yy, e_out, clip=(cx0, yy, cx0 + card_w, yy + ph * A.ease(t, e["t"] + 0.05, 0.35)))
                D.text(c, self.assets.credit(photo_key), "mono", 12, th.muted, cx0, yy + ph + 6, ee * e_out)
                yy += ph + 30
            ls = 34 if not self.crowded else 30  # v0.4.64: a narrower card: a size down, so a label keeps to about three lines
            lh = D.lead(th.heading, 42 if not self.crowded else 38)
            lines = D.wrap(e["label"], th.heading, ls, card_w)
            for j, line in enumerate(lines):
                D.text(c, line, th.heading, ls, th.ink, cx0 + 24 * (1 - ee), yy + j * lh, ee * e_out)
            yy += lh * len(lines) + D.lead(th.heading, 6)
            if e.get("sub"):
                for j, line in enumerate(D.wrap(e["sub"], th.body, 22, card_w)):
                    D.text(c, line, th.body, 22, th.muted, cx0, yy + j * D.lead(th.body, 30), A.ease(t, e["t"] + 0.2, A.FAST) * e_out)


# ============================================================ 3. CONTRADICTORY STATEMENTS

def _kind(story, claim):
    """Who an account is from: "defense", "family" or "official" (police, prosecutors, officials)."""
    role = story.role_of(claim.source) or ""
    if claim.source == "the defense" or re.search(r"defen[cs]e", role, re.I):
        return "defense"
    if role in FAMILY_ROLES or claim.source.lower().startswith(("his ", "her ", "the family")):
        return "family"
    return "official"


def _side(story, claim):
    """The column an account goes in: the official one, or the other side (the family's, or the defense's)."""
    return "official" if _kind(story, claim) == "official" else "family"


# accounts that oppose each other without a negation: a deliberate killing against self-defense or an accident
OPPOSED = [(r"\bdeliberate(?:ly)?\b|\bplanned\b|\bintentional(?:ly)?\b|\bpremeditated\b", r"\bself-defen[cs]e\b|\baccident(?:al(?:ly)?)?\b")]


def _opposed(c1, c2):
    for a, b in OPPOSED:
        if (re.search(a, c1.content, re.I) and re.search(b, c2.content, re.I) and not re.search(b, c1.content, re.I)) or \
                (re.search(b, c1.content, re.I) and re.search(a, c2.content, re.I) and not re.search(b, c2.content, re.I)):
            return True
    return False


def detect_contradiction(story, a, b):
    claims = [(s, c) for s in story.sentences[a:b] for c in s.claims if c.content and len(c.content.split()) > 3]
    best = None
    for i, (s1, c1) in enumerate(claims):
        for s2, c2 in claims[i + 1:]:
            if c1.source == c2.source:
                continue
            if c1.negated == c2.negated:
                if _side(story, c1) == _side(story, c2) or not _opposed(c1, c2):
                    continue
                ov = (content_words(c1.content) & content_words(c2.content)) | {"deliberate|self-defense"}
            else:
                ov = content_words(c1.content) & content_words(c2.content)
            if ov and (not best or len(ov) > best[0]):
                best = (len(ov), c1, c2, ov)
    if not best:
        return None
    _, c1, c2, ov = best
    sides = {"family": [], "official": []}
    for s, c in claims:
        side = _side(story, c)
        # a claim joins the contradiction if it shares polarity with one side and touches the same subject
        if c in (c1, c2) or (c.negated == (c1 if _side(story, c1) == side else c2).negated and side == _side(story, c1 if _side(story, c1) == side else c2)):
            sides[side].append(c)
    if not sides["family"] or not sides["official"]:
        return None
    defense = any(_kind(story, c) == "defense" for c in sides["family"])
    if defense and any(_kind(story, c) == "family" for c in sides["family"]):
        sides["family"] = [c for c in sides["family"] if _kind(story, c) == "defense"]
    if defense:
        # prosecution against defense: only the prosecution's accounts (not, say, what police said they found);
        # and the window starts with the dispute itself
        pros = [c for c in sides["official"] if re.search(r"prosecut|attorney", story.role_of(c.source) or c.source, re.I)]
        if pros:
            sides["official"] = pros
        used = sides["official"] + sides["family"]
        if not any(c in used for c in story.sentences[a].claims):
            return None
    prosecution = defense and all(re.search(r"prosecut|attorney", (story.role_of(c.source) or c.source), re.I) for c in sides["official"])
    # context: what does "that incident" refer to? the earliest quoted account of it
    context = None
    for s in ([] if defense else story.sentences[:a]):
        if re.search(r"fight|fighting|suspended|incident", s.text) and "“" in s.text and s.claims:
            q = re.search(r"“([^”]+)”", s.text)
            if q:
                context = {"quote": q.group(1).rstrip("."), "by": s.claims[0].source}
                break

    def pack(c):
        role = story.role_of(c.source)
        who = c.source.upper()
        if role in FAMILY_ROLES:
            who = f"{story.subject.split()[0]}’s {role}".upper()
        elif defense and role and c.source in story.people:
            who = f"{c.source} · {role}".upper()
        text = headline(c.content)
        if defense:
            text = re.sub(r"\band that\s+", "and ", text)
        cite = re.search(r",\s*citing ([^,]+),", story.sentences[[s.i for s, cc in claims if cc is c][0]].text)
        return {"who": who, "via": c.via, "cite": cite.group(1) if cite else "", "text": text, "negated": c.negated,
                "phrase": c.content[:30]}

    ch = story.chapters[story.sentences[a].chapter]
    payload = {"family": [pack(c) for c in sides["family"]], "official": [pack(c) for c in sides["official"]],
               "topic": sorted(ov), "context": context, "chapter": ch.title}
    if defense:
        payload["labels"] = {"family": "THE DEFENSE", "official": "THE PROSECUTION" if prosecution else "OFFICIAL ACCOUNTS"}
    return 0.62 + 0.08 * len(ov) + 0.05 * (len(sides["official"]) + len(sides["family"]) - 2), payload, [f"opposed claims share {sorted(ov)}"]


class ContradictionGraphic(Graphic):
    def build(self):
        self.cards = []
        for side in ("official", "family"):
            for k in self.p[side]:
                t0, t1 = self.span(k["phrase"])
                if t0 is None:
                    continue
                # the card arrives with the attribution, i.e. when the sentence starts
                sent_start = self._sentence_start(t0)
                self.cards.append(dict(k, side=side, t=max(0.4, sent_start), tw0=t0, tw1=self._clause_end(t0)))
        self.cards.sort(key=lambda k: k["t"])
        fam = [k for k in self.cards if k["side"] == "family"]
        self.t_neq = fam[0]["tw0"] if fam else self.duration / 2
        # the person who relayed a statement, if the producer assigned a photo of them: a small round portrait
        self.via_key = {k["via"]: self.assets.find(person=k["via"])[0] for k in self.cards if k.get("via")}
        self.cue(0.0, "whoosh-short-1", -8, "halves in")
        self.cue(0.12, "whoosh-short-2", -10, "halves in")
        for k in self.cards:
            self.cue(k["t"], "click-mech-2", -6, "statement")
        self.cue(self.t_neq, "impact-tr-1", -9, "contradiction")
        self.cue(self.t_neq, "bass-hit-1", -14, "contradiction")
        self.cue(self.out, "rwhoosh-3", -9, "out")
        self._fit()

    # v0.4.65 the statements fill the columns: the largest statement size (44-56 px) at which the fuller column
    # still fits above the bottom margin, and the block centred in the space left (no more empty lower half).
    TOP, BOTTOM, FS = 220, 990, (56, 54, 52, 50, 48, 46, 44)

    def _who(self, k):
        who = k["who"]
        if k.get("via"):
            who = f"{k['who']} · AS RELAYED BY {k['via'].upper()}"
        if k.get("cite"):
            who = f"{k['who']} · CITING {k['cite'].upper()}"
        return who

    def _bottom(self, fs):
        """Where the fuller column ends with every statement shown, at statement size fs (y0 = TOP)."""
        th = self.th
        lh = D.lead(th.heading, round(58 * fs / 44))
        ys = {"family": self.TOP, "official": self.TOP}
        ends = []
        for k in self.cards:
            av = 82 if k.get("via") and self.via_key.get(k["via"]) else 0
            who_lines = D.wrap(self._who(k), th.label, 20, 760 - av, 0.12)
            extra = max(0, len(who_lines) * D.lead(th.label, 28) - 56)
            n = len(D.wrap(k["text"], th.heading, fs, 760))
            ends.append(ys[k["side"]] + 56 + extra + lh * n)  # the last line's foot (the text box ends about there)
            ys[k["side"]] += 100 + lh * n + 60 + extra
        if self.p.get("context") and any(k["side"] == "family" for k in self.cards):
            y = ys["family"] - 30
            ends.append(y + max(150, 38 + 42 * len(D.wrap("“" + self.p["context"]["quote"] + ".”", "caladea", 32, 700))))
        return max(ends) if ends else self.TOP

    def _fit(self):
        self.fs, self.dy = 44, 0
        for fs in self.FS:
            b = self._bottom(fs)
            if b <= self.BOTTOM:
                self.fs, self.dy = fs, int(min(140, max(0, (self.BOTTOM - b) / 2)))
                return

    def _sentence_start(self, t):
        best = 0.0
        for w_prev, w in zip(self.tl.words, self.tl.words[1:]):
            if w.start > t:
                break
            if re.search(r"[.?!]", self.tl.text[w_prev.b:w.a]):
                best = w.start
        return best

    def _clause_end(self, t):
        for w, nxt in zip(self.tl.words, self.tl.words[1:] + [None]):
            if w.start >= t and (nxt is None or re.search(r"[.?!]", self.tl.text[w.b:nxt.a])):
                return w.end
        return self.tl.duration

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        el = A.ease(t, 0.0, 0.4, A.out_quint)
        warm, cool = th.c("bg2"), th.c("bg")
        D.rect(c, 0, 0, 960 * el, D.H, warm, e_out)
        D.rect(c, 1920 - 960 * A.ease(t, 0.1, 0.4, A.out_quint), 0, 1920, D.H, cool, e_out)
        es = A.ease(t, 0.3, 0.5)
        D.rect(c, 958, 0, 962, D.H * es, th.ink, 0.35 * e_out)
        labels = p.get("labels") or {}
        D.text(c, labels.get("family", "THE FAMILY’S ACCOUNT"), th.label, 22, th.accent2, 110, 110, A.ease(t, 0.3, A.FAST) * e_out, tracking=0.2)
        D.text(c, labels.get("official", "OFFICIAL ACCOUNTS"), th.label, 22, th.accent, 1050, 110, A.ease(t, 0.35, A.FAST) * e_out, tracking=0.2)
        D.rect(c, 110, 150, 110 + 740 * es, 152, th.accent2, 0.6 * e_out)
        D.rect(c, 1050, 150, 1050 + 760 * es, 152, th.accent, 0.6 * e_out)
        fs = self.fs
        ys = {"family": self.TOP + self.dy, "official": self.TOP + self.dy}
        for k in self.cards:
            x0 = 110 if k["side"] == "family" else 1050
            accent = th.accent2 if k["side"] == "family" else th.accent
            y = ys[k["side"]]
            ek = A.ease(t, k["t"], A.FAST)
            lines = D.wrap(k["text"], th.heading, fs, 760)
            lh = D.lead(th.heading, round(58 * fs / 44))  # v0.4.64: line steps follow the text size
            if ek <= 0:
                ys[k["side"]] += 100 + lh * len(lines) + 60
                continue
            who = self._who(k)
            ax = x0
            if k.get("via") and self.via_key.get(k["via"]):
                av = D.photo(self.assets.path(self.via_key[k["via"]]), 64, 64, focus=(0.55, 0.3), headroom=1.0)
                mask = D.disc(64, (255, 255, 255, 255))
                av.putalpha(mask.split()[3])
                D.blit(c, av, x0, y - 14, ek * e_out)
                ax += 82
            who_lines = D.wrap(who, th.label, 20, 760 - (ax - x0), 0.12)
            for j, line in enumerate(who_lines):
                D.text(c, line, th.label, 20, accent, ax + 20 * (1 - ek), y + j * D.lead(th.label, 28), ek * e_out, tracking=0.12)
            top = y + 56 + max(0, len(who_lines) * D.lead(th.label, 28) - 56)  # a two-line attribution pushes the statement down
            # statement words appear as they are spoken (the script's own words)
            body = k["text"]
            prog = A.clamp((t - k["tw0"]) / max(0.2, k["tw1"] - k["tw0"])) if t >= k["tw0"] else 0.0
            nshow = int(round(len(body.split()) * prog))
            shown, wi = 0, 0
            for j, line in enumerate(lines):
                ws = line.split()
                vis = ws[: max(0, nshow - wi)]
                wi += len(ws)
                lx = x0
                for w in vis:
                    neg = re.fullmatch(r"(not|no|never|didn’t|did)", w.strip(",.").lower()) and k["negated"]
                    colr = th.ink if not neg else accent
                    wpx = D.text(c, w + " ", th.heading, fs, colr, lx, top + j * lh, e_out)
                    if neg:
                        u = top + j * lh + D.lead(th.heading, round(60 * fs / 44))
                        D.rect(c, lx, u, lx + wpx - round(14 * fs / 44), u + 4, accent, e_out)
                    lx += wpx
            ys[k["side"]] += 100 + lh * len(lines) + 60 + (top - y - 56)
        # the earlier incident, as the family described it — context the narration only points at ("that incident")
        fam = [k for k in self.cards if k["side"] == "family"]
        ctx = p.get("context")
        if ctx and fam:
            ei = self.tl.phrase("earlier incident")
            tc = ei[0] if ei and ei[0] < fam[0]["tw0"] else fam[0]["tw1"] - 0.6
            ec = A.ease(t, tc, A.FAST)
            y = ys["family"] - 30
            D.rect(c, 110, y, 118, y + 150 * ec, th.accent2, e_out)
            D.text(c, f"THE EARLIER INCIDENT, AS {fam[0]['who']} RECALLED IT", th.label, 18, th.muted, 140, y + 4, ec * e_out, tracking=0.14)
            for j, line in enumerate(D.wrap("“" + ctx["quote"] + ".”", "caladea", 32, 700)):
                D.text(c, line, "caladea", 32, th.ink, 140, y + 38 + j * 42, ec * e_out)
        # the "≠" lands on the seam when the opposing belief is spoken
        en = A.prog(t, self.t_neq, A.SNAP)
        if en > 0:
            s = A.out_back(en, 2.2)
            d = max(2, int(132 * s))
            D.blit(c, D.disc(d, th.c("ink")), 960 - d / 2, 540 - d / 2, e_out)
            if s > 0.5:
                D.text(c, "≠", "sans-bold", int(96 * s), th.bg, 960, 540 - 66 * s, e_out, anchor="c")


# ============================================================ 4. LEGAL OUTCOME

CRIMES = r"(?:(?:first|second|third)-degree\s+)?(?:attempted\s+)?(?:murder|manslaughter|homicide|assault|robbery|kidnapping|arson|burglary)"
WORD_AGES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                                        "sixteen seventeen eighteen nineteen twenty".split())}


def detect_legal(story, a, b):
    sents = story.sentences[a:b]
    txt = " ".join(s.text for s in sents)
    # charges attached to someone ("faced charges of ...", "was / had been / is charged with ..."), not a general
    # statement about the law ("most 17-year-olds charged with felonies begin in Youth Part")
    m = re.search(r"\b(?:faces?|faced|facing)\s+(?:\w+\s+)?charges? of ([^.]+?)(?:,\s*(?:police|prosecutors) said|\.|;)", txt) or \
        re.search(r"\b(?:was|were|is|are|been|being)\s+(?:arrested\s+and\s+)?charged with ([^.,;]+)", txt) or \
        re.search(r"\bannounced\s+(?:an?\s+)?(?:additional\s+|new\s+)?((?:[\w-]+\s){0,2}?[\w-]+)\s+charges?\b", txt) or \
        re.search(rf"\bguilty of ({CRIMES})", txt) or re.search(rf"\b(?:in|for) the ({CRIMES})(?:\s+case)?\b", txt)
    if not m:
        return None
    charges = [x.strip() for x in re.split(r",\s*|\s+and\s+(?=[a-z])", m.group(1)) if x.strip()]
    if not charges or any(len(c.split()) > 7 or re.search(r"\b(?:begin|begins|can|may|will|would|is|are|was|were)\b", c) for c in charges) \
            or all(re.fullmatch(r"(?:felon(?:y|ies)|crimes?|offen[cs]es?|charges?|misdemeanou?rs?)", c.lower()) for c in charges):
        return None
    court = next((pl for s in sents for pl in s.places if re.search(r"Court", pl)), None)
    judge = next((n for s in sents for n in s.people if story.role_of(n) in ("Judge", "Justice")), None)
    outcome = re.search(r"\b(remanded without bail|held without bail|released on bail|convicted|acquitted|sentenced to [^.]+)", txt)
    verdict = None
    if not outcome:  # "found Moore guilty", "sentenced Moore to fifty-five years in prison": the outcome without the name
        g = re.search(r"\bfound\s+(?:\w+\s+){1,2}?(guilty|not guilty)\b", txt)
        sn = re.search(r"\bsentenced\s+(?:\w+\s+){1,2}?to\s+([^.,;]+?)(?:\s+for\b|[.,;])", txt)
        verdict = ("found " + g.group(1)) if g else ("sentenced to " + sn.group(1)) if sn else None
    date = next((d for s in sents for d in s.dates if not d.back), None)
    hearing = re.search(r"\b(arraigned|indicted|sentenced|convicted|acquitted)\b", txt)
    if not hearing and verdict and verdict.startswith("found"):
        hearing = re.search(r"\b(verdict|jury)\b", "verdict")
    attrib = re.search(r",\s*(police said|prosecutors said)", txt)
    n = sum(bool(x) for x in (court, judge, outcome or verdict, date))
    if n < 2:
        return None
    age = re.search(r"\b(\d{1,2})-year-old\b", txt)  # the defendant by age only: a name is never taken (juveniles)
    if not age:
        wa = re.search(r"\b(" + "|".join(WORD_AGES) + r")-year-old\b", txt, re.I)
        if wa:
            age = re.search(r"(.*)", f"{WORD_AGES[wa.group(1).lower()]}-year-old")
    out = outcome.group(1) if outcome else verdict
    payload = {"charges": charges, "court": court, "judge": judge, "outcome": out,
               "date": date.date.isoformat() if date else None, "date_phrase": date.text if date else None,
               "hearing": hearing.group(1) if hearing else None, "attrib": attrib.group(1) if attrib else None,
               "defendant": age.group(0) if age else "defendant"}
    return 0.5 + 0.1 * n + 0.04 * len(charges), payload, [f"charges {charges}; court={court}; judge={judge}; outcome={out}"]


class LegalGraphic(Graphic):
    def build(self):
        p = self.p
        last = 0
        self.charges = []
        for ch in p["charges"]:
            hit = self.tl.phrase(ch, last)
            if hit:
                last = hit[3]
                self.charges.append((ch, hit[0], hit[1]))
        self.t_attr = self.at(p["attrib"], default=None) if p.get("attrib") else None
        self.t_date = self.at(p["date_phrase"], default=0.5) if p.get("date_phrase") else 0.5
        self.t_court = self.at(p["court"], default=self.t_date) if p.get("court") else self.t_date
        self.t_judge = self.at("Judge " + p["judge"], default=None) if p.get("judge") else None
        self.t_out = self.at(p["outcome"].split()[0], default=None) if p.get("outcome") else None
        self.court_key, _ = self.assets.find(place=p.get("court") or "")
        self.cue(0.0, "paper-1", -6, "docket in")
        for i, (_, t0, _) in enumerate(self.charges):
            self.cue(t0, f"type-strike-{i % 6 + 1}", -6, "charge typed")
        if self.t_attr:
            self.cue(self.t_attr, "click-muted-1", -10, "attribution")
        self.cue(self.t_court, "doc-1", -10, "hearing")
        if self.t_judge:
            self.cue(self.t_judge, "type-strike-4", -8, "judge")
        if self.t_out:
            self.cue(self.t_out, "thump-deep-2", -3, "stamp")
            self.cue(self.t_out + 0.02, "doc-2", -10, "stamp paper")
        self.cue(self.out, "paper-2", -10, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        flip = th.traits.get("mirror")  # v0.4.64: the docket on the left, the courthouse on the right
        D.blit(c, _ruled(th), 0, 0, e_out)
        # header band
        eb = A.ease(t, 0.0, 0.4, A.out_quint)
        D.rect(c, 0, 0, D.W, 150 * eb, th.accent, e_out)
        head = (p.get("court") or "COURT").upper() if (self.court_key or not p.get("court")) else "COURT RECORD"  # no photo: the plate names it
        lbl = ""
        if p.get("date"):
            d = dt.date.fromisoformat(p["date"])
            lbl = f"{(p.get('hearing') or 'hearing').upper().replace('ARRAIGNED', 'ARRAIGNMENT')} · {long_date(d).upper()}"
        hs = D.fit_size(head, th.display, 1680 - (D.measure(lbl, "mono", 24)[0] + 60 if lbl else 0), 64, 36)  # v0.4.64: never into the date
        D.text(c, head, th.display, hs, th.bg, 120, 40 + (64 - hs) * 0.5, A.ease(t, 0.2, A.FAST) * e_out, clip=(0, 0, D.W, 150 * eb))
        if lbl:
            D.text(c, lbl, "mono", 24, th.bg, 1800, 62, A.ease(t, self.t_court, A.FAST) * e_out, anchor="r")
        # courthouse photo, printed look: white border, hard offset shadow (no blur)
        if self.court_key:
            ep = A.ease(t, 0.15, 0.45)
            x0, y0, s = (1240 if flip else 120), 250, 540
            D.rect(c, x0 + 14, y0 + 14, x0 + s + 34, y0 + s + 34, "#000000", 0.18 * ep * e_out)
            D.rect(c, x0, y0, x0 + s + 20, y0 + s + 20, "#FFFFFF", ep * e_out)
            img = D.photo(self.assets.path(self.court_key), s, s, focus=(0.5, 0.45), zoom=A.drift(t, self.duration, 0.05), headroom=1.06)
            D.blit(c, img, x0 + 10, y0 + 10, e_out, clip=(x0 + 10, y0 + 10, x0 + 10 + s * ep, y0 + 10 + s))
            src = self.assets.items[self.court_key]
            D.text(c, str(src.get("subject") or p.get("court") or "").split(",")[0].upper(), "mono", 16, th.ink, x0, y0 + s + 46, ep * e_out)
            D.text(c, self.assets.credit(self.court_key), "mono", 14, th.muted, x0, y0 + s + 72, ep * e_out)
        elif p.get("court"):
            # no photo of the court: a printed plate of what the narration says about it (nothing invented)
            ep = A.ease(t, 0.15, 0.45)
            x0, w = (1240 if flip else 120), 540
            court = p["court"].upper()
            size = D.fit_size(court, th.display, w, 84, 40, lines=3)
            D.text(c, "COURT", th.label, 20, th.accent, x0, 250, ep * e_out, tracking=0.2)
            y = 296
            for ln in D.wrap(court, th.display, size, w)[:3]:
                D.text(c, ln, th.display, size, th.ink, x0, y, e_out, clip=(x0, y - 12, x0 + (w + 8) * ep, y + size * 1.4))
                y += int(size * 1.08)
            D.rect(c, x0, y + 34, x0 + w * ep, y + 36, th.ink, 0.4 * e_out)
        # docket
        x0 = 120 if flip else 790
        ed = A.ease(t, 0.25, A.FAST)
        D.text(c, "DEFENDANT", th.label, 20, th.accent, x0, 230, ed * e_out, tracking=0.2)
        dfd = p["defendant"].upper()
        D.text(c, dfd, th.heading, D.fit_size(dfd, th.heading, 790, 46, 28), th.ink, x0 + 220, 214, ed * e_out)
        D.rect(c, x0, 282, x0 + 1010 * A.ease(t, 0.3, 0.5), 284, th.ink, 0.4 * e_out)
        D.text(c, "CHARGES", th.label, 20, th.accent, x0, 316, ed * e_out, tracking=0.2)
        y = 350
        for i, (ch, t0, t1) in enumerate(self.charges):
            ec = A.prog(t, t0 - 0.04, max(0.18, (t1 - t0) * 0.7))
            if ec > 0:
                D.text(c, str(i + 1), "mono", 30, th.accent, x0, y + 16, e_out)
                txt = ch.upper()
                cs = D.fit_size(txt, th.heading, 950, 52, 30)  # v0.4.64: a long charge (or a wider font) fits the docket
                D.text(c, txt, th.heading, cs, th.ink, x0 + 60, y + (52 - cs) * 0.5, e_out,
                       clip=(x0 + 60, y - 10, x0 + 60 + D.measure(txt, th.heading, cs)[0] * A.out_cubic(ec) + 4, y + D.lead(th.heading, 80)))
            y += D.lead(th.heading, 78)
        if self.t_attr:
            D.text(c, "— " + p["attrib"].upper(), th.label, 20, th.muted, x0 + 60, y + 4, A.ease(t, self.t_attr, A.FAST) * e_out, tracking=0.16)
        if self.t_judge:
            ej = A.ease(t, self.t_judge, A.FAST)
            yj = max(668, y + (D.lead(th.label, 24) + 56 if self.t_attr else 32))  # v0.4.64: below the charges when they are taller
            D.rect(c, x0, yj - 24, x0 + 1010 * ej, yj - 22, th.ink, 0.4 * e_out)
            D.text(c, "BEFORE", th.label, 20, th.accent, x0, yj + 8, ej * e_out, tracking=0.2)
            jt = "JUDGE " + p["judge"].upper()
            D.text(c, jt, th.heading, D.fit_size(jt, th.heading, 790, 46, 28), th.ink, x0 + 220, yj - 6, e_out,
                   clip=(x0 + 220, yj - 20, x0 + 220 + 800 * ej, yj + D.lead(th.heading, 70)))
        # the stamp
        if self.t_out:
            es = A.prog(t, self.t_out, 0.13)
            if es > 0:
                st = _stamp(p["outcome"], th)
                sc = 0.74 * (1.0 + 0.9 * (1 - A.out_expo(es)))
                w, h = int(st.width * sc), int(st.height * sc)
                img = st.resize((w, h), Image.BICUBIC) if sc != 1 else st
                cx = 780 if flip else 1450
                yj_end = max(668, y + (D.lead(th.label, 24) + 56 if self.t_attr else 32)) if self.t_judge else 668
                cy = min(905 + (yj_end - 668), D.H - 20 - st.height * 0.74 / 2)  # v0.4.64: under the judge when larger text pushes it down
                shake = 4 * (1 - A.prog(t, self.t_out + 0.13, 0.12)) if es >= 1 else 0
                D.blit(c, img, cx - w / 2 + shake, cy - h / 2, min(1, es * 2.5) * e_out)


def _ruled(th):
    key = ("ruled", th.name, bool(th.traits.get("mirror")))
    if key not in _CACHE:
        im = Image.new("RGBA", (D.W, D.H), (0, 0, 0, 0))
        col = th.c("muted", 22)
        for y in range(190, D.H, 52):
            im.paste(col, (0, y, D.W, y + 1))
        rx = D.W - 742 if th.traits.get("mirror") else 740  # v0.4.64: the margin rule between docket and photo
        im.paste(th.c("accent", 60), (rx, 150, rx + 2, D.H))
        _CACHE[key] = im
    return _CACHE[key]


def _stamp(outcome, th):
    key = ("stamp", outcome, th.accent)  # v0.4.63: the stamp is in the accent, which a colour set changes
    if key in _CACHE:
        return _CACHE[key]
    import numpy as np
    words = outcome.upper().split()
    top, bottom = words[0], " ".join(words[1:])
    S = 3
    f1, f2 = D.font("oswald", 120 * S), D.font("oswald", 52 * S)
    w = int(max(f1.getlength(top), f2.getlength(bottom)) + 120 * S)
    h = 300 * S
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    ink = th.c("accent")
    d.rectangle((6 * S, 6 * S, w - 6 * S, h - 6 * S), outline=ink, width=10 * S)
    d.rectangle((24 * S, 24 * S, w - 24 * S, h - 24 * S), outline=ink, width=4 * S)
    d.text((w / 2, 40 * S), top, font=f1, fill=ink, anchor="ma")
    d.text((w / 2, 196 * S), bottom, font=f2, fill=ink, anchor="ma")
    # rubber-stamp ink: deterministic speckle knocked out of the alpha (texture, not blur)
    a = np.array(im.split()[3], dtype=np.float32)
    rng = np.random.default_rng(7)
    speck = rng.random((h // (2 * S) + 1, w // (2 * S) + 1)) < 0.10
    speck = np.kron(speck, np.ones((2 * S, 2 * S)))[:h, :w]
    a[speck > 0] *= 0.25
    im.putalpha(Image.fromarray(a.clip(0, 255).astype("uint8")))
    im = im.rotate(-7, resample=Image.BICUBIC, expand=True)
    im = im.resize((im.width // S, im.height // S), Image.LANCZOS)
    _CACHE[key] = im
    return im


# ============================================================ 5. DIGITAL EVIDENCE ANALYSIS

EVIDENCE = [
    (r"surveillance video|video|footage", "SURVEILLANCE VIDEO"), (r"backpack", "BACKPACK"), (r"shell casings?", "SHELL CASINGS"),
    (r"phone records?|phone", "PHONE"), (r"MetroCard|turnstile", "TURNSTILE"), (r"DNA", "DNA"), (r"cameras?", "CAMERAS"),
    (r"license plate", "LICENSE PLATE"), (r"GPS|location data", "LOCATION DATA"),
    (r"records of (?:[\w’']+\s){0,3}?communicat\w+|communications? records?", "COMMUNICATION RECORDS"),
    (r"social media (?:messages?|posts?)", "SOCIAL MEDIA MESSAGES"), (r"search history", "SEARCH HISTORY"), (r"\bnotes\b", "NOTES"),
    (r"(?<!media )\bmessages\b", "MESSAGES"),
]
ROUTELESS_MIN = 3   # an evidence log with no route: at least this many distinct kinds of evidence
UNRELEASED = r"had not been (?:publicly )?released|not been made public|was not (?:publicly )?disclosed"
MOVES = r"(went through|boarded|jumped|tracked into|fled to|drove to|ran to|took)"


def detect_digital(story, a, b):
    sents = story.sentences[a:b]
    txt = " ".join(s.text for s in sents)
    items = []
    for s in sents:
        for pat, label in EVIDENCE:
            m = re.search(pat, s.text, re.I)
            if m and label not in [i["label"] for i in items] and label != "TURNSTILE":
                if label == "PHONE" and re.search(r"cellphone records", s.text, re.I):
                    label = "CELLPHONE RECORDS"
                    if label in [i["label"] for i in items]:
                        continue
                if label == "SOCIAL MEDIA MESSAGES" and m.group(0).lower().endswith(("post", "posts")):
                    label = "SOCIAL MEDIA POSTS"
                items.append({"label": label, "phrase": m.group(0), "sent": s.i})
    route = []
    for s in sents:
        for m in re.finditer(rf"{MOVES}\s+(?:a\s+|the\s+)?((?:No\.\s*\d+|[^,;.])+?)(?=,|;|\.| and were| and |$)", s.text):
            route.append({"verb": m.group(1), "what": m.group(2).strip(), "phrase": m.group(0)[:28]})
    if len(route) < 2:
        if len(items) < ROUTELESS_MIN:
            return None
        route = []  # an evidence log on its own; a single move is not a route
    items = items[:8]
    # origin from story context: where were they before?
    origin = None
    for s in story.sentences[:b]:
        if re.search(r"had been in ([A-Z][\w ]+?)(?: before|,|\.)", s.text):
            origin = re.search(r"had been in ([A-Z][\w ]+?)(?: before|,|\.)", s.text).group(1)
    loc, time, date = None, None, None
    for s in story.sentences[:a]:
        m = re.search(r"near ((?:East|West) [\w ]+? and [\w ]+?),", s.text)
        if m and not loc:
            loc = m.group(1)
        m = re.search(r"around (\d{1,2}:\d{2})(\s*(?:a\.m\.|am)|\s*(?:p\.m\.|pm))?(?:\s+(?:that|in the)\s+(morning|afternoon|evening|night))?", s.text)
        if m and not time:
            half = (m.group(2) or "").strip().lower()
            part = m.group(3) or ""
            ampm = "AM" if half.startswith("a") or part == "morning" else "PM" if half.startswith("p") or part in ("afternoon", "evening", "night") else ""
            time = (m.group(1) + (" " + ampm if ampm else "")).strip()
    inc = story.incident_date()
    briefing = None
    for s in story.sentences:
        if re.search(r"briefing", s.text) and s.dates:
            briefing = s.dates[0].date.isoformat()
            break
    status = {}
    for s in sents:
        if re.search(r"not been recovered|not recovered", s.text):
            status["BACKPACK"] = ("NOT RECOVERED", "not been recovered")
        if re.search(r"reported obtaining", s.text):
            outlets = [o for o in s.orgs if o not in ("police", "prosecutors")]
            status["SURVEILLANCE VIDEO"] = ("REPORTED · " + ", ".join(outlets).upper(), "reported obtaining")
        if re.search(r"returned to collect shell casings", s.text):
            status["SHELL CASINGS"] = ("COLLECTED BY THE THREE", "returned to collect")
        um = re.search(UNRELEASED, s.text)
        if um:  # "one social media message contained a detail ... that had not been publicly released"
            for pat, label in EVIDENCE:
                if re.search(pat, s.text, re.I) and label not in status:
                    status[label] = ("DETAIL NOT RELEASED", um.group(0))
                    break
        dm = re.search(r"\bdefen[cs]e disputed\b", s.text)
        if dm and re.search(r"digital|messages|posts", s.text):
            for label in ("SOCIAL MEDIA MESSAGES", "SOCIAL MEDIA POSTS", "MESSAGES"):
                status.setdefault(label, ("DISPUTED BY THE DEFENSE", "disputed"))
    for it in items:
        it["status"], it["status_phrase"] = status.get(it["label"], ("", ""))
        s = story.sentences[it["sent"]]
        if it["label"] == "SURVEILLANCE VIDEO":
            m = re.search(r"showing ([^.;]+)", s.text)
            it["detail"] = ("Showing " + m.group(1)) if m else ""
        else:  # the clause that mentions the item, verbatim
            cl = next((c.content for c in s.claims if it["phrase"].lower() in c.content.lower()), "")
            cl = re.split(r",\s*(?:went|jumped|boarded)\b", cl)[0]
            it["detail"] = headline(cl)
            if any(o is not it and o.get("detail") == it["detail"] and o["sent"] == it["sent"] for o in items):
                it["detail"] = ""  # one sentence listing several kinds of evidence: its words go under the first only
    place = next((r["what"] for r in route if re.search(r"\b(?:station|Station|Street|Avenue|Park|Square|Bridge)\b", r["what"])), None)
    nyc = bool(NYC.search(" ".join(s.text for s in story.sentences)))
    by_police = bool(re.search(r"\bpolice\b", txt, re.I)) or any(INVESTIGATORS.search(story.role_of(c.source) or c.source) for s in sents for c in s.claims)
    payload = {"items": items, "route": route, "origin": origin, "origin_loc": loc, "time": time, "date": inc.isoformat() if inc else None,
               "briefing": briefing, "place": place, "nyc": nyc, "by": "POLICE" if by_police else "", "incident": incident_noun(story)}
    score = 0.55 + 0.08 * len(items) + 0.06 * len(route) + (0.04 * sum(bool(i["status"]) for i in items) if not route else 0)
    return score, payload, [f"evidence {[i['label'] for i in items]} + route of {len(route)} moves"]


class DigitalGraphic(Graphic):
    def build(self):
        p = self.p
        self.items = []
        for it in p["items"]:
            t0 = self.at(it["phrase"], default=None)
            if t0 is None:
                continue
            ts = self.at(it["status_phrase"], default=t0 + 0.8) if it.get("status_phrase") else t0 + 0.8
            self.items.append(dict(it, t=t0, ts=ts))
        self.route = []
        for r in p["route"]:
            t0 = self.at(r["phrase"], default=None)
            if t0 is not None:
                self.route.append(dict(r, t=t0))
        self.t_route0 = (self.route[0]["t"] - 2.4) if self.route else 2.0
        self.station_key, _ = self.assets.find(place=p["place"]) if p.get("place") else (None, None)
        self.cue(0.0, "scan-1", -10, "hud boot")
        for it in self.items:
            n = len(it["label"])
            for k in range(0, n, 2):
                self.cue(it["t"] + k / 40, f"key-soft-{k % 6 + 1}", -16, "typing")
            if it.get("status"):
                self.cue(it["ts"], "notify-1" if "NOT" not in it["status"] else "pulse-low-1", -9, "status")
        for i, r in enumerate(self.route):
            self.cue(r["t"], "whoosh-dir-r" if i % 2 == 0 else "click-mech-1", -10 if i % 2 == 0 else -7, "route step")
        if self.station_key:
            self.cue(self._t_station(), "scan-2", -12, "location scan")
        if self.route:
            self.cue(self.route[-1]["t"] + 0.3, "pulse-low-2", -8, "tracked")
        self.cue(self.out, "rwhoosh-1", -10, "out")

    def _t_station(self):
        for r in self.route:
            if r["what"] == self.p.get("place"):
                return r["t"]
        return self.t_route0 + 1

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        D.blit(c, _grid(th.c("accent", 14), 48), 0, 0, A.ease(t, 0, 0.3) * e_out)
        # HUD
        eh = A.ease(t, 0.0, 0.3)
        D.rect(c, 0, 0, D.W, 64, th.bg2, e_out)
        D.text(c, "EVIDENCE ANALYSIS", "mono", 24, th.accent, 60, 18, eh * e_out)
        if p.get("briefing"):
            b = dt.date.fromisoformat(p["briefing"])
            src = "SOURCE: POLICE ACCOUNT · " if p.get("by", "POLICE") else ""
            D.text(c, f"{src}BRIEFING {short_date(b)}, {b.year}", "mono", 18, th.muted, 1860, 22, eh * e_out, anchor="r")
        D.rect(c, 0, 64, D.W * A.ease(t, 0.05, 0.5), 66, th.accent, 0.8 * e_out)
        tc = max(0.0, t)
        D.text(c, f"T+{int(tc // 60):02d}:{tc % 60:05.2f}", "mono", 18, th.accent, 1860, 1030, 0.7 * eh * e_out, anchor="r")
        # evidence log (with no route, it fills both columns)
        D.text(c, "EVIDENCE LOG", "mono", 20, th.muted, 80, 112, A.ease(t, 0.2, A.FAST) * e_out)
        for i, it in enumerate(self.items):
            col, row = (0, i) if self.route else divmod(i, 4)
            x0, y = 80 + 920 * col, 160 + 230 * row
            ei = A.ease(t, it["t"] - 0.05, A.FAST)
            if ei <= 0:
                continue
            D.blit(c, D.rounded(760, 200, 4, th.c("bg2"), th.c("accent", 70), 2), x0, y, ei * e_out)
            D.rect(c, x0, y, x0 + 6, y + 200, th.accent, ei * e_out)
            D.text(c, f"E{i + 1:02d}", "mono", 18, th.muted, x0 + 30, y + 22, ei * e_out)
            D.text(c, A.typed(it["label"], t, it["t"], 40), th.heading, 40, th.ink, x0 + 30, y + 46, e_out)
            if it.get("detail"):
                dl = D.wrap(it["detail"], th.body, 22, 690)[:1]
                if not self.route and dl and dl[0] != it["detail"]:
                    dl = [dl[0].rstrip(",;: ")]  # a cut line never ends on a dangling comma
                for j, line in enumerate(dl):
                    D.text(c, line, th.body, 23, th.muted, x0 + 30, y + 104 + j * 30, A.ease(t, it["t"] + 0.4, A.FAST) * e_out)
            if it.get("status"):
                es = A.prog(t, it["ts"], A.SNAP)
                if es > 0:
                    bad = "NOT" in it["status"]
                    colr = th.accent2 if bad else th.accent
                    w, _ = D.measure(it["status"], "mono", 18)
                    tag = D.rounded(w + 28, 34, 3, D.col(colr, 40), D.col(colr), 2)
                    D.blit(c, tag, x0 + 730 - tag.width, y + 148, min(1, es * 3) * e_out)
                    D.text(c, it["status"], "mono", 18, colr, x0 + 730 - tag.width + 14, y + 155, min(1, es * 3) * e_out)
        if not self.route:
            return
        # route panel
        rx0 = 960
        er = A.ease(t, self.t_route0, A.FAST)
        if er > 0:
            D.text(c, "ROUTE · AS DESCRIBED BY POLICE" if p.get("by", "POLICE") else "ROUTE · AS DESCRIBED", "mono", 20, th.muted, rx0, 112, er * e_out)
            D.text(c, "SCHEMATIC — NOT TO SCALE", "mono", 16, th.muted, 1860, 114, er * e_out * 0.8, anchor="r")
        nodes = self._nodes()
        # draw the path progressively: each step reaches its node when narrated
        pts = [n["xy"] for n in nodes]
        for i in range(1, len(nodes)):
            a, b = nodes[i - 1], nodes[i]
            pr = A.ease(t, b["t"] - 0.15, 0.45, A.out_quint)
            if pr <= 0:
                continue
            q = (a["xy"][0] + (b["xy"][0] - a["xy"][0]) * pr, a["xy"][1] + (b["xy"][1] - a["xy"][1]) * pr)
            colr = (a.get("line") or th.accent2) if a.get("train") else th.accent
            D.polyline(c, [a["xy"], q], colr, 8, e_out)
        for n in nodes:
            en = A.prog(t, n["t"] + (0.25 if n is not nodes[0] else 0), A.SNAP)
            if en <= 0:
                continue
            x, yy = n["xy"]
            s = A.out_back(en, 2.0)
            dsz = max(2, int((44 if n.get("end") else 30) * s))
            ring = th.c("accent2") if n.get("end") else th.c("accent")
            D.blit(c, D.disc(dsz, th.c("bg"), ring, 6), x - dsz / 2, yy - dsz / 2, e_out)
            if n.get("end"):
                pu = A.pulse(t, n["t"] + 0.3, 1.1)
                rd = int(44 + 40 * pu)
                D.blit(c, D.disc(rd, (0, 0, 0, 0), th.c("accent2", int(200 * (1 - pu))), 3), x - rd / 2, yy - rd / 2, e_out)
            if n.get("train"):
                D.blit(c, D.disc(56, D.col(n.get("line") or th.accent2)), x - 28 + 60, yy - 28, min(1, en * 2) * e_out)
                D.text(c, n.get("route_no") or "", "lib-sans", 40, "#FFFFFF", x + 60, yy - 24, min(1, en * 2) * e_out, anchor="c")
            lx = x + (110 if n.get("train") else 40)
            D.text(c, n["label"], th.heading, 34, th.ink, lx, yy - 26, e_out, clip=(lx, yy - 40, lx + 600 * A.out_smooth(min(1, en * 1.4)), yy + 30))
            if n.get("sub"):
                D.text(c, n["sub"], "mono", 18, th.muted, lx + 2, yy - 26 + D.lead(th.heading, 44), A.ease(t, n["t"] + 0.35, A.FAST) * e_out)
        # location tile with a crisp scan line
        if self.station_key:
            ts = self._t_station()
            ep = A.ease(t, ts, 0.35)
            if ep > 0:
                x, y0, w, h = 1610, 330, 220, 340
                img = D.photo(self.assets.path(self.station_key), w, h, focus=(0.5, 0.5), headroom=1.04, sat=0.85, contrast=1.08,
                              zoom=1 + 0.04 * A.out_cubic(A.prog(t, ts, 2.5)))  # v0.4.65: a short push-in as the place is named
                D.blit(c, img, x, y0, e_out, clip=(x, y0, x + w, y0 + h * ep))
                D.outline(c, x - 2, y0 - 2, x + w + 2, y0 + h * ep + 2, th.accent, 2, e_out)
                sl = A.prog(t, ts + 0.1, 0.8)
                if 0 < sl < 1:
                    D.rect(c, x, y0 + h * sl, x + w, y0 + h * sl + 2, th.accent, e_out)
                D.text(c, self.p["place"].upper().replace(" STREET ", " ST ").replace("STREET STATION", "ST STATION"), "mono", 14, th.ink, x, y0 + h + 10, ep * e_out)
                cr = self.assets.credit(self.station_key)  # v0.4.64: a long credit ends inside the frame (it ran off the edge)
                D.text(c, cr, "mono", 12, th.muted, min(x, D.W - 40 - D.measure(cr, "mono", 12)[0]), y0 + h + 30, ep * e_out)

    def _nodes(self):
        if hasattr(self, "_n"):
            return self._n
        p = self.p
        nodes = []
        sub = " · ".join(x for x in [p.get("origin_loc", "") and (p.get("incident") or "incident").upper() + " NEAR " + p["origin_loc"].upper().replace("EAST ", "E ").replace("STREET", "ST").replace("PLACE", "PL").replace(" AND ", " & "),
                                      (f"{short_date(dt.date.fromisoformat(p['date']))} · ~{p['time']}" if p.get("date") and p.get("time") else "")] if x)
        nodes.append({"label": (p.get("origin") or "START").upper(), "sub": sub, "t": self.t_route0, "xy": (1010, 220)})
        coords = [(1010, 440), (1010, 640), (1260, 860), (1520, 860)]
        k = 0
        for r in self.route:
            what = r["what"]
            if r["verb"] == "jumped":  # an action at the current node, not a move
                if nodes:
                    nodes[-1]["sub"] = (nodes[-1].get("sub", "") + " · " if nodes[-1].get("sub") else "") + f"{what.upper()} JUMPED"
                continue
            label = what.upper().replace(" STREET ", " ST ")
            n = {"label": label, "t": r["t"], "xy": coords[min(k, len(coords) - 1)]}
            if re.search(r"train", what, re.I):
                n["train"] = True
                num = re.search(r"No\.\s*(\d+)", what)
                n["route_no"] = num.group(1) if num else ""
                n["line"] = MTA_COLORS.get(n["route_no"]) if p.get("nyc") else None  # the real line colour, only for New York
                n["label"] = re.sub(r"\s*No\.\s*\d+\s*train", "", what, flags=re.I).upper() or "TRAIN"
                n["sub"] = (f"NO. {n['route_no']} TRAIN" if num else "TRAIN")
            if r["verb"] == "tracked into":
                n["end"] = True
                n["sub"] = "TRACKED INTO"
                n["xy"] = coords[-1]
            nodes.append(n)
            k += 1
        # the train leg bends: put the train node at the bend
        self._n = nodes
        return nodes


# ============================================================ 6. CASE TURNING POINT

TURN_VERBS = r"\b(arrested|charged|convicted|acquitted|identified|confessed|indicted|found|announced|died|won|lost|signed|retired)\b"


def detect_turning(story, a, b):
    if b - a != 2:
        return None
    q, ans = story.sentences[a], story.sentences[a + 1]
    if not q.question:
        return _turning_elapsed(story, q, ans)
    if not ans.dates or not re.search(TURN_VERBS, ans.text):
        return None
    if story.sentences[a].chapter != story.sentences[a + 1].chapter and False:
        return None
    strong = re.search(r"\b(arrested|charged|convicted|acquitted|indicted)\b", ans.text)
    inc = story.incident_date()
    days = (ans.dates[0].date - inc).days if inc else None
    m = re.search(r"(a\s+)?([\w-]+(?:-year-old)?)\s+had been (arrested)(?: and (charged with \w+))?", ans.text)
    age = None
    for s in story.sentences:
        mm = re.search(rf"{re.escape(story.subject)} was (\d+)\b", s.text) if story.subject else None
        if mm:
            age = int(mm.group(1))
            break
    payload = {"subject": story.subject, "age": age, "question": q.text, "incident": incident_noun(story), "date": ans.dates[0].date.isoformat(), "date_phrase": ans.dates[0].text, "days": days,
               "who": m.group(2) if m else "", "event": m.group(3) if m else "", "charge": m.group(4) if m and m.group(4) else "",
               "event_phrase": "had been arrested" if m else ans.text.split()[2]}
    return (0.75 if strong else 0.55) + (0.1 if days else 0), payload, [f"question answered by dated event ({days} days after incident)"]


def _turning_elapsed(story, ev, el):
    """No question: a dated decisive event, then the narration's own count of how long it took
    ("... arrested fifteen-year-old Jahmir Moore ..." / "It had been 231 days since April 17.")."""
    dates = [d for d in ev.dates if not d.back]
    strong = re.search(r"\b(arrested|charged|convicted|acquitted|indicted)\b", ev.text)
    m = re.search(r"\b(?:[Ii]t had been|[Ii]t took|[Ii]t was)\s+(\d+)\s+days\b", el.text)
    inc = story.incident_date()
    if not dates or not strong or not m or not inc:
        return None
    days = (dates[0].date - inc).days
    if days != int(m.group(1)):
        return None  # the narration counts differently: never show a number it does not say
    who = re.search(rf"\b{strong.group(1)}\s+(?:a\s+|the\s+)?(\d{{1,2}}|" + "|".join(WORD_AGES) + r")-year-old\b", ev.text, re.I)
    age = None
    for s in story.sentences:
        mm = re.search(rf"{re.escape(story.subject)} was (\d+)\b", s.text) if story.subject else None
        if mm:
            age = int(mm.group(1))
            break
    n = who.group(1) if who else ""
    n = str(WORD_AGES.get(n.lower(), n)) if n else ""
    payload = {"subject": story.subject, "age": age, "question": "", "incident": incident_noun(story), "date": dates[0].date.isoformat(),
               "date_phrase": dates[0].text, "days": days, "who": f"{n}-year-old" if n else "", "event": strong.group(1), "charge": "",
               "event_phrase": strong.group(1), "elapsed_phrase": m.group(0)}
    return 0.85, payload, [f"dated {strong.group(1)}, {days} days after the incident, as the narration counts"]


class TurningGraphic(Graphic):
    def build(self):
        p = self.p
        q = p["question"]
        self.qwords = []
        for w in self.tl.words:
            if w.a < len(q) + 2 and T.norm(w.text) and self.tl.text[: w.b].strip() in q:
                self.qwords.append(w)
        self.t_q_end = self.qwords[-1].end if self.qwords else (1.5 if q else 0.0)
        pz = self.tl.next_pause_after(self.t_q_end - 0.05)
        self.t_cut = self.at(p["date_phrase"], default=(pz[1] if pz else self.t_q_end + 0.4))
        self.t_event = self.at(p["event_phrase"], default=self.t_cut + 2)
        self.t_arrest = self.at(p["event"], default=self.t_event) if p.get("event") else self.t_event
        self.t_charge = self.at(p["charge"], default=self.t_arrest + 0.8) if p.get("charge") else None
        self.photo_key, _ = self.assets.find(person=p["subject"]) if p.get("subject") else (None, None)
        for i, w in enumerate(self.qwords):
            self.cue(w.start, "tick-2" if i < len(self.qwords) - 1 else "click-mech-3", -12 if i < len(self.qwords) - 1 else -6, "question word")
        self.cue(self.t_cut, "riser-2", -8, "tension into the answer")
        self.cue(self.t_cut, "impact-tr-2", -4, "the answer")
        self.cue(self.t_cut, "bass-hit-2", -9, "the answer")
        self.cue(self.t_cut + 0.25, "tick-seq-1", -14, "date roll")
        self.cue(self.t_arrest, "click-mech-1", -5, "arrested")
        if self.t_charge:
            self.cue(self.t_charge, "thump-deep-3", -5, "charge")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        flip = th.traits.get("mirror")  # v0.4.64: the photograph on the left, the words on the right
        if t < self.t_cut:
            # phase 1 — the question, word by word over his photograph (B/W, sharp)
            if self.photo_key:
                e = A.ease(t, 0.0, 0.4)
                img = D.photo(self.assets.path(self.photo_key), 1100, 1080, focus=(0.48, 0.3), zoom=1.0 + 0.06 * A.clamp(t / self.t_cut),
                              sat=0.0, contrast=1.12, bright=0.85)
                cr = self.assets.credit(self.photo_key)
                if flip:
                    D.blit(c, img, 0, 0, e, clip=(0, 0, 1100 * e, 1080))
                    D.blit(c, D.gradient(420, 1080, (0, 0, 0, 0), (0, 0, 0, 255), vertical=False), 680, 0)
                    if cr:
                        cw = D.measure(cr, "mono", 14)[0]
                        D.rect(c, 16, 1030, 30 + cw + 14, 1064, "#000000", 0.6 * e)
                        D.text(c, cr, "mono", 14, "#FFFFFF", 30, 1039, 0.85 * e)
                else:
                    D.blit(c, img, 820, 0, e, clip=(820 + 1100 * (1 - e), 0, 1920, 1080))
                    D.blit(c, D.gradient(420, 1080, (0, 0, 0, 255), (0, 0, 0, 0), vertical=False), 820, 0)
                    if cr:
                        cw = D.measure(cr, "mono", 14)[0]
                        D.rect(c, 1890 - cw - 14, 1030, 1904, 1064, "#000000", 0.6 * e)
                        D.text(c, cr, "mono", 14, "#FFFFFF", 1890, 1039, 0.85 * e, anchor="r")
            lines = _break_question(p["question"].upper(), th.display)
            k, y = 0, 300
            for line in lines:
                x = 1040 if flip else 120
                for wtxt in line.split():
                    w = self.qwords[k] if k < len(self.qwords) else None
                    tw = w.start - 0.03 if w else 0.3
                    ew = A.prog(t, tw, 0.12)
                    if ew > 0:
                        is_last = k == len(self.qwords) - 1
                        colr = th.accent if is_last else th.ink
                        dy = 26 * (1 - A.out_smooth(ew))
                        x += D.text(c, wtxt + " ", th.display, 132, colr, x, y + dy, min(1, ew * 3), clip=(0, y - 10, 1920, y + 160))
                    else:
                        x += D.measure(wtxt + " ", th.display, 132)[0]
                    k += 1
                y += 150
            # tension line across the pause
            el = A.prog(t, self.t_q_end, max(0.2, self.t_cut - self.t_q_end))
            if el > 0:
                D.rect(c, 0, 840, 1920 * A.in_out_cubic(el), 846, th.accent)
            return
        # phase 2 — the answer
        tc = t - self.t_cut
        if tc < 0.067:
            D.rect(c, 0, 0, D.W, D.H, "#FFFFFF")
            return
        fl = 1 - A.prog(tc, 0.067, 0.1)
        D.rect(c, 0, 0, D.W, 14, th.accent, e_out)
        D.rect(c, 0, D.H - 14, D.W, D.H, th.accent, e_out)
        d = dt.date.fromisoformat(p["date"])
        start = d - dt.timedelta(days=p["days"] or 0)
        roll = A.out_cubic(A.prog(tc, 0.1, 0.55))
        shown = start + dt.timedelta(days=int(round((p["days"] or 0) * roll)))
        tx = 660 if (flip and self.photo_key) else 120  # where the words start
        D.text(c, short_date(shown), th.display, 250, th.ink, tx, 150, e_out)
        D.text(c, str(d.year), "mono", 28, th.muted, tx + 12, 130, A.ease(tc, 0.1, A.FAST) * e_out)
        if p.get("days"):
            ed = A.ease(tc, 0.7, A.FAST)
            D.text(c, f"{p['days']} DAYS AFTER THE {(p.get('incident') or 'incident').upper()}", th.label, 30, th.accent, tx + 8, 468, ed * e_out, tracking=0.16,
                   clip=(tx, 450, tx + 1000 * ed, 450 + D.lead(th.label, 70)))
        ea = A.ease(t, self.t_arrest - 0.05, A.FAST)
        if ea > 0:
            txt = f"{p['who']} {p['event']}".upper().strip()
            size = D.fit_size(txt, th.display, (1380 - 180) if self.photo_key else 1680, 120, 60)
            D.text(c, txt, th.display, size, th.ink, tx, 580 + (120 - size) * 0.6, e_out, clip=(tx, 570, tx + 1700 * ea, 740))
        if self.t_charge:
            ec = A.prog(t, self.t_charge, A.SNAP)
            if ec > 0:
                txt = p["charge"].upper()
                w, _ = D.measure(txt, th.label, 44, 0.08)
                s = A.out_back(ec, 1.8)
                bw, bh = int((w + 60) * s), int(D.lead(th.label, 84) * s)
                D.rect(c, tx, 780, tx + max(2, bw), 780 + max(2, bh), th.accent, e_out)
                if s > 0.6:
                    D.text(c, txt, th.label, 44, "#FFFFFF", tx + 30, 795, min(1, ec * 2) * e_out, tracking=0.08)
        if self.photo_key:
            ep = A.ease(tc, 0.35, 0.45, A.out_quint)
            px, pw = (0 if flip else 1380), 540
            img = D.photo(self.assets.path(self.photo_key), pw, 1052, focus=(0.48, 0.3), zoom=1.0 + 0.04 * A.clamp(tc / 6),
                          sat=0.0, contrast=1.12, bright=0.9, headroom=1.08)
            D.blit(c, img, px, 14, e_out, clip=(px, 14, px + pw, 14 + 1052 * ep))
            ex = px + pw if flip else px - 6  # the accent edge faces the words
            D.rect(c, ex, 14, ex + 6, 14 + 1052 * ep, th.accent, e_out)
            cap = (p.get("subject") or "").upper() + (f" · {p['age']}" if p.get("age") else "")
            ec = A.ease(tc, 0.7, A.FAST)
            D.rect(c, px, 940, px + pw, 1066, "#000000", 0.6 * ec * e_out)
            D.text(c, cap, th.label, 24, "#FFFFFF", px + 30, 960, ec * e_out, tracking=0.14)
            D.text(c, self.assets.credit(self.photo_key), "mono", 12, "#FFFFFF", px + 30, 1004, 0.8 * ec * e_out)
        if fl > 0:
            D.rect(c, 0, 0, D.W, D.H, "#FFFFFF", fl * 0.9)


def _break_question(q, key="inter-black"):
    words = q.split()
    if len(words) <= 3:
        return [q]
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if D.measure(" ".join(cur), key, 132)[0] > 760 and len(cur) > 1:
            lines.append(" ".join(cur[:-1]))
            cur = [w]
    lines.append(" ".join(cur))
    return lines


# ============================================================ registration

THEMES = {
    "findings": Theme("findings", bg="#0B1120", bg2="#121A2E", ink="#F4F1EA", muted="#8E9AB3", accent="#F2B33D", accent2="#FF6A55",
                      display="oswald", heading="oswald-md", body="inter-bold", label="inter-bold"),
    "timeline": Theme("timeline", bg="#0F1013", bg2="#17181C", ink="#F3EFE8", muted="#8C8A86", accent="#E5484D", accent2="#E5484D",
                      display="oswald", heading="inter-bold", body="dm-sans", label="inter-bold"),
    "contradiction": Theme("contradiction", bg="#0C131D", bg2="#1C150F", ink="#F5F2EC", muted="#9A958C", accent="#6CA6FF", accent2="#F0A04B",
                           display="poppins", heading="poppins", body="dm-sans", label="inter-bold"),
    "legal": Theme("legal", bg="#EFE9DC", bg2="#E6DFCF", ink="#16130F", muted="#6E665A", accent="#8E1B1B", accent2="#8E1B1B",
                   display="caladea", heading="caladea", body="serif", label="inter-bold"),
    "digital": Theme("digital", bg="#05090B", bg2="#0A1418", ink="#E6FFFB", muted="#8DBDB7", accent="#2EE6D6", accent2="#FF4D5E",
                     display="mono", heading="mono", body="dm-sans", label="mono"),
    "turning": Theme("turning", bg="#000000", bg2="#0A0A0A", ink="#FFFFFF", muted="#8A8A8A", accent="#E10600", accent2="#E10600",
                     display="inter-black", heading="inter-black", body="inter-bold", label="inter-bold"),
}


# v0.4.63 Look options (cinegfx/look.py): three tested colour sets per category (the first is the approved design)
# and the other surface where the design has one; every set meets text 4.5:1 and accent 3:1 against its background.
_F = ("bg", "bg2", "ink", "muted", "accent", "accent2")


def _set(*colors):
    return dict(zip(_F, colors))


_PICTURES = ("own", "footage", "still", "photo")
# v0.4.64 type and layout: the font styles and the text size range each layout was checked with (tests/cinegfx_layout.py:
# no text running into other text, cut by its box or off the frame, on the approved Javits graphics and the app's own)
_TYPE = {"size": (0.85, 1.15)}
LOOKS = {
    "findings": {"palettes": [
        ("A", "Navy & amber", None),
        ("B", "Graphite & red", _set("#101214", "#1A1D21", "#F2F2F0", "#8A9099", "#E5484D", "#F2B33D")),
        ("C", "Forest & brass", _set("#0C1512", "#13201B", "#EFF3EE", "#86A096", "#D9B45B", "#E07A5F")),
        ("L", "Light version", _set("#F3F1EC", "#E7E3DA", "#14161C", "#666B78", "#B7791F", "#D2483A"))],
        **_TYPE, "fonts": ("sans", "serif", "geometric"), "mirror": "Photo on the right", "place": True,
        "present": {"prefer": "partial", "anchor": -1.0,
                    "why": "a photo card and a few facts: it can sit beside the footage"}},
    "timeline": {"palettes": [
        ("A", "Black & red", None),
        ("B", "Navy & gold", _set("#0B1220", "#131C2E", "#F4F1EA", "#8E9AB3", "#E8B04B", "#E8B04B")),
        ("C", "Charcoal & teal", _set("#111416", "#1A1F22", "#EEF2F1", "#87918F", "#2BB3A3", "#2BB3A3")),
        ("L", "Light version", _set("#F2EFE8", "#E6E2D8", "#15161A", "#6B6862", "#C62828", "#C62828"))],
        **_TYPE, "fonts": ("condensed", "sans", "serif", "geometric"), "place": True,
        "present": {"prefer": "own", "why": "a rail of dated cards across the whole width"}},
    "contradiction": {"palettes": [
        ("A", "Blue vs orange", None),
        ("B", "Teal vs coral", _set("#0B1416", "#1A1410", "#F3F5F2", "#8F9A96", "#39C3B5", "#FF7A59")),
        ("C", "Silver vs red", _set("#111214", "#1C1213", "#F4F2EE", "#96918C", "#C9D1DC", "#E5484D")),
        ("L", "Light version", _set("#F2F1EE", "#ECE6DF", "#15171A", "#6E6A64", "#2F6FD0", "#C9731C"))],
        "backdrops": ("own",),
        "backdrop_note": "Conflicting accounts keeps its own background: its two account columns fill the screen, so no picture would show.",
        **_TYPE, "fonts": ("condensed", "sans", "serif"),
        "present": {"prefer": "own", "lock": True, "why": "two account columns fill the screen"}},
    "legal": {"palettes": [
        ("A", "Cream & oxblood", None),
        ("B", "Cool paper & navy", _set("#ECEEF0", "#E1E4E8", "#121417", "#5F6670", "#1F3A68", "#1F3A68")),
        ("C", "Cream & green stamp", _set("#EFEBDF", "#E4DFD0", "#14150F", "#666452", "#1E5B3A", "#1E5B3A")),
        ("D", "Dark docket", _set("#15130F", "#1E1B16", "#F1EBDD", "#9C9282", "#D0503F", "#D0503F"))],
        **_TYPE, "fonts": ("condensed", "sans", "mono"), "mirror": "Courthouse photo on the right", "place": True,
        "dim": 0.75,
        "present": {"prefer": "footage", "why": "a court record reads clearly over darkened footage"}},  # v0.4.64: its small red labels over a picture: 2.8:1 at the general 62%, 3.5:1 at 75%
    "digital": {"palettes": [
        ("A", "Cyan terminal", None),
        ("B", "Amber terminal", _set("#0A0804", "#15110A", "#FFF6E5", "#BCA67F", "#FFB000", "#FF4D5E")),
        ("C", "Green phosphor", _set("#040A06", "#0A160E", "#E9FFF1", "#86BC98", "#39FF88", "#FF4D5E"))],
        **_TYPE, "fonts": ("condensed", "sans", "geometric"), "place": True,
        "present": {"prefer": "own", "lock": True, "why": "small evidence-log text needs its own dark screen"}},
    "turning": {"palettes": [
        ("A", "Black & red", None),
        ("B", "Black & burnt orange", _set("#000000", "#0A0A0A", "#FFFFFF", "#8A8A8A", "#D4500F", "#D4500F")),
        ("C", "Black & royal blue", _set("#000000", "#0A0A0A", "#FFFFFF", "#8A8A8A", "#1F6FEB", "#1F6FEB"))],
        "on_accent": ("#FFFFFF",),  # "CHARGED WITH MURDER" is white on the accent
        **_TYPE, "fonts": ("condensed", "serif", "geometric"), "mirror": "Photo on the left", "place": True,
        "present": {"prefer": "own", "why": "a full-screen statement marks the turn in the story"}},
}


# ============================================================ photo slots (what each graphic can show)
# A slot is filled only with a photo the producer has in the project (matched by file name, or chosen by
# hand), with the credit they type. Nothing is generated, searched for or substituted.

def _person(name, label=None):
    return {"key": "person:" + name, "kind": "person", "value": name, "label": label or f"Photo of {name}"}


def slots_findings(p):
    return [_person(p["source"], f"Photo of {p['source']} (who gave the findings)")] if p.get("source") else []


def slots_timeline(p):
    out, seen = [], set()
    for e in p.get("events") or []:
        for n in e.get("people") or []:
            if n not in seen:
                seen.add(n)
                out.append(_person(n, f"Photo of {n} (on the {short_date(dt.date.fromisoformat(e['date']))} card)"))
    last = (p.get("events") or [{}])[-1]
    if last.get("tag"):
        out.append({"key": "tag:" + last["tag"], "kind": "tag", "value": last["tag"], "label": f"Photo of the {last['tag']} (last card; no faces of mourners)"})
    return out


def slots_contradiction(p):
    vias = list(dict.fromkeys(k["via"] for side in ("family", "official") for k in p.get(side) or [] if k.get("via")))
    return [_person(v, f"Small portrait of {v} (who relayed a statement)") for v in vias]


def slots_legal(p):
    return [{"key": "place:" + p["court"], "kind": "place", "value": p["court"], "label": f"The court building ({p['court']})"}] if p.get("court") else []


def slots_digital(p):
    return [{"key": "place:" + p["place"], "kind": "place", "value": p["place"], "label": f"Location photo ({p['place']})"}] if p.get("place") else []


def slots_turning(p):
    return [_person(p["subject"], f"Photo of {p['subject']} (black and white)")] if p.get("subject") else []


class TrueCrime(Collection):
    key = "truecrime"
    label = "True crime"

    def __init__(self):
        super().__init__()
        self.add(Category("findings", "Investigative Findings", THEMES["findings"], detect_findings, FindingsGraphic, max_window=4, min_window=2,
                          slots=slots_findings, about="What an investigator said, each point with its status (possible, ruled out, not announced).", looks=LOOKS["findings"]))
        self.add(Category("timeline", "Chronological Timeline", THEMES["timeline"], detect_timeline, TimelineGraphic, max_window=5,
                          slots=slots_timeline, about="Three or more dated events (or exact times on one day) on a rail, each landing as it is spoken.", looks=LOOKS["timeline"]))
        self.add(Category("contradiction", "Contradictory Statements", THEMES["contradiction"], detect_contradiction, ContradictionGraphic,
                          max_window=3, min_window=2, slots=slots_contradiction, about="Two attributed accounts that oppose each other, side by side.", looks=LOOKS["contradiction"]))
        self.add(Category("legal", "Legal Outcome", THEMES["legal"], detect_legal, LegalGraphic, max_window=3,
                          slots=slots_legal, about="Charges, court, judge and the outcome, as a docket with a stamp.", looks=LOOKS["legal"]))
        self.add(Category("digital", "Digital Evidence Analysis", THEMES["digital"], detect_digital, DigitalGraphic, max_window=3,
                          slots=slots_digital, about="An evidence log (three or more kinds of evidence), with the route when police described one.", looks=LOOKS["digital"]))
        self.add(Category("turning", "Case Turning Point", THEMES["turning"], detect_turning, TurningGraphic, max_window=2, min_window=2,
                          cross_chapter=True, slots=slots_turning, about="A question (or the narration's own count of days), then the dated event that changes the case.", looks=LOOKS["turning"]))


register(TrueCrime())
