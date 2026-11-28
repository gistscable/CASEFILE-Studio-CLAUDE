"""v0.4.76 Combat sports collection (boxing, MMA, wrestling): three categories.

  tape      Tale of the tape     two fighters and what the narration measures of each (record, height, reach,
                                 weight, age, knockouts), side by side with the edge marked
  journey   Championship journey three or more dated title moments (won, defended, lost, regained), as a run
                                 of belt plates
  legacy    Superstar legacy     three or more dated defining moments (rivalries, wins, streaks, returns,
                                 betrayals, departures) as a wall of polaroids, a photo in each when the project
                                 has one

Words on screen are the narration's; photos only from the project.
"""
from __future__ import annotations

import re

from PIL import Image

from .. import anim as A
from .. import draw as D
from ..core import Category, Collection, Graphic, register
from ..theme import Theme
from . import _kit as K

# ============================================================ 1. TALE OF THE TAPE (tape)

N = K.NUMW_I
FT_RE = re.compile(rf"\b({N})\s*(?:feet|foot|ft\.?|')\s*(?:,?\s*(?:and\s+)?({N})\s*(?:inches|inch|in\.?|\"|”)?)?(?:\s+tall)?", re.I)
CM_RE = re.compile(r"\b(1[4-9]\d|2[0-2]\d)\s*(?:cm|centimet(?:re|er)s)\b(?:\s+tall)?", re.I)
REACH_RE = re.compile(rf"\b(?:({N})[- ](?:inch|in\.?)\s+reach|reach of\s+({N})\s*(?:inches|in\.?|\"|”)|({N})\s*(?:inches|in\.?)\s+of reach)", re.I)
REACH_CM_RE = re.compile(r"\b(?:(\d{3})\s*(?:cm|centimet(?:re|er)s?)\s+reach|reach of\s+(\d{3})\s*(?:cm|centimet(?:re|er)s?))", re.I)
WEIGHT_RE = re.compile(rf"\b(?:weigh(?:ed|s|ing)(?: in at)?\s+)?({N})\s*(?:pounds|lbs?\.?|kilograms|kilos|kg)\b", re.I)
REC_RE = re.compile(rf"\b(?:record of\s+|undefeated\s+|unbeaten\s+)?({N})\s+(?:wins|victories)\s*,?\s+({N})\s+(?:loss(?:es)?|defeats?)"
                    rf"(?:\s*,?\s*(?:and\s+)?({N})\s+draws?)?(?:\s*,?\s*(?:and|with)?\s*({N})\s+(?:knockouts|KOs|stoppages|by knockout))?", re.I)
REC_DASH = re.compile(r"\b(?:record of|record at|went|undefeated at|unbeaten at|stood at|a)\s+(\d{1,3})[-–](\d{1,3})(?:[-–](\d{1,2}))?\b")
KO_RE = re.compile(rf"\b({N})\s+(?:knockouts|KOs|stoppages)\b", re.I)
AGE_RE = re.compile(rf"\b(?:aged\s+({N})|({N})[- ]year[- ]old|at the age of\s+({N}))\b", re.I)


def _n(x):
    v = K.number(x)
    return None if v is None else int(v)


