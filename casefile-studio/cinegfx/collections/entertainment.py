"""v0.4.76 Entertainment collection (music, film, TV, celebrity): two categories.

  career    Career progression            three or more dated moments with at least one rise and one fall
                                          (breakthrough, fame, controversy, setback, comeback): the split
                                          portrait, the rise on one side and the fall on the other
  impact    Achievements and impact       three or more numbers of success (awards, copies sold, weeks at
                                          number one, views, streams, box office, tickets), each with its icon,
                                          counting up as said

Words on screen are the narration's; photos only from the project.
"""
from __future__ import annotations

import re

from PIL import Image, ImageEnhance

from .. import anim as A
from .. import draw as D
from ..core import Category, Collection, Graphic, register
from ..theme import Theme
from . import _kit as K

# ============================================================ 1. CAREER PROGRESSION (career)

E_UP = (r"released|broke through|burst onto|signed|starred|won|landed|topped|hit number one|became|headlined|sold out|"
        r"was nominated|premiered|debuted|returned|came back|made (?:a|his|her) comeback|launched|broke the record")
E_DOWN = (r"was accused|were accused|accused|was arrested|was charged|faced (?:allegations|charges|a lawsuit)|was sued|"
          r"scandal|controversy|was cancelled|was canceled|was dropped|was fired|flopped|bombed|was booed|went bankrupt|"
          r"lost (?:his|her|their)|entered rehab|checked into rehab|disappeared|vanished from|was banned|divorced|collapsed|struggled")


@K.safe
def detect_career(story, a, b):
    per = K.cache(story, "career")
    if (a, b) in per:
        return per[(a, b)]
    res = None
    pts = K.career_points(story, a, b, E_UP, E_DOWN)
    sents = {q["sent"] for q in pts}
    dirs = {q["dir"] for q in pts}
    if len(pts) >= 3 and dirs == {"up", "down"} and story.sentences[a].i in sents and story.sentences[b - 1].i in sents:
        pts = pts[:6]
        if all(pts[i]["year"] <= pts[i + 1]["year"] for i in range(len(pts) - 1)):
            kind, title = K.arc_title(pts)
            subject = K.subject_of(story, a, b)
            # a chapter title that says it in its own words ("From king to chaos") is the headline
            ch = story.chapters[story.sentences[a].chapter].title if story.chapters else ""
            if ch and re.search(r"\b(?:rise|fall|king|queen|chaos|glory|ruin|fame|downfall|comeback|redemption|from .+ to .+)\b", ch, re.I):
                title = ch.upper()
            score = min(0.95, 0.7 + 0.05 * (len(pts) - 3) + (0.06 if kind in ("redemption", "comeback") else 0))
            res = score, {"subject": subject, "title": title, "arc": kind, "points": pts}, [f"{len(pts)} career moments ({kind})"]
    per[(a, b)] = res
    return res


