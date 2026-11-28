"""v0.4.76 Football collection: four categories, each with its detector (reads the narration), a theme and a graphic.

  stats      Player and team analysis   three or more numbers about one player or team (goals, appearances,
                                        trophies, a transfer fee ...), counting up as they are said
  bracket    Road to the final          two or more rounds of a tournament with the opponent (and the score),
                                        joined into a route that ends at the trophy when the narration says so
  tactics    Tactical breakdown         a formation (4-3-3) on a pitch board, with the tactical ideas the
                                        narration names (high press, counter-attack, low block ...) as arrows
  risefall   Rise, fall and redemption  three or more dated career moments, at least one of them a fall,
                                        drawn as the career's curve

Words on screen are the narration's (numbers, names, its own phrases); photos only from the project.
"""
from __future__ import annotations

import math
import re

from .. import anim as A
from .. import draw as D
from ..core import Category, Collection, Graphic, register
from ..theme import Theme
from . import _kit as K

# ============================================================ 1. PLAYER AND TEAM ANALYSIS (stats)

_QUAL = r"(?:[A-Z][\w'’.-]*|d['’]Or|league|international|competitive|senior|official|career|club|major|domestic|European|world|top-flight|first-team|professional)"
STAT_NOUNS = (r"goals|assists|appearances|apps|games|matches|caps|hat-tricks|hat tricks|clean sheets|titles|trophies|"
              r"Ballons? d['’]Or|Golden Boots?|awards|wins|victories|points|starts|seasons|cups|medals|internationals")
STAT_RE = re.compile(rf"\b({K.NUMW_I})\s+((?:{_QUAL}\s+){{0,3}}?)({STAT_NOUNS})\b")
MONEY_RE = re.compile(r"([£$€])\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|m|bn)?\b(?:\s+(?:pound|euro|dollar)s?)?\s+"
                      r"(transfer|fee|move|deal|signing|contract|release clause|a year|a week|per week|a season)")
MONEY_RE2 = re.compile(r"\b(fee|transfer|move|deal|contract|signing)\s+(?:of|worth|for)\s+(?:a record\s+|around\s+|about\s+)?([£$€])\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|m|bn)?")
PCT_RE = re.compile(r"\b(\d{1,3}(?:\.\d)?)\s*(?:%|per cent|percent)\s+(?:of\s+(?:his|her|their)\s+)?(pass(?:es|ing)?(?: accuracy)?|win(?:s| rate)?|possession|shots on target|duels|tackles|shots)")
TEAM_RE = re.compile(r"\b(?:for|at|with|joined|signed for|captain of)\s+((?:[A-Z][\w'’.-]+)(?:\s+[A-Z][\w'’.-]+){0,2})")
PERIOD_RE = re.compile(rf"\b(?:between|from)\s+({K.YEAR})\s+(?:and|to|until)\s+({K.YEAR})\b")
_MONEY_LABEL = {"transfer": "TRANSFER FEE", "fee": "TRANSFER FEE", "move": "TRANSFER FEE", "signing": "TRANSFER FEE", "deal": "CONTRACT",
                "contract": "CONTRACT", "release clause": "RELEASE CLAUSE", "a year": "A YEAR", "a week": "A WEEK", "per week": "A WEEK",
                "a season": "A SEASON"}


def _stats_in(text):
    """[(start, stat)] every number the sentence gives about a career or a team."""
    out = []
    for m in STAT_RE.finditer(text):
        sn = K.stat_number(m.group(1))
        if not sn or sn["num"] <= 0 or (sn["num"] > 1900 and sn["num"] < 2100 and not m.group(2)):
            continue  # "2014 games"? a year, not a count
        qual = (m.group(2) or "").strip()
        label = (qual + " " + m.group(3)).strip().upper() if qual and len(qual) + len(m.group(3)) <= 24 else m.group(3).upper()
        out.append((m.start(), dict(sn, label=label.replace("’", "'"), phrase=m.group(0))))
    for m in MONEY_RE.finditer(text):
        sn = K.stat_number(m.group(2), m.group(3), m.group(1))
        if sn:
            out.append((m.start(), dict(sn, label=_MONEY_LABEL[m.group(4)], phrase=m.group(0)[:40])))
    for m in MONEY_RE2.finditer(text):
        sn = K.stat_number(m.group(3), m.group(4), m.group(2))
        if sn and not any(abs(m.start() - s) < 30 and st.get("prefix") for s, st in out):
            out.append((m.start(), dict(sn, label=_MONEY_LABEL[m.group(1)], phrase=m.group(0)[:40])))
    for m in PCT_RE.finditer(text):
        sn = K.stat_number(m.group(1))
        if sn:
            out.append((m.start(), dict(sn, value=sn["value"] + "%", suffix="%", label=m.group(2).upper(), phrase=m.group(0)[:40])))
    out.sort(key=lambda x: x[0])
    return out


@K.safe
def detect_stats(story, a, b):
    per = K.cache(story, "fb-stats")
    sents = story.sentences[a:b]
    found = []
    for s in sents:
        if s.i not in per:
            per[s.i] = _stats_in(s.text)
        found.append(per[s.i])
    if not found[0] or not found[-1]:  # the window starts and ends on a number: the tightest passage
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
    text = story.window_text(a, b)
    subject = K.subject_of(story, a, b)
    team = ""
    for m in TEAM_RE.finditer(text):
        name = m.group(1)
        if name != subject and name not in story.people and not re.match(r"(?:The|A|An|His|Her|Their)\b", name):
            team = name
            break
    pm = PERIOD_RE.search(text)
    period = f"{pm.group(1)}–{pm.group(2)}" if pm else ""
    score = min(0.95, 0.66 + 0.07 * (len(stats) - 3) + (0.05 if subject else 0))
    return score, {"subject": subject, "team": team, "period": period, "stats": stats}, [f"{len(stats)} numbers about {subject or 'the team'}"]