def _measures(text):
    """{key: (shown, value, phrase)} what one sentence measures of a fighter."""
    out = {}
    m = REC_RE.search(text)
    if m:
        w, l_ = _n(m.group(1)), _n(m.group(2))
        d = _n(m.group(3)) if m.group(3) else None
        out["record"] = (f"{w}-{l_}" + (f"-{d}" if d is not None else ""), w - l_, m.group(0)[:40])
        if m.group(4):
            ko = _n(m.group(4))
            out["ko"] = (str(ko), ko, m.group(0)[:40])
    else:
        m = REC_DASH.search(text)
        if m:
            w, l_ = int(m.group(1)), int(m.group(2))
            out["record"] = (m.group(1) + "-" + m.group(2) + (("-" + m.group(3)) if m.group(3) else ""), w - l_, m.group(0))
    if "ko" not in out:
        m = KO_RE.search(text)
        if m:
            ko = _n(m.group(1))
            out["ko"] = (str(ko), ko, m.group(0))
    m = FT_RE.search(text)
    if m and _n(m.group(1)) and 4 <= _n(m.group(1)) <= 7:
        ft, inch = _n(m.group(1)), (_n(m.group(2)) if m.group(2) else 0) or 0
        if inch < 12:
            out["height"] = (f"{ft}′{inch}″", ft * 12 + inch, m.group(0)[:30])
    else:
        m = CM_RE.search(text)
        if m:
            out["height"] = (f"{m.group(1)} CM", int(m.group(1)) / 2.54, m.group(0))
    m = REACH_RE.search(text)
    if m:
        v = _n(next(g for g in m.groups() if g))
        if v and 55 <= v <= 90:
            out["reach"] = (f"{v}″", v, m.group(0))
    else:
        m = REACH_CM_RE.search(text)
        if m:
            v = int(next(g for g in m.groups() if g))
            out["reach"] = (f"{v} CM", v / 2.54, m.group(0))
    m = WEIGHT_RE.search(text)
    if m and _n(m.group(1)):
        v = _n(m.group(1))
        kg = re.search(r"kilo|kg", m.group(0), re.I)
        out["weight"] = (f"{v} {'KG' if kg else 'LBS'}", v * (2.2046 if kg else 1), m.group(0)[:30])
    m = AGE_RE.search(text)
    if m:
        v = _n(next(g for g in m.groups() if g))
        if v and 15 <= v <= 70:
            out["age"] = (str(v), -v, m.group(0))   # younger is the edge
    return out


ROWS = [("record", "RECORD"), ("height", "HEIGHT"), ("reach", "REACH"), ("weight", "WEIGHT"), ("ko", "KNOCKOUTS"), ("age", "AGE")]


def _fighter_name(story, s):
    names = [n for n in s.people if not K.is_club(n)]
    lead = K.lead_name(s.text)
    if lead:
        return lead
    return names[0] if names else ""


@K.safe
def detect_tape(story, a, b):
    if b - a > 3:
        return None
    fighters = []
    for s in story.sentences[a:b]:
        # a sentence may measure two fighters ("Tyson stood 5ft 10in ...; Paul stood 6ft 1in ..."): split at ; and at ", while"
        for part in re.split(r";\s*|,\s+while\s+|\.\s+", s.text):
            ms = _measures(part)
            if len(ms) < 2:
                continue
            name = K.lead_name(part) or _fighter_name(story, s)
            if not name or any(f["name"] == name for f in fighters):
                continue
            fighters.append({"name": name, "m": ms})
    if len(fighters) != 2:
        return None
    if not _measures(story.sentences[a].text) or not _measures(story.sentences[b - 1].text):
        return None
    common = [k for k, _ in ROWS if k in fighters[0]["m"] and k in fighters[1]["m"]]
    if len(common) < 2:
        return None
    rows = []
    for k, label in ROWS:
        if k not in common:
            continue
        l_, r_ = fighters[0]["m"][k], fighters[1]["m"][k]
        edge = 0 if l_[1] > r_[1] else 1 if r_[1] > l_[1] else -1
        rows.append({"key": k, "label": label, "left": l_[0], "right": r_[0], "edge": edge, "phrase_l": l_[2], "phrase_r": r_[2]})
    score = min(0.97, 0.72 + 0.06 * len(rows))
    return score, {"left": fighters[0]["name"], "right": fighters[1]["name"], "rows": rows}, [f"{len(rows)} measures of two fighters"]