class CareerGraphic(Graphic):
    def build(self):
        p = self.p
        self.pts, last = [], 0
        for i, q in enumerate(p["points"]):
            hit = self.tl.phrase(q["phrase"], last)
            if hit:
                last = hit[2]
            yh = self.tl.phrase(q["year_phrase"], max(0, last - 160)) if q.get("year_phrase") else None
            t = min([x for x in ((hit[0] if hit else None), (yh[0] if yh else None)) if x is not None] or [0.7 + 1.0 * i])
            self.pts.append(dict(q, t=max(0.5, t - 0.05)))
        for i in range(1, len(self.pts)):
            self.pts[i]["t"] = max(self.pts[i]["t"], self.pts[i - 1]["t"] + 0.4)
        self.left = [q for q in self.pts if q["dir"] == "up" and not q["comeback"]]
        self.right = [q for q in self.pts if q["dir"] == "down"]
        self.back = [q for q in self.pts if q["comeback"]]
        self.t_fall = self.right[0]["t"] if self.right else self.out
        self.photo_key = self.assets.find(person=p["subject"])[0] if p.get("subject") else None
        self.cue(0.05, "warm-swell-1", -16, "the rise")
        self.cue(0.1, "whoosh-mid-1", -9, "panel")
        for q in self.left:
            self.cue(q["t"], "sparkle-1", -15, "a high")
        for q in self.right:
            self.cue(q["t"], "flash-2", -11, "the headlines")
            self.cue(q["t"] + 0.05, "thump-deep-2", -9, "the fall")
        for q in self.back:
            self.cue(q["t"], "riser-3", -14, "the comeback")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def _portrait(self, w, h, fall):
        img = D.photo(self.assets.path(self.photo_key), w, h, focus=(0.5, 0.3))
        if fall:  # the fall: drained, darker, a red cast (a grade, never a blur)
            g = ImageEnhance.Color(img.convert("RGB")).enhance(0.1)
            g = ImageEnhance.Brightness(g).enhance(0.8)
            red = Image.new("RGB", g.size, D.col(self.th.accent2)[:3])
            img = Image.blend(g, red, 0.22).convert("RGBA")
        return img

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        cx = 960
        ein = A.ease(t, 0.05, 0.5, A.out_quint)
        # the split portrait (or the two halves of colour) in the centre
        pw, ph, py = 520, 760, 230
        x0 = cx - pw / 2
        if self.photo_key:
            rise = self._portrait(pw, ph, False)
            D.blit(c, rise, x0, py, ein * e_out, clip=(x0, py, cx, py + ph))
            ef = A.ease(t, self.t_fall - 0.1, 0.5, A.out_cubic)
            if ef > 0:
                fall = self._portrait(pw, ph, True)
                D.blit(c, fall, x0, py, e_out, clip=(cx, py + ph * (1 - ef), x0 + pw, py + ph))
            D.blit(c, D.gradient(pw, 300, th.c("bg", 0), th.c("bg", 255)), x0, py + ph - 300, e_out)
            K.credit(c, self.assets, self.photo_key, cx, py + ph - 30, th.ink, 0.8 * e_out, anchor="c")
        else:  # no portrait: the two halves in colour, the climb and the drop drawn in them
            D.rect(c, x0, py, cx, py + ph * ein, th.accent, 0.14 * e_out)
            ef = A.ease(t, self.t_fall - 0.1, 0.5, A.out_cubic)
            D.rect(c, cx, py + ph * (1 - ef), x0 + pw, py + ph, th.accent2, 0.14 * e_out)
            if self.left:
                ea = A.ease(t, self.left[0]["t"], 0.6, A.out_cubic)
                K.arrow(c, [(x0 + 50, py + ph - 140), (x0 + 120, py + ph - 300), (x0 + 170, py + ph - 260), (cx - 40, py + 120)],
                        th.accent, 12, e_out, ea, head=46)
            if self.right:
                ea = A.ease(t, self.right[0]["t"], 0.6, A.out_cubic)
                K.arrow(c, [(cx + 40, py + 120), (cx + 110, py + 300), (cx + 150, py + 250), (x0 + pw - 50, py + ph - 140)],
                        th.accent2, 12, e_out, ea, head=46)
        # the split line (it stops above the comeback band)
        line_h = (ph + 20) if not self.back else (930 - 24 - (py - 20))
        D.rect(c, cx - 2, py - 20, cx + 2, py - 20 + line_h * A.ease(t, 0.2, 0.6, A.out_quint), th.ink, 0.9 * e_out)
        # the headline across the top
        et = A.ease(t, 0.15, 0.45)
        title = p.get("title") or ""
        ts = K.fit(title, th.display, 1680, 88, 44)
        D.text(c, title, th.display, ts, th.ink, cx, 96 + (88 - ts) * 0.6, e_out, anchor="c",
               clip=(cx - 860 * et, 80, cx + 860 * et, 250))
        D.text(c, (p.get("subject") or "").upper(), th.label, 24, th.accent, cx, 60, et * e_out, anchor="c", tracking=0.22)
        # the rise (left) and the fall (right)
        for side, items, colr in ((0, self.left, th.accent), (1, self.right, th.accent2)):
            if not items:
                continue
            word = "THE RISE" if side == 0 else "THE FALL"
            ew = A.ease(t, items[0]["t"] - 0.1, A.FAST)
            ax = cx - pw / 2 - 50 if side == 0 else cx + pw / 2 + 50
            anchor = "r" if side == 0 else "l"
            D.text(c, word, th.label, 26, colr, ax, 270, ew * e_out, anchor=anchor, tracking=0.24)
            y = 330
            for q in items[:3]:
                e = A.ease(t, q["t"], A.FAST)
                if e <= 0:
                    continue
                lines = D.wrap(q["label"], th.heading, 30, 380)[:3]
                if y + 86 + D.lead(th.heading, 42) * len(lines) > (900 if self.back else 1040):
                    break  # no room under the column (the comeback band): the moments already shown carry it
                dx = (-24 if side == 0 else 24) * (1 - A.out_smooth(e))
                D.text(c, str(q["year"]), th.display, 64, colr, ax + dx, y, e * e_out, anchor=anchor)
                for j, line in enumerate(lines):
                    D.text(c, line, th.heading, 30, th.ink, ax + dx, y + 86 + j * D.lead(th.heading, 42), e * e_out, anchor=anchor)
                y += 86 + D.lead(th.heading, 42) * len(lines) + 30
        # the comeback: a band across the bottom
        for q in self.back[:1]:
            e = A.ease(t, q["t"], 0.35, A.out_quint)
            if e <= 0:
                continue
            bw = 1100
            D.blit(c, D.rounded(int(bw * e) or 1, 96, 14, th.c("bg2"), th.c("accent"), 3), cx - bw * e / 2, 930, e_out)
            if e > 0.6:
                ea = A.prog(e, 0.6, 0.4)
                txt = f"{q['year']}  ·  {q['label']}"
                fs = K.fit(txt, th.heading, bw - 60, 38, 24)
                D.text(c, txt, th.heading, fs, th.ink, cx, 956 + (38 - fs) * 0.5, ea * e_out, anchor="c")


