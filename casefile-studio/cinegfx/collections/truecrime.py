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
    payload = {"source": lead, "role": story.role_of(lead), "items": items[:5], "quote": quotes[0] if quotes else None,
               "briefing": briefing.isoformat() if briefing else None, "chapter": story.chapters[story.sentences[a].chapter].title,
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
        # --- photo panel
        px0, py0, pw, ph = 96, 96, 680, 888
        if self.photo_key:
            e = A.ease(t, 0.0, 0.5, A.out_expo)
            img = D.photo(self.assets.path(self.photo_key), pw, ph, focus=(0.77, 0.42), zoom=A.drift(t, self.duration, 0.07), sat=0.92, contrast=1.06)
            reveal = py0 + ph * (1 - e)
            D.blit(c, img, px0, py0, e_out, clip=(px0, reveal, px0 + pw, py0 + ph))
            D.blit(c, D.gradient(pw, 360, (11, 17, 32, 0), (11, 17, 32, 245)), px0, py0 + ph - 360, e * e_out)
            D.rect(c, px0 + pw - 6, reveal, px0 + pw, py0 + ph, th.accent, e_out)
            en = A.ease(t, 0.3, A.FAST)
            name = p["source"].upper()
            D.text(c, name, th.display, 64, th.ink, px0 + 40 - 30 * (1 - en), py0 + ph - 170, en * e_out)
            D.text(c, (p["role"] or "").upper(), th.label, 22, th.accent, px0 + 42, py0 + ph - 88, en * e_out, tracking=0.14)
            cr = self.assets.credit(self.photo_key)
            D.rect(c, px0, py0, px0 + D.measure(cr, "mono", 14)[0] + 28, py0 + 34, "#000000", 0.55 * en * e_out)
            D.text(c, cr, "mono", 14, "#FFFFFF", px0 + 14, py0 + 9, 0.85 * en * e_out)
        # --- heading
        x0 = 856
        ek = A.ease(t, 0.12, A.FAST)
        kicker = f"CHAPTER {p['chapter_no']} · {p['chapter'].upper()}" if p.get("chapter_no") else p["chapter"].upper()
        D.text(c, kicker, th.label, 20, th.muted, x0 + 30 * (1 - ek), 112, ek * e_out, tracking=0.16)
        eh = A.ease(t, 0.2, 0.34)
        surname = p["source"].split()[-1].upper()
        D.text(c, f"WHAT {surname} SAID", th.display, 92, th.ink, x0, 140, e_out, clip=(x0, 140, x0 + 960 * eh, 280))
        if p.get("briefing"):
            b = dt.date.fromisoformat(p["briefing"])
            D.text(c, f"NYPD BRIEFING · {long_date(b).upper()}", "mono", 20, th.accent, x0 + 2, 268, A.ease(t, 0.45, A.FAST) * e_out)
        D.rect(c, x0, 312, x0 + 968 * A.ease(t, 0.3, 0.5), 315, th.ink, 0.25 * e_out)
        # --- finding rows
        y = 340
        for i, r in enumerate(self.rows):
            er = A.ease(t, r["t"], A.FAST)
            if er <= 0:
                y += 112
                continue
            D.text(c, f"{i + 1:02d}", "mono", 22, th.accent, x0, y + 22, er * e_out)
            lx = x0 + 70 + 40 * (1 - er)
            D.text(c, r["label"], th.heading, 56, th.ink, lx, y, e_out, clip=(x0 + 60, y - 10, x0 + 70 + 700 * er, y + 90))
            sub = r.get("note") or (f"{r['source'].split()[-1]} said" if r.get("source") else "")
            if r["kind"] == "ruled" and r.get("evidence"):
                sub = "“" + r["evidence"] + "”"
            sub = sub if len(sub) < 70 else sub[:67].rsplit(" ", 1)[0] + "…”"
            D.text(c, sub, th.body, 20, th.muted, x0 + 72, y + 74, A.ease(t, r["t"] + 0.2, A.FAST) * e_out)
            # status chip
            ec = A.prog(t, r["t"] + 0.14, A.SNAP)
            if ec > 0:
                chip = _chip(r["status"], th, r["kind"])
                s = A.out_back(ec, 1.6)
                cw, ch = max(1, int(chip.width * s)), max(1, int(chip.height * s))
                ci = chip.resize((cw, ch), Image.BICUBIC) if s != 1 else chip
                D.blit(c, ci, x0 + 968 - chip.width + (chip.width - cw) / 2, y + 14 + (chip.height - ch) / 2, min(1, ec * 3) * e_out)
            D.rect(c, x0, y + 104, x0 + 968 * A.ease(t, r["t"], 0.5), y + 105, th.ink, 0.12 * e_out)
            y += 112
        # --- pull quote, typed in time with the narration
        q = p.get("quote")
        if q and self.q0 is not None:
            eq = A.ease(t, self.q0 - 0.1, A.FAST)
            qy = 812
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
            ds = [d for d in s.dates if ca <= d.start < cb]
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
            evs.append({"date": main.date.isoformat(), "label": headline(label), "sub": sub.strip(" ,."), "phrase_date": main.text,
                        "phrase_clause": clause.strip(" ,;")[:40], "rel": rel, "sent": s.i})
    return evs


def detect_timeline(story, a, b):
    evs = _events(story, a, b)
    dates = {e["date"] for e in evs}
    if len(dates) < 3:
        return None
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
        self.crump_key, _ = self.assets.find(person="Ben Crump")
        self.vigil_key, _ = self.assets.find(tag="vigil")
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
        D.text(c, p["chapter"].upper(), th.display, 72, th.ink, 120, 124, e_out, clip=(120, 120, 120 + 1700 * eh, 240))
        first = dt.date.fromisoformat(p["incident"]) if p.get("incident") else dt.date.fromisoformat(self.events[0]["date"])
        lastd = dt.date.fromisoformat(self.events[-1]["date"])
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
                dy = ry - 120 + 30 * (1 - A.out_expo(ed))
                D.text(c, short_date(d), th.display, 92, th.ink, x, dy - 20, e_out, anchor="c", clip=(x - 200, ry - 150, x + 200, ry - 12))
            # card below the rail
            cy = ry + 40
            card_w = 330
            cx0 = x - card_w / 2
            D.rect(c, cx0, cy, cx0 + card_w * ee, cy + 4, th.accent if e.get("rel") else th.ink, e_out)
            yy = cy + 24
            photo_key = self.crump_key if "Crump" in e["label"] else (self.vigil_key if re.search(r"vigil", e["label"], re.I) and i == len(self.events) - 1 else None)
            if photo_key:
                ph = 150
                img = D.photo(self.assets.path(photo_key), card_w, ph, focus=(0.55, 0.32) if photo_key == self.crump_key else (0.62, 0.6),
                              zoom=1 + 0.05 * A.prog(t, e["t"], 4.0), sat=0.95)
                D.blit(c, img, cx0, yy, e_out, clip=(cx0, yy, cx0 + card_w, yy + ph * A.ease(t, e["t"] + 0.05, 0.35)))
                D.text(c, self.assets.credit(photo_key), "mono", 12, th.muted, cx0, yy + ph + 6, ee * e_out)
                yy += ph + 30
            for j, line in enumerate(D.wrap(e["label"], th.heading, 34, card_w)):
                D.text(c, line, th.heading, 34, th.ink, cx0 + 24 * (1 - ee), yy + j * 42, ee * e_out)
            yy += 42 * len(D.wrap(e["label"], th.heading, 34, card_w)) + 6
            if e.get("sub"):
                for j, line in enumerate(D.wrap(e["sub"], th.body, 22, card_w)):
                    D.text(c, line, th.body, 22, th.muted, cx0, yy + j * 30, A.ease(t, e["t"] + 0.2, A.FAST) * e_out)


# ============================================================ 3. CONTRADICTORY STATEMENTS

def _side(story, claim):
    role = story.role_of(claim.source)
    if role in FAMILY_ROLES or claim.source.lower().startswith(("his ", "her ", "the family")):
        return "family"
    return "official"


def detect_contradiction(story, a, b):
    claims = [(s, c) for s in story.sentences[a:b] for c in s.claims if c.content and len(c.content.split()) > 3]
    best = None
    for i, (s1, c1) in enumerate(claims):
        for s2, c2 in claims[i + 1:]:
            if c1.source == c2.source or c1.negated == c2.negated:
                continue
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
    # context: what does "that incident" refer to? the earliest quoted account of it
    context = None
    for s in story.sentences[:a]:
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
        cite = re.search(r",\s*citing ([^,]+),", story.sentences[[s.i for s, cc in claims if cc is c][0]].text)
        return {"who": who, "via": c.via, "cite": cite.group(1) if cite else "", "text": headline(c.content), "negated": c.negated,
                "phrase": c.content[:30]}

    ch = story.chapters[story.sentences[a].chapter]
    payload = {"family": [pack(c) for c in sides["family"]], "official": [pack(c) for c in sides["official"]],
               "topic": sorted(ov), "context": context, "chapter": ch.title}
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
        self.crump_key, _ = self.assets.find(person="Ben Crump")
        self.cue(0.0, "whoosh-short-1", -8, "halves in")
        self.cue(0.12, "whoosh-short-2", -10, "halves in")
        for k in self.cards:
            self.cue(k["t"], "click-mech-2", -6, "statement")
        self.cue(self.t_neq, "impact-tr-1", -9, "contradiction")
        self.cue(self.t_neq, "bass-hit-1", -14, "contradiction")
        self.cue(self.out, "rwhoosh-3", -9, "out")

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
        D.text(c, "THE FAMILY’S ACCOUNT", th.label, 22, th.accent2, 110, 110, A.ease(t, 0.3, A.FAST) * e_out, tracking=0.2)
        D.text(c, "OFFICIAL ACCOUNTS", th.label, 22, th.accent, 1050, 110, A.ease(t, 0.35, A.FAST) * e_out, tracking=0.2)
        D.rect(c, 110, 150, 110 + 740 * es, 152, th.accent2, 0.6 * e_out)
        D.rect(c, 1050, 150, 1050 + 760 * es, 152, th.accent, 0.6 * e_out)
        ys = {"family": 220, "official": 220}
        for k in self.cards:
            x0 = 110 if k["side"] == "family" else 1050
            accent = th.accent2 if k["side"] == "family" else th.accent
            y = ys[k["side"]]
            ek = A.ease(t, k["t"], A.FAST)
            lines = D.wrap(k["text"], th.heading, 44, 760)
            if ek <= 0:
                ys[k["side"]] += 100 + 58 * len(lines) + 60
                continue
            who = k["who"]
            if k.get("via"):
                who = f"{k['who']} · AS RELAYED BY {k['via'].upper()}"
            if k.get("cite"):
                who = f"{k['who']} · CITING {k['cite'].upper()}"
            ax = x0
            if k.get("via") and self.crump_key and k["via"] == "Ben Crump":
                av = D.photo(self.assets.path(self.crump_key), 64, 64, focus=(0.55, 0.3), headroom=1.0)
                mask = D.disc(64, (255, 255, 255, 255))
                av.putalpha(mask.split()[3])
                D.blit(c, av, x0, y - 14, ek * e_out)
                ax += 82
            for j, line in enumerate(D.wrap(who, th.label, 20, 760 - (ax - x0), 0.12)):
                D.text(c, line, th.label, 20, accent, ax + 20 * (1 - ek), y + j * 28, ek * e_out, tracking=0.12)
            # statement words appear as they are spoken (the script's own words)
            body = k["text"]
            lines = D.wrap(body, th.heading, 44, 760)
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
                    wpx = D.text(c, w + " ", th.heading, 44, colr, lx, y + 56 + j * 58, e_out)
                    if neg:
                        D.rect(c, lx, y + 56 + j * 58 + 60, lx + wpx - 14, y + 56 + j * 58 + 64, accent, e_out)
                    lx += wpx
            ys[k["side"]] += 100 + 58 * len(lines) + 60
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

def detect_legal(story, a, b):
    sents = story.sentences[a:b]
    txt = " ".join(s.text for s in sents)
    m = re.search(r"charges? of ([^.]+?)(?:,\s*police said|\.|;)", txt) or re.search(r"charged with ([^.,;]+)", txt)
    if not m:
        return None
    charges = [x.strip() for x in re.split(r",\s*|\s+and\s+(?=[a-z])", m.group(1)) if x.strip()]
    court = next((pl for s in sents for pl in s.places if re.search(r"Court", pl)), None)
    judge = next((n for s in sents for n in s.people if story.role_of(n) in ("Judge", "Justice")), None)
    outcome = re.search(r"\b(remanded without bail|held without bail|released on bail|convicted|acquitted|sentenced to [^.]+)", txt)
    date = next((d for s in sents for d in s.dates), None)
    hearing = re.search(r"\b(arraigned|indicted|sentenced|convicted|acquitted)\b", txt)
    attrib = re.search(r",\s*(police said|prosecutors said)", txt)
    n = sum(bool(x) for x in (court, judge, outcome, date))
    if n < 2:
        return None
    payload = {"charges": charges, "court": court, "judge": judge, "outcome": outcome.group(1) if outcome else None,
               "date": date.date.isoformat() if date else None, "date_phrase": date.text if date else None,
               "hearing": hearing.group(1) if hearing else None, "attrib": attrib.group(1) if attrib else None,
               "defendant": "17-year-old" if "17-year-old" in txt else "defendant"}
    return 0.5 + 0.1 * n + 0.04 * len(charges), payload, [f"charges {charges}; court={court}; judge={judge}; outcome={payload['outcome']}"]


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
        D.blit(c, _ruled(th), 0, 0, e_out)
        # header band
        eb = A.ease(t, 0.0, 0.4, A.out_quint)
        D.rect(c, 0, 0, D.W, 150 * eb, th.accent, e_out)
        D.text(c, (p.get("court") or "COURT").upper(), th.display, 64, th.bg, 120, 40, A.ease(t, 0.2, A.FAST) * e_out, clip=(0, 0, D.W, 150 * eb))
        if p.get("date"):
            d = dt.date.fromisoformat(p["date"])
            lbl = f"{(p.get('hearing') or 'hearing').upper().replace('ARRAIGNED', 'ARRAIGNMENT')} · {long_date(d).upper()}"
            D.text(c, lbl, "mono", 24, th.bg, 1800, 62, A.ease(t, self.t_court, A.FAST) * e_out, anchor="r")
        # courthouse photo, printed look: white border, hard offset shadow (no blur)
        if self.court_key:
            ep = A.ease(t, 0.15, 0.45)
            x0, y0, s = 120, 250, 540
            D.rect(c, x0 + 14, y0 + 14, x0 + s + 34, y0 + s + 34, "#000000", 0.18 * ep * e_out)
            D.rect(c, x0, y0, x0 + s + 20, y0 + s + 20, "#FFFFFF", ep * e_out)
            img = D.photo(self.assets.path(self.court_key), s, s, focus=(0.5, 0.45), zoom=A.drift(t, self.duration, 0.05), headroom=1.06)
            D.blit(c, img, x0 + 10, y0 + 10, e_out, clip=(x0 + 10, y0 + 10, x0 + 10 + s * ep, y0 + 10 + s))
            src = self.assets.items[self.court_key]
            D.text(c, src["subject"].split(",")[0].upper(), "mono", 16, th.ink, x0, y0 + s + 46, ep * e_out)
            D.text(c, self.assets.credit(self.court_key), "mono", 14, th.muted, x0, y0 + s + 72, ep * e_out)
        # docket
        x0 = 790
        ed = A.ease(t, 0.25, A.FAST)
        D.text(c, "DEFENDANT", th.label, 20, th.accent, x0, 230, ed * e_out, tracking=0.2)
        D.text(c, p["defendant"].upper(), th.heading, 46, th.ink, x0 + 220, 214, ed * e_out)
        D.rect(c, x0, 282, x0 + 1010 * A.ease(t, 0.3, 0.5), 284, th.ink, 0.4 * e_out)
        D.text(c, "CHARGES", th.label, 20, th.accent, x0, 316, ed * e_out, tracking=0.2)
        y = 350
        for i, (ch, t0, t1) in enumerate(self.charges):
            ec = A.prog(t, t0 - 0.04, max(0.18, (t1 - t0) * 0.7))
            if ec > 0:
                D.text(c, str(i + 1), "mono", 30, th.accent, x0, y + 16, e_out)
                txt = ch.upper()
                D.text(c, txt, th.heading, 52, th.ink, x0 + 60, y, e_out, clip=(x0 + 60, y - 10, x0 + 60 + D.measure(txt, th.heading, 52)[0] * A.out_cubic(ec) + 4, y + 80))
            y += 78
        if self.t_attr:
            D.text(c, "— " + p["attrib"].upper(), th.label, 20, th.muted, x0 + 60, y + 4, A.ease(t, self.t_attr, A.FAST) * e_out, tracking=0.16)
        if self.t_judge:
            ej = A.ease(t, self.t_judge, A.FAST)
            yj = 668
            D.rect(c, x0, yj - 24, x0 + 1010 * ej, yj - 22, th.ink, 0.4 * e_out)
            D.text(c, "BEFORE", th.label, 20, th.accent, x0, yj + 8, ej * e_out, tracking=0.2)
            D.text(c, "JUDGE " + p["judge"].upper(), th.heading, 46, th.ink, x0 + 220, yj - 6, e_out,
                   clip=(x0 + 220, yj - 20, x0 + 220 + 800 * ej, yj + 70))
        # the stamp
        if self.t_out:
            es = A.prog(t, self.t_out, 0.13)
            if es > 0:
                st = _stamp(p["outcome"], th)
                sc = 0.74 * (1.0 + 0.9 * (1 - A.out_expo(es)))
                w, h = int(st.width * sc), int(st.height * sc)
                img = st.resize((w, h), Image.BICUBIC) if sc != 1 else st
                cx, cy = 1450, 905
                shake = 4 * (1 - A.prog(t, self.t_out + 0.13, 0.12)) if es >= 1 else 0
                D.blit(c, img, cx - w / 2 + shake, cy - h / 2, min(1, es * 2.5) * e_out)


def _ruled(th):
    key = ("ruled", th.name)
    if key not in _CACHE:
        im = Image.new("RGBA", (D.W, D.H), (0, 0, 0, 0))
        col = th.c("muted", 22)
        for y in range(190, D.H, 52):
            im.paste(col, (0, y, D.W, y + 1))
        im.paste(th.c("accent", 60), (740, 150, 742, D.H))
        _CACHE[key] = im
    return _CACHE[key]


def _stamp(outcome, th):
    key = ("stamp", outcome)
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
]
MOVES = r"(went through|boarded|jumped|tracked into|fled to|drove to|ran to|took)"