class TapeGraphic(Graphic):
    def build(self):
        p = self.p
        self.rows = []
        for i, r in enumerate(p["rows"]):
            hl = self.tl.phrase(r["phrase_l"])
            hr = self.tl.phrase(r["phrase_r"], hl[2] if hl else 0)
            tl_ = (hl[0] if hl else 0.8 + 0.6 * i) - 0.05
            tr_ = (hr[0] if hr else tl_ + 1.5) - 0.05
            self.rows.append(dict(r, tl=max(0.5, tl_), tr=max(0.6, tr_)))
        self.keys = [self.assets.find(person=p["left"])[0], self.assets.find(person=p["right"])[0]]
        self.cue(0.0, "ring-bell-1", -14, "the bell")
        self.cue(0.1, "whoosh-dir-r", -9, "fighters in")
        for r in self.rows:
            self.cue(r["tl"], "punch-2", -15, "left measure")
            self.cue(r["tr"], "punch-1", -15, "right measure")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        ein = A.ease(t, 0.05, 0.55, A.out_quint)
        colors = (th.accent, th.accent2)
        # the fighters: photos at the sides, or their colour panel
        for side in (0, 1):
            key = self.keys[side]
            w = 560
            x = -w * (1 - ein) if side == 0 else 1920 - w + w * (1 - ein)
            if key:
                img = D.photo(self.assets.path(key), w, 1080, focus=(0.5, 0.3), zoom=1.0 + 0.04 * A.clamp(t / max(1.0, self.out)))
                img = K.slanted(img, 120, right=(side == 0))
                D.blit(c, img, x, 0, e_out)
                D.blit(c, D.gradient(w, 420, th.c("bg", 0), th.c("bg", 250)), x, 660, e_out)
                K.credit(c, self.assets, key, 24 if side == 0 else 1896, 1040, "#FFFFFF", 0.85 * e_out, anchor="l" if side == 0 else "r")
            else:
                pts = [(x, 0), (x + 100, 0), (x, 1080)] if side == 0 else [(x + w, 0), (x + w, 1080), (x + w - 100, 1080)]
                K.tri(c, pts, colors[side], 0.85 * e_out)
            name = K.short_name(p["left" if side == 0 else "right"]).upper()
            ns = K.fit(name, th.display, 400, 110, 48)
            nx = 150 if side == 0 else 1770
            D.text(c, name, th.display, ns, th.ink, nx + (-60 if side == 0 else 60) * (1 - ein), 820 + (110 - ns) * 0.7, ein * e_out,
                   anchor="l" if side == 0 else "r")
            D.rect(c, (nx if side == 0 else nx - 140 * ein), 990, (nx + 140 * ein if side == 0 else nx), 998, colors[side], e_out)
        # the centre column
        cx = 960
        et = A.ease(t, 0.2, A.FAST)
        D.text(c, "TALE OF THE TAPE", th.label, 26, th.accent, cx, 96, et * e_out, anchor="c", tracking=0.24)
        D.text(c, "VS", th.display, 72, th.ink, cx, 136, et * e_out, anchor="c")
        n = max(1, len(self.rows))
        step = min(132, 560 / n)
        top = 300 + (560 - step * n) / 2
        for i, r in enumerate(self.rows):
            y = top + i * step
            el, er = A.ease(t, r["tl"], A.FAST), A.ease(t, r["tr"], A.FAST)
            if el <= 0 and er <= 0:
                continue
            D.text(c, r["label"], th.label, 24, th.muted, cx, y + 30, max(el, er) * e_out, anchor="c", tracking=0.2)
            eb = A.ease(t, max(r["tl"], r["tr"]) + 0.3, A.FAST)
            for side, e, val in ((0, el, r["left"]), (1, er, r["right"])):
                if e <= 0:
                    continue
                edge = r["edge"] == side
                colr = colors[side] if edge else th.ink
                vx = cx - 170 if side == 0 else cx + 170
                w = D.text(c, val, th.display, 76, colr, vx + (20 if side == 0 else -20) * (1 - A.out_smooth(e)), y, e * e_out,
                           anchor="r" if side == 0 else "l")
                if edge and eb > 0:  # the edge: the value underlined in its corner's colour
                    x0 = vx - w if side == 0 else vx
                    D.rect(c, x0, y + 104, x0 + w * eb, y + 110, colors[side], e_out)
            D.rect(c, cx - 400, y + step - 8, cx + 400, y + step - 7, th.muted, 0.25 * e_out)


# ============================================================ 2. CHAMPIONSHIP JOURNEY (journey)

ORGS = (r"WBC|WBA|IBF|WBO|IBO|The Ring|Ring Magazine|UFC|Bellator|ONE|PFL|WWE|WWF|WCW|AEW|NXT|ECW|TNA|NWA|Olympic|undisputed|lineal|"
        r"heavyweight|cruiserweight|light[- ]heavyweight|super[- ]middleweight|middleweight|welterweight|lightweight|featherweight|bantamweight|flyweight|"
        r"Intercontinental|Universal|Tag Team|World Heavyweight|United States|European")