class StatsGraphic(Graphic):
    def build(self):
        p = self.p
        self.stats, last = [], 0
        for i, s in enumerate(p["stats"]):
            hit = self.tl.phrase(s["phrase"], last)
            if hit:
                last = hit[2]
            self.stats.append(dict(s, t=max(0.4, (hit[0] if hit else 0.6 + 0.8 * i) - 0.05)))
        self.photo_key = self.assets.find(person=p["subject"])[0] if p.get("subject") else None
        n = len(self.stats)
        self.cols = 2 if n == 4 else 3
        self.rows = math.ceil(n / self.cols)
        self.cue(0.05, "whoosh-mid-1", -8, "panel")
        self.cue(0.1, "crowd-swell-1", -18, "stadium air")
        for s in self.stats:
            self.cue(s["t"], "ticker-1", -15, "count up")
            self.cue(s["t"] + 0.7, "click-mech-1", -9, "number lands")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        flip = th.traits.get("mirror")
        has_photo = bool(self.photo_key)
        # the photo panel with the sports-poster slant and stripes
        if has_photo:
            ep = A.ease(t, 0.0, 0.5, A.out_quint)
            pw = 820
            img = D.photo(self.assets.path(self.photo_key), pw, 1080, focus=(0.5, 0.3), zoom=1.0 + 0.05 * A.clamp(t / max(1, self.out)))
            img = K.slanted(img, 170, right=not flip)
            x = (0 if not flip else 1920 - pw)
            off = -pw * (1 - ep) if not flip else pw * (1 - ep)
            for k, colr in enumerate((th.accent, th.accent2, th.accent)):
                sx = (pw - 120 + k * 46) if not flip else (1920 - pw + 120 - k * 46 - 26)
                K.tri(c, [(sx + off, 0), (sx + 26 + off, 0), (sx + 26 - 170 + off, 1080), (sx - 170 + off, 1080)] if not flip else
                      [(sx + off, 0), (sx + 26 + off, 0), (sx + 26 + 170 + off, 1080), (sx + 170 + off, 1080)], colr, 0.9 * e_out * ep)
            D.blit(c, img, x + off, 0, e_out)
            K.credit(c, self.assets, self.photo_key, (24 if not flip else 1896), 1040, "#FFFFFF", 0.85 * e_out * ep, anchor="l" if not flip else "r")
        x0, x1 = (120, 1800) if not has_photo else ((880, 1800) if not flip else (120, 1040))
        w = x1 - x0
        # header: the team / period line, the name
        eh = A.ease(t, 0.15, 0.4)
        top = " · ".join(x for x in (p.get("team", "").upper(), p.get("period", "")) if x)
        D.text(c, top, th.label, 24, th.accent, x0, 150, eh * e_out, tracking=0.18)
        name = (p.get("subject") or p.get("team") or "").upper()
        ns = K.fit(name, th.display, w, 120, 54)
        D.text(c, name, th.display, ns, th.ink, x0, 190 + (120 - ns) * 0.6, e_out, clip=(x0, 180, x0 + w * eh, 340))
        D.rect(c, x0, 352, x0 + w * A.ease(t, 0.3, 0.6, A.out_quint), 355, th.muted, 0.6 * e_out)
        # the numbers
        gap = 44
        tw = (w - gap * (self.cols - 1)) / self.cols
        th_ = 420 if self.rows == 1 else 270
        y0 = 440 if self.rows == 1 else 410
        big = 180 if self.rows == 1 else 140
        for i, s in enumerate(self.stats):
            r, col = divmod(i, self.cols)
            tx, ty = x0 + col * (tw + gap), y0 + r * (th_ + 30)
            e = A.ease(t, s["t"], A.FAST)
            if e <= 0:
                continue
            D.rect(c, tx, ty, tx + tw * e, ty + 6, th.accent, e_out)
            pc = A.prog(t, s["t"], 0.7)
            txt = K.counted(s, pc)
            size = K.fit(s["value"], th.display, tw, big, 48)
            D.text(c, txt, th.display, size, th.ink, tx, ty + 28 + 18 * (1 - A.out_smooth(e)), e * e_out, clip=(tx, ty + 12, tx + tw, ty + th_))
            ly = ty + 40 + size * 1.25
            for j, line in enumerate(D.wrap(s["label"], th.label, 24, int(tw))[:2]):
                D.text(c, line, th.label, 24, th.muted, tx, ly + j * D.lead(th.label, 32), A.ease(t, s["t"] + 0.25, A.FAST) * e_out, tracking=0.12)


# ============================================================ 2. ROAD TO THE FINAL (bracket)

STAGES = [(r"group stage|group phase", "GROUP STAGE", 0), (r"first round", "FIRST ROUND", 1), (r"second round", "SECOND ROUND", 2),
          (r"third round", "THIRD ROUND", 3), (r"fourth round", "FOURTH ROUND", 4), (r"fifth round", "FIFTH ROUND", 5),
          (r"round of 32|last 32|last thirty-two", "ROUND OF 32", 5), (r"round of 16|last 16|last sixteen", "ROUND OF 16", 6),
          (r"quarter-?finals?|last eight", "QUARTER-FINAL", 7), (r"semi-?finals?|last four", "SEMI-FINAL", 8),
          (r"(?<!semi-)(?<!semi)(?<!quarter-)(?<!quarter)\bfinal\b", "FINAL", 9)]
STAGE_RE = [(re.compile(rf"\b(?:{pat})\b", re.I), lab, k) for pat, lab, k in STAGES]
WIN = r"beat|beating|defeated|defeating|knocked out|knocking out|eliminated|eliminating|edged|edging|thrashed|thrashing|overcame|overcoming|saw off|dispatched|stunned|crushed|hammered|outclassed|got past|swept aside|routed"
LOSS = r"lost to|losing to|fell to|were beaten by|was beaten by|were knocked out by|went out to|were eliminated by"
DRAW = r"drew with|drawing with|held"
OPP = r"((?:[A-Z][\w'’.-]*)(?:\s+(?:de|del|da|di|of)\s+[A-Z][\w'’.-]*)?(?:\s+[A-Z][\w'’.-]*){0,2})"
MATCH_RE = re.compile(rf"\b(?P<v>{LOSS}|{WIN}|{DRAW})\s+{OPP}(?:\s+(?:by\s+)?(?P<s1>\d{{1,2}})\s*[-–]\s*(?P<s2>\d{{1,2}})(?P<x>\s+on aggregate|\s+on penalties|\s+after extra time)?)?")
COMPETITIONS = (r"Champions League|Europa League|Conference League|European Cup|Club World Cup|World Cup|European Championships?|Euro\s?\d{4}|"
                r"FA Cup|League Cup|Carabao Cup|Copa del Rey|Copa América|Copa Libertadores|Africa Cup of Nations|AFCON|Coppa Italia|"
                r"DFB-Pokal|Coupe de France|Gold Cup|Asian Cup|Nations League|Olympic(?:s| tournament)")
