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
    "Chief of Detectives", "Bronx District Attorney", "Assistant District Attorney", "District Attorney", "Police Commissioner", "Commissioner",
    "Assistant State Attorney", "State Attorney", "Attorney General", "Deputy Chief", "Police Chief", "Chief", "Major", "Lieutenant",
    "Special Agent", "Agent", "Deputy", "Inspector", "Superintendent", "Medical Examiner", "Coroner", "Defense attorney", "defense attorney",
    "Prosecutor",
    "Mayor", "President", "Governor", "Senator", "Judge", "Justice", "attorney", "lawyer", "Detective", "Officer",
    "Sergeant", "Captain", "Sheriff", "Coach", "coach", "manager", "Manager", "promoter", "referee", "Referee",
    "captain", "principal", "prosecutor",
]
FAMILY = ["father", "mother", "sister", "brother", "son", "daughter", "uncle", "aunt", "cousin", "wife", "husband", "grandmother", "grandfather"]
MEDIA = ["Daily News", "New York Post", "CBS New York", "NBC New York", "ABC7", "FOX 5", "PIX11", "Associated Press", "Reuters",
         "BBC", "ESPN", "Sky Sports", "The Athletic", "The Guardian", "New York Times"]
ORG_SUFFIX = r"(?:Department of [A-Z][a-z]+|Ministry|Department|Office|Police|NYPD|FBI|Court|League|Federation|Association|Club|Council|Commission)"
PLACE_SUFFIX = r"(?:Street|St\.|Avenue|Ave\.|Road|Boulevard|Park|Place|station|Station|Court|Hospital|School|Stadium|Arena|Garden|Bridge|Square|Hall)"
ATTRIB_VERBS = r"(?:said|says|told|reported|recalled|called|characterized|described|announced|believes|believed|added|confirmed|denied|claimed|insisted|testified|outlined|argued|disputed|admitted|maintained|contended|alleged|acknowledged)"
NEG = re.compile(r"\b(?:not|no(?!\.\s*\d)|never|none|without|n't|nobody|nothing|neither|nor)\b", re.I)


@dataclass
class DateRef:
    date: dt.date
    text: str          # as written ("October 29", "That day", "the following day's")
    start: int         # within the sentence
    end: int
    relative: str = ""  # "" absolute, else how it was resolved
    back: bool = False  # a look back ("231 days since April 17"), not where the narration is now


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
    span: tuple = (0, 0)  # (start, end) characters within its paragraph


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
    of: str = ""        # a relative: whose ("Moore" in "Moore's mother, Tabia Aska"); "" = the subject's / unstated


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
            if s.dates and re.search(r"\b(shot|shooting|killed|murder|stabbed|died|final|fight|match|bout|gunfire)\b", s.text, re.I):
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
    return build(chapters, paras, title, subject, reference)


def build(chapters: list, paras: list, title: str = "", subject: str = "", reference: dt.date | None = None) -> Story:
    """The story model from chapters ([Chapter]) and paragraphs ([(chapter index, text)]): how the app
    builds it from the narration on its timeline, so every sentence maps back to timed words."""
    reference = reference or dt.date(dt.date.today().year, 12, 31)
    sentences = []
    for pi, (ci, ptext) in enumerate(paras):
        for a, b in T.split_sentences(ptext):
            raw = ptext[a:b]
            st = raw.strip()
            if st:
                lead = len(raw) - len(raw.lstrip())
                sentences.append(Sentence(len(sentences), ci, pi, st, words=len(T.tokens(st)), question=st.rstrip("\"”'’ ").endswith("?"),
                                          span=(a + lead, a + lead + len(st))))
    story = Story(title, subject, chapters, sentences, {}, reference)
    _people(story)
    _dates(story)
    _orgs_places(story)
    _claims(story)
    return story


_TOK = r"(?!(?:Sr|Jr)\b)[A-Z][a-z]+(?:[A-Z][a-z]+)?(?:[’'][A-Z][a-z]+)?"          # Kenny, JoQuetta, O’Neil
NAME = rf"((?:[A-Z]\.\s)?{_TOK}(?:\s[A-Z]\.)?(?:\s{_TOK}){{1,2}}(?:\s(?:Sr|Jr)\.)?)"   # J. Logan Murphy, Michael Baldwin Sr.
_NOT_FIRST = {"The", "This", "That", "These", "Those", "Under", "After", "Before", "When", "While", "At", "In", "On", "As", "If", "For",
              "Subscribe", "Chapter", "New", "North", "South", "East", "West", "Mayor", "Police", "Officers", "Detectives", "Prosecutors",
              "Judge", "Chief", "State", "Defense", "Assistant", "Deputy", "Major", "Florida", "Tampa", "Bronx", "Manhattan", "Brooklyn",
              "Queens", "Ghana", "United", "Bible", "Moms", "Crime", "Raymond", "Memorial", "Hillsborough", "Lowry", "Busch", "Rome",
              "Crotona", "Freeman", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Monday", "Tuesday", "Everytown",
              "Department", "Office", "His", "Her", "Their", "You", "Now", "Later", "Then", "Among", "Alongside", "According", "During"}