TITLE_RE = re.compile(rf"(?:(?:the|his|her|a|their)\s+)?((?:(?:{ORGS})\s+){{0,3}})(title|titles|belt|belts|championship|championships|crown|strap|gold medal)\b", re.I)
JWIN = r"won|win|winning|took|taking|claimed|captured|lifted|became|retained|defended|unified|regained|reclaimed|beat|defeated|knocked out|stopped|submitted|pinned|outpointed"
JLOSS = r"lost|losing|dropped|surrendered|was stripped of|were stripped|vacated|relinquished|gave up|were gone|was gone"
JWIN_RE = re.compile(rf"\b(?:{JWIN})\b", re.I)
JLOSS_RE = re.compile(rf"\b(?:{JLOSS})\b", re.I)
REGAIN_RE = re.compile(r"\b(?:regained|reclaimed|won back|took back|recaptured)\b", re.I)


def _title_moments(story, a, b):
    out = []
    for s in story.sentences[a:b]:
        txt = s.text
        if not K.years_in(txt) or not TITLE_RE.search(txt):
            continue
        parts, start = [], 0
        for m in re.finditer(r";|,\s+(?:and|but|then)\s+|\s+and then\s+", txt):
            parts.append((start, m.start()))
            start = m.end()
        parts.append((start, len(txt)))
        last_year = None
        for p0, p1 in parts:
            cl = txt[p0:p1]
            yy = K.years_in(cl)
            year = yy[0][0] if yy else last_year
            if yy:
                last_year = yy[-1][0]
            tm = TITLE_RE.search(cl)
            if year is None or not tm:
                continue
            ml, mw = JLOSS_RE.search(cl), JWIN_RE.search(cl)
            if not ml and not mw:
                continue
            lost = bool(ml and (not mw or ml.start() < mw.start() or re.search(r"(?:were|was) gone", cl)))
            m = ml if lost and ml.start() < (mw.start() if mw else 10 ** 6) else (mw or ml)
            # the belt has its own line: the label is what happened ("Defeated Trevor Berbick", "Lost to Buster Douglas")
            label = K.headline(cl[m.start():], 46, cut=r"\s+(?:to (?:win|take|claim|capture|become|lift|retain|unify)|for (?:the|his|her) )")
            if len(label) < 6:
                label = K.headline(cl, 46)
            org = re.sub(r"\s+", " ", (tm.group(1) or "").strip()).upper()
            belt = (org + " " + tm.group(2).upper()).strip() if org else tm.group(2).upper()
            out.append({"year": year, "label": label, "kind": "lost" if lost else ("regained" if REGAIN_RE.search(cl) else "won"),
                        "belt": belt, "phrase": cl[m.start():m.start() + 26].strip(), "year_phrase": str(year) if yy else "", "sent": s.i})
    return out


@K.safe
def detect_journey(story, a, b):
    ms = _title_moments(story, a, b)
    if len(ms) < 3:
        return None
    sents = {m["sent"] for m in ms}
    if story.sentences[a].i not in sents or story.sentences[b - 1].i not in sents:
        return None
    ms = ms[:6]
    subject = K.subject_of(story, a, b)
    kinds = {m["kind"] for m in ms}
    score = min(0.96, 0.7 + 0.06 * (len(ms) - 3) + (0.06 if "lost" in kinds else 0))
    return score, {"subject": subject, "moments": ms}, [f"{len(ms)} title moments"]