def detect_digital(story, a, b):
    sents = story.sentences[a:b]
    txt = " ".join(s.text for s in sents)
    items = []
    for s in sents:
        for pat, label in EVIDENCE:
            m = re.search(pat, s.text, re.I)
            if m and label not in [i["label"] for i in items] and label != "TURNSTILE":
                items.append({"label": label, "phrase": m.group(0), "sent": s.i})
    route = []
    for s in sents:
        for m in re.finditer(rf"{MOVES}\s+(?:a\s+|the\s+)?((?:No\.\s*\d+|[^,;.])+?)(?=,|;|\.| and were| and |$)", s.text):
            route.append({"verb": m.group(1), "what": m.group(2).strip(), "phrase": m.group(0)[:28]})
    if len(items) < 2 or len(route) < 2:
        return None
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
        m = re.search(r"around (\d{1,2}:\d{2})", s.text)
        if m and not time:
            time = m.group(1)
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
    payload = {"items": items, "route": route, "origin": origin, "origin_loc": loc, "time": time, "date": inc.isoformat() if inc else None,
               "briefing": briefing}
    return 0.55 + 0.08 * len(items) + 0.06 * len(route), payload, [f"evidence {[i['label'] for i in items]} + route of {len(route)} moves"]


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
        self.station_key, _ = self.assets.find(place="Freeman Street station")
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
            if "station" in r["what"].lower():
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
            D.text(c, f"SOURCE: POLICE ACCOUNT · BRIEFING {short_date(b)}, {b.year}", "mono", 18, th.muted, 1860, 22, eh * e_out, anchor="r")
        D.rect(c, 0, 64, D.W * A.ease(t, 0.05, 0.5), 66, th.accent, 0.8 * e_out)
        tc = max(0.0, t)
        D.text(c, f"T+{int(tc // 60):02d}:{tc % 60:05.2f}", "mono", 18, th.accent, 1860, 1030, 0.7 * eh * e_out, anchor="r")
        # evidence log
        x0 = 80
        D.text(c, "EVIDENCE LOG", "mono", 20, th.muted, x0, 112, A.ease(t, 0.2, A.FAST) * e_out)
        y = 160
        for i, it in enumerate(self.items):
            ei = A.ease(t, it["t"] - 0.05, A.FAST)
            if ei <= 0:
                y += 230
                continue
            D.blit(c, D.rounded(760, 200, 4, th.c("bg2"), th.c("accent", 70), 2), x0, y, ei * e_out)
            D.rect(c, x0, y, x0 + 6, y + 200, th.accent, ei * e_out)
            D.text(c, f"E{i + 1:02d}", "mono", 18, th.muted, x0 + 30, y + 22, ei * e_out)
            D.text(c, A.typed(it["label"], t, it["t"], 40), th.heading, 40, th.ink, x0 + 30, y + 46, e_out)
            if it.get("detail"):
                for j, line in enumerate(D.wrap(it["detail"], th.body, 22, 690)[:1]):
                    D.text(c, line, th.body, 22, th.muted, x0 + 30, y + 104 + j * 30, A.ease(t, it["t"] + 0.4, A.FAST) * e_out)
            if it.get("status"):
                es = A.prog(t, it["ts"], A.SNAP)
                if es > 0:
                    bad = "NOT" in it["status"]
                    colr = th.accent2 if bad else th.accent
                    w, _ = D.measure(it["status"], "mono", 18)
                    tag = D.rounded(w + 28, 34, 3, D.col(colr, 40), D.col(colr), 2)
                    D.blit(c, tag, x0 + 730 - tag.width, y + 148, min(1, es * 3) * e_out)
                    D.text(c, it["status"], "mono", 18, colr, x0 + 730 - tag.width + 14, y + 155, min(1, es * 3) * e_out)
            y += 230
        # route panel
        rx0 = 960
        er = A.ease(t, self.t_route0, A.FAST)
        if er > 0:
            D.text(c, "ROUTE · AS DESCRIBED BY POLICE", "mono", 20, th.muted, rx0, 112, er * e_out)
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
            colr = "#00933C" if a.get("train") else th.accent
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
                D.blit(c, D.disc(56, D.col("#00933C")), x - 28 + 60, yy - 28, min(1, en * 2) * e_out)
                D.text(c, n.get("route_no") or "", "lib-sans", 40, "#FFFFFF", x + 60, yy - 24, min(1, en * 2) * e_out, anchor="c")
            lx = x + (110 if n.get("train") else 40)
            D.text(c, n["label"], th.heading, 34, th.ink, lx, yy - 26, e_out, clip=(lx, yy - 40, lx + 600 * A.out_expo(min(1, en * 1.4)), yy + 30))
            if n.get("sub"):
                D.text(c, n["sub"], "mono", 16, th.muted, lx + 2, yy + 18, A.ease(t, n["t"] + 0.35, A.FAST) * e_out)
        # location tile with a crisp scan line
        if self.station_key:
            ts = self._t_station()
            ep = A.ease(t, ts, 0.35)
            if ep > 0:
                x, y0, w, h = 1610, 330, 220, 340
                img = D.photo(self.assets.path(self.station_key), w, h, focus=(0.5, 0.5), headroom=1.04, sat=0.85, contrast=1.08)
                D.blit(c, img, x, y0, e_out, clip=(x, y0, x + w, y0 + h * ep))
                D.outline(c, x - 2, y0 - 2, x + w + 2, y0 + h * ep + 2, th.accent, 2, e_out)
                sl = A.prog(t, ts + 0.1, 0.8)
                if 0 < sl < 1:
                    D.rect(c, x, y0 + h * sl, x + w, y0 + h * sl + 2, th.accent, e_out)
                D.text(c, "FREEMAN ST STATION", "mono", 14, th.ink, x, y0 + h + 10, ep * e_out)
                D.text(c, self.assets.credit(self.station_key), "mono", 12, th.muted, x, y0 + h + 30, ep * e_out)

    def _nodes(self):
        if hasattr(self, "_n"):
            return self._n
        p = self.p
        nodes = []
        sub = " · ".join(x for x in [p.get("origin_loc", "") and "SHOOTING NEAR " + p["origin_loc"].upper().replace("EAST ", "E ").replace("STREET", "ST").replace("PLACE", "PL").replace(" AND ", " & "),
                                      (f"{short_date(dt.date.fromisoformat(p['date']))} · ~{p['time']} AM" if p.get("date") and p.get("time") else "")] if x)
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
    if not q.question or not ans.dates or not re.search(TURN_VERBS, ans.text):
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
    payload = {"subject": story.subject, "age": age, "question": q.text, "date": ans.dates[0].date.isoformat(), "date_phrase": ans.dates[0].text, "days": days,
               "who": m.group(2) if m else "", "event": m.group(3) if m else "", "charge": m.group(4) if m and m.group(4) else "",
               "event_phrase": "had been arrested" if m else ans.text.split()[2]}
    return (0.75 if strong else 0.55) + (0.1 if days else 0), payload, [f"question answered by dated event ({days} days after incident)"]


