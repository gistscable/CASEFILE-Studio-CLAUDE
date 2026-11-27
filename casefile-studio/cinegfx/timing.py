"""Narration timing: a word-level timeline for any narration, from the best evidence available.

* An SRT (what the app already produces / imports) gives cue windows; words inside a cue are spread by
  syllable weight.
* Without an SRT, the narration audio's own pauses (FFmpeg silencedetect) are aligned to the script's
  punctuation by a small monotonic DP, and words between anchors are spread by syllable weight.

Every graphic schedules its reveals against these word times, so a date lands when it is spoken,
not when a fixed template timer fires."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass

from . import text as T


@dataclass
class Word:
    text: str
    start: float
    end: float
    a: int          # char span in the narration text
    b: int


@dataclass
class Timeline:
    text: str
    words: list
    duration: float
    pauses: list    # [(start, end)] silences inside the narration

    def at_char(self, pos: int) -> float:
        """Time the word containing / following char `pos` starts."""
        for w in self.words:
            if w.b > pos:
                return w.start
        return self.duration

    def end_char(self, pos: int) -> float:
        """Time the word containing / preceding char `pos` ends."""
        last = 0.0
        for w in self.words:
            if w.a >= pos:
                break
            last = w.end
        return last

    def phrase(self, needle: str, after: int = 0):
        """(start, end, a, b) of the first occurrence of `needle` (case/quote-insensitive) at or after char `after`."""
        a = find(self.text, needle, after)
        if a < 0:
            return None
        b = a + len(needle)
        return self.at_char(a), self.end_char(b), a, b

    def next_pause_after(self, t: float, within: float = 2.5):
        for s, e in self.pauses:
            if s >= t - 0.02 and s - t <= within:
                return s, e
        return None


def find(hay: str, needle: str, after: int = 0) -> int:
    def fold(s):
        return s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').lower()
    return fold(hay).find(fold(needle), after)


def ffbin(name="ffmpeg"):
    return shutil.which(name) or name


def probe_duration(path: str) -> float:
    out = subprocess.run([ffbin("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def detect_pauses(path: str, noise_db: float = -38, min_len: float = 0.12):
    """[(start, end)] silences, end clamped to the file; one cheap decode, no loudness analysis."""
    r = subprocess.run([ffbin(), "-hide_banner", "-nostdin", "-i", path, "-af", f"silencedetect=n={noise_db}dB:d={min_len}", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    dur = probe_duration(path)
    out = []
    for i, s in enumerate(starts):
        out.append((max(0.0, s), ends[i] if i < len(ends) else dur))
    return out, dur


def _weight(word: str) -> float:
    w = T.norm(word)
    if re.fullmatch(r"\d+", w):          # spoken numbers are longer than their digits
        n = int(w)
        return 2.0 if n < 13 else 3.0 if n < 100 else 4.5
    return 0.55 + T.syllables(w)


def _boundary_strength(gap: str) -> float:
    if re.search(r"[.?!]", gap):
        return 1.0
    if re.search(r"[;:—–]", gap):
        return 0.8
    if "," in gap:
        return 0.6
    return 0.08


def align(text: str, duration: float, pauses: list) -> Timeline:
    spans = [(a, b) for _, a, b in T.token_spans(text)]
    if not spans:
        return Timeline(text, [], duration, pauses)
    lead = pauses[0][1] if pauses and pauses[0][0] <= 0.05 else 0.0
    inner = [(s, e) for s, e in pauses if s > lead + 0.05 and e < duration - 0.05]
    tail = next((s for s, e in pauses if e >= duration - 0.05 and s > lead), duration)
    weights = [_weight(text[a:b]) for a, b in spans]
    tot = sum(weights)
    # expected time of each word boundary if speech were uniform in syllables
    cum, acc = [], 0.0
    for w in weights[:-1]:
        acc += w
        cum.append(lead + (tail - lead - sum(e - s for s, e in inner)) * acc / tot)
    def strength(i):
        gap = text[spans[i][1]:spans[i + 1][0]]
        if gap.strip() == "." and T.norm(text[spans[i][0]:spans[i][1]]) in T.ABBREV:
            return 0.08  # "No. 5", "St. Barnabas"
        return _boundary_strength(gap)
    bounds = [(i, strength(i)) for i in range(len(spans) - 1)]
    # monotonic DP: pause k -> boundary j; cost = time distance (in s, after shifting by earlier pauses) - strength bonus
    K, J = len(inner), len(bounds)
    INF = 1e9
    best = [[INF] * (J + 1) for _ in range(K + 1)]
    back = [[-1] * (J + 1) for _ in range(K + 1)]
    for j in range(J + 1):
        best[0][j] = 0.0
    for k in range(1, K + 1):
        shift = sum(e - s for s, e in inner[:k - 1])
        ps = inner[k - 1][0]
        run_min, run_arg = INF, -1
        for j in range(1, J + 1):
            if best[k - 1][j - 1] < run_min:
                run_min, run_arg = best[k - 1][j - 1], j - 1
            bi, strength = bounds[j - 1]
            c = abs((cum[bi] + shift) - ps) - 1.6 * strength
            if run_min + c < best[k][j]:
                best[k][j], back[k][j] = run_min + c, run_arg
    anchors = {}
    if K:
        j = min(range(1, J + 1), key=lambda jj: best[K][jj])
        for k in range(K, 0, -1):
            anchors[bounds[j - 1][0]] = inner[k - 1]
            j = back[k][j]
    # place words: segments between anchors get syllable-proportional time
    words, seg_start, t0 = [], 0, lead
    cuts = sorted(anchors) + [len(spans) - 1]
    for c in cuts:
        seg = range(seg_start, c + 1)
        t1 = anchors[c][0] if c in anchors else tail
        sw = sum(weights[i] for i in seg) or 1.0
        t = t0
        for i in seg:
            d = (t1 - t0) * weights[i] / sw
            a, b = spans[i]
            words.append(Word(text[a:b], round(t, 3), round(t + d, 3), a, b))
            t += d
        t0 = anchors[c][1] if c in anchors else t1
        seg_start = c + 1
    return Timeline(text, words, duration, inner)


# ---------------------------------------------------------------- SRT

_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(raw: str):
    cues = []
    for block in re.split(r"\n\s*\n", raw.replace("\r\n", "\n").strip()):
        m = _TS.search(block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        s = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = " ".join(l.strip() for l in block[m.end():].strip().split("\n"))
        cues.append((s, e, re.sub(r"<[^>]+>", "", body)))
    return cues


def from_srt(raw: str, duration: float | None = None) -> Timeline:
    cues = parse_srt(raw)
    text, words, pauses = "", [], []
    prev_end = None
    for s, e, body in cues:
        if prev_end is not None and s - prev_end >= 0.12:
            pauses.append((prev_end, s))
        off = len(text) + (1 if text else 0)
        text = (text + " " + body) if text else body
        spans = [(a, b) for _, a, b in T.token_spans(body)]
        wts = [_weight(body[a:b]) for a, b in spans]
        tot = sum(wts) or 1.0
        t = s
        for (a, b), w in zip(spans, wts):
            d = (e - s) * w / tot
            words.append(Word(body[a:b], round(t, 3), round(t + d, 3), off + a, off + b))
            t += d
        prev_end = e
    return Timeline(text, words, duration or (cues[-1][1] if cues else 0.0), pauses)


def to_srt(tl: Timeline, max_words: int = 9) -> str:
    """Cue the timeline at its pauses / sentence ends (the same SRT the app's caption tools read)."""
    out, cue = [], []

    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    def flush():
        if cue:
            out.append(f"{len(out) + 1}\n{ts(cue[0].start)} --> {ts(cue[-1].end)}\n{tl.text[cue[0].a:cue[-1].b]}\n")
            cue.clear()

    for i, w in enumerate(tl.words):
        cue.append(w)
        nxt = tl.words[i + 1] if i + 1 < len(tl.words) else None
        stop = nxt and re.search(r"[.?!]", tl.text[w.b:nxt.a]) and T.norm(w.text) not in T.ABBREV
        if not nxt or nxt.start - w.end > 0.1 or stop or len(cue) >= max_words:
            flush()
    return "\n".join(out)


def timeline_for(audio: str, text: str, srt: str | None = None) -> Timeline:
    if srt and os.path.exists(srt):
        return from_srt(open(srt, encoding="utf-8").read(), probe_duration(audio))
    pauses, dur = detect_pauses(audio)
    return align(text, dur, pauses)