_NOT_LAST = {"Times", "School", "Police", "Department", "Office", "Court", "Center", "Centre", "Street", "Avenue", "Boulevard", "Park",
             "County", "Division", "Force", "Stoppers", "Action", "Safety", "Patrol", "News", "Post", "Tech", "Stadium", "Church",
             "Fellowship", "Terrace", "High", "Middle", "Attorney", "General", "Timeline", "Station", "Place", "Road", "Hospital", "Bay",
             "City", "States", "Fund", "Prep", "Preparatory", "Task", "Marshals", "Justice", "Detention", "Jail", "Part", "Field"}
_MONTHS_CAP = {m.capitalize() for m in T.MONTHS}


def _plain(full):
    return re.sub(r"\s(?:Sr|Jr)\.$", "", full)


def _aliases(full, first=False):
    toks = [t for t in _plain(full).split() if not re.fullmatch(r"[A-Z]\.", t)]
    return {toks[-1], toks[0]} if first and len(toks) > 1 else {toks[-1]}


def _people(story: Story):
    people: dict[str, Person] = {}
    name = NAME
    roles = "|".join(sorted((re.escape(r) for r in ROLE_TITLES), key=len, reverse=True))
    fam = "|".join(FAMILY)
    if story.subject:
        people[story.subject] = Person(story.subject, "subject", {story.subject.split()[0], story.subject.split()[-1]})

    def known(full):
        return full in people or any(_plain(full) == _plain(n) for n in people)

    for s in story.sentences:
        for m in re.finditer(rf"\b({roles})\s+{name}", s.text):
            full = m.group(2)
            if full not in people:
                people[full] = Person(full, m.group(1), _aliases(full))
            elif not people[full].role:
                people[full].role = m.group(1)
        # "his father, Thomas Frimpong" / "Jevario’s mother, Jasmine Baldwin, and grandfather, Michael Baldwin Sr."
        for m in re.finditer(rf"\b(?:(?P<pos>[Hh]is|[Hh]er|[Tt]heir|[Tt]he)|(?P<own>{_TOK})[’']s)\s+(?P<rel>{fam}),\s+{name}", s.text):
            full = m.group(4)
            people.setdefault(full, Person(full, m.group("rel"), _aliases(full, True), m.group("own") or ""))
            tail = s.text[m.end():]
            for m2 in re.finditer(rf"^,?\s+and\s+(?:(?:his|her|their)\s+)?(?P<rel>{fam}),\s+{name}", tail):
                people.setdefault(m2.group(2), Person(m2.group(2), m2.group("rel"), _aliases(m2.group(2), True), m.group("own") or ""))
        for m in re.finditer(rf"{name}\s*,\s+(?:the|a|an)?\s*({roles})\b", s.text):
            people.setdefault(m.group(1), Person(m.group(1), m.group(2), _aliases(m.group(1))))
    # a professional named by surname only ("Defense attorney Sinardi"), when that surname is nobody else's
    for s in story.sentences:
        for m in re.finditer(rf"\b({roles})\s+({_TOK})\b(?!\s+[A-Z])", s.text):
            one = m.group(2)
            if one in _MONTHS_CAP or any(one in p.aliases or one in p.name.split() for p in people.values()):
                continue
            people.setdefault(one, Person(one, m.group(1), {one}))
    # anyone else the narration names in full at least twice ("Jahmir Moore"): no role, but a person
    counts: dict[str, int] = {}
    for s in story.sentences:
        for m in re.finditer(rf"(?<![\w’'-]){name}", s.text):
            full = m.group(1)
            toks = _plain(full).split()
            if toks[0] in _NOT_FIRST or toks[0] in _MONTHS_CAP or toks[-1] in _NOT_LAST or any(t in _MONTHS_CAP for t in toks):
                continue
            if re.search(r"\b(?:the|The)\s+$", s.text[:m.start()]):
                continue
            counts[full] = counts.get(full, 0) + 1
    for full, n in counts.items():
        if n >= 2 and not known(full):
            people[full] = Person(full, "", _aliases(full, True))
    # a surname shared by two people (Javits / Thomas Frimpong; Jasmine / Michael Baldwin Sr.) is not an alias for either
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


