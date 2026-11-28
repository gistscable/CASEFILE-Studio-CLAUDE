"""v0.4.76 Shared pieces of the niche collections (football, combat sports, entertainment, documentary).

Not a collection: nothing here registers. Reading helpers take words only from the narration (numbers, names,
years and short headlines cut from its own clauses: never a word it did not say), and the drawing helpers are
the icons and panels the niche graphics share. Every detector is wrapped in `safe`: a window it cannot read is
simply not a candidate (the engine offers every window of every chapter to every category)."""
from __future__ import annotations

import functools
import math
import re

from PIL import Image, ImageDraw

from .. import anim as A
from .. import draw as D

# ---------------------------------------------------------------- reading

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
             "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
             "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
            "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15}
NUMW = r"(?:\d[\d,]*(?:\.\d+)?|" + "|".join(sorted(NUM_WORDS, key=len, reverse=True)) + r")"
NUMW_I = r"(?i:" + NUMW[3:]   # the same, any case ("Five Ballon d'Or awards")
YEAR = r"(?:19[0-9]{2}|20[0-4][0-9])"
SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12, "m": 1e6, "bn": 1e9, "k": 1e3}
PRONOUN = re.compile(r"^(?:he|she|they|it|we|the club|the team|the side|the band|the group|the company|the firm)\b\s*", re.I)
CUT_AT = re.compile(r"\s*(?:,|;|:|—|–|\s-\s|\band the\b|\bthat\b|\bwhich\b|\bwho\b|\bwhen\b|\bwhile\b|\bbefore\b|\bafter\b|\bbecause\b|"
                    r"\bas\b|\bwhere\b|\band then\b|\bbut\b|\buntil\b)", re.I)


def safe(fn):
    """A detector that never stops the plan: anything it cannot read is not a candidate."""
    @functools.wraps(fn)
    def run(*a, **k):
        try:
            return fn(*a, **k)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, ZeroDivisionError, re.error):
            return None
    return run


def number(s):
    """The value of a number as the narration writes it ("672", "1,234", "2.5", "five", "twenty"); None otherwise."""
    if s is None:
        return None
    w = str(s).strip().lower().replace(",", "")
    if w in NUM_WORDS:
        return float(NUM_WORDS[w])
    try:
        return float(w)
    except ValueError:
        return None


def cache(story, key):
    """A per-story scratch dict (the detectors read each sentence once, not once per window)."""
    c = getattr(story, "_niche_cache", None)
    if c is None:
        c = {}
        story._niche_cache = c
    return c.setdefault(key, {})


def years_in(text):
    return [(int(m.group(0)), m.start(), m.end()) for m in re.finditer(rf"\b{YEAR}\b", text)]


PREP_RE = re.compile(r"\s+(?:in|at|on|with|during|against|after|before|for|to|from|as|amid|despite|under|over|into|while)\s+", re.I)


def headline(clause, limit=34, cut=None):
    """A short headline cut from a clause of the narration: the subject pronoun dropped, cut before a
    subordinate part (and before `cut`, a regex, when given), then before a preposition or at a word boundary
    within `limit` characters. Only the narration's own words."""
    s = re.sub(r"\s+", " ", clause).strip().strip(".,;:!?\"“”'")
    s = re.sub(rf"^(?:(?:in|by|from|since|until|during|at)\s+(?:the\s+)?(?:(?:early|late|mid|summer|autumn|spring|winter|end of)\s+)?{YEAR}s?\s*,?\s*)", "", s, flags=re.I)
    s = re.sub(r"^(?:and|then|but|so|yet|finally|eventually|later|soon|by then)\s*,?\s+", "", s, flags=re.I)
    s = PRONOUN.sub("", s)
    m = CUT_AT.search(s, 8)
    if m:
        s = s[:m.start()]
    if cut:
        m = re.search(cut, s[8:], re.I)
        if m:
            s = s[:8 + m.start()]
    if len(s) > limit:
        preps = [m.start() for m in PREP_RE.finditer(s) if 10 < m.start() <= limit]
        if preps:  # "Beat Michaels at WrestleMania | in a match many still call ..."
            s = s[:preps[-1]]
    if len(s) > limit:
        cut = s[:limit + 1]
        sp = cut.rfind(" ")
        s = cut[:sp] if sp > 10 else cut[:limit]
        # never end on a dangling small word ("Signed for a" -> "Signed for" -> "Signed")
        while True:
            t2 = re.sub(r"\s+(?:the|a|an|of|for|to|in|on|at|with|and|by|his|her|their|its|from|as|into|after|over)$", "", s, flags=re.I)
            if t2 == s:
                break
            s = t2
    s = s.strip(" ,;:-—–")
    return s[:1].upper() + s[1:] if s else ""