COMP_RE = re.compile(rf"\b(?:the\s+)?(\d{{4}}\s+)?({COMPETITIONS})\b")
OUTCOME_RE = re.compile(r"\b(won the final|lifted the (?:trophy|cup)|were crowned (?:\w+\s+)?champions|became (?:\w+\s+)?champions|"
                        r"won the (?:tournament|competition|cup|trophy)|lost the final|finished as runners-up|were runners-up)\b", re.I)
_NOT_OPP = {"The", "A", "An", "Their", "His", "Her", "Them", "It", "In", "On", "At"}


def _stage_near(text, a, b):
    best = None
    for rx, lab, k in STAGE_RE:
        for m in rx.finditer(text):
            d = (m.start() - b) if m.start() >= b else (a - m.end()) * 1.5
            if d < 0:
                d = 0
            if d <= 90 and (best is None or d < best[0]):
                best = (d, lab, k, m.group(0))
    return best


def _matches(text):
    out = []
    for m in MATCH_RE.finditer(text):
        opp = m.group(2).strip()
        toks = opp.split()
        while toks and toks[-1] in ("In", "On", "At", "And", "After", "Before"):
            toks.pop()
        if not toks or toks[0] in _NOT_OPP:
            continue
        opp = " ".join(toks)
        v = m.group("v").lower()
        res = "L" if re.fullmatch(LOSS, v) else "D" if re.fullmatch(DRAW, v) else "W"
        score = ""
        if m.group("s1"):
            score = f"{m.group('s1')}–{m.group('s2')}"
            if m.group("x") and "penalties" in m.group("x"):
                score += " (pens)"
            elif m.group("x") and "aggregate" in m.group("x"):
                score += " agg."
        st = _stage_near(text, m.start(), m.end())
        out.append({"opponent": opp, "result": res, "score": score, "stage": st[1] if st else "", "order": st[2] if st else None,
                    "stage_phrase": st[3] if st else "", "phrase": m.group(0)[:48], "start": m.start()})
    return out


@K.safe
def detect_bracket(story, a, b):
    per = K.cache(story, "fb-bracket")
    found = []
    for s in story.sentences[a:b]:
        if s.i not in per:
            per[s.i] = _matches(s.text)
        found.append(per[s.i])
    if not found[0] or not found[-1]:
        return None
    rounds = [m for lst in found for m in lst]
    staged = [r for r in rounds if r["stage"]]
    stages = {r["stage"] for r in staged}
    if len(stages) < 2 and len(rounds) < 3:
        return None
    if staged and len(staged) == len(rounds):
        seen, uniq = set(), []
        for r in sorted(rounds, key=lambda r: r["order"]):
            if r["stage"] in seen and r["stage"] != "GROUP STAGE":
                continue
            seen.add(r["stage"])
            uniq.append(r)
        rounds = uniq
    rounds = rounds[:6]
    if len(rounds) < 2:
        return None
    text = story.window_text(a, b)
    comp = COMP_RE.search(text)
    if not comp:  # named earlier in the same chapter
        ch = story.sentences[a].chapter
        for s in story.sentences[:a][::-1]:
            if s.chapter != ch:
                break
            comp = COMP_RE.search(s.text)
            if comp:
                break
    oc = OUTCOME_RE.search(text)
    outcome = ""
    if oc:
        outcome = "lost" if re.search(r"lost|runners-up", oc.group(1), re.I) else "won"
    team = ""
    first = story.sentences[a].text
    tm = re.match(rf"^\s*(?:In the [\w -]+?,\s*)?((?:[A-Z][\w'’.-]+)(?:\s+[A-Z][\w'’.-]+){{0,2}})\s+(?:{WIN}|{LOSS}|{DRAW})\b", first)
    if tm and tm.group(1).split()[0] not in _NOT_OPP:
        team = tm.group(1)
    score = min(0.95, 0.62 + 0.08 * len(rounds) + (0.05 if outcome else 0))
    payload = {"competition": ((comp.group(1) or "") + comp.group(2)).strip() if comp else "", "team": team,
               "rounds": [{k: r[k] for k in ("opponent", "result", "score", "stage", "phrase", "stage_phrase")} for r in rounds],
               "outcome": outcome, "outcome_phrase": oc.group(1) if oc else ""}
    return score, payload, [f"{len(rounds)} rounds" + (f" of the {payload['competition']}" if payload["competition"] else "")]


