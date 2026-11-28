"""Narration -> editorial elements, synced to word timings (never to fixed durations or SRT boundaries).

Input is the narration as segments, each with its script text and word timings: the script is the truth
for WHAT is said (spelling, names), the recogniser gives WHEN (autotiming.align maps one onto the other).
Every element carries the exact word times its parts land on, and nothing is shown that the narrator does
not say: numbers, dates and names are read from the script words, never looked up or invented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
            "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
            "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
            "twentieth": 20, "thirtieth": 30}
FLASHBACK = re.compile(r"\b(we (have|need) to go back|let'?s go back|rewind|years earlier|but first)\b", re.I)
SMALL = {"a", "an", "the", "of", "in", "at", "on", "to", "and", "for", "by", "with"}


@dataclass
class Word:
    text: str          # as written in the script ("Twenty-one", "d'Or,")
    s: float           # absolute start (s)
    e: float           # absolute end (s)
    seg: int = 0       # narration segment
    sent: int = 0      # sentence index (global)

    @property
    def key(self) -> str:
        return re.sub(r"[^a-z0-9'\-]+", "", self.text.lower().replace("’", "'"))

    @property
    def bare(self) -> str:
        return re.sub(r"[^a-z0-9]+", "", self.text.lower())

    @property
    def ends_sentence(self) -> bool:
        return bool(re.search(r"[.?!](\W*)$", self.text)) and not self.text.endswith("...")

    @property
    def cap(self) -> bool:
        return self.text[:1].isupper()


@dataclass
class Element:
    family: str                      # name | headline | numbered | minimal | label | cumulative | impact
    t_in: float
    t_out: float
    data: dict = field(default_factory=dict)
    why: str = ""

    def __repr__(self):
        return f"<{self.family} {self.t_in:.2f}-{self.t_out:.2f} {self.data}>"


# ---------------------------------------------------------------- words
def _canon(word: str) -> str:
    """Matching key that treats '1.' and 'One.', '21' and 'Twenty-one', '6th' and 'sixth' as the same word."""
    w = re.sub(r"[^a-z0-9\-]+", "", word.lower().replace("’", "'").replace("'", ""))
    r = number_at([Word(w, 0, 0)], 0)
    if r and r[1] == 1:
        return str(r[0])
    return w.replace("-", "")


def align_words(script: str, heard: list[dict]) -> list[dict]:
    """Script words with recogniser times. Like autotiming.align, but number-aware and with the
    recogniser's split hyphen tokens ('Twenty' '-one') joined first."""
    import difflib
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import autotiming
    merged = []
    for h in heard:
        if merged and h["word"].strip().startswith("-"):
            merged[-1] = {**merged[-1], "word": merged[-1]["word"].strip().rstrip(",.") + h["word"].strip(), "end": h["end"]}
        else:
            merged.append(dict(h))
    sw = autotiming.script_words(script)
    a, b = [_canon(w) for w in sw], [_canon(h["word"]) for h in merged]
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [{"word": sw[i1 + k], "start": merged[j1 + k]["start"], "end": merged[j1 + k]["end"]} for k in range(i2 - i1)]
        elif tag == "replace":
            out += autotiming._spread(sw[i1:i2], merged[j1]["start"], merged[j2 - 1]["end"])
        elif tag == "delete":
            start = out[-1]["end"] if out else 0.0
            end = merged[j1]["start"] if j1 < len(merged) else start + 0.25 * (i2 - i1)
            out += autotiming._spread(sw[i1:i2], start, max(end, start + 0.02 * (i2 - i1)))
    return out


def timeline(segments) -> list[Word]:
    """segments: [{"text": script, "at": offset_s, "heard": [{"word","start","end"}...]}] -> absolute words."""
    out, sent = [], 0
    for k, sg in enumerate(segments):
        words = align_words(sg["text"], sg["heard"])
        for w in words:
            out.append(Word(w["word"], round(sg["at"] + w["start"], 3), round(sg["at"] + w["end"], 3), k, sent))
            if out[-1].ends_sentence:
                sent += 1
        if out and not out[-1].ends_sentence:
            sent += 1
    return out