def short_name(full):
    """The name a graphic shows big: the surname (\"Mike Tyson\" -> \"TYSON\")."""
    toks = [t for t in re.split(r"\s+", full.strip()) if t and not re.fullmatch(r"(?:Sr|Jr)\.?|[A-Z]\.", t)]
    return toks[-1] if toks else full


CLUB_WORDS = {"FC", "AFC", "CF", "SC", "United", "City", "Real", "Athletic", "Atletico", "Atlético", "Sporting", "Inter", "Bayern",
              "Borussia", "Juventus", "Arsenal", "Chelsea", "Liverpool", "Madrid", "Barcelona", "Milan", "Munich", "Dortmund",
              "Paris", "Saint-Germain", "Germain", "Ajax", "Benfica", "Porto", "Celtic", "Rangers", "Napoli", "Roma", "Lazio",
              "Villa", "Hotspur", "Wanderers", "Rovers", "Albion", "Palace", "Forest", "County", "Town", "Olympique", "Lyon",
              "Marseille", "Galatasaray", "Fenerbahce", "PSV", "Leverkusen", "Leipzig", "Sevilla", "Valencia", "Everton",
              "Newcastle", "Tottenham", "Manchester", "Brazil", "Argentina", "France", "Germany", "Spain", "England", "Italy",
              "Portugal", "Netherlands", "Nigeria", "Ghana", "Senegal", "Morocco", "Egypt", "Croatia", "Belgium", "Uruguay"}


def is_club(name):
    return any(t in CLUB_WORDS for t in name.split())


def people_in(story, a, b, clubs=False):
    """Named people in the window, most mentioned first (clubs and countries left out unless asked)."""
    seen = {}
    for s in story.sentences[a:b]:
        for n in s.people:
            if clubs or not is_club(n):
                seen[n] = seen.get(n, 0) + 1
    return sorted(seen, key=lambda n: (-seen[n], n))


_NOT_NAME = {"The", "A", "An", "In", "On", "At", "By", "His", "Her", "Their", "It", "He", "She", "They", "We", "This", "That",
             "Then", "But", "And", "When", "After", "Before", "During", "Nobody", "Everyone", "Nothing", "There", "For", "From",
             "With", "Over", "Under", "Within", "Years", "Months", "Weeks", "Days", "Fans", "Critics", "Everybody", "Few", "Many"}
LEAD_RE = re.compile(r"^((?:[A-Z][\w'’.-]+)(?:\s+(?:de|van|von|da|dos|del|di|le|la|bin|al)?\s*[A-Z][\w'’.-]+){0,2})\s+(?=[a-z])")


def lead_name(text):
    """The name a sentence opens with ("Lionel Messi scored", "In 2009, Ronaldo joined"): the narration's own subject."""
    s = re.sub(rf"^(?:(?:in|by|on|at|from|during)\s+(?:the\s+)?(?:(?:early|late|mid|summer|autumn|spring|winter|end of)\s+)?(?:[A-Z][a-z]+\s+)?{YEAR}s?\s*,?\s*)", "",
               text.strip(), flags=re.I)
    s = re.sub(r"^(?:and|then|but|so|yet|finally|eventually|later|soon)\s*,?\s+", "", s, flags=re.I)
    m = LEAD_RE.match(s)
    if not m:
        return ""
    name = m.group(1)
    toks = name.split()
    if toks[0] in _NOT_NAME or is_club(name):
        return ""
    return name


