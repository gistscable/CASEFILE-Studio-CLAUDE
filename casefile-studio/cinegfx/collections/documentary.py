"""v0.4.76 Documentary collection: the general set for the niches without graphics of their own yet (history,
business, psychology, faith and religion, general documentary). Built from tested pieces of the other collections,
each read for any subject:

  timeline  Chronological timeline   three or more dated events on a rail (the true-crime timeline: dates are dates)
  figures   Key figures              three or more numbers the narration gives (people, money, per cent, years,
                                     copies, followers ...), each with its icon, counting up as said
  arc       Rise and fall            three or more dated moments with a rise and a fall (a person, a company, an
                                     empire, a movement): the split rise / fall layout

Words on screen are the narration's; photos only from the project.
"""
from __future__ import annotations

import re

from ..core import Category, Collection, register
from . import _kit as K
from . import entertainment as E
from . import truecrime as TC

_QUAL = r"(?:[A-Z][\w'’.-]*|full-time|part-time|active|registered|loyal|paying|monthly|daily|annual|new|registered)"
FIG_NOUNS = {
    "people": r"people|employees|staff|workers|members|followers|believers|worshippers|pilgrims|participants|volunteers|subjects|patients|"
              r"students|soldiers|troops|men|women|children|citizens|residents|customers|users|subscribers|visitors|viewers|refugees|lives|deaths|victims|casualties",
    "chart": r"stores|shops|branches|offices|factories|countries|cities|languages|churches|mosques|temples|congregations|schools|hospitals|"
             r"products|phones|cars|vehicles|devices|units|barrels|tonnes|tons|companies|startups|acquisitions|studies|experiments|trials|books|translations|copies|years|centuries|days|miles|kilometres|kilometers",
}
FIG_RES = [(kind, re.compile(rf"\b(?:more than\s+|over\s+|nearly\s+|almost\s+|around\s+|about\s+|some\s+|roughly\s+)?({K.NUMW_I}){E.SCALE_W}\s+"
                             rf"((?:{_QUAL}\s+){{0,2}}?)({nouns})\b")) for kind, nouns in FIG_NOUNS.items()]
MONEY_RE = re.compile(r"([£$€₦])\s?(\d[\d,]*(?:\.\d+)?)\s*(trillion|billion|million|thousand|bn|m|k)?\b(?:\s+(?:in|of|a)\s+(revenue|sales|profit|profits|losses|debt|funding|investment|a year|valuation|market value))?")
PCT_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:%|per cent|percent)(?:\s+of\s+((?:the\s+)?[a-z]+(?:\s+[a-z]+)?))?")


def figure_stats(text):
    """[(start, stat)]: impact numbers (entertainment) plus people, places, money and per cent."""
    out = list(E.impact_stats(text))
    taken = [(s, s + len(st.get("phrase", ""))) for s, st in out]
    for kind, rx in FIG_RES:
        for m in rx.finditer(text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            sn = K.stat_number(m.group(1), m.group(2))
            if not sn or (1900 < sn["num"] < 2100 and not m.group(2)) or (m.group(4) in ("years", "days") and sn["num"] < 3):
                continue
            qual = (m.group(3) or "").strip()
            label = (qual + " " + m.group(4)).strip() if qual and len(qual) + len(m.group(4)) < 26 else m.group(4)
            out.append((m.start(), dict(sn, label=label.upper(), kind=kind, phrase=m.group(0)[:40])))
            taken.append((m.start(), m.end()))
    for m in MONEY_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        sn = K.stat_number(m.group(2), m.group(3), m.group(1))
        if sn and (m.group(3) or m.group(4) or sn["num"] >= 1000):
            out.append((m.start(), dict(sn, label=(m.group(4) or "").upper() or "", kind="chart", phrase=m.group(0)[:40])))
            taken.append((m.start(), m.end()))
    for m in PCT_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        sn = K.stat_number(m.group(1))
        if sn:
            label = ("OF " + m.group(2).upper()) if m.group(2) else ""
            out.append((m.start(), dict(sn, value=sn["value"] + "%", suffix="%", label=label, kind="chart", phrase=m.group(0)[:40])))
    out.sort(key=lambda x: x[0])
    return [(s, st) for s, st in out if st.get("label")]   # a number with nothing to say what it counts is not shown


@K.safe
def detect_figures(story, a, b):
    per = K.cache(story, "doc-figures")
    found = []
    for s in story.sentences[a:b]:
        if s.i not in per:
            per[s.i] = figure_stats(s.text)
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
    subject = K.subject_of(story, a, b)
    score = min(0.92, 0.66 + 0.06 * (len(stats) - 3))
    return score, {"subject": subject, "work": "", "heading": "KEY FIGURES", "stats": stats}, [f"{len(stats)} figures"]


@K.safe
def detect_arc(story, a, b):
    per = K.cache(story, "doc-arc")
    if (a, b) in per:
        return per[(a, b)]
    res = None
    pts = K.career_points(story, a, b)
    sents = {q["sent"] for q in pts}
    if len(pts) >= 3 and {q["dir"] for q in pts} == {"up", "down"} and story.sentences[a].i in sents and story.sentences[b - 1].i in sents:
        pts = pts[:6]
        if all(pts[i]["year"] <= pts[i + 1]["year"] for i in range(len(pts) - 1)):
            kind, title = K.arc_title(pts)
            subject = K.subject_of(story, a, b)
            score = min(0.9, 0.66 + 0.05 * (len(pts) - 3) + (0.05 if kind in ("redemption", "comeback") else 0))
            res = score, {"subject": subject, "title": title, "arc": kind, "points": pts}, [f"{len(pts)} dated moments ({kind})"]
    per[(a, b)] = res
    return res


class Documentary(Collection):
    key = "documentary"
    label = "Documentary"

    def __init__(self):
        super().__init__()
        self.add(Category("timeline", "Chronological timeline", TC.THEMES["timeline"], TC.detect_timeline, TC.TimelineGraphic, max_window=5,
                          slots=TC.slots_timeline, about="Three or more dated events on a rail, each landing as it is spoken.",
                          looks=TC.LOOKS["timeline"]))
        self.add(Category("figures", "Key figures", E.THEMES["impact"], detect_figures, E.ImpactGraphic, max_window=3,
                          slots=E.slots_impact, about="Three or more numbers the narration gives (people, money, per cent, places), counting up as said.",
                          looks=E.LOOKS["impact"]))
        self.add(Category("arc", "Rise and fall", E.THEMES["career"], detect_arc, E.CareerGraphic, max_window=5, min_window=2,
                          slots=E.slots_career, about="Three or more dated moments with a rise and a fall (a person, a company, an empire).",
                          looks=E.LOOKS["career"]))


register(Documentary())