# ============================================================ 2. ACHIEVEMENTS AND CULTURAL IMPACT (impact)

_QUAL = r"(?:[A-Z][\w'’.-]*|platinum|gold|diamond|number-one|No\. 1|top-ten|top ten|hit|studio|consecutive|sold-out|record-breaking|worldwide)"
IMPACT_NOUNS = {
    "trophy": r"Grammy Awards?|Grammys?|Academy Awards?|Oscars?|Emmy Awards?|Emmys?|Golden Globes?|BAFTAs?|Tony Awards?|Tonys?|"
              r"Brit Awards?|MTV Awards?|VMAs?|awards?|nominations|honours|honors|medals|prizes",
    "disc": r"copies|records|albums|singles|units|certifications",
    "play": r"views|streams|plays|downloads|subscribers|episodes|seasons|films|movies",
    "chart": r"weeks at number one|weeks at No\. 1|weeks on the chart|weeks on the charts|weeks at the top|number-one (?:hits|singles|albums)|No\. 1 (?:hits|singles|albums)|hits|chart-toppers",
    "people": r"followers|fans|tickets|people|viewers|listeners|concerts|shows|dates|countries",
}
SCALE_W = r"(?:\s*(million|billion|thousand|m|bn|k)\b)?"
IMPACT_RES = [(kind, re.compile(rf"\b(?:more than\s+|over\s+|nearly\s+|almost\s+|around\s+|about\s+|some\s+)?({K.NUMW_I}){SCALE_W}\s+((?:{_QUAL}\s+){{0,3}}?)({nouns})\b"))
              for kind, nouns in IMPACT_NOUNS.items()]
MONEY_RES = re.compile(r"([£$€])\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|m|bn)?\s+(?:at the box office|worldwide|in ticket sales|in sales|in revenue|gross|grossed|from the tour)")
MONEY_RES2 = re.compile(r"\b(grossed|earned|made|took|generated)\s+(?:more than\s+|over\s+|nearly\s+|almost\s+)?([£$€])\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|m|bn)?")
WEEK_RE = re.compile(rf"\b({K.NUMW_I})\s+(weeks)\s+(at number one|at No\. 1|at the top(?: of the charts?)?|on the charts?)", re.I)