def sentences(words: list[Word]) -> list[list[Word]]:
    out: dict[int, list[Word]] = {}
    for w in words:
        out.setdefault(w.sent, []).append(w)
    return [out[k] for k in sorted(out)]


# ---------------------------------------------------------------- spoken numbers
def number_at(ws: list[Word], i: int, year_ok: bool = False):
    """(value, n_words, ordinal) for a spoken number starting at ws[i], else None.
    'twenty-two', 'eighty-eight', 'two thousand and nine', 'twenty ten' (year_ok), '47', 'sixth'."""
    if i >= len(ws):
        return None
    k = ws[i].key.strip("'-.,")
    digits = re.fullmatch(r"(\d+)(st|nd|rd|th)?", re.sub(r"[^0-9a-z]", "", k))
    if digits:
        return int(digits.group(1)), 1, bool(digits.group(2))

    def one(word: str):
        parts = [p for p in word.split("-") if p]
        if not parts:
            return None
        if len(parts) == 1:
            p = parts[0]
            if p in UNITS:
                return UNITS[p], False
            if p in TENS:
                return TENS[p], False
            if p in ORDINALS:
                return ORDINALS[p], True
            return None
        if len(parts) == 2 and parts[0] in TENS:
            if parts[1] in UNITS and UNITS[parts[1]] < 10:
                return TENS[parts[0]] + UNITS[parts[1]], False
            if parts[1] in ORDINALS and ORDINALS[parts[1]] < 10:
                return TENS[parts[0]] + ORDINALS[parts[1]], True
        return None

    first = one(re.sub(r"[^a-z\-]", "", k))
    if first is None:
        return None
    v, ordinal = first
    n = 1
    nxt = lambda j: re.sub(r"[^a-z\-]", "", ws[j].key) if j < len(ws) else ""  # noqa: E731
    if nxt(i + 1) == "thousand" and not ordinal:
        v *= 1000
        n = 2
        j = i + 2
        if nxt(j) == "and":
            j += 1
        r = one(nxt(j)) if j < len(ws) else None
        if r and not r[1] and r[0] < 1000:
            v += r[0]
            n = j - i + 1
        return v, n, False
    if nxt(i + 1) == "hundred" and not ordinal:
        return v * 100, 2, False
    if year_ok and v in (19, 20) and not ws[i].text.rstrip().endswith((",", ".")):
        r = one(nxt(i + 1))
        if r and not r[1] and 10 <= r[0] < 100:
            return v * 100 + r[0], 2, False
    return v, n, ordinal


def clean(text: str) -> str:
    return re.sub(r"[.,;:!?…]+$", "", text.replace("...", "")).strip()


def upper_phrase(ws: list[Word]) -> str:
    return " ".join(clean(w.text) for w in ws).upper().replace("’", "'")


def spoken_to_digits(ws: list[Word], minutes: bool = False) -> tuple[str, list[tuple[str, float]]]:
    """Upper-case display text with spoken numbers written as digits ('twenty-five to thirty' -> '25–30'),
    plus per-token times for word-synced reveals."""
    toks, i = [], 0
    while i < len(ws):
        r = number_at(ws, i)
        if r and r[2] and minutes and i + r[1] < len(ws) and ws[i + r[1]].key.startswith("minute"):
            # "in the twenty-first minute" -> "21'"
            if len(toks) >= 2 and [t for t, _ in toks[-2:]] == ["IN", "THE"]:
                toks = toks[:-2]
            toks.append((f"{r[0]}'", ws[i].s))
            i += r[1] + 1
            continue
        if r and not r[2]:
            v, n, _ = r
            nxt = ws[i + n].key if i + n < len(ws) else ""
            if nxt == "to" and number_at(ws, i + n + 1):
                v2, n2, _ = number_at(ws, i + n + 1)
                toks.append((f"{v}–{v2}", ws[i].s))
                i += n + 1 + n2
                continue
            if minutes:
                toks.append((f"{v}'", ws[i].s))
                i += n
                if i < len(ws) and ws[i].key.startswith("minute"):
                    i += 1
                continue
            toks.append((str(v), ws[i].s))
            i += n
            continue
        toks.append((clean(ws[i].text).upper(), ws[i].s))
        i += 1
    toks = [(t, s) for t, s in toks if t]
    return " ".join(t for t, _ in toks), toks