class JourneyGraphic(Graphic):
    def build(self):
        p = self.p
        self.ms, last = [], 0
        for i, m in enumerate(p["moments"]):
            hit = self.tl.phrase(m["phrase"], last)
            if hit:
                last = hit[2]
            yh = self.tl.phrase(m["year_phrase"], max(0, last - 160)) if m.get("year_phrase") else None
            t = min([x for x in ((hit[0] if hit else None), (yh[0] if yh else None)) if x is not None] or [0.7 + 1.0 * i])
            self.ms.append(dict(m, t=max(0.5, t - 0.05)))
        for i in range(1, len(self.ms)):
            self.ms[i]["t"] = max(self.ms[i]["t"], self.ms[i - 1]["t"] + 0.4)
        n = len(self.ms)
        self.cw = int(min(400, (1680 - 30 * (n - 1)) / n))
        self.xs = [120 + i * (self.cw + 30) + (1680 - n * self.cw - 30 * (n - 1)) / 2 for i in range(n)]
        self.photo_key = self.assets.find(person=p["subject"])[0] if p.get("subject") else None
        self.cue(0.0, "ring-bell-3", -15, "the bell")
        self.cue(0.1, "whoosh-mid-1", -9, "title")
        for m in self.ms:
            if m["kind"] == "lost":
                self.cue(m["t"], "thump-deep-3", -8, "title lost")
            else:
                self.cue(m["t"], "arena-hit-1" if m["kind"] == "regained" else "impact-tr-1", -11, "title won")
                self.cue(m["t"] + 0.1, "crowd-cheer-1", -18, "the crowd")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        ek = A.ease(t, 0.1, A.FAST)
        D.text(c, "CHAMPIONSHIP JOURNEY", th.label, 24, th.accent, 120, 116, ek * e_out, tracking=0.22)
        name = (p.get("subject") or "").upper()
        maxw = 1680 - (220 if self.photo_key else 0)
        ns = K.fit(name, th.display, maxw, 100, 48)
        D.text(c, name, th.display, ns, th.ink, 120, 152 + (100 - ns) * 0.6, e_out, clip=(120, 146, 120 + maxw * A.ease(t, 0.15, 0.5), 290))
        if self.photo_key:
            e = A.ease(t, 0.2, 0.45)
            img = K.circle_photo(D.photo(self.assets.path(self.photo_key), 176, 176, focus=(0.5, 0.3)))
            D.blit(c, D.disc(188, th.c("accent")), 1800 - 188, 104, e * e_out)
            D.blit(c, img, 1800 - 182, 110, e * e_out)
        # the strap the plates hang on
        sy = 540
        D.rect(c, 120, sy - 6, 120 + 1680 * A.ease(t, 0.15, 0.7, A.out_quint), sy + 6, th.bg2, e_out)
        for i, m in enumerate(self.ms):
            e = A.ease(t, m["t"], 0.32)
            if e <= 0:
                continue
            x, w = self.xs[i], self.cw
            lost = m["kind"] == "lost"
            colr = th.accent2 if lost else th.accent
            s = 0.85 + 0.15 * A.out_back(min(1, e), 1.8)
            pw, ph = int(w * s), int(230 * s)
            px, py = x + (w - pw) / 2, sy - ph / 2
            D.blit(c, D.rounded(pw, ph, 26, th.c("bg2"), D.col(colr), 4), px, py, e * e_out)
            ic = K.icon("belt", int(110 * s), th.muted if lost else colr)
            D.blit(c, ic, px + pw / 2 - ic.width / 2, py + 12 * s, e * e_out)
            D.text(c, str(m["year"]), th.display, int(68 * s), th.ink if not lost else th.muted, px + pw / 2, py + ph - 100 * s, e * e_out, anchor="c")
            if lost:  # struck through: the reign ended
                es = A.ease(t, m["t"] + 0.25, A.SNAP)
                D.rect(c, px + 20, py + ph / 2 - 3, px + 20 + (pw - 40) * es, py + ph / 2 + 3, th.accent2, e_out)
            eb = A.ease(t, m["t"] + 0.2, A.FAST)
            belt_lines = D.wrap(m["belt"], th.label, 24, w - 12, 0.12)[:2]
            for j, line in enumerate(belt_lines):
                D.text(c, line, th.label, 24, colr, x + w / 2, 700 + j * D.lead(th.label, 32), eb * e_out, anchor="c", tracking=0.12)
            ly = 700 + D.lead(th.label, 32) * len(belt_lines) + 20
            for j, line in enumerate(D.wrap(m["label"], th.heading, 36, w - 12)[:3]):
                D.text(c, line, th.heading, 36, th.ink, x + w / 2, ly + j * D.lead(th.heading, 46), eb * e_out, anchor="c")