def title_subject(story):
    """The person the title names after its dash ("Iron — Mike Tyson"), or ""."""
    m = re.search(r"[—–-]\s*([A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,2})\s*$", story.title or "")
    return m.group(1) if m and not is_club(m.group(1)) else ""


def subject_of(story, a, b):
    """Whose passage this is: the story's subject when the window names them, else the person it names most,
    else the name the passage's sentences open with."""
    subj = story.subject if story.subject and not is_club(story.subject) else ""  # a club is not whose career it is
    subj = title_subject(story) or subj
    leads = {}
    for s in story.sentences[a:b]:
        n = lead_name(s.text)
        if n:
            leads[n] = leads.get(n, 0) + 1
    if subj and leads and not any(n == subj or subj.endswith(" " + n) or n.endswith(" " + subj.split()[-1]) or n == subj.split()[-1] for n in leads):
        subj = ""  # the passage is about someone else (its sentences open with another name)
    ppl = people_in(story, a, b)
    if subj and subj in ppl:
        return subj
    text = story.window_text(a, b)
    if subj and re.search(rf"\b{re.escape(subj.split()[-1])}\b", text):
        return subj
    # "Tyson" opens the sentences: the full name the story knows for it
    known = list(story.people) + ppl + [subj] if subj else list(story.people) + ppl
    for n in list(leads):
        full = [k for k in known if k and k != n and k.endswith(" " + n)]
        if full:
            leads[full[0]] = leads.get(full[0], 0) + leads.pop(n)
    if leads and (not ppl or max(leads.values()) >= 2 or ppl[0] not in leads):
        if not ppl or not any(n in leads for n in ppl):
            ppl = []
    if ppl:
        return ppl[0]
    # "Ronaldo" twice and "Cristiano Ronaldo" once: one person, shown by the full name
    for n in list(leads):
        full = [m for m in leads if m != n and m.endswith(" " + n)]
        if full:
            leads[max(full, key=len)] += leads.pop(n)
    if leads:
        return max(leads, key=lambda n: (leads[n], len(n)))
    return subj


def fmt_value(v, decimals=0, comma=True):
    if decimals:
        return f"{v:,.{decimals}f}" if comma else f"{v:.{decimals}f}"
    return f"{int(round(v)):,}" if comma else str(int(round(v)))


def counted(stat, p):
    """A stat's text at count-up progress p (0..1): the number climbs, its prefix and suffix stay."""
    num = stat.get("num")
    if num is None or p >= 1:
        return stat["value"]
    dec = stat.get("decimals", 0)
    comma = "," in stat.get("digits", "") or (num >= 10000 and stat.get("comma", True))
    return f"{stat.get('prefix', '')}{fmt_value(num * A.out_cubic(p), dec, comma)}{stat.get('suffix', '')}"


def stat_number(raw, scale=None, cur=""):
    """{value, num, digits, decimals, prefix, suffix} for "672", "1.2" + "billion", "$" ... as shown on screen."""
    num = number(raw)
    if num is None:
        return None
    digits = str(raw)
    dec = len(digits.split(".")[1]) if "." in digits and digits.replace(",", "").replace(".", "").isdigit() else 0
    suffix = ""
    sc = (scale or "").lower()
    if sc in ("million", "m"):
        suffix = "M"
    elif sc in ("billion", "bn"):
        suffix = "B"
    elif sc == "trillion":
        suffix = "T"
    elif sc in ("thousand", "k"):
        suffix = "K"
    if not digits[:1].isdigit():  # a number word: shown as digits (it is the same number)
        digits = str(int(num))
    value = f"{cur}{digits}{suffix}"
    return {"value": value, "num": num, "digits": digits, "decimals": dec, "prefix": cur, "suffix": suffix}


# ---------------------------------------------------------------- career moments (rise / fall)

UP = (r"signed(?: for| with)?|joined|made (?:his|her|their) debut|debuted|broke through|burst onto|scored|won|lifted|named|"
      r"captained|became|promoted|returned|came back|made (?:a|his|her|their) comeback|recovered|bounced back|rebuilt|"
      r"broke the record|set a record|crowned|starred|released|launched|topped|hit number one|hit No\. 1|landed|cast|"
      r"rose|soared|founded|went public|expanded|redeemed|reclaimed|regained|finally won")