# ---------------------------------------------------------------- detectors
def _is_name_sentence(sw):
    ws = [w for w in sw if clean(w.text)]
    return 2 <= len(ws) <= 3 and all(w.cap and clean(w.text).isalpha() for w in ws)


def _date_in(sw):
    """('6 APRIL 2010', first_word, last_word) or ('DECEMBER 2009', ...)"""
    for i, w in enumerate(sw):
        m = clean(w.text).lower()
        if m in MONTHS:
            day = None
            if i >= 2 and sw[i - 1].key == "of":  # "the sixth of April"
                r = number_at(sw, i - 2) or (number_at(sw, i - 3) if i >= 3 else None)
                if r and r[0] <= 31:
                    day = (r[0], sw[i - 2] if number_at(sw, i - 2) else sw[i - 3])
            y = number_at(sw, i + 1, year_ok=True)
            if y and y[0] >= 1850:
                last = sw[i + y[1]]
                text = f"{m.upper()} {y[0]}"
                first = w
                if day:
                    text = f"{day[0]} {text}"
                    first = day[1]
                    if sw.index(first) > 0 and sw[sw.index(first) - 1].key == "the":
                        first = sw[sw.index(first) - 1]
                return text, first, last
    return None


def _place_in(sw, start):
    """Capitalised words after 'at'/'in' (+'the') from `start`, e.g. 'at the Camp Nou' -> [Camp, Nou]."""
    for i in range(start, len(sw) - 1):
        if sw[i].key in ("at", "in"):
            j = i + 1 + (sw[i + 1].key == "the")
            out = []
            while j < len(sw) and sw[j].cap and clean(sw[j].text).isalpha():
                out.append(sw[j])
                if re.search(r"[,.;]$", sw[j].text):
                    break
                j += 1
            if out:
                return out
    return None


def _proper_after_verb(sw):
    """'Messi wins the Ballon d'Or, by ...' -> words of 'Ballon d'Or'."""
    for i, w in enumerate(sw):
        if w.key in ("wins", "won", "lifts", "lifted", "reaches", "reached", "claims", "claimed"):
            j = i + 1
            if j < len(sw) and sw[j].key == "the":
                j += 1
            out = []
            while j < len(sw) and (sw[j].cap or sw[j].key.startswith("d'") or sw[j].key in ("of", "de")):
                out.append(sw[j])
                if re.search(r"[,.;]$", sw[j].text):
                    break
                j += 1
            if out:
                return out
    return None


def _count_pairs(sw):
    """[(value, label_words, number_word)] for '<number> <noun...>' pairs."""
    out, i = [], 0
    while i < len(sw):
        r = number_at(sw, i)
        if r and not r[2] and r[0] >= 2:
            v, n, _ = r
            j = i + n
            if j < len(sw):
                if sw[j].key == "of" and j + 1 < len(sw) and sw[j + 1].key in ("them", "those", "these"):
                    lab = [x for x in sw[j + 2:]]  # "Thirty-four of them in La Liga" -> "IN LA LIGA"
                    out.append((v, lab, sw[i]))
                    break
                if sw[j].key not in SMALL and not number_at(sw, j):
                    lab = [sw[j]]
                    out.append((v, lab, sw[i]))
                    i = j + 1
                    continue
        i += 1
    return out