# ============================================================ 3. SUPERSTAR LEGACY (legacy)

L_UP = (r"beat|defeated|pinned|submitted|knocked out|stopped|won|headlined|main-evented|debuted|made (?:his|her) debut|returned|came back|"
        r"made (?:a|his|her) comeback|shocked|stunned|was inducted|entered the Hall of Fame|broke the record|set a record|unified|crowned")
L_DOWN = (r"streak ended|lost|was betrayed|betrayed|turned on|attacked|left|walked out|departed|quit|was released|was fired|was suspended|"
          r"retired|announc\w+ (?:his|her) retirement|was injured|suffered|was banned|failed a drug test|tested positive|was stripped")
RIVAL_RE = re.compile(r"\brivalry with\s+((?:The\s+)?[A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,2})|\b((?:The\s+)?[A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,2})['’]s?\s+rivalry with\s+((?:The\s+)?[A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,2})")


@K.safe
def detect_legacy(story, a, b):
    per = K.cache(story, "legacy")
    if (a, b) in per:
        return per[(a, b)]
    res = None
    pts = K.career_points(story, a, b, L_UP, L_DOWN)
    text = story.window_text(a, b)
    rm = RIVAL_RE.search(text)
    sents = {q["sent"] for q in pts}
    first_ok = story.sentences[a].i in sents or (rm and rm.start() < len(story.sentences[a].text))
    if len(pts) >= 3 and first_ok and story.sentences[b - 1].i in sents:
        pts = pts[:5]
        rival = ""
        subject = K.subject_of(story, a, b)
        if rm:
            if rm.group(1):
                rival = rm.group(1)
            else:
                subject, rival = rm.group(2), rm.group(3)
        for q in pts:  # the person named in each moment, for its photo
            s = story.sentences[q["sent"]]
            q["people"] = [n for n in s.people if not K.is_club(n)][:2]
            for nm in (rival, subject):
                if nm and re.search(rf"\b{re.escape(K.short_name(nm))}\b", q["label"]) and nm not in q["people"]:
                    q["people"].append(nm)
        score = min(0.95, 0.68 + 0.05 * (len(pts) - 3) + (0.1 if rival else 0))
        res = score, {"subject": subject, "rival": rival, "moments": pts, "rival_phrase": rm.group(0)[:40] if rm else ""}, \
            [f"{len(pts)} defining moments" + (f", the rivalry with {rival}" if rival else "")]
    per[(a, b)] = res
    return res


SPOTS = [(150, 330, -5.0), (590, 380, 3.5), (1030, 320, -2.5), (1450, 370, 4.5), (820, 560, -1.5)]