DOWN = (r"(?:suffered|picked up|sustained)\b[^.,;]{0,40}?\binjur\w*|injured|tore|ruptured|broke (?:his|her) (?:leg|ankle|foot|arm|neck)|"
        r"relegated|sacked|fired|dropped|benched|banned|suspended|lost (?:his|her|their)? ?(?:place|job|title|crown|way|form|everything)|"
        r"missed|declined|slumped|was released|were released|exiled|arrested|charged|jailed|scandal|struggled|fell|collapsed|went bankrupt|"
        r"filed for bankruptcy|sold (?:its|his|her|their|the) (?:\w+ )?(?:business|company|division|stake|empire|label)|crashed|was cancelled|was canceled|entered rehab|checked into rehab|divorced|faded|retired injured|"
        r"was forced out|stepped down|resigned|was ousted|was booed|flopped")
COMEBACK = r"returned|came back|made (?:a|his|her|their) comeback|bounced back|recovered|redeemed|reclaimed|regained|finally won|rebuilt"
UP_RE = re.compile(rf"\b(?:{UP})\b", re.I)
DOWN_RE = re.compile(rf"\b(?:{DOWN})\b", re.I)
COMEBACK_RE = re.compile(rf"\b(?:{COMEBACK})\b", re.I)


def career_points(story, a, b, extra_up=None, extra_down=None):
    """[{year, label, dir: up|down, comeback, phrase}] in narration order: each clause with a year and a rise or a
    fall in it (one per clause; the first verb decides)."""
    out = []
    subj = subject_of(story, a, b)
    mine = {subj, subj.split()[-1], subj.split()[0]} if subj else set()
    up_re = re.compile(rf"\b(?:{UP}{'|' + extra_up if extra_up else ''})\b", re.I)
    down_re = re.compile(rf"\b(?:{DOWN}{'|' + extra_down if extra_down else ''})\b", re.I)
    for s in story.sentences[a:b]:
        txt = s.text
        ys = years_in(txt)
        if not ys:
            continue
        # clauses: split at ; and at ", and" / " and then" so two dated events in one sentence stay apart
        parts, start = [], 0
        for m in re.finditer(r";|,\s+(?:and|but|then)\s+|\.\s|\s+(?:and|but)\s+(?=(?:the\s+)?[A-Z][\w'’.-]+\s+[a-z])", txt):
            parts.append((start, m.start()))
            start = m.end()
        parts.append((start, len(txt)))
        last_year = None
        for p0, p1 in parts:
            cl = txt[p0:p1]
            yy = [y for y in ys if p0 <= y[1] < p1]
            year = yy[0][0] if yy else last_year
            if yy:
                last_year = yy[-1][0]
            if year is None:
                continue
            other = lead_name(cl)
            if subj and other and other not in mine and not subj.endswith(" " + other) and not other.endswith(" " + subj.split()[-1]):
                continue  # another actor's moment ("Apple launched the iPhone") is not the subject's rise or fall
            mu, md = up_re.search(cl), down_re.search(cl)
            if not mu and not md:
                continue
            down = bool(md and (not mu or md.start() < mu.start()))
            m = md if down else mu
            verb_at = m.start()
            label = headline(cl[verb_at:], 46)
            if len(label) < 6:
                continue
            out.append({"year": year, "label": label, "dir": "down" if down else "up",
                        "comeback": bool(not down and COMEBACK_RE.search(cl[verb_at:verb_at + 40])),
                        "phrase": cl[verb_at:verb_at + 28].strip(), "year_phrase": str(year) if yy else "", "sent": s.i})
    return out


def arc_title(points):
    """The arc the points make, in the narration's terms: (kind, words)."""
    dirs = [p["dir"] for p in points]
    if "down" in dirs:
        first_down = dirs.index("down")
        if any(d == "up" for d in dirs[first_down + 1:]):
            return ("redemption", "RISE, FALL AND REDEMPTION") if "up" in dirs[:first_down] else ("comeback", "THE FALL AND THE COMEBACK")
        return ("fall", "THE RISE AND FALL") if "up" in dirs[:first_down] else ("fall", "THE FALL")
    return ("rise", "THE RISE")