def analyse(words: list[Word]) -> list[Element]:
    S = sentences(words)
    els: list[Element] = []
    used = set()
    k = 0
    while k < len(S):
        sw = S[k]
        nxt = S[k + 1] if k + 1 < len(S) else []
        txt = " ".join(w.text for w in sw)
        # 1 player intro: a sentence that is only a name, opening a segment
        if _is_name_sentence(sw) and (k == 0 or S[k - 1][-1].seg != sw[0].seg):
            lines = [(clean(w.text).upper(), w.s) for w in sw]
            t_out = (nxt[0].s + 1.4) if nxt else sw[-1].e + 1.5
            els.append(Element("name", sw[0].s, t_out, {"lines": lines}, "a sentence that is only a name opens the story"))
            used.add(k)
            k += 1
            continue
        # 3 numbered narrative points: lone number sentences 1,2,3...
        if len(sw) == 1 and number_at(sw, 0) and number_at(sw, 0)[0] == 1:
            items, j = [], k
            minutes = False
            while j + 1 < len(S) and len(S[j]) == 1 and number_at(S[j], 0) and number_at(S[j], 0)[0] == len(items) + 1:
                lab = S[j + 1]
                minutes = minutes or any(w.key.startswith("minute") for w in lab)
                items.append((number_at(S[j], 0)[0], S[j][0], lab))
                j += 2
            if len(items) >= 3:
                rows = []
                for v, nw, lab in items:
                    text, toks = spoken_to_digits(lab, minutes=minutes)
                    rows.append({"n": v, "t": nw.s, "label": text, "tokens": toks, "end": lab[-1].e})
                els.append(Element("numbered", items[0][1].s, rows[-1]["end"] + 0.7, {"items": rows},
                                   f"{len(items)} spoken numbers in sequence, each followed by its point"))
                used.update(range(k, j))
                k = j
                continue
        # 4 flashback / historical transition
        if FLASHBACK.search(txt):
            parts, cur = [], []
            for w in sw:
                cur.append(w)
                if w.text.endswith(("...", ",", ";")) or w.text.endswith("—"):
                    parts.append(cur)
                    cur = []
            if cur:
                parts.append(cur)
            lines = []
            for p in parts:
                t = upper_phrase(p)
                if p is parts[0] and len(parts) > 1:
                    t += "."
                lines.append({"text": t, "t0": p[0].s, "t1": p[-1].e})
            els.append(Element("minimal", sw[0].s, sw[-1].e + 1.0, {"lines": lines}, "the narration announces a step back in time"))
            used.add(k)
            k += 1
            continue
        # 5 date / season / venue / event labels
        d = _date_in(sw)
        if d:
            text, first, last = d
            lines = [{"text": text, "t": first.s}]
            same_seg = bool(nxt) and nxt[0].seg == sw[0].seg
            ev = _proper_after_verb(nxt) if same_seg else None
            short_place = same_seg and len([w for w in nxt if clean(w.text)]) <= 3 and all(
                w.cap and not number_at([w], 0) for w in nxt)
            inline = _place_in(sw, sw.index(last) + 1)
            if inline and not short_place and not ev:   # "... twenty ten, at the Camp Nou, ..."
                lines.append({"text": upper_phrase(inline), "t": inline[0].s})
                end = sw[-1].e + 1.0
            elif short_place:
                lines.append({"text": upper_phrase(nxt), "t": nxt[0].s})
                end = nxt[-1].e + 1.0
            elif ev:
                lines.append({"text": upper_phrase(ev), "t": ev[0].s})
                end = nxt[-1].e + 0.3
            else:
                end = sw[-1].e + 1.2
            els.append(Element("label", first.s, end, {"lines": lines}, "a date is spoken" + (" with its venue/event" if len(lines) > 1 else "")))
            used.add(k)
            if short_place or ev:
                used.add(k + 1)
                k += 2
            else:
                k += 1
            continue
        # 2 headline: "... is a one-man show." (+ a scoreline / question as the supporting statement)
        m = re.search(r"\b(?:is|was|becomes|became) (?:a|an|the) ([\w'\-]+(?: [\w'\-]+){0,2})[.!]$", txt)
        if m and len(sw) <= 9:
            nwords = len(m.group(1).split())
            head = sw[-nwords:]
            data = {"text": upper_phrase(head), "t": head[0].s}
            end = sw[-1].e + 1.6
            if nxt and (re.search(r"\?$", nxt[-1].text) or sum(1 for i in range(len(nxt)) if number_at(nxt, i)) >= 2):
                toks = []
                for i, w in enumerate(nxt):
                    r = number_at(nxt, i)
                    if r and not r[2]:
                        toks.append((str(r[0]), w.s))
                    elif w.cap and w.key not in ("by", "it"):
                        toks.append((clean(w.text).upper(), w.s))
                if re.search(r"\?$", nxt[-1].text):
                    toks = [(clean(w.text).upper(), w.s) for w in nxt]
                data["sub"] = toks
                end = nxt[-1].e + 0.6
                used.add(k + 1)
            els.append(Element("headline", head[0].s, end, data, "a short defining statement"))
            used.add(k)
            k += 2 if "sub" in data else 1
            continue
        # quote: "X said it best. A player like this only comes along every ..."
        if re.search(r"\bsaid it best\b|\bput it\b", txt) and nxt:
            who = clean(sw[0].text).upper()
            split = next((i for i, w in enumerate(nxt) if w.key in ("only", "is", "was", "comes", "will", "never")), None)
            if split and split >= 2:
                head, rest = nxt[:split], nxt[split:]
                sub, toks = spoken_to_digits(rest)
                els.append(Element("headline", head[0].s, nxt[-1].e + 2.2,
                                   {"text": upper_phrase(head), "t": head[0].s, "sub": toks, "sub_mode": "words",
                                    "attrib": f"— {who}", "attrib_t": nxt[-1].e + 0.2, "quote": True},
                                   "an attributed quote"))
                used.update({k, k + 1})
                k += 2
                continue
        # 7 single-statistic impact: "Four goals. One night."
        pairs = _count_pairs(sw)
        if len(sw) <= 3 and len(pairs) == 1:
            v, lab, nw = pairs[0]
            data = {"value": str(v), "t": nw.s, "label": upper_phrase(lab), "label_t": lab[0].s}
            end = sw[-1].e + 1.2
            if nxt and len(nxt) <= 3 and not _count_pairs(nxt):
                data["sub"] = upper_phrase(nxt)
                data["sub_t"] = nxt[0].s
                end = nxt[-1].e + 1.0
                used.add(k + 1)
            els.append(Element("impact", nw.s, end, data, "one number carries the sentence"))
            used.add(k)
            k += 2 if "sub" in data else 1
            continue
        # 6 layered cumulative statistics
        allp = pairs + (_count_pairs(nxt) if nxt and number_at(nxt, 0) else [])
        if len(pairs) >= 2 or (len(pairs) >= 1 and len(allp) >= 3):
            rows = [{"value": str(v), "label": upper_phrase(lab), "t": nw.s} for v, lab, nw in allp]
            last = (nxt if len(allp) > len(pairs) else sw)[-1]
            els.append(Element("cumulative", rows[0]["t"], last.e + 1.4, {"items": rows}, f"{len(rows)} figures build on each other"))
            used.add(k)
            if len(allp) > len(pairs):
                used.add(k + 1)
                k += 2
            else:
                k += 1
            continue
        k += 1
    # never overlap: an element ends a beat before the next begins
    els.sort(key=lambda e: e.t_in)
    for a, b in zip(els, els[1:]):
        if a.t_out > b.t_in - 0.15:
            a.t_out = max(a.t_in + 0.6, b.t_in - 0.15)
    return els