class BracketGraphic(Graphic):
    def build(self):
        p = self.p
        self.rounds, last = [], 0
        for i, r in enumerate(p["rounds"]):
            hit = self.tl.phrase(r["phrase"], last)
            if hit:
                last = hit[2]
            t = (hit[0] if hit else 0.6 + 0.9 * i) - 0.08
            self.rounds.append(dict(r, t=max(0.45, t)))
        for i in range(1, len(self.rounds)):  # in route order: never before the round it follows
            self.rounds[i]["t"] = max(self.rounds[i]["t"], self.rounds[i - 1]["t"] + 0.35)
        self.t_out = None
        won_final = self.rounds[-1]["stage"] == "FINAL" and self.rounds[-1]["result"] == "W"
        if p.get("outcome_phrase"):
            self.t_out = max(self.rounds[-1]["t"] + 0.5, self.at(p["outcome_phrase"], default=self.rounds[-1]["t"] + 1.0))
        elif won_final:  # the final won: the trophy, without words the narration did not say
            self.t_out = self.rounds[-1]["t"] + 0.6
        n = len(self.rounds)
        self.trophy = bool(p.get("outcome")) or won_final
        self.won = p.get("outcome") == "won" or (won_final and p.get("outcome") != "lost")
        right = 1460 if self.trophy else 1800
        gap = 46
        self.cw = min(330, (right - 120 - gap * (n - 1)) / n)
        self.xs = [120 + i * (self.cw + gap) for i in range(n)]
        self.cue(0.05, "whoosh-dir-r", -8, "route")
        for r in self.rounds:
            self.cue(r["t"], "click-mech-2", -8, "round")
            if r["result"] == "W" and r["stage"] == "FINAL":
                self.cue(r["t"] + 0.2, "crowd-cheer-1", -14, "the final")
        if self.t_out:
            self.cue(self.t_out, "impact-tr-2", -7, "trophy")
            if self.won:
                self.cue(self.t_out + 0.05, "crowd-cheer-1", -12, "champions")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        ek = A.ease(t, 0.1, A.FAST)
        D.text(c, "ROAD TO THE FINAL", th.label, 24, th.accent, 120, 110, ek * e_out, tracking=0.22)
        title = (p.get("competition") or p.get("team") or "").upper()
        ts = K.fit(title, th.display, 1300, 84, 44)
        D.text(c, title, th.display, ts, th.ink, 120, 146 + (84 - ts) * 0.6, e_out, clip=(120, 140, 120 + 1500 * A.ease(t, 0.15, 0.45), 270))
        if p.get("team") and p.get("competition"):
            D.text(c, p["team"].upper(), th.heading, 32, th.muted, 1800, 170, ek * e_out, anchor="r", tracking=0.06)
        cy, ch = 600, 300
        # the route behind the cards
        for i in range(len(self.rounds) - 1):
            r2 = self.rounds[i + 1]
            pr = A.ease(t, r2["t"] - 0.3, 0.32, A.out_cubic)
            xa, xb = self.xs[i] + self.cw, self.xs[i + 1]
            D.rect(c, xa, cy - 2, xa + (xb - xa) * pr, cy + 2, th.accent, e_out)
        if self.trophy and self.t_out:
            pr = A.ease(t, self.t_out - 0.3, 0.32, A.out_cubic)
            xa = self.xs[-1] + self.cw
            D.rect(c, xa, cy - 2, xa + (1560 - xa) * pr, cy + 2, th.accent, e_out)
        for i, r in enumerate(self.rounds):
            e = A.ease(t, r["t"], A.FAST)
            if e <= 0:
                continue
            x, w = self.xs[i], self.cw
            y0 = cy - ch / 2 + 24 * (1 - A.out_smooth(e))
            D.blit(c, D.rounded(int(w), ch, 14, th.c("bg2"), th.c("accent" if r["result"] == "W" else "muted", 150), 2), x, y0, e * e_out)
            D.text(c, r["stage"] or f"ROUND {i + 1}", th.label, 22, th.accent, x + 22, y0 + 26, e * e_out, tracking=0.16)
            opp = r["opponent"].upper()
            os_ = K.fit(opp, th.heading, w - 44, 58, 26, lines=2)
            lines = D.wrap(opp, th.heading, os_, int(w - 44))[:2]
            for j, line in enumerate(lines):
                D.text(c, line, th.heading, os_, th.ink, x + 22, y0 + 74 + j * D.lead(th.heading, os_ * 1.15), e * e_out)
            chip = (("W" if r["result"] == "W" else "L" if r["result"] == "L" else "D") + (" " + r["score"] if r["score"] else ""))
            ec = A.prog(t, r["t"] + 0.2, A.SNAP)
            if ec > 0:
                colr = th.accent if r["result"] == "W" else th.accent2 if r["result"] == "L" else th.muted
                cwid = D.measure(chip, th.label, 28, 0.06)[0] + 36
                D.blit(c, D.rounded(int(cwid), 52, 8, (0, 0, 0, 0), D.col(colr), 2), x + 22, y0 + ch - 76, min(1, ec * 2) * e_out)
                D.text(c, chip, th.label, 28, colr, x + 40, y0 + ch - 67, min(1, ec * 2) * e_out, tracking=0.06)
        if self.trophy and self.t_out:
            et = A.prog(t, self.t_out, 0.35)
            if et > 0:
                s = A.out_back(et, 1.6)
                sz = max(2, int(230 * s))
                won = self.won
                D.blit(c, K.icon("trophy", sz, th.accent if won else th.muted), 1690 - sz / 2, cy - 40 - sz / 2, e_out)
                words = (p.get("outcome_phrase") or "").upper()
                fs = K.fit(words, th.heading, 330, 34, 20, lines=2)
                for j, line in enumerate(D.wrap(words, th.heading, fs, 330)[:2]):
                    D.text(c, line, th.heading, fs, th.ink, 1690, cy + 110 + j * D.lead(th.heading, fs * 1.2), min(1, et * 2) * e_out, anchor="c")


# ============================================================ 3. TACTICAL BREAKDOWN (tactics)

FORM_RE = re.compile(r"\b([2-5])\s*[-–]\s*([1-6])\s*[-–]\s*([1-5])(?:\s*[-–]\s*([1-5]))?(?:\s*[-–]\s*([1-4]))?\b")
FORM_WORDS = re.compile(r"\b(?i:(two|three|four|five)-(one|two|three|four|five|six)-(one|two|three|four|five)(?:-(one|two|three|four|five))?)\b")
FORM_CONTEXT = re.compile(r"\b(formation|system|shape|set up|setup|lined up|line-up|lineup|played|plays|playing|switched|deployed|"
                          r"used|using|went with|back four|back three|back five)\b", re.I)
NOTES = [
    ("press", r"high press(?:ing)?|pressing game|pressed high|press(?:ed|ing)? from the front|gegenpress\w*|counter-?press\w*|pressing"),
    ("counter", r"counter-?attack\w*|on the counter|on the break|in transition|breakaways?"),
    ("highline", r"high (?:defensive )?line"),
    ("lowblock", r"low block|parked the bus|parking the bus|sat deep|sitting deep|defended deep|deep block"),
    ("wide", r"overload(?:ed|ing)? the (?:left|right)(?: flank| wing| side)?|down the (?:left|right)(?: flank| wing| side)?|"
             r"wing-?backs? (?:pushed|pushing|bombed|bombing) (?:up|forward|on)|full-?backs? (?:pushed|pushing|bombed|bombing) (?:up|forward|on)|"
             r"stretch(?:ed|ing)? the pitch|width"),
    ("possession", r"tiki-?taka|possession football|short passing|build(?:ing)? (?:up )?from the back|kept the ball|dominated possession|keep possession"),
    ("direct", r"long balls?|direct football|direct play|went direct|route one"),
    ("falsenine", r"false (?:nine|9)"),
]
NOTE_RE = [(k, re.compile(rf"\b(?:{pat})\b", re.I)) for k, pat in NOTES]
_W2N = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _formations(text):
    out = []
    for m in FORM_RE.finditer(text):
        shape = [int(g) for g in m.groups() if g]
        if sum(shape) == 10 and len(shape) >= 3:
            out.append({"shape": shape, "text": "-".join(map(str, shape)), "phrase": m.group(0), "start": m.start()})
    for m in FORM_WORDS.finditer(text):
        shape = [_W2N[g.lower()] for g in m.groups() if g]
        if sum(shape) == 10:
            out.append({"shape": shape, "text": "-".join(map(str, shape)), "phrase": m.group(0), "start": m.start()})
    return sorted(out, key=lambda f: f["start"])


