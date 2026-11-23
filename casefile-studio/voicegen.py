"""Voice (v0.4.21): narrate a script in the producer's own cloned voice.

Talks to a local speech server that speaks the OpenAI speech API
(``POST /v1/audio/speech``). VoiceStudio is the one this was written for; any
compatible server works. Nothing is sent to a paid service: the server runs on
the producer's own computer. This module only asks it to read text aloud and
joins the pieces into one narration file.

Uploading your own recording is always the other choice; this never replaces it.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

DEFAULT_BASE = "http://host.docker.internal:3900"
PAUSE_PARAGRAPH = 0.55  # seconds of silence between paragraphs
PAUSE_SENTENCE = 0.18  # between pieces of one paragraph
MAX_CHARS = 420  # per request; long requests drift or get cut by local engines


class VoiceError(RuntimeError):
    pass


DIRECTION = re.compile(r"^\[(VISUAL|ON SCREEN|SFX|MUSIC|B-?ROLL|TEXT|CARD|LOWER THIRD|NOTE|EDITOR)[^\]]*\]", re.I)


def spoken_text(markdown):
    """Narration only: no headings, tables, metadata, editor directions
    ([VISUAL] lines, (re-cut notes), [tags]) or audit footers."""
    lines, keep = [], True
    for line in (markdown or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            keep = not re.search(r"audit|totals|not narrated", s, re.I)
            continue
        if s == "---" or not keep or not s or s.startswith(("|", ">")):
            if s == "" and lines and lines[-1] != "":
                lines.append("")
            continue
        if re.match(r"^[-*]\s", s) or re.match(r"^\*\*[^*]{1,60}:\*\*", s):
            continue
        s = re.sub(r"[*_`]", "", s).strip()
        if re.fullmatch(r"(HOOK|CHAPTER \d+)", s) or DIRECTION.match(s):
            continue
        if re.match(r"^Retained narration\b", s, re.I):
            continue
        if re.fullmatch(r"\([^()]*(?:\([^()]*\)[^()]*)*\)", s):  # a whole line in brackets is a note
            continue
        s = re.sub(r"^(\([^()]{1,80}\)\s*|\[[^\]]{1,60}\]\s*)+", "", s)  # leading (tag) / [TAG]
        s = re.sub(r"(\s*\[[^\]]{1,60}\])+$", "", s).strip()  # trailing [callback ...]
        if s:
            lines.append(s)
    return "\n".join(lines).strip()


def pieces(text, limit=MAX_CHARS):
    """[(text, pause after it)] split at paragraphs, then sentences."""
    out = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    for para in paragraphs:
        para = re.sub(r"\s+", " ", para)
        sentences = re.split(r"(?<=[.?!”\"])\s+(?=[A-Z“\"0-9])", para)
        cur = ""
        chunk = []
        for s in sentences:
            if cur and len(cur) + 1 + len(s) > limit:
                chunk.append(cur)
                cur = s
            else:
                cur = (cur + " " + s).strip()
        if cur:
            chunk.append(cur)
        for i, c in enumerate(chunk):
            out.append((c, PAUSE_PARAGRAPH if i == len(chunk) - 1 else PAUSE_SENTENCE))
    return out


class SpeechServer:
    def __init__(self, base=None, key=None, model=None, voice=None, client=None, timeout=1800):
        self.base = (base or os.environ.get("CASEFILE_VOICE_URL") or DEFAULT_BASE).rstrip("/")
        self.key = (key or os.environ.get("OMNIVOICE_API_KEY") or "").strip()
        self.model = (model or "omnivoice").strip()
        self.voice = (voice or "").strip()
        self.client = client
        self.timeout = timeout

    def _http(self):
        if self.client is not None:
            return self.client
        import httpx

        return httpx.Client(timeout=self.timeout)

    def _headers(self):
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    def status(self):
        try:
            r = self._http().get(self.base + "/health", headers=self._headers(), timeout=6)
        except Exception:
            return {"ready": False, "detail": f"No voice server answers at {self.base}. Start VoiceStudio on this computer."}
        if r.status_code == 503:
            return {"ready": False, "detail": "The voice server is still starting. Try again in a minute."}
        if r.status_code >= 400:
            return {"ready": False, "detail": f"The voice server answered with error {r.status_code}."}
        try:
            j = r.json()
        except ValueError:
            j = {}
        device = j.get("device")
        detail = "Voice server ready" + (f" (version {j['version']})" if j.get("version") else "")
        if device:
            detail += f", running on {device}" + (". On CPU a long narration can take hours." if device == "cpu" else ".")
        return {"ready": True, "detail": detail, "device": device}

    def voices(self):
        try:
            r = self._http().get(self.base + "/profiles", headers=self._headers(), timeout=10)
            data = r.json() if r.status_code < 400 else []
        except Exception:
            return []
        if isinstance(data, dict):
            data = data.get("profiles") or data.get("data") or data.get("voices") or []
        out = []
        for v in data if isinstance(data, list) else []:
            if isinstance(v, dict) and (v.get("id") or v.get("name")):
                out.append({"id": str(v.get("id") or v.get("name")), "name": str(v.get("name") or v.get("id"))})
            elif isinstance(v, str):
                out.append({"id": v, "name": v})
        return out

    def speak(self, text):
        if not self.voice:
            raise VoiceError("Choose which voice to use first.")
        try:
            r = self._http().post(
                self.base + "/v1/audio/speech", headers=self._headers(), timeout=self.timeout,
                json={"model": self.model, "voice": self.voice, "input": text, "response_format": "wav"},
            )
        except Exception as e:
            raise VoiceError(f"The voice server stopped answering: {str(e)[:160]}")
        if r.status_code in (401, 403):
            raise VoiceError("The voice server refused the key. Check the API key.")
        if r.status_code >= 400:
            raise VoiceError(f"The voice server returned error {r.status_code}: {r.text[:200]}")
        if len(r.content) < 200:
            raise VoiceError("The voice server returned no audio.")
        return r.content


def narrate(text, server, work_dir, out_path, progress=lambda *a: None, cancelled=lambda: False):
    """Read `text` aloud piece by piece and join it into one file at out_path.
    Returns {"pieces", "seconds", "words"}."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    parts = pieces(text)
    if not parts:
        raise VoiceError("There is no narration text to read.")
    files = []
    for i, (chunk, pause) in enumerate(parts):
        if cancelled():
            raise VoiceError("Cancelled.")
        progress(int(92 * i / len(parts)), f"Voicing part {i + 1} of {len(parts)}")
        raw = work / f"raw{i:04d}.wav"
        raw.write_bytes(server.speak(chunk))
        norm = work / f"p{i:04d}.wav"
        # One format for every piece, edge silence trimmed, then an exact pause.
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af",
             "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.03,"
             "areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.03,areverse,"
             f"aresample=48000,apad=pad_dur={pause}", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(norm)],
            capture_output=True, text=True,
        )
        if r.returncode or not norm.exists():
            raise VoiceError("One voiced part could not be read as audio: " + (r.stderr or "")[-200:])
        files.append(norm)
    progress(94, "Joining the narration")
    listing = work / "list.txt"
    listing.write_text("\n".join(f"file '{f.as_posix()}'" for f in files))
    out_path = Path(out_path)
    codec = ["-c:a", "libmp3lame", "-b:a", "192k"] if out_path.suffix.lower() == ".mp3" else ["-c:a", "pcm_s16le"]
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "1", *codec, str(out_path)],
        capture_output=True, text=True,
    )
    if r.returncode or not out_path.exists():
        raise VoiceError("Could not join the narration: " + (r.stderr or "")[-200:])
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out_path)],
                       capture_output=True, text=True).stdout.strip()
    return {"pieces": len(parts), "seconds": float(d or 0), "words": len(text.split())}