# ---------------------------------------------------------------- drawing

def scrim(c, x0, y0, x1, y1, color, alpha):
    D.rect(c, x0, y0, x1, y1, color, alpha)


_ICONS = {}


def icon(kind, size, color):
    """Small flat icons drawn from shapes (supersampled): trophy, star, belt, disc, play, chart, crown, ball, glove."""
    key = (kind, size, color)
    if key in _ICONS:
        return _ICONS[key]
    S = D.SS * size
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = D.col(color)
    u = S / 100.0
    if kind == "trophy":
        d.pieslice((22 * u, -18 * u, 78 * u, 58 * u), 0, 180, fill=col)          # the cup
        d.rectangle((22 * u, 4 * u, 78 * u, 20 * u), fill=col)
        d.arc((6 * u, 8 * u, 34 * u, 40 * u), 90, 270, fill=col, width=int(6 * u))   # handles
        d.arc((66 * u, 8 * u, 94 * u, 40 * u), -90, 90, fill=col, width=int(6 * u))
        d.rectangle((45 * u, 56 * u, 55 * u, 76 * u), fill=col)                    # stem
        d.rectangle((30 * u, 76 * u, 70 * u, 84 * u), fill=col)
        d.rectangle((24 * u, 86 * u, 76 * u, 96 * u), fill=col)                    # base
    elif kind == "star":
        pts = []
        for i in range(10):
            r = 48 * u if i % 2 == 0 else 20 * u
            ang = -math.pi / 2 + i * math.pi / 5
            pts.append((50 * u + r * math.cos(ang), 52 * u + r * math.sin(ang)))
        d.polygon(pts, fill=col)
    elif kind == "belt":
        d.rounded_rectangle((2 * u, 34 * u, 98 * u, 66 * u), radius=int(8 * u), fill=col)
        d.ellipse((28 * u, 14 * u, 72 * u, 86 * u), fill=col)
        d.ellipse((38 * u, 26 * u, 62 * u, 74 * u), fill=(0, 0, 0, 0))
        d.ellipse((44 * u, 36 * u, 56 * u, 64 * u), fill=col)
    elif kind == "disc":
        d.ellipse((4 * u, 4 * u, 96 * u, 96 * u), fill=col)
        d.ellipse((36 * u, 36 * u, 64 * u, 64 * u), fill=(0, 0, 0, 0))
        d.ellipse((45 * u, 45 * u, 55 * u, 55 * u), fill=col)
    elif kind == "play":
        d.rounded_rectangle((4 * u, 16 * u, 96 * u, 84 * u), radius=int(16 * u), fill=col)
        d.polygon([(40 * u, 32 * u), (40 * u, 68 * u), (68 * u, 50 * u)], fill=(0, 0, 0, 0))
    elif kind == "chart":
        for i, h in enumerate((30, 52, 44, 80)):
            d.rectangle(((8 + i * 23) * u, (96 - h) * u, (24 + i * 23) * u, 96 * u), fill=col)
    elif kind == "crown":
        d.polygon([(6 * u, 80 * u), (6 * u, 28 * u), (30 * u, 52 * u), (50 * u, 16 * u), (70 * u, 52 * u), (94 * u, 28 * u), (94 * u, 80 * u)], fill=col)
        d.rectangle((6 * u, 84 * u, 94 * u, 94 * u), fill=col)
    elif kind == "ball":
        d.ellipse((4 * u, 4 * u, 96 * u, 96 * u), fill=col)
        pent = [(50 * u + 18 * u * math.cos(-math.pi / 2 + i * 2 * math.pi / 5), 50 * u + 18 * u * math.sin(-math.pi / 2 + i * 2 * math.pi / 5)) for i in range(5)]
        d.polygon(pent, fill=(0, 0, 0, 0))
    elif kind == "people":
        d.ellipse((30 * u, 8 * u, 70 * u, 48 * u), fill=col)
        d.pieslice((12 * u, 52 * u, 88 * u, 128 * u), 180, 360, fill=col)
    else:  # a dot
        d.ellipse((20 * u, 20 * u, 80 * u, 80 * u), fill=col)
    out = im.resize((size, size), Image.LANCZOS)
    _ICONS[key] = out
    if len(_ICONS) > 256:
        _ICONS.pop(next(iter(_ICONS)))
    return out