def _notes(text):
    out, kinds = [], set()
    for k, rx in NOTE_RE:
        m = rx.search(text)
        if m and k not in kinds:
            kinds.add(k)
            side = "left" if "left" in m.group(0).lower() else "right" if "right" in m.group(0).lower() else ""
            out.append({"kind": k, "phrase": m.group(0), "label": m.group(0).upper(), "side": side, "start": m.start()})
    return sorted(out, key=lambda n: n["start"])


@K.safe
def detect_tactics(story, a, b):
    text = story.window_text(a, b)
    forms = _formations(text)
    if not forms or not FORM_CONTEXT.search(text):
        return None
    if not _formations(story.sentences[a].text) and not _notes(story.sentences[a].text):
        return None
    notes = _notes(text)
    if not notes and len(forms) < 2:
        return None
    if len(story.sentences[b - 1].text) and not (_formations(story.sentences[b - 1].text) or _notes(story.sentences[b - 1].text)):
        return None
    teams = []
    for f in forms[:2]:
        before = text[max(0, f["start"] - 80): f["start"]]
        tm = re.findall(r"\b((?:[A-Z][\w'’.-]+)(?:\s+[A-Z][\w'’.-]+){0,2})\b", before)
        tm = [x for x in tm if x.split()[0] not in ("The", "A", "An", "In", "His", "Her", "Their", "It", "He", "She", "They")]
        teams.append(tm[-1] if tm else "")
    for f, tname in zip(forms, teams):
        f["team"] = tname
    score = min(0.95, 0.7 + 0.08 * len(notes) + (0.08 if len(forms) > 1 else 0))
    return score, {"formations": [{k: f[k] for k in ("shape", "text", "phrase", "team")} for f in forms[:2]],
                   "notes": [{k: n[k] for k in ("kind", "phrase", "label", "side")} for n in notes[:4]]}, \
        [f"formation {forms[0]['text']}" + (f" and {len(notes)} tactical ideas" if notes else "")]


_PITCH = {}


def _pitch(th, w, h):
    """The board (stripes and lines), drawn once per look and size."""
    key = (th.name, w, h)
    if key in _PITCH:
        return _PITCH[key]
    from PIL import Image
    im = Image.new("RGBA", (w, h), th.c("bg2"))
    for k in range(0, 12, 2):
        D.rect(im, k * w / 12, 0, (k + 1) * w / 12, h, th.bg, 0.55)
    lc, lw = th.c("ink", 120), 3
    D.outline(im, 2, 2, w - 2, h - 2, lc, lw)
    D.rect(im, w / 2 - 1, 0, w / 2 + 2, h, lc)
    r = h * 0.135
    circ = [(w / 2 + r * math.cos(a_ * math.pi / 30), h / 2 + r * math.sin(a_ * math.pi / 30)) for a_ in range(61)]
    D.polyline(im, circ, lc, lw)
    for side in (0, 1):
        bw, bh = w * 0.157, h * 0.593
        gw, gh = w * 0.052, h * 0.27
        x = 0 if side == 0 else w - bw
        D.outline(im, x, (h - bh) / 2, x + bw, (h + bh) / 2, lc, lw)
        xg = 0 if side == 0 else w - gw
        D.outline(im, xg, (h - gh) / 2, xg + gw, (h + gh) / 2, lc, lw)
        sx = w * 0.105 if side == 0 else w - w * 0.105
        D.blit(im, D.disc(8, lc), sx - 4, h / 2 - 4)
        arc_c = (w * 0.105, h / 2) if side == 0 else (w - w * 0.105, h / 2)
        pts = [(arc_c[0] + (1 if side == 0 else -1) * r * math.cos(a_), arc_c[1] + r * math.sin(a_)) for a_ in [x_ / 20 - 0.92 for x_ in range(0, 38)]]
        pts = [q for q in pts if (q[0] > bw + 1 if side == 0 else q[0] < w - bw - 1)]
        if len(pts) > 1:
            D.polyline(im, pts, lc, lw)
    D.blit(im, D.disc(10, lc), w / 2 - 5, h / 2 - 5)
    _PITCH[key] = im
    if len(_PITCH) > 6:
        _PITCH.pop(next(iter(_PITCH)))
    return im


