"""The narration: the production script read into a story, with a time for every word.

The words come from the script, always. Timings only say *when* each script word is spoken: they come from an
SRT, a word list (JSON), the narration audio, or (with nothing else) an estimate. A transcript that spells a name
differently ("more" for "Moore") still times the script's word; it never replaces it.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .cinegfx import story as S
from . import timings as TM


@dataclass
class Narration:
    story: object                 # cinegfx Story
    words: list                   # [{"w": script word (whitespace token), "t": start s, "e": end s}]
    times: list                   # per sentence: (t0, t1, [word index ...])
    timing: dict = field(default_factory=dict)   # {"source": srt|words|audio|estimated, "matched": 0..1, "notes": [...]}

    def sentence_words(self, i):
        return [self.words[k] for k in self.times[i][2]]


_NOT_NAMES = {"The", "This", "That", "Chief", "Judge", "Police", "Under", "After", "Before", "When", "At", "In", "On",
              "Subscribe", "Chapter", "State", "City", "County", "Department", "Office", "Court", "New", "North", "South",
              "East", "West", "Street", "Avenue", "Mayor", "Detective", "Officer", "Attorney", "District", "Assistant"}


def _subject(text, topic=""):
    """Whose story it is: `topic` when the narration uses that name, else the person it names most
    (Casefile: cinematic._subject)."""
    months = set(S.T.MONTHS) | {m.capitalize() for m in S.T.MONTHS}
    names = {}
    for m in re.finditer(r"\b([A-Z][a-z]+)\s([A-Z][a-z]+)\b", text):
        a, b = m.group(1), m.group(2)
        if a in _NOT_NAMES or b in _NOT_NAMES or a in months or b in months:
            continue
        names[f"{a} {b}"] = names.get(f"{a} {b}", 0) + 1
    t = re.sub(r"\s+", " ", str(topic or "")).strip()
    if t in names:
        return t
    if not names:
        return ""
    score = {n: c * 2 + len(re.findall(rf"\b{re.escape(n.split()[0])}\b", text)) for n, c in names.items()}
    return max(score, key=lambda n: (score[n], n))


def read_script(raw: str, subject: str = "", title: str = ""):
    """The story from a production script (Markdown: `# Title`, `## Chapter 1 — Name` headings, plain paragraphs
    of narration; lines starting with **, |, --- or > and sections such as "Sources" or "Producer notes" are not
    narration). The subject is the name after the dash in the title, `subject`, or the person named most."""
    st = S.parse_script(raw, title=title, subject=subject)
    if not st.subject:
        st.subject = _subject(" ".join(s.text for s in st.sentences), subject)
    return st


def script_words(story):
    """The narration's words in order (whitespace tokens of each sentence) and, per sentence, their indexes."""
    words, per = [], []
    for s in story.sentences:
        idx = []
        for m in re.finditer(r"\S+", s.text):
            idx.append(len(words))
            words.append(m.group(0))
        per.append(idx)
    return words, per


def narration(raw_script: str, srt: str | None = None, words_json=None, audio: str | None = None, subject: str = "",
              offset: float = 0.0, wpm: float = 150.0) -> Narration:
    """Read the script and time it. Give one of: `srt` (SRT text), `words_json` (parsed JSON word list),
    `audio` (path to the narration recording); with none, the times are estimated at `wpm` words a minute.
    `offset`: seconds to add to every time (where the narration starts on the editor's timeline)."""
    st = read_script(raw_script, subject=subject)
    toks, per = script_words(st)
    if srt is not None:
        times, info = TM.from_srt(toks, srt)
    elif words_json is not None:
        times, info = TM.from_words(toks, words_json)
    elif audio:
        times, info = TM.from_audio(toks, audio)
    else:
        times, info = TM.estimate(toks, wpm=wpm)
    words = [{"w": w, "t": round(t + offset, 3), "e": round(e + offset, 3)} for w, (t, e) in zip(toks, times)]
    sent = [((words[idx[0]]["t"], words[idx[-1]]["e"], idx) if idx else (None, None, [])) for idx in per]
    return Narration(st, words, sent, info)


def reference_date(story) -> dt.date:
    return story.reference