def _year_for(month, day, last, back, ref):
    """A date written without its year: the latest one up to the reference (recording) date — unless the
    narration has given a year and that lands more than ~13 months from where the story is (`last`): a case from
    2024 told in 2026 states its year once ("April 17, 2024 ... On April 22 ..."). Then the nearest such date to
    `last`, never after it for a look back ("231 days since April 17")."""
    year = ref.year if month <= ref.month else ref.year - 1
    if last is None or not last[1]:
        return year
    try:
        if abs((dt.date(year, month, day) - last[0]).days) <= 400 and not (back and dt.date(year, month, day) > last[0]):
            return year
    except ValueError:
        return year
    best = None  # (distance, date)
    for y in (last[0].year - 1, last[0].year, last[0].year + 1):
        try:
            d = dt.date(y, month, day)
        except ValueError:
            continue
        if back and d > last[0]:
            continue
        # the narration moves forward: the next such date (or the same day); a look back, the previous one
        key = (last[0] - d).days if back else ((d - last[0]).days if d >= last[0] else 10 ** 6 + (last[0] - d).days)
        if best is None or key < best[0]:
            best = (key, d)
    best = best[1] if best else None
    return best.year if best else last[0].year


def _dates(story: Story):
    last = None         # (date, the narration has given a year)
    ref = story.reference
    for s in story.sentences:
        out = []
        for m in re.finditer(rf"\b{_MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,\s*(\d{{4}}))?", s.text):
            month, day = T.MONTHS[m.group(1).lower()], int(m.group(2))
            back = bool(re.search(r"\b(?:since|days after|weeks after|months after)\s+$", s.text[:m.start()]))
            year = int(m.group(3)) if m.group(3) else _year_for(month, day, last, back, ref)
            try:
                out.append(DateRef(dt.date(year, month, day), m.group(0), m.start(), m.end(), back=back))
            except ValueError:
                pass
        rel = [(r"\b[Tt]hat day\b", 0), (r"\b[Tt]he same day\b", 0), (r"\b[Aa] day later\b", 1), (r"\b[Tt]he (?:following|next) (?:day|morning|afternoon|evening|night)(?:'s|’s)?", 1),
               (r"\b[Tt]he day before\b", -1), (r"\b[Aa] week later\b", 7)]
        anchor = last[0] if last else None
        for pat, delta in rel:
            for m in re.finditer(pat, s.text):
                prior = [d for d in out if d.start < m.start() and not d.back]
                base = prior[-1].date if prior else anchor
                if base:
                    out.append(DateRef(base + dt.timedelta(days=delta), m.group(0), m.start(), m.end(), relative=f"{delta:+d} day from {base.isoformat()}"))
        out.sort(key=lambda d: d.start)
        s.dates = out
        now = [d for d in out if not d.back]
        if now:
            had_year = bool(last and last[1]) or any(re.search(r",\s*\d{4}$", d.text) for d in now)
            last = (now[-1].date, had_year)


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
            own = re.match(r"([A-Z][\w-]*)[’']s\b", phrase)
            for p in story.people.values():
                if p.role == f and (not own or not p.of or own.group(1) == p.of):
                    return p.name
            return f"his {f}" if "his" in phrase.lower() or "’s" in phrase or "'s" in phrase else phrase
    return None


def _claims(story: Story):
    last_person = None
    fam = "|".join(FAMILY)
    for s in story.sentences:
        taken = []
        for m in re.finditer(rf"(?P<src>(?:[A-Z][\w’'-]*(?:’s|'s)\s+|[Hh]is\s+|[Hh]er\s+|[Tt]heir\s+)(?:{fam})(?:\s+and\s+(?:his|her)\s+(?:{fam}))?|(?:[A-Z][\w.'’-]*\s){{0,5}}[A-Z][\w.'’-]*|(?:[Tt]he|[Hh]is|[Hh]er|[Tt]heir)\s+defen[cs]e(?:\s+attorneys?)?|[Hh]e|[Ss]he|[Tt]hey|[Pp]olice|[Pp]rosecutors|[Tt]he department)\s*(?:,[^,]{{3,60}},\s*)?(?:had\s+|also\s+)?(?P<verb>{ATTRIB_VERBS})\b(?:\s+that)?\s*(?P<body>[^;]*)", s.text):
            if any(a < m.start() < b for a, b in taken):
                continue  # a claim inside another's words ("he believed" in "X said he believed")
            src = m.group("src").strip()
            if src in {"The", "A", "An", "This", "That"}:
                continue
            member = _family_member(story, src)
            if re.fullmatch(r"(?:the|his|her|their)\s+defen[cs]e(?:\s+attorneys?)?", src, re.I):
                src = "the defense"
            elif member:
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