def impact_stats(text):
    """[(start, stat)]: what the sentence counts of a success, each with its icon kind."""
    out, taken = [], []
    m_ = list(WEEK_RE.finditer(text))
    for m in m_:
        sn = K.stat_number(m.group(1))
        if sn:
            out.append((m.start(), dict(sn, label=(m.group(2) + " " + m.group(3)).upper(), kind="chart", phrase=m.group(0)[:40])))
            taken.append((m.start(), m.end()))
    for kind, rx in IMPACT_RES:
        for m in rx.finditer(text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            sn = K.stat_number(m.group(1), m.group(2))
            if not sn or (1900 < sn["num"] < 2100 and not m.group(2)):
                continue
            qual = (m.group(3) or "").strip()
            noun = m.group(4)
            label = (qual + " " + noun).strip() if qual and len(qual) + len(noun) < 26 else noun
            out.append((m.start(), dict(sn, label=label.upper(), kind=kind, phrase=m.group(0)[:40])))
            taken.append((m.start(), m.end()))
    for m in MONEY_RES.finditer(text):
        sn = K.stat_number(m.group(2), m.group(3), m.group(1))
        if sn:
            out.append((m.start(), dict(sn, label=re.sub(r"^(?:at the |in )", "", m.group(0)[m.group(0).find(" ", len(m.group(1)) + len(m.group(2))) + 1:]).upper()
                                        .replace((m.group(3) or "").upper() + " ", "", 1).strip() or "GROSS", kind="chart", phrase=m.group(0)[:40])))
    for m in MONEY_RES2.finditer(text):
        if any(abs(m.start() - s) < 20 for s, _ in out):
            continue
        sn = K.stat_number(m.group(3), m.group(4), m.group(2))
        if sn:
            out.append((m.start(), dict(sn, label=m.group(1).upper(), kind="chart", phrase=m.group(0)[:40])))
    out.sort(key=lambda x: x[0])
    return out


@K.safe
def detect_impact(story, a, b):
    per = K.cache(story, "impact")
    found = []
    for s in story.sentences[a:b]:
        if s.i not in per:
            per[s.i] = impact_stats(s.text)
        found.append(per[s.i])
    if not found[0] or not found[-1]:
        return None
    stats, labels = [], set()
    for lst in found:
        for _, st in lst:
            if st["label"] not in labels:
                labels.add(st["label"])
                stats.append(st)
    if len(stats) < 3:
        return None
    stats = stats[:6]
    work = ""
    wm = re.match(r"^\s*([A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,3})\s+(?:sold|spent|won|grossed|earned|was|became|drew|topped|reached|broke)\b",
                  story.sentences[a].text)
    who = K.title_subject(story)
    if wm and wm.group(1) not in story.people and wm.group(1) != who and wm.group(1).split()[0] not in K._NOT_NAME:
        work = wm.group(1)  # the album / film / show the numbers are about ("Thriller sold ...")
    subject = who if (work and who) else K.subject_of(story, a, b)
    if subject == work:
        subject = who
    score = min(0.95, 0.68 + 0.06 * (len(stats) - 3) + (0.04 if work else 0))
    return score, {"subject": subject, "work": work, "stats": stats}, [f"{len(stats)} measures of success" + (f" for {work}" if work else "")]


class ImpactGraphic(Graphic):
    def build(self):
        p = self.p
        self.stats, last = [], 0
        for i, s in enumerate(p["stats"]):
            hit = self.tl.phrase(s["phrase"], last)
            if hit:
                last = hit[2]
            self.stats.append(dict(s, t=max(0.45, (hit[0] if hit else 0.6 + 0.8 * i) - 0.05)))
        n = len(self.stats)
        self.cols = n if n <= 3 else (2 if n == 4 else 3)
        self.rows = 1 if n <= 3 else 2
        self.photo_key = self.assets.find(person=p["subject"])[0] if p.get("subject") else None
        self.cue(0.05, "warm-swell-2", -16, "impact")
        for s in self.stats:
            self.cue(s["t"], "sparkle-2", -15, "achievement")
            self.cue(s["t"] + 0.65, "flash-2", -14, "number lands")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        ek = A.ease(t, 0.1, A.FAST)
        x0, x1 = 120, 1800
        if self.photo_key:
            e = A.ease(t, 0.15, 0.45)
            img = K.circle_photo(D.photo(self.assets.path(self.photo_key), 150, 150, focus=(0.5, 0.3)))
            D.blit(c, D.disc(162, th.c("accent")), x0, 92, e * e_out)
            D.blit(c, img, x0 + 6, 98, e * e_out)
            hx = x0 + 196
        else:
            hx = x0
        sub = (p.get("subject") or "").upper()
        D.text(c, sub, th.label, 24, th.accent, hx, 106, ek * e_out, tracking=0.22)
        title = (p.get("work") or "").upper() or p.get("heading") or "ACHIEVEMENTS"
        ts = K.fit(title, th.display, x1 - hx, 92, 44)
        D.text(c, title, th.display, ts, th.ink, hx, 140 + (92 - ts) * 0.6, e_out, clip=(hx, 132, hx + (x1 - hx) * A.ease(t, 0.15, 0.5), 260))
        gap = 40
        w = (x1 - x0 - gap * (self.cols - 1)) / self.cols
        h = 300 if self.rows == 2 else 520
        top = 330 if self.rows == 2 else 380
        for i, s in enumerate(self.stats):
            r, col = divmod(i, self.cols)
            x, y = x0 + col * (w + gap), top + r * (h + 30)
            e = A.ease(t, s["t"], 0.32, A.out_quint)
            if e <= 0:
                continue
            yy = y + 30 * (1 - e)
            D.blit(c, D.rounded(int(w), h, 18, th.c("bg2"), th.c("accent", 90), 2), x, yy, e * e_out)
            isz = 72 if self.rows == 2 else 110
            ic = K.icon(s["kind"], isz, th.accent)
            D.blit(c, ic, x + 34, yy + 30, e * e_out)
            big = 104 if self.rows == 2 else 150
            size = K.fit(s["value"], th.display, w - 68, big, 44)
            ny = yy + 30 + isz + (14 if self.rows == 2 else 36)
            D.text(c, K.counted(s, A.prog(t, s["t"], 0.65)), th.display, size, th.ink, x + 34, ny, e * e_out)
            ly = ny + size * 1.44
            for j, line in enumerate(D.wrap(s["label"], th.label, 24, int(w - 68), 0.12)[:2]):
                D.text(c, line, th.label, 24, th.muted, x + 34, ly + j * D.lead(th.label, 32), A.ease(t, s["t"] + 0.3, A.FAST) * e_out, tracking=0.12)


# ============================================================ registration

THEMES = {
    "career": Theme("en-career", bg="#0C0A0E", bg2="#1A1620", ink="#FAF6F0", muted="#A39CA8", accent="#F4C152", accent2="#F0524F",
                    display="inter-black", heading="inter-bold", body="dm-sans", label="inter-bold"),
    "impact": Theme("en-impact", bg="#100B1A", bg2="#1C1530", ink="#FBF7FF", muted="#ADA3C2", accent="#F4C152", accent2="#FF7AB6",
                    display="oswald", heading="inter-bold", body="dm-sans", label="inter-bold"),
}
_F = ("bg", "bg2", "ink", "muted", "accent", "accent2")


def _set(*colors):
    return dict(zip(_F, colors))


_TYPE = {"size": (0.85, 1.15)}
LOOKS = {
    "career": {"palettes": [
        ("A", "Gold & red", None),
        ("B", "Silver & crimson", _set("#0E0F12", "#1A1C21", "#F4F5F7", "#9599A3", "#D6DCE6", "#E5484D")),
        ("C", "Pink & teal", _set("#0F0A12", "#1D1422", "#FBF4FA", "#AE9FB0", "#FF7AB6", "#39C3B5"))],
        **_TYPE, "fonts": ("sans", "geometric", "condensed"),
        "backdrops": ("own",), "backdrop_note": "Career progression keeps its own background: the split portrait and both columns fill the screen.",
        "present": {"prefer": "own", "lock": True, "why": "a split portrait and two columns fill the screen"}},
    "impact": {"palettes": [
        ("A", "Gold on violet", None),
        ("B", "Gold on black", _set("#0B0B0C", "#17171A", "#F7F5F0", "#9D9A93", "#F2B33D", "#FF7AB6")),
        ("C", "Pink on navy", _set("#0A1020", "#141C33", "#F7F8FF", "#9AA4C2", "#FF7AB6", "#F4C152"))],
        **_TYPE, "fonts": ("condensed", "sans", "geometric"), "place": True,
        "present": {"prefer": "own", "why": "a grid of award cards across the whole width"}},
}


def _person(name, label):
    return {"key": "person:" + name, "kind": "person", "value": name, "label": label}


def slots_career(p):
    return [_person(p["subject"], f"Portrait of {p['subject']} (split rise / fall)")] if p.get("subject") else []


def slots_impact(p):
    return [_person(p["subject"], f"Small portrait of {p['subject']}")] if p.get("subject") else []


class Entertainment(Collection):
    key = "entertainment"
    label = "Entertainment"

    def __init__(self):
        super().__init__()
        self.add(Category("career", "Career progression", THEMES["career"], detect_career, CareerGraphic, max_window=5, min_window=2,
                          slots=slots_career, about="Three or more dated moments with a rise and a fall: the split portrait, rise one side, fall the other.",
                          looks=LOOKS["career"]))
        self.add(Category("impact", "Achievements and impact", THEMES["impact"], detect_impact, ImpactGraphic, max_window=3,
                          slots=slots_impact, about="Three or more numbers of success (awards, copies sold, weeks at number one, views), counting up.",
                          looks=LOOKS["impact"]))


register(Entertainment())