class TurningGraphic(Graphic):
    def build(self):
        p = self.p
        q = p["question"]
        self.qwords = []
        for w in self.tl.words:
            if w.a < len(q) + 2 and T.norm(w.text) and self.tl.text[: w.b].strip() in q:
                self.qwords.append(w)
        self.t_q_end = self.qwords[-1].end if self.qwords else 1.5
        pz = self.tl.next_pause_after(self.t_q_end - 0.05)
        self.t_cut = self.at(p["date_phrase"], default=(pz[1] if pz else self.t_q_end + 0.4))
        self.t_event = self.at(p["event_phrase"], default=self.t_cut + 2)
        self.t_arrest = self.at(p["event"], default=self.t_event) if p.get("event") else self.t_event
        self.t_charge = self.at(p["charge"], default=self.t_arrest + 0.8) if p.get("charge") else None
        self.photo_key, _ = self.assets.find(person="Javits Frimpong")
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
        if t < self.t_cut:
            # phase 1 — the question, word by word over his photograph (B/W, sharp)
            if self.photo_key:
                e = A.ease(t, 0.0, 0.4)
                img = D.photo(self.assets.path(self.photo_key), 1100, 1080, focus=(0.48, 0.3), zoom=1.0 + 0.06 * A.clamp(t / self.t_cut),
                              sat=0.0, contrast=1.12, bright=0.85)
                D.blit(c, img, 820, 0, e, clip=(820 + 1100 * (1 - e), 0, 1920, 1080))
                D.blit(c, D.gradient(420, 1080, (0, 0, 0, 255), (0, 0, 0, 0), vertical=False), 820, 0)
                cr = self.assets.credit(self.photo_key)
                cw = D.measure(cr, "mono", 14)[0]
                D.rect(c, 1890 - cw - 14, 1030, 1904, 1064, "#000000", 0.6 * e)
                D.text(c, cr, "mono", 14, "#FFFFFF", 1890, 1039, 0.85 * e, anchor="r")
            lines = _break_question(p["question"].upper())
            k, y = 0, 300
            for line in lines:
                x = 120
                for wtxt in line.split():
                    w = self.qwords[k] if k < len(self.qwords) else None
                    tw = w.start - 0.03 if w else 0.3
                    ew = A.prog(t, tw, 0.12)
                    if ew > 0:
                        is_last = k == len(self.qwords) - 1
                        colr = th.accent if is_last else th.ink
                        dy = 26 * (1 - A.out_expo(ew))
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
        D.text(c, short_date(shown), th.display, 250, th.ink, 120, 150, e_out)
        D.text(c, str(d.year), "mono", 28, th.muted, 132, 130, A.ease(tc, 0.1, A.FAST) * e_out)
        if p.get("days"):
            ed = A.ease(tc, 0.7, A.FAST)
            D.text(c, f"{p['days']} DAYS AFTER THE SHOOTING", th.label, 30, th.accent, 128, 468, ed * e_out, tracking=0.16,
                   clip=(120, 450, 120 + 1000 * ed, 520))
        ea = A.ease(t, self.t_arrest - 0.05, A.FAST)
        if ea > 0:
            txt = f"{p['who']} {p['event']}".upper().strip()
            size = D.fit_size(txt, th.display, (1380 - 180) if self.photo_key else 1680, 120, 60)
            D.text(c, txt, th.display, size, th.ink, 120, 580 + (120 - size) * 0.6, e_out, clip=(120, 570, 120 + 1700 * ea, 740))
        if self.t_charge:
            ec = A.prog(t, self.t_charge, A.SNAP)
            if ec > 0:
                txt = p["charge"].upper()
                w, _ = D.measure(txt, th.label, 44, 0.08)
                s = A.out_back(ec, 1.8)
                bw, bh = int((w + 60) * s), int(84 * s)
                D.rect(c, 120, 780, 120 + max(2, bw), 780 + max(2, bh), th.accent, e_out)
                if s > 0.6:
                    D.text(c, txt, th.label, 44, "#FFFFFF", 150, 795, min(1, ec * 2) * e_out, tracking=0.08)
        if self.photo_key:
            ep = A.ease(tc, 0.35, 0.45, A.out_quint)
            px, pw = 1380, 540
            img = D.photo(self.assets.path(self.photo_key), pw, 1052, focus=(0.48, 0.3), zoom=1.0 + 0.04 * A.clamp(tc / 6),
                          sat=0.0, contrast=1.12, bright=0.9, headroom=1.08)
            D.blit(c, img, px, 14, e_out, clip=(px, 14, px + pw, 14 + 1052 * ep))
            D.rect(c, px - 6, 14, px, 14 + 1052 * ep, th.accent, e_out)
            cap = (p.get("subject") or "").upper() + (f" · {p['age']}" if p.get("age") else "")
            ec = A.ease(tc, 0.7, A.FAST)
            D.rect(c, px, 940, px + pw, 1066, "#000000", 0.6 * ec * e_out)
            D.text(c, cap, th.label, 24, "#FFFFFF", px + 30, 960, ec * e_out, tracking=0.14)
            D.text(c, self.assets.credit(self.photo_key), "mono", 12, "#FFFFFF", px + 30, 1004, 0.8 * ec * e_out)
        if fl > 0:
            D.rect(c, 0, 0, D.W, D.H, "#FFFFFF", fl * 0.9)