def arrow(c, pts, color, width=6, alpha=1.0, p=1.0, head=22):
    """A polyline arrow drawn to fraction p of its length, with its head at the tip."""
    if p <= 0 or len(pts) < 2:
        return
    tip, part = D.path_point(pts, p)
    if len(part) >= 2:
        D.polyline(c, part, color, width, alpha)
    prev = part[-2] if len(part) >= 2 else pts[0]
    ang = math.atan2(tip[1] - prev[1], tip[0] - prev[0])
    h = head * min(1.0, p * 3)
    a1 = (tip[0] - h * math.cos(ang - 0.45), tip[1] - h * math.sin(ang - 0.45))
    a2 = (tip[0] - h * math.cos(ang + 0.45), tip[1] - h * math.sin(ang + 0.45))
    tri(c, [tip, a1, a2], color, alpha)


def tri(c, pts, color, alpha=1.0):
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    x0, y0 = int(min(xs)) - 2, int(min(ys)) - 2
    w, h = int(max(xs)) - x0 + 3, int(max(ys)) - y0 + 3
    if w <= 0 or h <= 0:
        return
    big = Image.new("RGBA", (w * D.SS, h * D.SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).polygon([((x - x0) * D.SS, (y - y0) * D.SS) for x, y in pts], fill=D.col(color))
    D.blit(c, big.resize((w, h), Image.LANCZOS), x0, y0, alpha)


def curve(p0, p1, bend=0.25, n=24):
    """Points of a gentle arc from p0 to p1 (bend: fraction of the length, to the left of travel)."""
    (x0, y0), (x1, y1) = p0, p1
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    cx, cy = mx - dy * bend, my + dx * bend
    return [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1)
            for t in (i / (n - 1) for i in range(n))]


def dashed(c, x0, y0, x1, y1, color, width=3, dash=14, gap=10, alpha=1.0):
    L = math.hypot(x1 - x0, y1 - y0)
    if L <= 0:
        return
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    s = 0.0
    while s < L:
        e = min(L, s + dash)
        D.polyline(c, [(x0 + ux * s, y0 + uy * s), (x0 + ux * e, y0 + uy * e)], color, width, alpha, pad=4)
        s = e + gap


def slanted(img, slant, right=True):
    """A photo with one slanted edge (the sports-poster cut): alpha mask, no blur."""
    w, h = img.size
    mask = Image.new("L", (w * D.SS, h * D.SS), 0)
    s = slant * D.SS
    W_, H_ = w * D.SS, h * D.SS
    pts = [(0, 0), (W_, 0), (W_ - s, H_), (0, H_)] if right else [(s, 0), (W_, 0), (W_, H_), (0, H_)]
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    out = img.convert("RGBA")
    a = out.getchannel("A")
    from PIL import ImageChops
    out.putalpha(ImageChops.multiply(a, mask))
    return out


def circle_photo(img):
    w, h = img.size
    mask = Image.new("L", (w * D.SS, h * D.SS), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, w * D.SS - 1, h * D.SS - 1), fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def credit(c, assets, key, x, y, color, alpha=1.0, anchor="l"):
    cr = assets.credit(key) if key else ""
    if cr:
        D.text(c, cr, "mono", 13, color, x, y, alpha, anchor=anchor)


def fit(text, key, maxw, start, minimum=18, tracking=0.0, lines=1):
    return D.fit_size(text, key, int(maxw), int(start), int(minimum), tracking, lines)


def no_record():
    """Drawing into an off-screen sprite: its text is not the frame's (the layout check reads the frame only)."""
    class _Off:
        def __enter__(self):
            self.saved, D.RECORD = D.RECORD, None

        def __exit__(self, *exc):
            D.RECORD = self.saved
    return _Off()
