"""Timing from the audio (v0.4.21): Whisper hears the narration, the script
supplies the spelling.

CapCut's SRT/JSON stay fully supported; this is the other choice. Whisper runs
on this computer (free, no key). It hears *when* each word is said but often
misspells names and writes figures its own way. So the times are taken from
Whisper and the words from the script, matched word by word. The result is an
SRT and a word-timing JSON in the formats the editor already imports, with the
script's spelling throughout, plus a list of the places where what was heard
differs from the script, for the producer to check.
"""
from __future__ import annotations

import difflib
import json
import os
import re

MODELS = ("base.en", "small.en", "medium.en", "base", "small", "medium")


_WHY = None


def available():
    global _WHY
    try:
        import faster_whisper  # noqa: F401

        _WHY = None
        return True
    except Exception as e:  # v0.4.33: keep the reason, so the app can show it
        _WHY = f"{type(e).__name__}: {e}"[:300]
        return False


def unavailable_reason():
    """Why Whisper cannot load (None when it can)."""
    return None if available() else _WHY


def transcribe(path, model="base.en", cache_dir=None, progress=lambda *a: None, cancelled=lambda: False):
    """[{word, start, end}] as heard. Needs the faster-whisper package."""
    from faster_whisper import WhisperModel

    if model not in MODELS:
        model = "base.en"
    progress(3, f"Loading the {model} speech model (the first run downloads it)")
    wm = WhisperModel(model, device="cpu", compute_type="int8", download_root=cache_dir)
    segments, info = wm.transcribe(str(path), word_timestamps=True, vad_filter=False, beam_size=5)
    total = float(getattr(info, "duration", 0) or 0) or 1.0
    out = []
    for seg in segments:
        if cancelled():
            raise RuntimeError("Cancelled.")
        for w in seg.words or []:
            out.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})
        progress(min(90, 5 + int(85 * float(seg.end) / total)), "Listening to the narration")
    return out


def norm(word):
    return re.sub(r"[^a-z0-9]+", "", word.lower().replace("’", "'").replace("'", ""))


def script_words(text):
    return [w for w in re.split(r"\s+", text or "") if norm(w) or re.search(r"\d", w)]


def _spread(words, start, end):
    """Give `words` the span start..end, shared by length."""
    weights = [max(1, len(norm(w)) or 1) for w in words]
    total = sum(weights)
    out, t = [], start
    for w, wt in zip(words, weights):
        d = (end - start) * wt / total
        out.append({"word": w, "start": t, "end": t + d})
        t += d
    return out


def align(script_text, heard):
    """Script words with the times Whisper heard. Returns (words, report)."""
    sw = script_words(script_text)
    heard = [h for h in heard if norm(h["word"])]
    if not sw:
        raise ValueError("There is no script to match the audio to.")
    if not heard:
        raise ValueError("No speech was heard in the audio.")
    a, b = [norm(w) for w in sw], [norm(h["word"]) for h in heard]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out, differences, exact, extra = [], [], 0, 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                h = heard[j1 + k]
                out.append({"word": sw[i1 + k], "start": h["start"], "end": h["end"], "exact": True})
            exact += i2 - i1
        elif tag == "replace":
            start, end = heard[j1]["start"], heard[j2 - 1]["end"]
            out += [{**w, "exact": False} for w in _spread(sw[i1:i2], start, end)]
            differences.append({"at": start, "script": " ".join(sw[i1:i2]), "heard": " ".join(h["word"] for h in heard[j1:j2])})
        elif tag == "delete":  # in the script, not heard: squeeze between neighbours
            start = out[-1]["end"] if out else 0.0
            end = heard[j1]["start"] if j1 < len(heard) else start + 0.25 * (i2 - i1)
            end = max(end, start + 0.02 * (i2 - i1))
            out += [{**w, "exact": False} for w in _spread(sw[i1:i2], start, end)]
            differences.append({"at": start, "script": " ".join(sw[i1:i2]), "heard": "(nothing heard)"})
        else:  # heard, not in the script
            extra += j2 - j1
            differences.append({"at": heard[j1]["start"], "script": "(not in the script)", "heard": " ".join(h["word"] for h in heard[j1:j2])})
    last = 0.0
    for w in out:  # keep times ordered and non-zero for the editor
        w["start"] = max(w["start"], last)
        w["end"] = max(w["end"], w["start"] + 0.01)
        last = w["start"]
    report = {
        "script_words": len(sw), "heard_words": len(heard), "matched": exact,
        "match": round(exact / len(sw), 4), "extra_heard": extra,
        "differences": differences[:400], "difference_count": len(differences),
        "duration": out[-1]["end"] if out else 0.0,
    }
    return out, report


def stamp(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(words, max_chars=42, max_seconds=5.0):
    """Captions that break at sentence ends, then at length."""
    blocks, cur = [], []
    for w in words:
        text = " ".join(x["word"] for x in cur + [w])
        if cur and (len(text) > max_chars or w["end"] - cur[0]["start"] > max_seconds):
            blocks.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.?!][”\"']?$", w["word"]):
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    lines = []
    for i, b in enumerate(blocks, 1):
        end = blocks[i][0]["start"] if i < len(blocks) else b[-1]["end"]  # continuous captions
        lines += [str(i), f"{stamp(b[0]['start'])} --> {stamp(max(end, b[0]['start'] + 0.05))}", " ".join(x["word"] for x in b), ""]
    return "\n".join(lines)


def to_json(words, source="whisper+script"):
    return json.dumps({"source": source, "words": [
        {"word": w["word"], "start": round(w["start"], 3), "end": round(w["end"], 3)} for w in words
    ]}, ensure_ascii=False)


def differences_text(report):
    lines = [f"Matched {report['matched']} of {report['script_words']} script words ({report['match'] * 100:.1f}%).",
             f"{report['difference_count']} places where the audio and the script differ:", ""]
    for d in report["differences"]:
        lines.append(f"{stamp(d['at'])}  script: {d['script']}   |   heard: {d['heard']}")
    return "\n".join(lines) + "\n"
