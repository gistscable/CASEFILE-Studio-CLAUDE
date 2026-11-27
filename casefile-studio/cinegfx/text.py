"""Text utilities shared by the story, timing and collection layers (no niche knowledge here)."""
from __future__ import annotations

import re
import unicodedata

WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?(?:[-.][A-Za-z0-9]+)*")
ABBREV = {"st", "no", "dr", "mr", "mrs", "ms", "jr", "sr", "u.s", "vs", "v", "gen", "lt", "sgt", "det", "capt", "ft", "mt", "ave", "blvd"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
MONTH_ABBR = {v: k[:3].upper() for k, v in MONTHS.items()}
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30}


def norm(s: str) -> str:
    """Lower-case ASCII with typographic quotes folded, for matching."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower()


def tokens(s: str) -> list[str]:
    return [m.group(0) for m in WORD.finditer(norm(s))]


def token_spans(s: str) -> list[tuple[str, int, int]]:
    """(normalised token, start, end) over the ORIGINAL string (same length after norm for our folds)."""
    n = norm(s)
    if len(n) != len(s):  # a fold changed the length: fall back to a per-character map
        out, i = [], 0
        for m in WORD.finditer(n):
            out.append((m.group(0), m.start(), m.end()))
        return out
    return [(m.group(0), m.start(), m.end()) for m in WORD.finditer(n)]


def syllables(word: str) -> int:
    """A rough syllable count (speech-time weight). Digits are read out: '17' ~ 3, '2025' ~ 5."""
    w = norm(word).strip("'")
    if not w:
        return 0
    if w.isdigit():
        if len(w) == 4:
            return 5
        return {1: 1, 2: 2}.get(len(w), 3) + (1 if len(w) == 2 and w[0] in "17" else 0)
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    if w.endswith("ed") and not w.endswith(("ted", "ded")) and n > 1:
        n -= 1
    return max(1, n)


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans (start, end) in `text`; abbreviations like 'St.' and 'No. 5' do not end one."""
    spans, start = [], 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in ".?!":
            j = i + 1
            while j < len(text) and text[j] in "\"'”’)":
                j += 1
            if j >= len(text) or text[j].isspace():
                word = re.findall(r"([A-Za-z.]+)$", text[start:i])
                prev = word[0].lower().rstrip(".") if word else ""
                nxt = text[j:].lstrip()[:1]
                if ch == "." and (prev in ABBREV or (len(prev) == 1 and prev.isalpha())) and (not nxt or not nxt.isupper() or prev in {"no", "st"}):
                    i += 1
                    continue
                if nxt and not (nxt.isupper() or nxt.isdigit() or nxt in "\"“'‘"):
                    i += 1
                    continue
                spans.append((start, j))
                while j < len(text) and text[j].isspace():
                    j += 1
                start = i = j
                continue
        i += 1
    if text[start:].strip():
        spans.append((start, len(text.rstrip())))
    return spans


def clauses(sentence: str) -> list[str]:
    """Split on ';' and on ', and' / ', but' joining independent clauses (kept simple)."""
    parts = []
    for chunk in re.split(r";\s*", sentence):
        parts += [p for p in re.split(r",\s+(?:and|but)\s+(?=the |a |an |police |his |her |their |[A-Z])", chunk) if p.strip()]
    return [p.strip().rstrip(".") for p in parts]


def cap_first(s: str) -> str:
    s = s.strip()
    return s[:1].upper() + s[1:] if s else s


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" ,;:")
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    return s