class TacticsGraphic(Graphic):
    PX0, PY0, PW, PH = 100, 176, 1200, 776

    def build(self):
        p = self.p
        self.forms, last = [], 0
        for i, f in enumerate(p["formations"]):
            hit = self.tl.phrase(f["phrase"], last)
            if hit:
                last = hit[2]
            self.forms.append(dict(f, t=max(0.5, (hit[0] if hit else 0.6 + 1.2 * i) - 0.05)))
        self.notes, last = [], 0
        for i, n in enumerate(p["notes"]):
            hit = self.tl.phrase(n["phrase"], last)
            if hit:
                last = hit[2]
            self.notes.append(dict(n, t=max(self.forms[0]["t"] + 0.6, (hit[0] if hit else self.forms[0]["t"] + 1.2 + i) - 0.05), n=i + 1))
        two = len(self.forms) > 1
        self.teams = []
        for k, f in enumerate(self.forms):
            lines = f["shape"]
            span = (0.17, 0.44) if two else (0.17, 0.74)
            pts = [[(0.045, 0.5)]]
            for li, cnt in enumerate(lines):
                x = span[0] + (span[1] - span[0]) * li / max(1, len(lines) - 1)
                pts.append([(x, 0.13 + (j + 0.5) * 0.74 / cnt) for j in range(cnt)])
            if k == 1:
                pts = [[(1 - x, y) for x, y in ln] for ln in pts]
            self.teams.append(pts)
        self.cue(0.05, "whistle-1", -16, "kick off")
        self.cue(0.1, "whoosh-mid-2", -9, "board")
        for f in self.forms:
            for li in range(len(f["shape"]) + 1):
                self.cue(f["t"] + 0.1 * li, "pop-soft-1" if li % 2 == 0 else "pop-soft-2", -12, "players")
        for n in self.notes:
            self.cue(n["t"], "whoosh-short-1", -11, "tactic arrow")
            self.cue(n["t"] + 0.45, "click-mech-2", -10, "tactic noted")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def P(self, x, y):
        return self.PX0 + x * self.PW, self.PY0 + y * self.PH

    def _shift(self, t, kind, line):
        """How far a line of team one moves for a note already said (high line forward, low block back, false nine)."""
        dx = 0.0
        for n in self.notes:
            e = A.ease(t, n["t"], 0.6, A.in_out_cubic)
            if e <= 0:
                continue
            if n["kind"] == "highline" and line == 1:
                dx += 0.08 * e
            elif n["kind"] == "lowblock" and line in (1, 2):
                dx -= 0.06 * e
        return dx

    def draw(self, c, t):
        th = self.th
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        ep = A.ease(t, 0.05, 0.5, A.out_quint)
        pitch = _pitch(th, self.PW, self.PH)
        D.blit(c, pitch, self.PX0, self.PY0, e_out, clip=(self.PX0, self.PY0, self.PX0 + self.PW * ep, self.PY0 + self.PH))
        D.text(c, "TACTICAL BREAKDOWN", th.label, 24, th.accent, self.PX0, 112, A.ease(t, 0.1, A.FAST) * e_out, tracking=0.22)
        # low block shading (behind the players)
        for n in self.notes:
            if n["kind"] == "lowblock":
                e = A.ease(t, n["t"], 0.5)
                x0, y0 = self.P(0.02, 0.06)
                x1, y1 = self.P(0.42, 0.94)
                D.rect(c, x0, y0, x0 + (x1 - x0) * e, y1, th.accent, 0.12 * e_out)
        # players
        colors = (th.accent, th.accent2)
        for k, (f, pts) in enumerate(zip(self.forms, self.teams)):
            for li, ln in enumerate(pts):
                e = A.prog(t, f["t"] + 0.1 * li, 0.3)
                if e <= 0:
                    continue
                s = A.out_back(e, 1.7)
                sz = max(2, int(40 * s))
                for j, (x, y) in enumerate(ln):
                    dx = self._shift(t, None, li) if k == 0 else 0.0
                    if k == 0 and li == len(pts) - 1:
                        for n in self.notes:
                            if n["kind"] == "falsenine" and abs(y - 0.5) < 0.2:
                                dx -= 0.1 * A.ease(t, n["t"], 0.6, A.in_out_cubic)
                    px, py = self.P(x + dx, y)
                    D.blit(c, D.disc(sz, D.col(colors[k]), th.c("ink"), 3), px - sz / 2, py - sz / 2, e_out)
            if k == 0:
                for n in self.notes:
                    if n["kind"] == "highline":
                        e = A.ease(t, n["t"] + 0.4, 0.4)
                        if e > 0:
                            x = pts[1][0][0] + self._shift(t, None, 1)
                            px, py0 = self.P(x, 0.04)
                            _, py1 = self.P(x, 0.96)
                            K.dashed(c, px, py0, px, py0 + (py1 - py0) * e, th.accent, 3, alpha=0.85 * e_out)
        # arrows
        team = self.teams[0]
        for n in self.notes:
            e = A.ease(t, n["t"], 0.55, A.out_cubic)
            if e <= 0:
                continue
            paths = []
            k = n["kind"]
            if k == "press":
                for x, y in team[-1]:
                    paths.append([self.P(x + 0.02, y), self.P(x + 0.12, y + (0.5 - y) * 0.3)])
            elif k == "counter":
                paths.append(K.curve(self.P(0.3, 0.62), self.P(0.86, 0.42), 0.18))
            elif k == "wide":
                sides = [n["side"]] if n["side"] else ["left", "right"]
                for sd in sides:
                    y = 0.07 if sd == "left" else 0.93
                    paths.append([self.P(0.22, y), self.P(0.74, y)])
            elif k == "possession":
                mid = team[2] if len(team) > 2 else team[-1]
                tri = [mid[0], mid[len(mid) // 2], mid[-1]] if len(mid) >= 3 else mid + team[1][:1]
                loop = [self.P(*q) for q in tri] + [self.P(*tri[0])]
                for i in range(len(loop) - 1):
                    K.dashed(c, *loop[i], *loop[i + 1], th.ink, 3, alpha=0.8 * e_out * e)
                paths.append([self.P(tri[1][0] + 0.02, tri[1][1]), self.P(tri[1][0] + 0.14, tri[1][1] - 0.04)])
            elif k == "direct":
                paths.append(K.curve(self.P(0.12, 0.5), self.P(0.8, 0.38), -0.22))
            elif k == "falsenine":
                lead = min(team[-1], key=lambda q: abs(q[1] - 0.5))
                paths.append([self.P(lead[0] + 0.01, lead[1] + 0.06), self.P(lead[0] - 0.1, lead[1] + 0.06)])
            elif k in ("highline", "lowblock"):
                y = 0.5
                x = team[1][0][0]
                paths.append([self.P(x, y + 0.02), self.P(x + (0.08 if k == "highline" else -0.06), y + 0.02)])
            for path in paths:
                K.arrow(c, path, th.ink, 6, e_out, e, head=24)
            if paths:
                bx, by = paths[0][-1] if k != "possession" else paths[0][0]
                eb = A.prog(t, n["t"] + 0.4, A.SNAP)
                if eb > 0:
                    sz = max(2, int(38 * A.out_back(eb, 1.8)))
                    D.blit(c, D.disc(sz, th.c("accent"), th.c("bg"), 3), bx + 10, by - sz - 6, e_out)
                    D.text(c, str(n["n"]), th.label, 22, th.bg, bx + 10 + sz / 2, by - sz - 6 + sz * 0.16, min(1, eb * 2) * e_out, anchor="c")
        # the side panel: formation(s), then the ideas in order
        x0 = 1370
        y = 196
        for k, f in enumerate(self.forms):
            e = A.ease(t, f["t"], A.FAST)
            if e <= 0:
                continue
            if f.get("team"):
                D.text(c, f["team"].upper(), th.label, 22, colors[k], x0, y, e * e_out, tracking=0.16)
                y += 36
            size = 120 if len(self.forms) == 1 else 92
            D.text(c, f["text"], th.display, size, th.ink if len(self.forms) == 1 else colors[k], x0, y + 16 * (1 - A.out_smooth(e)), e * e_out)
            y += size * 1.3
        y = max(y + 20, 520)
        for n in self.notes:
            e = A.ease(t, n["t"] + 0.4, A.FAST)
            if e <= 0:
                continue
            D.blit(c, D.disc(36, th.c("accent")), x0, y + 2, e * e_out)
            D.text(c, str(n["n"]), th.label, 22, th.bg, x0 + 18, y + 7, e * e_out, anchor="c")
            lines = D.wrap(n["label"], th.heading, 30, 380)[:2]
            for j, line in enumerate(lines):
                D.text(c, line, th.heading, 30, th.ink, x0 + 56 + 14 * (1 - e), y + j * D.lead(th.heading, 38), e * e_out)
            y += D.lead(th.heading, 38) * len(lines) + 26


# ============================================================ 4. RISE, FALL AND REDEMPTION (risefall)

SPORT_UP = r"scored|won the (?:league|title|cup|treble|double|Ballon d'Or)|hat-trick|named (?:captain|player)"
SPORT_DOWN = r"relegated|sacked|dropped|benched|was sold|left on a free|transfer request"


@K.safe
def detect_risefall(story, a, b, extra_up=SPORT_UP, extra_down=SPORT_DOWN):
    per = K.cache(story, "risefall:" + str(hash((extra_up, extra_down))))
    key = (a, b)
    if key in per:
        return per[key]
    pts = K.career_points(story, a, b, extra_up, extra_down)
    res = None
    sents = {p_["sent"] for p_ in pts}
    if len(pts) >= 3 and any(p_["dir"] == "down" for p_ in pts) and any(p_["dir"] == "up" for p_ in pts) and \
            story.sentences[a].i in sents and story.sentences[b - 1].i in sents:
        pts = pts[:6]
        if all(pts[i]["year"] <= pts[i + 1]["year"] for i in range(len(pts) - 1)):
            kind, title = K.arc_title(pts)
            subject = K.subject_of(story, a, b)
            score = min(0.95, 0.66 + 0.06 * (len(pts) - 3) + (0.12 if kind in ("redemption", "comeback") else 0))
            res = score, {"subject": subject, "title": title, "arc": kind, "points": pts}, [f"{len(pts)} dated career moments ({kind})"]
    per[key] = res
    return res


class RiseFallGraphic(Graphic):
    X0, X1, Y0, Y1 = 170, 1750, 410, 700   # the dots' range; years under the axis at AXIS
    AXIS = 862

    def build(self):
        p = self.p
        self.pts, last = [], 0
        for i, q in enumerate(p["points"]):
            hit = self.tl.phrase(q["phrase"], last)
            if hit:
                last = hit[2]
            yh = self.tl.phrase(q["year_phrase"], max(0, (hit[2] if hit else last) - 120)) if q.get("year_phrase") else None
            t = min([x for x in ((hit[0] if hit else None), (yh[0] if yh else None)) if x is not None] or [0.6 + 1.0 * i])
            self.pts.append(dict(q, t=max(0.5, t - 0.05)))
        for i in range(1, len(self.pts)):
            self.pts[i]["t"] = max(self.pts[i]["t"], self.pts[i - 1]["t"] + 0.4)
        lvl, levels = 0.0, []
        for q in self.pts:
            lvl += (1.8 if q["comeback"] else 1.0) if q["dir"] == "up" else -1.7
            levels.append(lvl)
        lo, hi = min(levels + [0.0]), max(levels + [0.0])
        span = max(1e-6, hi - lo)
        n = len(self.pts)
        self.xy = [(self.X0 + 120 + i * (self.X1 - self.X0 - 240) / max(1, n - 1), self.Y1 - (lv - lo) / span * (self.Y1 - self.Y0)) for i, lv in enumerate(levels)]
        self.start = (self.X0, self.Y1 - (0 - lo) / span * (self.Y1 - self.Y0))
        self.step = (self.X1 - self.X0 - 240) / max(1, n - 1)
        self.card_w = int(min(360, self.step - 24))
        self.photo_key = self.assets.find(person=p["subject"])[0] if p.get("subject") else None
        self.cue(0.05, "whoosh-mid-1", -9, "chart")
        for q in self.pts:
            if q["dir"] == "down":
                self.cue(q["t"], "thump-deep-2", -8, "the fall")
                self.cue(q["t"], "sweep-down-1", -15, "the fall")
            elif q["comeback"]:
                self.cue(q["t"], "riser-3", -14, "the comeback")
                self.cue(q["t"] + 0.35, "crowd-cheer-1", -15, "the comeback")
            else:
                self.cue(q["t"], "sweep-up-2", -14, "the rise")
                self.cue(q["t"] + 0.3, "click-mech-1", -10, "moment")
        self.cue(self.out, "rwhoosh-2", -9, "out")

    def draw(self, c, t):
        th, p = self.th, self.p
        e_out = 1 - A.out_cubic(A.prog(t, self.out, A.EXIT))
        ek = A.ease(t, 0.1, A.FAST)
        D.text(c, (p.get("subject") or "").upper(), th.label, 24, th.accent, 120, 104, ek * e_out, tracking=0.2)
        title = p.get("title") or ""
        ts = K.fit(title, th.display, 1400 if not self.photo_key else 1250, 92, 48)
        D.text(c, title, th.display, ts, th.ink, 120, 140 + (92 - ts) * 0.6, e_out, clip=(120, 120, 120 + 1600 * A.ease(t, 0.15, 0.5), 300))
        if self.photo_key:
            e = A.ease(t, 0.2, 0.45)
            img = K.circle_photo(D.photo(self.assets.path(self.photo_key), 170, 170, focus=(0.5, 0.3), sat=0.9))
            D.blit(c, D.disc(182, th.c("accent")), 1800 - 182, 92, e * e_out)
            D.blit(c, img, 1800 - 176, 98, e * e_out)
        # axis
        D.rect(c, self.X0, self.AXIS, self.X0 + (self.X1 - self.X0) * A.ease(t, 0.1, 0.6, A.out_quint), self.AXIS + 2, th.muted, 0.6 * e_out)
        # the curve, segment by segment as each moment is said
        prev = self.start
        for i, q in enumerate(self.pts):
            pr = A.ease(t, q["t"] - 0.15, 0.5, A.in_out_cubic)
            if pr <= 0:
                break
            cur = self.xy[i]
            seg = [prev, (prev[0] + (cur[0] - prev[0]) * pr, prev[1] + (cur[1] - prev[1]) * pr)]
            colr = th.accent2 if q["dir"] == "down" else th.accent
            D.polyline(c, seg, colr, 14, 0.18 * e_out)
            D.polyline(c, seg, colr, 5, e_out)
            prev = cur
        for i, q in enumerate(self.pts):
            e = A.prog(t, q["t"] + 0.3, 0.3)
            if e <= 0:
                continue
            x, y = self.xy[i]
            colr = th.accent2 if q["dir"] == "down" else th.accent
            sz = max(2, int(30 * A.out_back(e, 1.8)))
            D.blit(c, D.disc(sz, D.col(colr), th.c("ink"), 3), x - sz / 2, y - sz / 2, e_out)
            D.text(c, str(q["year"]), th.display, 44, th.ink, x, self.AXIS + 22, min(1, e * 2) * e_out, anchor="c")
            lines = D.wrap(q["label"], th.heading, 28, self.card_w)[:3]
            lh = D.lead(th.heading, 34)
            hgt = lh * len(lines)
            below = q["dir"] == "down"
            ty = (y + 34) if below else (y - 34 - hgt)
            # the guide from the dot to the axis, not through a label below the dot
            D.rect(c, x - 1, (ty + hgt + 10) if below else (y + 18), x + 1, self.AXIS - 4, th.muted, 0.35 * min(1, e * 2) * e_out)
            ec = A.ease(t, q["t"] + 0.35, A.FAST)
            for j, line in enumerate(lines):
                D.text(c, line, th.heading, 28, th.ink, x, ty + j * lh + 10 * (1 - ec), ec * e_out, anchor="c")


# ============================================================ registration

THEMES = {
    "stats": Theme("fb-stats", bg="#0A0E1A", bg2="#141B2E", ink="#F5F3EE", muted="#9AA3B8", accent="#E8B53A", accent2="#E5484D",
                   display="oswald", heading="oswald-md", body="inter-bold", label="inter-bold"),
    "bracket": Theme("fb-bracket", bg="#07122B", bg2="#0E1E44", ink="#F2F5FF", muted="#93A0C4", accent="#5CC8FF", accent2="#FF6B6B",
                     display="oswald", heading="oswald-md", body="inter-bold", label="inter-bold"),
    "tactics": Theme("fb-tactics", bg="#0B2A17", bg2="#10361F", ink="#F4F7F2", muted="#A9C2B0", accent="#F7D046", accent2="#FF7A7F",
                     display="oswald", heading="inter-bold", body="inter-bold", label="inter-bold"),
    "risefall": Theme("fb-risefall", bg="#0D0D10", bg2="#18181D", ink="#F7F4EE", muted="#9A968F", accent="#F2B33D", accent2="#F0524F",
                      display="inter-black", heading="inter-bold", body="dm-sans", label="inter-bold"),
}
_F = ("bg", "bg2", "ink", "muted", "accent", "accent2")


def _set(*colors):
    return dict(zip(_F, colors))


_TYPE = {"size": (0.85, 1.15)}
LOOKS = {
    "stats": {"palettes": [
        ("A", "Navy & gold", None),
        ("B", "Black & red", _set("#0C0C0E", "#17171B", "#F6F4EF", "#9A9AA2", "#E5484D", "#F2B33D")),
        ("C", "Royal blue & white", _set("#081A3A", "#0F2552", "#F4F7FF", "#9DB0D6", "#6FB4FF", "#FFD166"))],
        **_TYPE, "fonts": ("sans", "geometric"), "mirror": "Photo on the right", "place": True,
        "present": {"prefer": "own", "why": "a player's photo and big numbers: a profile card"}},
    "bracket": {"palettes": [
        ("A", "Night blue", None),
        ("B", "Black & gold", _set("#0B0B0C", "#16161A", "#F5F2EA", "#9C988E", "#E8B53A", "#FF6B6B")),
        ("C", "Deep green", _set("#07201A", "#0D2E25", "#F1F7F4", "#97B3A8", "#4FD1A5", "#FF7A6B"))],
        **_TYPE, "fonts": ("sans", "geometric"), "place": True,
        "present": {"prefer": "own", "why": "a route of rounds across the whole width"}},
    "tactics": {"palettes": [
        ("A", "Grass green", None),
        ("B", "Chalkboard", _set("#1B1F1D", "#232926", "#F2F2EE", "#A3AAA5", "#F5C542", "#FF7A7F")),
        ("C", "Night pitch", _set("#06180F", "#0A2416", "#EEF6F0", "#94B3A0", "#7CD4FF", "#FF8C66"))],
        **_TYPE, "fonts": ("condensed", "geometric"),
        "backdrops": ("own",), "backdrop_note": "The tactics board keeps its own pitch: the board fills the screen.",
        "present": {"prefer": "own", "lock": True, "why": "the pitch board fills the screen"}},
    "risefall": {"palettes": [
        ("A", "Black, gold & red", None),
        ("B", "Navy, teal & coral", _set("#0B1220", "#131C2E", "#F4F1EA", "#8E9AB3", "#39C3B5", "#FF7A59")),
        ("C", "Charcoal, green & red", _set("#111214", "#1B1C1F", "#F3F1EC", "#96938C", "#5BD68A", "#F0524F"))],
        **_TYPE, "fonts": ("condensed", "sans", "geometric"), "place": True,
        "present": {"prefer": "own", "why": "a career curve across the whole width"}},
}


def _person(name, label):
    return {"key": "person:" + name, "kind": "person", "value": name, "label": label}


def slots_stats(p):
    return [_person(p["subject"], f"Photo of {p['subject']} (the profile)")] if p.get("subject") else []


def slots_risefall(p):
    return [_person(p["subject"], f"Small portrait of {p['subject']}")] if p.get("subject") else []


class Football(Collection):
    key = "football"
    label = "Football"

    def __init__(self):
        super().__init__()
        self.add(Category("stats", "Player and team analysis", THEMES["stats"], detect_stats, StatsGraphic, max_window=3, slots=slots_stats,
                          about="Three or more numbers about a player or team (goals, appearances, trophies, a fee), counting up as they are said.",
                          looks=LOOKS["stats"]))
        self.add(Category("bracket", "Road to the final", THEMES["bracket"], detect_bracket, BracketGraphic, max_window=4,
                          about="Two or more rounds of a tournament with the opponent (and the score), as a route to the trophy.",
                          looks=LOOKS["bracket"]))
        self.add(Category("tactics", "Tactical breakdown", THEMES["tactics"], detect_tactics, TacticsGraphic, max_window=3,
                          about="A formation (4-3-3) on a pitch board, with the tactical ideas the narration names as arrows.",
                          looks=LOOKS["tactics"]))
        self.add(Category("risefall", "Rise, fall and redemption", THEMES["risefall"], detect_risefall, RiseFallGraphic, max_window=5, min_window=2,
                          slots=slots_risefall, about="Three or more dated career moments, at least one a fall, drawn as the career's curve.",
                          looks=LOOKS["risefall"]))


register(Football())
