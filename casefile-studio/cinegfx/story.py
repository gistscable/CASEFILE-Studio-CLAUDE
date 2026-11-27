"""Story intelligence: the whole production script (and its SRT, through timing.py) read once into a
model every graphics collection can query — chapters, sentences, dated events (with relative dates
resolved: "that day", "a day later", "the following day's"), people with their roles, organisations,
places, attributed claims with their polarity, and questions. Nothing here is specific to one niche;
collections (true crime, sport, history ...) add their own vocabularies on top."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import text as T

ROLE_TITLES = [
    "Chief of Detectives", "Bronx District Attorney", "District Attorney", "Police Commissioner", "Commissioner",
    "Mayor", "President", "Governor", "Senator", "Judge", "Justice", "attorney", "lawyer", "Detective", "Officer",
    "Sergeant", "Captain", "Sheriff", "Coach", "coach", "manager", "Manager", "promoter", "referee", "Referee",
    "captain", "principal", "prosecutor",
]
FAMILY = ["father", "mother", "sister", "brother", "son", "daughter", "uncle", "aunt", "cousin", "wife", "husband", "grandmother", "grandfather"]
MEDIA = ["Daily News", "New York Post", "CBS New York", "NBC New York", "ABC7", "FOX 5", "PIX11", "Associated Press", "Reuters",
         "BBC", "ESPN", "Sky Sports", "The Athletic", "The Guardian", "New York Times"]
ORG_SUFFIX = r"(?:Department of [A-Z][a-z]+|Ministry|Department|Office|Police|NYPD|FBI|Court|League|Federation|Association|Club|Council|Commission)"
PLACE_SUFFIX = r"(?:Street|St\.|Avenue|Ave\.|Road|Boulevard|Park|Place|station|Station|Court|Hospital|School|Stadium|Arena|Garden|Bridge|Square|Hall)"
ATTRIB_VERBS = r"(?:said|says|told|reported|recalled|called|characterized|described|announced|believes|believed|added|confirmed|denied|claimed|insisted|testified|outlined)"
NEG = re.compile(r"\b(?:not|no(?!\.\s*\d)|never|none|without|n't|nobody|nothing|neither|nor)\b", re.I)


@dataclass
class DateRef:
    date: dt.date
    text: str          # as written ("October 29", "That day", "the following day's")
    start: int         # within the sentence
    end: int
    relative: str = ""  # "" absolute, else how it was resolved


@dataclass
class Claim:
    source: str        # who says it (a person's full name, an organisation, "police", ...)
    verb: str
    content: str
    negated: bool
    start: int
    end: int
    via: str = ""      # relayed: "Ben Crump said prosecutors told the family ..." -> source prosecutors, via Ben Crump


@dataclass
class Sentence:
    i: int
    chapter: int
    para: int
    text: str
    dates: list = field(default_factory=list)
    people: list = field(default_factory=list)     # full names mentioned (aliases resolved)
    orgs: list = field(default_factory=list)
    places: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    question: bool = False
    words: int = 0


@dataclass
class Chapter:
    i: int
    title: str
    number: int | None


@dataclass
class Person:
    name: str
    role: str = ""
    aliases: set = field(default_factory=set)


class Story:
    def __init__(self, title: str, subject: str, chapters: list, sentences: list, people: dict, reference: dt.date):
        self.title, self.subject, self.chapters, self.sentences = title, subject, chapters, sentences
        self.people, self.reference = people, reference

    # --- queries used by collections
    def chapter_of(self, s: Sentence) -> Chapter:
        return self.chapters[s.chapter]

    def role_of(self, name: str) -> str:
        p = self.people.get(name)
        return p.role if p else ""

    def first(self, pattern: str, flags=re.I):
        """(sentence, match) of the first sentence anywhere in the story matching `pattern`."""
        for s in self.sentences:
            m = re.search(pattern, s.text, flags)
            if m:
                return s, m
        return None, None

    def incident_date(self):
        """The date the story turns on: the first dated sentence about a shooting / killing / match / fight."""
        for s in self.sentences:
            if s.dates and re.search(r"\b(shot|shooting|killed|murder|stabbed|died|final|fight|match|bout)\b", s.text, re.I):
                return s.dates[0].date
        return None

    def window_text(self, a: int, b: int) -> str:
        return " ".join(s.text for s in self.sentences[a:b])


# ------------------------------------------------------------------ parsing

_HEAD = re.compile(r"^#{1,3}\s+(.*)$")
_SKIP_SECTION = re.compile(r"not narrated|compilation|totals|producer notes|sources", re.I)


def _date_reference(raw: str) -> dt.date:
    m = re.search(r"(?:recording date|date)[^A-Za-z0-9]*\**\s*:?\**\s*([A-Z][a-z]+ \d{1,2}, \d{4})", raw)
    if m:
        try:
            return dt.datetime.strptime(m.group(1), "%B %d, %Y").date()
        except ValueError:
            pass
    years = [int(y) for y in re.findall(r"\b(20\d\d|19\d\d)\b", raw)]
    return dt.date(max(years) if years else dt.date.today().year, 12, 31)


def parse_script(raw: str, title: str = "", subject: str = "") -> Story:
    """Read a production script (markdown headings for chapters; plain paragraphs of narration)."""
    reference = _date_reference(raw)
    chapters, paras = [], []
    current, skip = None, False
    for line in raw.replace("\r\n", "\n").split("\n"):
        h = _HEAD.match(line.strip())
        if h:
            head = h.group(1).strip()
            if line.startswith("# ") and not title:
                title = head
                continue
            skip = bool(_SKIP_SECTION.search(head))
            if not skip:
                num = re.search(r"chapter\s+(\d+)", head, re.I)
                name = re.split(r"\s+[—–-]\s+", head, maxsplit=1)
                chapters.append(Chapter(len(chapters), name[-1].strip() if num else head, int(num.group(1)) if num else None))
                current = len(chapters) - 1
            continue
        s = line.strip()
        if skip or not s or s.startswith(("**", "|", "---", ">")) or current is None:
            continue
        paras.append((current, s))
    if not subject:
        m = re.search(r"[—–-]\s*([A-Z][a-z]+ [A-Z][a-z]+)", title or "")
        subject = m.group(1) if m else ""
    sentences = []
    for pi, (ci, ptext) in enumerate(paras):
        for a, b in T.split_sentences(ptext):
            st = ptext[a:b].strip()
            if st:
                sentences.append(Sentence(len(sentences), ci, pi, st, words=len(T.tokens(st)), question=st.rstrip("\"”'’ ").endswith("?")))
    story = Story(title, subject, chapters, sentences, {}, reference)
    _people(story)
    _dates(story)
    _orgs_places(story)
    _claims(story)
    return story


def _people(story: Story):
    people: dict[str, Person] = {}
    name = r"([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2})"
    roles = "|".join(sorted((re.escape(r) for r in ROLE_TITLES), key=len, reverse=True))
    fam = "|".join(FAMILY)
    if story.subject:
        people[story.subject] = Person(story.subject, "subject", {story.subject.split()[0], story.subject.split()[-1]})
    for s in story.sentences:
        for m in re.finditer(rf"\b({roles})\s+{name}", s.text):
            full = m.group(2)
            if full not in people:
                people[full] = Person(full, m.group(1), {full.split()[-1]})
            elif not people[full].role:
                people[full].role = m.group(1)
        for m in re.finditer(rf"\b(?:his|her|their|the)\s+({fam}),\s+{name}", s.text):
            full = m.group(2)
            people.setdefault(full, Person(full, m.group(1), {full.split()[-1], full.split()[0]}))
        for m in re.finditer(rf"{name}\s*,\s+(?:the|a|an)?\s*({roles})\b", s.text):
            people.setdefault(m.group(1), Person(m.group(1), m.group(2), {m.group(1).split()[-1]}))
    # a surname shared by two people (Javits / Thomas Frimpong) is not an alias for either
    counts: dict[str, int] = {}
    for p in people.values():
        for a in p.aliases:
            counts[a] = counts.get(a, 0) + 1
    for p in people.values():
        p.aliases = {a for a in p.aliases if counts[a] == 1}
    story.people = people
    for s in story.sentences:
        found = []
        for p in people.values():
            if p.name in s.text or any(re.search(rf"\b{re.escape(a)}\b", s.text) for a in p.aliases):
                found.append(p.name)
        s.people = found


_MONTH_RE = r"(January|February|March|April|May|June|July|August|September|October|November|December)"


def _dates(story: Story):
    last = None
    ref = story.reference
    for s in story.sentences:
        out = []
        for m in re.finditer(rf"\b{_MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,\s*(\d{{4}}))?", s.text):
            month, day = T.MONTHS[m.group(1).lower()], int(m.group(2))
            year = int(m.group(3)) if m.group(3) else (ref.year if month <= ref.month else ref.year - 1)
            try:
                out.append(DateRef(dt.date(year, month, day), m.group(0), m.start(), m.end()))
            except ValueError:
                pass
        rel = [(r"\b[Tt]hat day\b", 0), (r"\b[Tt]he same day\b", 0), (r"\b[Aa] day later\b", 1), (r"\b[Tt]he (?:following|next) day(?:'s|’s)?", 1),
               (r"\b[Tt]he day before\b", -1), (r"\b[Aa] week later\b", 7)]
        anchor = last
        for pat, delta in rel:
            for m in re.finditer(pat, s.text):
                prior = [d for d in out if d.start < m.start()]
                base = prior[-1].date if prior else anchor
                if base:
                    out.append(DateRef(base + dt.timedelta(days=delta), m.group(0), m.start(), m.end(), relative=f"{delta:+d} day from {base.isoformat()}"))
        out.sort(key=lambda d: d.start)
        s.dates = out
        if out:
            last = out[-1].date


def _orgs_places(story: Story):
    for s in story.sentences:
        orgs = [m for m in MEDIA if m in s.text]
        for m in re.finditer(rf"\b(?:the\s+)?((?:[A-Z][a-z]+\s)*{ORG_SUFFIX})\b", s.text):
            orgs.append(m.group(1).strip())
        if re.search(r"\bpolice\b", s.text, re.I):
            orgs.append("police")
        if re.search(r"\bprosecutors?\b", s.text, re.I):
            orgs.append("prosecutors")
        s.orgs = list(dict.fromkeys(orgs))
        places = []
        for m in re.finditer(rf"\b((?:(?:East|West|North|South)\s)?(?:St\.\s)?(?:[A-Z0-9][A-Za-z0-9]+\s){{0,3}}{PLACE_SUFFIX})", s.text):
            places.append(m.group(1).strip())
        for m in re.finditer(r"\b(?:in|into|near|at|to|by|from)\s+((?:the\s)?(?:Bronx|Manhattan|Brooklyn|Queens|Harlem|[A-Z][a-z]+ City))\b", s.text):
            places.append(m.group(1).replace("the ", "").strip())
        places = [re.sub(r"^(?:The|A|At|On|In|Near|By)\s+", "", p) for p in places]
        s.places = list(dict.fromkeys(p for p in places if len(p.split()) > 1 or p in {"Bronx", "Manhattan", "Brooklyn", "Queens", "Harlem"}))


def _family_member(story: Story, phrase: str):
    for f in FAMILY:
        if re.search(rf"\b{f}\b", phrase):
            for p in story.people.values():
                if p.role == f:
                    return p.name
            return f"his {f}" if "his" in phrase.lower() or "’s" in phrase or "'s" in phrase else phrase
    return None


def _claims(story: Story):
    last_person = None
    fam = "|".join(FAMILY)
    for s in story.sentences:
        taken = []
        for m in re.finditer(rf"(?P<src>(?:[A-Z][\w’'-]*(?:’s|'s)\s+|[Hh]is\s+|[Hh]er\s+|[Tt]heir\s+)(?:{fam})(?:\s+and\s+(?:his|her)\s+(?:{fam}))?|(?:[A-Z][\w.'’-]*\s){{0,5}}[A-Z][\w.'’-]*|[Hh]e|[Ss]he|[Tt]hey|[Pp]olice|[Pp]rosecutors|[Tt]he department)\s*(?:,[^,]{{3,60}},\s*)?(?:had\s+|also\s+)?(?P<verb>{ATTRIB_VERBS})\b(?:\s+that)?\s*(?P<body>[^;]*)", s.text):
            if any(a < m.start() < b for a, b in taken):
                continue  # a claim inside another's words ("he believed" in "X said he believed")
            src = m.group("src").strip()
            if src in {"The", "A", "An", "This", "That"}:
                continue
            member = _family_member(story, src)
            if member:
                src = member
            elif src.lower() in {"he", "she", "they"}:
                src = last_person or src
            else:
                for p in story.people.values():
                    if p.name in src or any(a == src.split()[-1] for a in p.aliases):
                        src = p.name
                        break
            body = m.group("body").strip().rstrip(".?!")
            via = ""
            relay = re.match(r"(prosecutors|police|investigators|officials|detectives|the family|doctors|the club|the team)\s+(?:had\s+)?(?:told|informed|assured)\s+[\w\s]{2,30}?\s+(?:that\s+)?(?:they|it|he|she)\s+(.*)$", body, re.I)
            if relay:
                via, src, body = src, relay.group(1), relay.group(2)
            s.claims.append(Claim(src, m.group("verb"), body, bool(NEG.search(body)), m.start(), m.end(), via))
            taken.append((m.start(), m.end()))
        if s.people:
            last_person = s.people[-1]