def _break_question(q):
    words = q.split()
    if len(words) <= 3:
        return [q]
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if D.measure(" ".join(cur), "inter-black", 132)[0] > 760 and len(cur) > 1:
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
    "digital": Theme("digital", bg="#05090B", bg2="#0A1418", ink="#E6FFFB", muted="#5E8C88", accent="#2EE6D6", accent2="#FF4D5E",
                     display="mono", heading="mono", body="dm-sans", label="mono"),
    "turning": Theme("turning", bg="#000000", bg2="#0A0A0A", ink="#FFFFFF", muted="#8A8A8A", accent="#E10600", accent2="#E10600",
                     display="inter-black", heading="inter-black", body="inter-bold", label="inter-bold"),
}


class TrueCrime(Collection):
    key = "truecrime"
    label = "True crime"

    def __init__(self):
        super().__init__()
        self.add(Category("findings", "Investigative Findings", THEMES["findings"], detect_findings, FindingsGraphic, max_window=4, min_window=2))
        self.add(Category("timeline", "Chronological Timeline", THEMES["timeline"], detect_timeline, TimelineGraphic, max_window=3))
        self.add(Category("contradiction", "Contradictory Statements", THEMES["contradiction"], detect_contradiction, ContradictionGraphic, max_window=3, min_window=2))
        self.add(Category("legal", "Legal Outcome", THEMES["legal"], detect_legal, LegalGraphic, max_window=2))
        self.add(Category("digital", "Digital Evidence Analysis", THEMES["digital"], detect_digital, DigitalGraphic, max_window=3))
        self.add(Category("turning", "Case Turning Point", THEMES["turning"], detect_turning, TurningGraphic, max_window=2, min_window=2, cross_chapter=True))


register(TrueCrime())
