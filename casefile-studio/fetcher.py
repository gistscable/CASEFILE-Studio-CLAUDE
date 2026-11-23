"""Fetch from guide (v0.4.19).

Reads the editing guide's Source library and Base clips table, downloads each
YouTube video once, and produces the exact files the guide names:

- Footage sources (``S03.mp4``): the video from 0:00 to the last window the
  guide uses plus a margin, so every guide window (``~0:42–0:46``) still means
  the same moment in the downloaded file. With no window known, the whole video.
- Base clips (``BASE-C--location--02.mp4`` with ``0:40–0:52``): cut to exactly
  that window, so the editor uses the trimmed clip whole.
- Base frames (``BASE-V--portrait--01.jpg`` at ``1:12``): one still captured at
  that time.

Downloaders: yt-dlp (default; runs inside the container, free, no account) or
an Apify actor (optional; needs an API token). Both only fetch; the reuse basis,
rights notes and audio-clearance ticks stay manual in the app. Every fetched file
records where it came from (link, video ID, uploader, title, window, time).

This module has no web-framework imports so it can be tested on its own;
app.py wires it to the API and the job runner.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAD_END = 10.0  # seconds kept after the last window a source needs
FRAME_PAD = 3.0  # seconds downloaded after a base frame's timestamp
DEFAULT_ACTOR = "danng/youtube-to-mp4-youtube-downloader-with-yt-dlp"
DEFAULT_HEIGHT = 1080
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_VID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?"
_RANGE = re.compile(r"(" + _TIME + r")\s*(?:–|—|-|to)\s*(" + _TIME + r")")
_BASE_NAME = re.compile(
    r"BASE-[VSC][^\s|`\"'<>()\[\],]*?\.(?:mp4|mov|webm|mkv|jpe?g|png|webp)", re.I
)
_URL = re.compile(r"https?://[^\s)<>|\]`\"']+")


class FetchError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Links and times
# --------------------------------------------------------------------------


def youtube_id(url):
    """The 11-character video ID of a YouTube link, or None for anything else."""
    try:
        u = urlparse(str(url or "").strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or u.hostname not in YOUTUBE_HOSTS:
        return None
    if u.hostname.endswith("youtu.be"):
        vid = u.path.strip("/").split("/")[0]
    else:
        vid = parse_qs(u.query).get("v", [""])[0]
        if not vid:
            parts = [p for p in u.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
                vid = parts[1]
    return vid if _VID.match(vid or "") else None


def watch_url(vid):
    return f"https://www.youtube.com/watch?v={vid}"


def seconds(stamp):
    parts = [float(x) for x in str(stamp).split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def url_time(url):
    """Start time carried by a link (``&t=90``, ``t=1m30s``, ``start=90``)."""
    try:
        q = parse_qs(urlparse(url).query)
    except ValueError:
        return None
    raw = (q.get("t") or q.get("start") or [None])[0]
    if not raw:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", raw)
    if not m or not any(m.groups()):
        return None
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)


def ranges(text):
    out = []
    for a, b in _RANGE.findall(str(text or "")):
        a, b = seconds(a), seconds(b)
        if b > a:
            out.append((a, b))
    return out


def clock(sec):
    sec = max(0, int(round(sec)))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# --------------------------------------------------------------------------
# What the guide asks for
# --------------------------------------------------------------------------


def _save_as(notes, sid):
    m = re.search(r"Save\s+as:\s*`?([^`\s·|,;]+\.[A-Za-z0-9]{2,4})`?", notes or "", re.I)
    name = m.group(1) if m else f"{sid}.mp4"
    name = Path(name).name
    if Path(name).suffix.lower() not in VIDEO_EXT + IMAGE_EXT:
        name = Path(name).stem + ".mp4"
    # The editor links sources by their ID in the filename; keep it there.
    if not re.search(r"(?<![A-Za-z0-9])" + re.escape(sid) + r"(?![A-Za-z0-9])", name, re.I):
        name = f"{sid}-{name}"
    return name


def _have(project, name, sid=None, vid=None):
    low = name.lower()
    for a in project.get("assets", []):
        n = str(a.get("name", ""))
        if n.lower() == low:
            return a
        if sid and a.get("kind") in ("image", "video") and (
            re.search(r"(?<![A-Za-z0-9])" + re.escape(sid) + r"(?![A-Za-z0-9])", n, re.I)
            or (vid and vid in n)
        ):
            return a
    return None


def plan(project, include_unused=False):
    """Every file the guide names, with where to get it and whether it is here.

    Each item: kind (source | base-clip | base-frame), save_as, url, video_id,
    need ("full" or the end second to download to), window / at, used,
    status (have | todo | manual | unused) and a plain-English note.
    """
    guide = (project.get("episode") or {}).get("guide")
    if not guide:
        return {"items": [], "error": "Import the editing guide first."}
    raw = guide.get("raw", "")
    sources = guide.get("sources", [])
    by_id = {s["id"]: s for s in sources}
    used, windows = set(), {}
    for cue in guide.get("cues", []):
        refs = [(cue.get("source_id"), cue.get("suggested_windows") or cue.get("primary_windows") or [])]
        refs += [
            (o.get("source_id"), o.get("suggested_windows") or [])
            for o in cue.get("alternatives", [])
        ]
        for sid, wins in refs:
            if not sid:
                continue
            used.add(sid)
            for w in wins:
                try:
                    windows.setdefault(sid, []).append((float(w["start"]), float(w["end"])))
                except (KeyError, TypeError, ValueError):
                    pass
        brk = cue.get("audio_break")
        if brk and cue.get("source_id"):
            windows.setdefault(cue["source_id"], []).append((float(brk["in"]), float(brk["out"])))
    items = []
    for s in sources:
        sid = s["id"]
        vid = youtube_id(s.get("url"))
        name = _save_as(s.get("notes", ""), sid)
        wins = windows.get(sid, []) + ranges(
            (re.search(r"Window:\s*([^\n·|]*)", s.get("notes", ""), re.I) or [None, ""])[1]
        )
        item = {
            "kind": "source",
            "id": sid,
            "save_as": name,
            "title": s.get("title", ""),
            "url": s.get("url"),
            "video_id": vid,
            "need": (max(b for _, b in wins) + PAD_END) if wins else "full",
            "used": sid in used,
        }
        have = _have(project, name, sid, vid)
        if have:
            item.update(status="have", note=f"Already in the project as {have['name']}.")
        elif not vid:
            item.update(status="manual", note="Not a YouTube link. Download it yourself, or ask the guide writer for the YouTube upload.")
        elif not item["used"] and not include_unused:
            item.update(status="unused", note="Listed in the library but no card uses it.")
        else:
            span = "the whole video" if item["need"] == "full" else f"0:00 to {clock(item['need'])}"
            item.update(status="todo", note=f"Downloads {span}, so the guide's windows line up.")
        items.append(item)
    seen = set()
    for line in raw.splitlines():
        m = _BASE_NAME.search(line)
        if not m:
            continue
        name = Path(m.group(0)).name
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        rest = line[m.end():]
        frame = Path(name).suffix.lower() in IMAGE_EXT
        url = next((u.rstrip(".,;") for u in _URL.findall(rest) if youtube_id(u)), None)
        via = None
        if not url:
            for sid in re.findall(r"(?<![A-Za-z0-9-])([A-Z][A-Z_]*\d+)(?![A-Za-z0-9])", rest):
                if sid in by_id and youtube_id(by_id[sid].get("url")):
                    url, via = by_id[sid]["url"], sid
                    break
        vid = youtube_id(url)
        rs = ranges(rest)
        item = {
            "kind": "base-frame" if frame else "base-clip",
            "id": name,
            "save_as": name,
            "title": re.sub(r"[`|*]", " ", rest).strip()[:160],
            "url": url,
            "video_id": vid,
            "used": True,
            "via_source": via,
        }
        if frame:
            at = None
            singles = re.findall(r"(?<![\d:])(" + _TIME + r")(?![\d:])", _RANGE.sub(" ", rest))
            if singles:
                at = seconds(singles[0])
            elif rs:
                at = rs[0][0]
            elif url:
                at = url_time(url)
            item["at"] = at
            item["need"] = (at + FRAME_PAD) if at is not None else None
        else:
            item["window"] = list(rs[0]) if rs else None
            item["need"] = (rs[0][1] + 1.0) if rs else "full"
        have = _have(project, name)
        if have:
            item.update(status="have", note="Already in the project.")
        elif not vid:
            item.update(status="manual", note="No YouTube link or source ID on this row. Get this file by hand.")
        elif frame and item.get("at") is None:
            item.update(status="manual", note="No timestamp for this frame. Add one (for example 1:12) to the guide row.")
        else:
            what = (
                f"frame at {clock(item['at'])}" if frame
                else f"clip {clock(item['window'][0])}–{clock(item['window'][1])}" if item.get("window")
                else "the whole video (no window on this row)"
            )
            item.update(status="todo", note=("From " + via + ": " if via else "") + what + ".")
        items.append(item)
    counts = {}
    for i in items:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    return {"items": items, "counts": counts}


# --------------------------------------------------------------------------
# Downloaders
# --------------------------------------------------------------------------


def _run(cmd, cancelled, timeout, on_line=None, on_tick=None, on_err=None):
    """Run a command; stop it if the producer cancels or it takes too long.
    v0.4.27: stdout lines go to `on_line` as they arrive, and `on_tick` is
    called about twice a second, so a download can report its progress."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
        bufsize=1, errors="replace",
    )
    out_lines, err_lines = [], []

    def pump(stream, sink, callback):
        for line in stream:
            sink.append(line)
            if callback:
                try:
                    callback(line.rstrip("\n"))
                except Exception:  # progress is best effort; never break a download
                    pass

    readers = [
        threading.Thread(target=pump, args=(proc.stdout, out_lines, on_line), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, err_lines, on_err), daemon=True),
    ]
    for t in readers:
        t.start()
    start = time.monotonic()
    while True:
        try:
            proc.wait(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if on_tick:
                try:
                    on_tick()
                except Exception:
                    pass
            if cancelled() or time.monotonic() - start > timeout:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
                proc.wait()
                for t in readers:
                    t.join(timeout=2)
                raise FetchError("Cancelled." if cancelled() else "Timed out.")
    for t in readers:
        t.join(timeout=5)
    return proc.returncode, "".join(out_lines), "".join(err_lines)


PROGRESS_TAG = "CFPROG"
FFMPEG_TIME = re.compile(r"time=\s*(-?\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


def ffmpeg_seconds(line):
    """'... time=00:01:12.40 bitrate=...' -> 72.4 (None if not a progress line).
    v0.4.34: cut sections go through ffmpeg, which reports how far into the
    video it is, never a byte total; with the section length that is a real %."""
    m = FFMPEG_TIME.search(line or "")
    if not m or m.group(1).startswith("-"):
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _num(v):
    try:
        n = float(v)
        return n if n == n and n >= 0 else None
    except (TypeError, ValueError):
        return None


def parse_progress(line):
    """yt-dlp's --progress-template line -> {done, total, speed, part} or None."""
    if not line.startswith(PROGRESS_TAG):
        return None
    parts = line[len(PROGRESS_TAG):].strip().split("|")
    if len(parts) < 4:
        return None
    done, total, estimate, speed = (_num(p) for p in parts[:4])
    vcodec = parts[4].strip() if len(parts) > 4 else ""
    return {"done": done, "total": total or estimate, "speed": speed,
            "part": "audio" if vcodec == "none" else "video" if vcodec and vcodec != "NA" else ""}


class YtDlp:
    name = "yt-dlp"

    def __init__(self, binary=None, max_height=DEFAULT_HEIGHT, timeout=1800):
        self.binary = binary or os.environ.get("CASEFILE_YTDLP") or shutil.which("yt-dlp")
        self.max_height = int(max_height)
        self.timeout = timeout

    def status(self):
        if not self.binary:
            return {"ready": False, "detail": "yt-dlp is not installed in this container. Rebuild the Docker image from v0.4.19."}
        try:
            v = subprocess.run([self.binary, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return {"ready": False, "detail": "yt-dlp could not start."}
        js = next((r for r in ("deno", "node", "bun") if shutil.which(r)), None)
        detail = f"yt-dlp {v or '?'}"
        detail += f", JavaScript runtime: {js}" if js else ", no JavaScript runtime (YouTube may fail)"
        return {"ready": True, "detail": detail, "version": v, "js_runtime": js}

    def download(self, vid, need, folder, cancelled, report=None):
        folder = Path(folder)
        report = report or (lambda **kw: None)
        h = self.max_height
        fmt = (
            f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/b[height<={h}][ext=mp4]/"
            f"bv*[height<={h}]+ba/b[height<={h}]/b"
        )
        cmd = [
            self.binary, "--no-playlist", "--newline", "--no-warnings",
            "--progress-template",
            f"download:{PROGRESS_TAG} %(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
            "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(info.vcodec)s",
            "--restrict-filenames", "-f", fmt, "--merge-output-format", "mp4",
            "--write-info-json", "--retries", "3", "--fragment-retries", "3",
            "-o", str(folder / f"{vid}.%(ext)s"),
        ]
        js = next((r for r in ("deno", "node", "bun") if shutil.which(r)), None)
        if js and js != "deno":
            cmd += ["--js-runtimes", js]  # yt-dlp enables only deno by default
        if need != "full" and need is not None:
            cmd += ["--download-sections", f"*0-{int(need) + 1}"]
        cmd.append(watch_url(vid))
        # Progress: yt-dlp's own numbers when it gives them; otherwise (cut
        # sections go through ffmpeg) the growing size of the file on disk.
        seen = {"template": False, "size": -1}

        def on_line(line):
            p = parse_progress(line)
            if p and p["done"] is not None:
                seen["template"] = True
                report(done=p["done"], total=p["total"], speed=p["speed"], part=p["part"])
            elif "[Merger]" in line or "Merging formats" in line:
                report(phase="joining picture and sound")

        section = float(int(need) + 1) if need != "full" and need is not None else None

        def on_err(line):
            t = ffmpeg_seconds(line)
            if t is not None and section:
                seen["secs"] = min(t, section)
                report(secs=round(seen["secs"], 1), secs_total=section)

        def on_tick():
            if seen["template"]:
                return
            size = sum(p.stat().st_size for p in folder.glob(vid + "*") if p.is_file() and not p.name.endswith(".json"))
            if size != seen["size"]:
                seen["size"] = size
                report(done=size, total=None, speed=None, part="")

        code, out, err = _run(cmd, cancelled, self.timeout, on_line, on_tick, on_err)
        files = [p for p in folder.glob(vid + ".*") if p.suffix.lower() in VIDEO_EXT]
        if code or not files:
            tail = (err or out or "").strip().splitlines()[-3:]
            raise FetchError("yt-dlp: " + (" ".join(tail) or f"exit code {code}")[:500])
        info = {}
        meta = folder / f"{vid}.info.json"
        if meta.exists():
            try:
                j = json.loads(meta.read_text())
                info = {k: j.get(k) for k in ("title", "uploader", "channel", "upload_date", "duration", "webpage_url")}
            except ValueError:
                pass
        return max(files, key=lambda p: p.stat().st_size), info


class Apify:
    name = "apify"

    def __init__(self, token, actor=None, base="https://api.apify.com", client=None, timeout=900):
        self.token = (token or os.environ.get("APIFY_TOKEN") or "").strip()
        self.actor = (actor or os.environ.get("APIFY_ACTOR") or DEFAULT_ACTOR).strip()
        self.base = base.rstrip("/")
        self.client = client
        self.timeout = timeout

    def status(self):
        if not self.token:
            return {"ready": False, "detail": "Paste an Apify API token, or start the container with -e APIFY_TOKEN=..."}
        if not re.fullmatch(r"[A-Za-z0-9_.-]+[/~][A-Za-z0-9_.-]+", self.actor):
            return {"ready": False, "detail": "The Apify actor must look like owner/actor-name."}
        return {"ready": True, "detail": f"Apify actor {self.actor}"}

    def _http(self):
        if self.client is not None:
            return self.client
        import httpx

        return httpx.Client(timeout=self.timeout, follow_redirects=True)

    def download(self, vid, need, folder, cancelled, report=None):
        report = report or (lambda **kw: None)
        ok = self.status()
        if not ok["ready"]:
            raise FetchError(ok["detail"])
        http = self._http()
        actor = self.actor.replace("/", "~")
        report(phase="waiting for Apify to prepare the file")
        r = http.post(
            f"{self.base}/v2/acts/{actor}/run-sync-get-dataset-items",
            params={"token": self.token},
            json={"url": watch_url(vid)},
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise FetchError(f"Apify returned HTTP {r.status_code}: {r.text[:300]}")
        try:
            rows = r.json()
        except ValueError:
            raise FetchError("Apify returned something that is not JSON.")
        row = next((x for x in (rows if isinstance(rows, list) else [rows]) if isinstance(x, dict)), None)
        if not row:
            raise FetchError("The Apify actor returned no result for this video.")
        if row.get("success") is False or row.get("error"):
            raise FetchError("Apify: " + str(row.get("error") or "the actor reported a failure")[:300])
        link = None
        for key in ("downloadUrl", "download_url", "fileUrl", "file_url", "videoUrl", "video_url", "mediaUrl", "url"):
            v = row.get(key)
            if isinstance(v, str) and v.startswith("http") and not youtube_id(v):
                link = v
                break
        if not link:
            raise FetchError("The Apify result has no download link (expected downloadUrl). Try another actor.")
        if cancelled():
            raise FetchError("Cancelled.")
        out = Path(folder) / f"{vid}.mp4"
        params = {"token": self.token} if urlparse(link).hostname == urlparse(self.base).hostname else None
        with http.stream("GET", link, params=params, timeout=self.timeout) as resp:
            if resp.status_code >= 400:
                raise FetchError(f"Downloading the Apify file failed with HTTP {resp.status_code}.")
            total = _num(resp.headers.get("content-length"))
            done, started = 0, time.monotonic()
            with out.open("wb") as f:
                for chunk in resp.iter_bytes(1024 * 1024):
                    if cancelled():
                        raise FetchError("Cancelled.")
                    f.write(chunk)
                    done += len(chunk)
                    report(done=done, total=total, speed=done / max(0.001, time.monotonic() - started), part="")
        if out.stat().st_size < 1000:
            raise FetchError("The Apify file is empty.")
        info = {k: row.get(k) for k in ("title", "uploader", "channel", "upload_date") if row.get(k)}
        info["actor"] = self.actor
        return out, info


def backend(name, **kw):
    if name == "apify":
        return Apify(kw.get("token"), kw.get("actor"), **({"base": kw["base"]} if kw.get("base") else {}))
    return YtDlp(kw.get("binary"), kw.get("max_height") or DEFAULT_HEIGHT)


# --------------------------------------------------------------------------
# Turning a download into the file the guide names
# --------------------------------------------------------------------------


def _ffmpeg(args, cancelled, timeout=900):
    code, out, err = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], cancelled, timeout)
    if code:
        raise FetchError("ffmpeg: " + (err or "").strip()[-400:])


def _duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def materialize(item, video, out_dir, cancelled=lambda: False):
    """Write the guide-named file for `item` from the downloaded `video`."""
    out = Path(out_dir) / item["save_as"]
    length = _duration(video)
    if item["kind"] == "base-frame":
        at = float(item["at"])
        if length and at > length:
            raise FetchError(f"The frame time {clock(at)} is past the end of the video ({clock(length)}).")
        _ffmpeg(["-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)], cancelled)
    elif item["kind"] == "base-clip" and item.get("window"):
        a, b = item["window"]
        if length and a >= length - 0.5:
            raise FetchError(f"The window starts at {clock(a)}, after the video ends ({clock(length)}).")
        b = min(b, length) if length else b
        _ffmpeg(
            ["-ss", f"{a:.3f}", "-i", str(video), "-t", f"{b - a:.3f}", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-b:a", "160k", "-movflags", "+faststart", str(out)],
            cancelled,
        )
    else:
        if out.suffix.lower() == video.suffix.lower():
            shutil.copyfile(video, out)
        else:
            _ffmpeg(["-i", str(video), "-c", "copy", "-movflags", "+faststart", str(out)], cancelled)
        need = item.get("need")
        if length and need not in (None, "full") and item["kind"] == "source":
            last = float(need) - PAD_END
            if last > length + 0.5:
                raise FetchError(f"The guide uses up to {clock(last)} but the video is only {clock(length)} long.")
    if not out.exists() or out.stat().st_size == 0:
        raise FetchError("No file was produced.")
    return out


def run(items, downloader, work_dir, on_file, progress=lambda *a: None, cancelled=lambda: False, attempts=2,
        on_status=lambda item_id, **state: None):
    """Download each YouTube video once and hand every guide-named file to
    `on_file(path, item, info)`. Returns per-item results; never raises for a
    single item's failure, so one bad link does not stop the rest.
    v0.4.27: `on_status(item_id, status=..., done=..., total=..., speed=...,
    error=...)` reports each file: waiting, downloading, saving, done, failed."""
    for item in items:
        on_status(item["id"], status="waiting")
    work_dir = Path(work_dir)
    groups = {}
    for item in items:
        groups.setdefault(item["video_id"], []).append(item)
    results, done = [], 0
    total = max(1, len(items))
    for vid, group in groups.items():
        if cancelled():
            break
        need = "full" if any(i.get("need") in ("full", None) and i["kind"] != "base-frame" for i in group) else max(
            float(i["need"]) for i in group if i.get("need") not in ("full", None)
        )
        folder = work_dir / vid
        folder.mkdir(parents=True, exist_ok=True)
        names = ", ".join(i["save_as"] for i in group)
        progress(int(100 * done / total), f"Downloading {names}")
        video, info, error = None, {}, None

        def report(**kw):
            for item in group:
                on_status(item["id"], status="downloading", **kw)

        for attempt in range(attempts):
            report(attempt=attempt + 1, attempts=attempts, done=0, total=None, speed=None, phase="starting")
            try:
                video, info = downloader.download(vid, need, folder, cancelled, report)
                break
            except FetchError as e:
                error = str(e)
                if cancelled() or "Cancelled" in error:
                    break
                time.sleep(min(5, 1 + attempt * 2))
        for item in group:
            done += 1
            if video is None:
                results.append({"id": item["id"], "save_as": item["save_as"], "ok": False, "error": error or "Download failed."})
                on_status(item["id"], status="failed", error=error or "Download failed.")
                continue
            try:
                on_status(item["id"], status="saving")
                path = materialize(item, video, folder, cancelled)
                record = {
                    "url": watch_url(vid),
                    "video_id": vid,
                    "backend": downloader.name,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "window": item.get("window"),
                    "at": item.get("at"),
                    "downloaded_to": None if need == "full" else need,
                    **{k: v for k, v in info.items() if v},
                }
                on_file(path, item, record)
                results.append({"id": item["id"], "save_as": item["save_as"], "ok": True})
                on_status(item["id"], status="done")
            except Exception as e:  # one bad item must not stop the rest
                results.append({"id": item["id"], "save_as": item["save_as"], "ok": False, "error": str(e)[:400]})
                on_status(item["id"], status="failed", error=str(e)[:400])
            progress(int(100 * done / total), f"Saved {item['save_as']}")
        shutil.rmtree(folder, ignore_errors=True)
    return results