class LegacyGraphic(Graphic):
    PW, PH = 400, 480   # the polaroid (photo area 360 x 330)

    def build(self):
        p = self.p
        self.ms, last = [], 0
        for i, m in enumerate(p["moments"]):
            hit = self.tl.phrase(m["phrase"], last)
            if hit:
                last = hit[2]
            yh = self.tl.phrase(m["year_phrase"], max(0, last - 160)) if m.get("year_phrase") else None
            t = min([x for x in ((hit[0] if hit else None), (yh[0] if yh else None)) if x is not None] or [0.7 + 1.0 * i])
            self.ms.append(dict(m, t=max(0.5, t - 0.05)))
        for i in range(1, len(self.ms)):
            self.ms[i]["t"] = max(self.ms[i]["t"], self.ms[i - 1]["t"] + 0.4)
        n = len(self.ms)
        spots = SPOTS[:n] if n < 5 else SPOTS
        if n == 3:
            spots = [(200, 350, -4.0), (760, 320, 2.5), (1320, 360, -3.0)]
        elif n == 4:
            spots = [(120, 360, -4.0), (560, 320, 3.0), (1000, 365, -2.0), (1420, 330, 4.0)]
        elif n == 5:
            spots = [(90, 330, -4.0), (440, 390, 3.0), (780, 320, -2.0), (1120, 385, 3.5), (1450, 335, -3.0)]
        self.spots = spots
        used = set()
        self.keys = []
        for m in self.ms:
            key = None
            for nm in m.get("people", []):
                k = self.assets.find(person=nm)[0]
                if k and k not in used:
                    key = k
                    break
            if key:
                used.add(key)
            self.keys.append(key)
        self.cards = [self._card(i) for i in range(n)]
        self.cue(0.05, "arena-boom-1", -16, "the arena")
        for m in self.ms:
            self.cue(m["t"], "flash-1", -12, "polaroid")
            self.cue(m["t"] + 0.12, "thump-deep-1" if m["dir"] == "down" else "punch-3", -13, "moment")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def _card(self, i):
        """The polaroid as a sprite (rotated): photo or year in the window, the caption drawn by draw()."""
        th, m = self.th, self.ms[i]
        W_, H_ = self.PW, self.PH
        with K.no_record():
            card = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
            card.alpha_composite(D.rounded(W_, H_, 6, D.col("#F4F1EA")))
            key = self.keys[i]
            if key:
                card.alpha_composite(D.photo(self.assets.path(key), W_ - 40, 330, focus=(0.5, 0.3), sat=0.85, contrast=1.05), (20, 20))
            else:
                D.rect(card, 20, 20, W_ - 20, 350, th.bg2)
                D.text(card, str(m["year"]), th.display, 124, th.accent2 if m["dir"] == "down" else th.accent, W_ / 2, 108, anchor="c")
        return card

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        ek = A.ease(t, 0.1, A.FAST)
        D.text(c, "SUPERSTAR LEGACY", th.label, 24, th.accent, 120, 96, ek * e_out, tracking=0.22)
        title = (p.get("subject") or "").upper()
        if p.get("rival"):
            title = f"{K.short_name(p['subject']).upper()} VS {K.short_name(p['rival']).upper()}" if p.get("subject") else p["rival"].upper()
        ts = K.fit(title, th.display, 1680, 96, 44)
        D.text(c, title, th.display, ts, th.ink, 120, 130 + (96 - ts) * 0.6, e_out, clip=(120, 124, 120 + 1700 * A.ease(t, 0.15, 0.5), 260))
        for i, m in enumerate(self.ms):
            e = A.prog(t, m["t"], 0.4)
            if e <= 0:
                continue
            x, y, rot = self.spots[i]
            s = A.out_back(e, 1.4)
            drop = (1 - A.out_cubic(e)) * -60
            card = self.cards[i]
            ang = rot * (0.4 + 0.6 * s)
            im = card.rotate(ang, resample=Image.BICUBIC, expand=True)
            # a flash: the card brightens as it lands
            flash = max(0.0, 1 - A.prog(t, m["t"], 0.25))
            D.blit(c, im, x + (self.PW - im.width) / 2, y + drop + (self.PH - im.height) / 2, min(1, e * 2.5) * e_out)
            if flash > 0:
                D.blit(c, D.rounded(self.PW, self.PH, 6, (255, 255, 255, 255)), x, y + drop, flash * 0.5 * e_out)
            # the caption on the polaroid's white strip (dark ink)
            ec = A.ease(t, m["t"] + 0.2, A.FAST)
            cy = y + drop + 366
            cap = D.wrap(m["label"], th.body, 26, self.PW - 40)[:2]
            if self.keys[i]:
                D.text(c, str(m["year"]), th.label, 24, "#8A2A2A" if m["dir"] == "down" else "#1C1C1C", x + self.PW / 2, cy - 8, ec * e_out, anchor="c", tracking=0.1)
                cy += 30
            elif len(cap) == 1:
                cy += 16
            for j, line in enumerate(cap):
                D.text(c, line, th.body, 26, "#1C1C1C", x + self.PW / 2, cy + j * D.lead(th.body, 32), ec * e_out, anchor="c")


# ============================================================ registration

