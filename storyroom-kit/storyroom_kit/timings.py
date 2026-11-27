"""When each script word is spoken.

Every source is matched to the script's own words (folded to lower-case letters and digits) with a sequence
alignment, so missing, extra or misspelt transcript words do not shift anything: matched words take the
transcript's times, the rest are spread by syllables between their matched neighbours. Each function returns
([(start, end)] one per script word, info).
"""
from __future__ import annotations

import difflib
import json
import re

from .cinegfx import text as T
from .cinegfx import timing as CT


def key(word: str) -> str:
    return "".join(T.tokens(word))


def weight(word: str) -> float:
    k = key(word)
    return CT._weight(k) if k else 0.2


# ---------------------------------------------------------------- aligning

def align(script: list, heard: list):
    """script: [word]; heard: [(word, start, end)] in time order. Returns ([(start, end)] per script word, matched share)."""
    a = [key(w) for w in script]
    b = [key(w) for w, _, _ in heard]
    times = [None] * len(script)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    matched = 0
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            i, j = blk.a + k, blk.b + k
            if a[i]:
                times[i] = (float(heard[j][1]), float(heard[j][2]))
                matched += 1
    # a script word the transcript wrote as two ("fifteen year old" for "15-year-old") or misspelt: give the
    # unmatched run of script words the time between their matched neighbours, by syllables
    first = float(heard[0][1]) if heard else 0.0
    last = float(heard[-1][2]) if heard else 0.0
    i = 0
    while i < len(script):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(script) and times[j] is None:
            j += 1
        t0 = times[i - 1][1] if i > 0 else min(first, times[j][0] if j < len(script) else first)
        t1 = times[j][0] if j < len(script) else max(last, t0 + 0.35 * (j - i))
        _spread(script, times, i, j, t0, max(t0, t1))
        i = j
    total = sum(1 for x in a if x)
    return times, (matched / total if total else 0.0)


def _spread(script, times, i, j, t0, t1):
    ws = [weight(script[k]) for k in range(i, j)]
    tot = sum(ws) or 1.0
    t = t0
    for k, w in zip(range(i, j), ws):
        d = (t1 - t0) * w / tot
        times[k] = (round(t, 3), round(t + d, 3))
        t += d


def _info(source, matched, notes=None):
    notes = list(notes or [])
    if source != "estimated" and matched < 0.85:
        notes.append(f"Only {round(matched * 100)}% of the script's words were found in the timings: check that they are for this "
                     "script and this recording. Unmatched words were timed between their neighbours.")
    return {"source": source, "matched": round(matched, 3), "notes": notes}


# ---------------------------------------------------------------- sources

def _cue_words(cues):
    out = []
    for s, e, body in cues:
        toks = body.split()
        ws = [weight(w) for w in toks]
        tot = sum(ws) or 1.0
        t = s
        for w, wt in zip(toks, ws):
            d = (e - s) * wt / tot
            out.append((w, t, t + d))
            t += d
    return out


def from_srt(script: list, raw: str):
    """An SRT of the narration (captions from CapCut, Premiere, Descript, Whisper ...): words inside a caption are
    spread by syllables over it, then matched to the script."""
    cues = CT.parse_srt(raw)
    if not cues:
        raise ValueError("The SRT has no captions.")
    times, m = align(script, _cue_words(cues))
    return times, _info("srt", m)


def _num(x):
    return float(x) if x is not None else None


def word_list(data):
    """[(word, start, end)] in seconds from common word-timing JSON shapes:
    [{word|text|w, start|t, end|e}], {"words": [...]}, {"segments": [{"words": [...]}]} (Whisper), and times in
    milliseconds when the keys say so (start_ms / end_ms)."""
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    if isinstance(data, dict):
        if isinstance(data.get("words"), list):
            data = data["words"]
        elif isinstance(data.get("segments"), list):
            data = [w for s in data["segments"] for w in (s.get("words") or [])]
    if not isinstance(data, list):
        raise ValueError("Word timings: expected a list of {word, start, end}.")
    out = []
    for w in data:
        if isinstance(w, (list, tuple)) and len(w) >= 3:
            out.append((str(w[0]), float(w[1]), float(w[2])))
            continue
        if not isinstance(w, dict):
            continue
        text = w.get("word", w.get("text", w.get("w")))
        if text is None:
            continue
        if "start_ms" in w or "end_ms" in w:
            s, e = _num(w.get("start_ms")) / 1000, _num(w.get("end_ms")) / 1000
        else:
            s, e = _num(w.get("start", w.get("t"))), _num(w.get("end", w.get("e")))
        if s is None:
            continue
        out.append((str(text).strip(), s, e if e is not None else s + 0.2))
    out.sort(key=lambda x: x[1])
    return [x for x in out if x[0]]


def from_words(script: list, data):
    heard = word_list(data)
    if not heard:
        raise ValueError("The word timings are empty.")
    times, m = align(script, heard)
    return times, _info("words", m)


def from_audio(script: list, audio: str):
    """The narration recording: its pauses (FFmpeg silencedetect) are aligned to the script's punctuation and the
    words between them are spread by syllables (cinegfx timing.align). Good; an SRT or word list is better."""
    text = " ".join(script)
    pauses, dur = CT.detect_pauses(audio)
    tl = CT.align(text, dur, pauses)
    spans, pos = [], 0
    for w in script:
        spans.append((pos, pos + len(w)))
        pos += len(w) + 1
    times, k = [None] * len(script), 0
    for i, (a, b) in enumerate(spans):
        sub = []
        while k < len(tl.words) and tl.words[k].a < b:
            if tl.words[k].b > a:
                sub.append(tl.words[k])
            k += 1
        if sub:
            times[i] = (sub[0].start, sub[-1].end)
    for i in range(len(script)):  # a word with no letters ("—"): zero length at its neighbour
        if times[i] is None:
            t = times[i - 1][1] if i and times[i - 1] else 0.0
            times[i] = (t, t)
    return times, _info("audio", 1.0, ["Timed from the recording's pauses; an SRT or word timings are more exact."])


def estimate(script: list, wpm: float = 150.0):
    """No timings: an even reading at `wpm` words a minute with short pauses at commas and sentence ends.
    Good for planning; render with real timings so the reveals land on the spoken words."""
    per_unit = 60.0 / wpm / 2.0     # a typical word weighs about 2 (cinegfx timing._weight)
    times, t = [], 0.3
    for w in script:
        d = weight(w) * per_unit
        times.append((round(t, 3), round(t + d, 3)))
        t += d
        if re.search(r"[.?!][\"'”’)]*$", w):
            t += 0.35
        elif re.search(r"[,;:—–][\"'”’)]*$", w):
            t += 0.12
    return times, {"source": "estimated", "matched": 1.0,
                   "notes": [f"No timings given: estimated at {wpm:g} words a minute. Give the narration's SRT, word timings or "
                             "audio so each reveal lands on its spoken word."]}