THEMES = {
    "tape": Theme("cb-tape", bg="#0B0B0D", bg2="#16161A", ink="#F7F5F0", muted="#9B9890", accent="#E5484D", accent2="#4C9BFF",
                  display="oswald", heading="oswald-md", body="inter-bold", label="inter-bold"),
    "journey": Theme("cb-journey", bg="#0E0B06", bg2="#1C1710", ink="#FBF6EA", muted="#A79C86", accent="#E9B949", accent2="#E5534B",
                     display="oswald", heading="oswald-md", body="inter-bold", label="inter-bold"),
    "legacy": Theme("cb-legacy", bg="#121010", bg2="#2A2523", ink="#F6F2EC", muted="#A59D94", accent="#E9B949", accent2="#E5534B",
                    display="inter-black", heading="inter-bold", body="dm-sans", label="inter-bold"),
}
_F = ("bg", "bg2", "ink", "muted", "accent", "accent2")


def _set(*colors):
    return dict(zip(_F, colors))


_TYPE = {"size": (0.85, 1.15)}
LOOKS = {
    "tape": {"palettes": [
        ("A", "Red corner, blue corner", None),
        ("B", "Gold & silver", _set("#0D0C0A", "#191714", "#F6F3EC", "#9C978C", "#E9B949", "#C9D1DC")),
        ("C", "Neon fight night", _set("#0A0612", "#140D22", "#F5F2FF", "#9E95B8", "#FF4FA3", "#38D6FF"))],
        **_TYPE, "fonts": ("condensed", "geometric"),
        "backdrops": ("own",), "backdrop_note": "The tale of the tape keeps its own background: the two fighters fill the screen.",
        "present": {"prefer": "own", "lock": True, "why": "two fighters and their numbers fill the screen"}},
    "journey": {"palettes": [
        ("A", "Championship gold", None),
        ("B", "Silver & red", _set("#0D0E10", "#1A1C20", "#F4F5F7", "#9499A3", "#C9D1DC", "#E5484D")),
        ("C", "Royal purple & gold", _set("#120A1C", "#1F132E", "#F7F2FF", "#A89BBE", "#E9B949", "#FF6B6B"))],
        **_TYPE, "fonts": ("condensed", "sans", "geometric"), "place": True,
        "present": {"prefer": "own", "why": "a run of belt plates across the whole width"}},
    "legacy": {"palettes": [
        ("A", "Dark wall", None),
        ("B", "Concrete", _set("#1A1B1D", "#2B2D30", "#F3F3F1", "#A3A5A8", "#F2B33D", "#F0524F")),
        ("C", "Deep red", _set("#1A0A0B", "#2B1214", "#F8EFEC", "#B39A97", "#F2B33D", "#FF7A6B"))],
        **_TYPE, "fonts": ("sans", "geometric", "condensed"),
        "present": {"prefer": "own", "why": "a wall of polaroids across the whole width"}},
}


def _person(name, label):
    return {"key": "person:" + name, "kind": "person", "value": name, "label": label}


def slots_tape(p):
    return [_person(p["left"], f"Photo of {p['left']} (left corner)"), _person(p["right"], f"Photo of {p['right']} (right corner)")]


def slots_journey(p):
    return [_person(p["subject"], f"Small portrait of {p['subject']}")] if p.get("subject") else []


def slots_legacy(p):
    seen, out = set(), []
    for m in p.get("moments", []):
        for nm in m.get("people", []):
            if nm not in seen:
                seen.add(nm)
                out.append(_person(nm, f"Polaroid of {nm}"))
    return out[:5]


class Combat(Collection):
    key = "combat"
    label = "Boxing, MMA & wrestling"

    def __init__(self):
        super().__init__()
        self.add(Category("tape", "Tale of the tape", THEMES["tape"], detect_tape, TapeGraphic, max_window=3, slots=slots_tape,
                          about="Two fighters and what the narration measures of each (record, height, reach, weight), side by side.",
                          looks=LOOKS["tape"]))
        self.add(Category("journey", "Championship journey", THEMES["journey"], detect_journey, JourneyGraphic, max_window=4,
                          slots=slots_journey, about="Three or more dated title moments (won, defended, lost, regained) as belt plates.",
                          looks=LOOKS["journey"]))
        self.add(Category("legacy", "Superstar legacy", THEMES["legacy"], detect_legacy, LegacyGraphic, max_window=5, min_window=2,
                          slots=slots_legacy, about="Three or more dated defining moments (rivalries, returns, betrayals, departures) as polaroids.",
                          looks=LOOKS["legacy"]))


register(Combat())
