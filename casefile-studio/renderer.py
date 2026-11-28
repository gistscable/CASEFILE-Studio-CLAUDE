"""Deterministic FFmpeg renderer. No AI calls, shell interpolation, or remote media."""

from __future__ import annotations
import hashlib, json, math, os, re, shutil, subprocess, tempfile, textwrap, threading, time
from pathlib import Path
from typing import Callable
from editorial import strip_references
import captionstyle
import effects
import cta
import watermark
import picture
import stickers
import motion as motiongfx
import sportsgfx
import sound as sfx
import music as musiclib

# v0.4.56: the limiter after the effects mix. level=disabled: no automatic make-up gain (the
# default lifts everything ~0.45 dB); latency=1: the 5 ms look-ahead is compensated. So turning
# the effects on leaves the narration sample-for-sample where it was and at the same level.
SFX_LIMIT = "alimiter=limit=0.95:attack=5:release=50:level=disabled:latency=1"
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from storage import DATA, ROOT, resolve_asset

FPS = 24


def _font(name):
    """The system DejaVu font (Linux/Docker), else the copy bundled with the app (macOS, Windows)."""
    system = Path("/usr/share/fonts/truetype/dejavu") / name
    return str(system if system.exists() else ROOT / "web/assets/fonts" / name)


FONT = _font("DejaVuSans.ttf")
BOLD = _font("DejaVuSans-Bold.ttf")


def plain(text: str) -> str:
    return strip_references(text)


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=40,
    )
    if result.returncode:
        raise ValueError(
            "This media file could not be decoded. Try MP4, WAV, MP3, PNG, or JPEG."
        )
    data = json.loads(result.stdout)
    video = next(
        (
            s
            for s in data.get("streams", [])
            if s["codec_type"] == "video"
            and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    audio = next(
        (s for s in data.get("streams", []) if s["codec_type"] == "audio"), None
    )
    return {
        "video_duration": float(video["duration"])
        if video and video.get("duration") not in (None, "N/A")
        else None,
        "audio_duration": float(audio["duration"])
        if audio and audio.get("duration") not in (None, "N/A")
        else None,
        "duration": float(
            data.get("format", {}).get("duration")
            or (video or audio or {}).get("duration")
            or 0
        ),
        "width": (video or {}).get("width"),
        "height": (video or {}).get("height"),
        "has_audio": bool(audio),
        "has_video": bool(video),
        # v0.4.47: what the browser needs to know to play it in the preview.
        "codec": (video or {}).get("codec_name"),
        "alpha": _has_alpha(video),
    }


def _has_alpha(video):
    if not video:
        return False
    fmt = str(video.get("pix_fmt") or "")
    return bool(re.match(r"(yuva|rgba|argb|bgra|abgr|gbrap|ya\d|pal8)", fmt)) or str(
        (video.get("tags") or {}).get("alpha_mode") or (video.get("tags") or {}).get("ALPHA_MODE") or "") == "1"


# v0.4.47 Codecs every current browser plays in a <video>. ProRes, QuickTime Animation, HEVC with
# transparency, DNxHD and the like (most transparent .MOV files) do not play in Chrome or Firefox.
BROWSER_CODECS = {"h264", "vp8", "vp9", "av1"}
PREVIEW_MAX_SECONDS = float(cta.SPEC["file_max_seconds"])  # a CTA animation plays at most 15 s
# v0.4.50 The preview stills were 640 px wide, 15 a second and lossy WebP: soft and smeared on a
# Retina screen, where the CTA is drawn ~950 px wide (~1800 px fullscreen). They are now the part of
# the frame the animation uses, at the file's own resolution, 24 a second (as the export), lossless.
PREVIEW_VERSION = cta.SPEC["preview_version"]  # stills older than this are made again
PREVIEW_FPS = FPS
PREVIEW_MAX_PIXELS = 1280 * 720  # per still, so a full-frame animation stays light in the browser
PREVIEW_FIND_WIDTH = 480  # the quick pass that finds where the animation is drawn
PREVIEW_LOSSY_ABOVE = 400_000  # bytes: once a still is this big (noisy, photo-like), the rest are lossy


def needs_preview(info):
    """Does this uploaded video need a browser-safe copy for the edit preview?"""
    return bool(info and info.get("has_video") and info.get("codec") and info["codec"] not in BROWSER_CODECS)


def _raw_frames(path: Path, seconds, vf, w, h):
    """RGBA frames of `path` through `vf`, one at a time, without writing them to disk."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-t", f"{float(seconds):.3f}", "-an",
           "-vf", vf + ",format=rgba", "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size = w * h * 4
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.stderr.close()
        if proc.wait(timeout=600):
            raise ValueError("Casefile could not make a preview of this video: " + ((err or "").strip().splitlines() or ["no frames"])[-1][:200])


def preview_area(path: Path, width, height, seconds=PREVIEW_MAX_SECONDS):
    """(x0, y0, x1, y1) in pixels: the part of the frame the animation ever draws on (not fully
    transparent), with a small margin; the whole frame when it is never transparent."""
    fw = min(PREVIEW_FIND_WIDTH, width)
    fh = max(1, round(height * fw / width))
    seen = None
    for f in _raw_frames(path, seconds, f"fps={PREVIEW_FPS},scale={fw}:{fh}:flags=area", fw, fh):
        a = f[:, :, 3] > 0
        seen = a if seen is None else (seen | a)
    if seen is None:
        raise ValueError("Casefile could not make a preview of this video: no frames")
    if seen.all() or not seen.any():
        return 0, 0, width, height
    ys, xs = np.nonzero(seen)
    k = width / fw
    x0 = max(0, math.floor((xs.min() - 1) * k))
    y0 = max(0, math.floor((ys.min() - 1) * height / fh))
    x1 = min(width, math.ceil((xs.max() + 2) * k))
    y1 = min(height, math.ceil((ys.max() + 2) * height / fh))
    return x0, y0, x1, y1


def preview_frames(path: Path, folder: Path, seconds=PREVIEW_MAX_SECONDS):
    """v0.4.47 The first `seconds` of a video as WebP stills with their transparency, for the edit
    preview (every browser shows a WebP with alpha, Safari/WebKit and DuckDuckGo included, which is
    not true of any transparent video format). The preview shows the still for its clock time, so
    it stays in step when paused or scrubbed. Exports use the original file.

    v0.4.50: only the part of the frame the animation uses (`box`, as fractions of the frame), at the
    file's own resolution (up to PREVIEW_MAX_PIXELS a still), 24 a second, lossless."""
    info = probe(path)
    W, H = int(info.get("width") or 0), int(info.get("height") or 0)
    if not info.get("has_video") or W < 2 or H < 2:
        raise ValueError("Casefile could not make a preview of this video: no picture found")
    x0, y0, x1, y1 = preview_area(path, W, H, seconds)
    cw, ch = x1 - x0, y1 - y0
    k = min(1.0, math.sqrt(PREVIEW_MAX_PIXELS / (cw * ch)))
    sw, sh = max(1, round(cw * k)), max(1, round(ch * k))
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    vf = f"fps={PREVIEW_FPS},crop={cw}:{ch}:{x0}:{y0}" + (f",scale={sw}:{sh}:flags=lanczos" if (sw, sh) != (cw, ch) else "")
    # Lossless (exact edges and colours, and small for flat graphics) until a still comes out big;
    # from then on lossy, so a full-frame, noisy animation does not take minutes. Pillow encodes
    # WebP outside Python's lock, so a few threads share the work.
    from concurrent.futures import ThreadPoolExecutor
    lossy = threading.Event()

    def save(n, f):
        out = folder / f"{n:04d}.webp"
        im = Image.fromarray(f, "RGBA")
        if not lossy.is_set():
            im.save(out, "WEBP", lossless=True, quality=60, method=4)
            if out.stat().st_size <= PREVIEW_LOSSY_ABOVE:
                return
            lossy.set()
        im.save(out, "WEBP", quality=80, alpha_quality=100, method=2)

    n = 0
    workers = max(1, min(4, os.cpu_count() or 1))
    try:
        with ThreadPoolExecutor(workers) as pool:
            pending = []
            for f in _raw_frames(path, seconds, vf, sw, sh):
                pending.append(pool.submit(save, n, f.copy()))
                n += 1
                if len(pending) >= workers * 2:  # keep only a few frames in memory
                    pending.pop(0).result()
            for p in pending:
                p.result()
    except (ValueError, OSError):
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if not n:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError("Casefile could not make a preview of this video: no frames")
    box = [round(x0 / W, 5), round(y0 / H, 5), round(x1 / W, 5), round(y1 / H, 5)]
    return {"count": n, "fps": PREVIEW_FPS, "width": sw, "height": sh, "box": box, "version": PREVIEW_VERSION}


def waveform(path: Path, bins=160):
    out = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "800",
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        timeout=120,
    )
    samples = np.frombuffer(out.stdout, dtype=np.float32)
    if len(samples) == 0:
        return []
    values = np.array(
        [
            float(np.max(np.abs(c))) if len(c) else 0
            for c in np.array_split(samples, bins)
        ]
    )
    return (values / max(float(values.max()), 0.001)).round(3).tolist()


def thumbnail(path: Path, out: Path):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=480:270:force_original_aspect_ratio=increase,crop=480:270",
            str(out),
        ],
        capture_output=True,
        timeout=40,
        check=True,
    )


def scene_captions(scene: dict):
    duration = float(scene.get("duration", 5))
    if scene.get("captions_exact") or scene.get("captions"):
        return [
            {
                "start": max(0, float(c["start"])),
                "end": min(duration, float(c["end"])),
                "text": plain(c["text"]),
            }
            for c in scene.get("captions", [])
            if float(c["start"]) < duration and float(c["end"]) > float(c["start"])
        ]
    words = plain(scene.get("narration", "")).split()
    if not words:
        return []
    groups = [words[i : i + 9] for i in range(0, len(words), 9)]
    cursor = 0
    cues = []
    for g in groups:
        start = duration * cursor / len(words)
        cursor += len(g)
        cues.append(
            {"start": start, "end": duration * cursor / len(words), "text": " ".join(g)}
        )
    return cues


def srt_time(sec):
    ms = round(sec * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def project_srt(project):
    e = project.get("episode") or {}
    imported = (e.get("timings") or {}).get("captions")
    if e.get("guide") and imported:
        # Export the global supplied caption track once, not repeated fragments
        # split by visual cuts. Independent of whether burn-in captions are ON.
        return "\n".join(
            f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}\n"
            for i, c in enumerate(imported, 1)
        )
    cues, offset = [], 0.0
    for scene in project.get("scenes", []):
        for c in scene_captions(scene):
            cues.append(
                f"{len(cues) + 1}\n{srt_time(offset + c['start'])} --> {srt_time(offset + c['end'])}\n{c['text']}\n"
            )
        offset += scene["duration"]
    return "\n".join(cues)


def ass_time(sec):
    cs = round(sec * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def hide_cues(cues, windows, keep=0.3):
    """Captions with the parts inside `windows` [(start, end), scene seconds] taken out
    (v0.4.52: a motion graphic on screen already shows the words). A piece left shorter
    than `keep` seconds is dropped."""
    out = []
    for c in cues:
        pieces = [(c["start"], c["end"])]
        for a, b in windows:
            nxt = []
            for s, e in pieces:
                if b <= s or a >= e:
                    nxt.append((s, e))
                    continue
                if a - s >= keep:
                    nxt.append((s, a))
                if e - b >= keep:
                    nxt.append((b, e))
            pieces = nxt
        out += [{**c, "start": s, "end": e} for s, e in pieces]
    return out


def write_ass(scene, path, width, height, style=None, captions=True, lower=None, hide=()):
    """Burned-in captions in the project's caption style (v0.4.25) and the
    scene's lower-third name card (v0.4.26; `lower` from
    effects.effective_lower_thirds, v0.4.30). `hide`: scene seconds without captions."""
    lift = bool(scene.get("source_label") and scene.get("asset_id"))
    card = lower if lower is not None else scene.get("lower_third")
    lt_style, lt_events = effects.lower_third_ass(card, float(scene.get("duration", 5)), width, height, lift)
    cues = scene_captions(scene) if captions else []
    if hide and cues:
        cues = hide_cues(cues, hide)
    path.write_text(captionstyle.ass(cues, width, height, style, [lt_style] if lt_style else [], lt_events), encoding="utf-8")


def get_font(size, bold=False):
    try:
        return ImageFont.truetype(BOLD if bold else FONT, max(10, int(size)))
    except OSError:
        return ImageFont.load_default()


def overlay_image(project, scene, index, width, height, draft):
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    unit = effects.text_unit(width, height)  # = height in 16:9, so wide videos are unchanged
    tall = height > width
    if scene.get("show_title", True):
        for y in range(int(height * 0.4)):
            alpha = round(155 * (1 - y / (height * 0.4)) ** 1.5)
            d.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
        x, y = int(width * 0.055), int(height * 0.07)
        d.rectangle((x, y, x + int(width * 0.025), y + 3), fill=(214, 164, 96, 255))
        label = (
            f"{index + 1:02d}  /  {scene.get('chapter', 'DOCUMENTARY').upper()[:45]}"
        )
        d.text(
            (x, y + int(height * 0.023)),
            label,
            font=get_font(unit * 0.018, True),
            fill=(212, 188, 151, 255),
        )
        title = "\n".join(textwrap.wrap(scene.get("title", "Untitled scene"), width=22 if tall else 40))
        d.multiline_text(
            (x, y + int(height * (0.045 if tall else 0.062))),
            title,
            font=get_font(unit * 0.05, True),
            fill=(244, 242, 235, 255),
            spacing=8,
        )
    mark = (
        "FICTIONAL DEMO · AI ILLUSTRATION"
        if project.get("is_demo")
        else (
            "UNREVIEWED INSPECTION"
            if scene.get("inspection_only")
            else "REVIEW DRAFT"
            if draft
            else ""
        )
    )
    if mark:
        f = get_font(unit * 0.014)
        box = d.textbbox((0, 0), mark, font=f)
        tw = box[2] - box[0]
        d.rounded_rectangle(
            (
                width - tw - width * 0.045,
                height * 0.935,
                width - width * 0.025,
                height * 0.973,
            ),
            radius=3,
            fill=(0, 0, 0, 150),
        )
        d.text(
            (width - tw - width * 0.035, height * 0.942),
            mark,
            font=f,
            fill=(220, 211, 191, 230),
        )
    if scene.get("inspection_only"):
        d.rectangle((0, 0, width, height * 0.058), fill=(34, 25, 13, 245))
        d.text(
            (width * 0.025, height * 0.014),
            "UNREVIEWED INSPECTION — NOT FOR PUBLICATION",
            font=get_font(unit * (0.016 if tall else 0.023), True),
            fill=(236, 197, 127, 255),
        )
    if scene.get("source_label") and scene.get("asset_id"):
        label = str(scene["source_label"])[:180]
        font = get_font(unit * 0.018)
        lines = textwrap.wrap(label, width=34 if tall else 76)
        x, y = int(width * 0.045), int(height * effects.FORMATS["9:16" if tall else "16:9"]["label_top"])
        line_height = int(unit * 0.026)
        box_width = max(
            (d.textbbox((0, 0), line, font=font)[2] for line in lines[:2]), default=0
        )
        d.rounded_rectangle(
            (
                x - 8,
                y - 5,
                min(width * 0.93, x + box_width + 9),
                y + line_height * min(2, len(lines)) + 6,
            ),
            radius=3,
            fill=(0, 0, 0, 190),
        )
        for i, line in enumerate(lines[:2]):
            d.text((x, y + i * line_height), line, font=font, fill=(241, 237, 226, 255))
    return image


def run(cmd, cancelled: Callable[[], bool]):
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        while True:
            try:
                _, err = proc.communicate(timeout=1)
                if proc.returncode:
                    raise RuntimeError(
                        "Render failed: " + err.decode(errors="replace")[-1400:]
                    )
                return
            except subprocess.TimeoutExpired:
                if cancelled():
                    proc.terminate()
                    try:
                        proc.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.communicate()
                    raise RuntimeError("Cancelled by you. No output was published.")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


def available_cpus() -> int:
    """CPUs this process may use (inside Docker: what Docker Desktop gives it)."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


# v0.4.62 the H.264 encoder for the scene clips. libx264 (software, CRF 20) is the default everywhere; on a Mac,
# CASEFILE_VIDEO_ENCODER=videotoolbox uses Apple's hardware encoder (faster, lighter on the CPU, a fixed generous
# bitrate instead of constant quality). It is used only after a tiny test encode succeeds on this machine;
# otherwise the export uses libx264 and says why. One encoder per export (the scene clips are joined by copy).
VIDEOTOOLBOX = "h264_videotoolbox"
_ENCODER_PROBE: dict[str, tuple[bool, str]] = {}


def _encoder_works(name: str) -> tuple[bool, str]:
    if name not in _ENCODER_PROBE:
        try:
            r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=24:d=0.25",
                                "-pix_fmt", "yuv420p", "-c:v", name, "-b:v", "1M", "-f", "null", "-"],
                               capture_output=True, text=True, timeout=30)
            _ENCODER_PROBE[name] = (r.returncode == 0, (r.stderr or "").strip()[-200:])
        except (OSError, subprocess.SubprocessError) as e:
            _ENCODER_PROBE[name] = (False, str(e)[:200])
    return _ENCODER_PROBE[name]


def video_encoder() -> tuple[str, str | None]:
    """(encoder, warning or None) for this export, from CASEFILE_VIDEO_ENCODER."""
    want = (os.environ.get("CASEFILE_VIDEO_ENCODER") or "").strip().lower()
    if want in ("", "libx264", "x264", "software"):
        return "libx264", None
    if want not in ("videotoolbox", VIDEOTOOLBOX):
        return "libx264", f"CASEFILE_VIDEO_ENCODER={want!r} is not known (use videotoolbox or libx264); exported with libx264."
    ok, why = _encoder_works(VIDEOTOOLBOX)
    if not ok:
        return "libx264", f"The Apple VideoToolbox encoder is not available here ({why or 'test encode failed'}); exported with libx264."
    return VIDEOTOOLBOX, None


def video_codec_args(encoder: str, width: int, height: int, threads: str) -> list[str]:
    if encoder == VIDEOTOOLBOX:
        mbps = max(2, round(width * height * FPS * 0.25 / 1e6))  # 1080p: 12 Mb/s (above libx264 CRF 20 for this content)
        return ["-c:v", VIDEOTOOLBOX, "-b:v", f"{mbps}M", "-maxrate", f"{round(mbps * 1.5)}M", "-bufsize", f"{mbps * 2}M",
                "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", threads]


def machine(arch: str | None = None, cpuinfo: str | None = None) -> dict:
    """v0.4.48: what the render runs on. `emulated` is True when this is an
    Intel (x86-64) build running on another chip (e.g. an amd64 Docker image on
    an Apple-silicon Mac, translated by Rosetta or QEMU), which makes FFmpeg
    several times slower than a native build."""
    import platform

    arch = (arch or platform.machine()).lower()
    emulated = False
    if arch in ("x86_64", "amd64", "i386", "i686"):
        info = cpuinfo
        if info is None:
            try:
                info = Path("/proc/cpuinfo").read_text(errors="replace")
            except OSError:
                info = ""
        # Translated x86 programs still read the real (ARM) kernel's CPU list.
        emulated = bool(info) and (
            "CPU implementer" in info or "VirtualApple" in info or "vendor_id" not in info
        )
    return {"arch": arch, "cpus": available_cpus(), "emulated": emulated}


def machine_note(info: dict | None = None) -> str:
    """A short warning for progress messages, or "" when nothing is wrong."""
    info = info or machine()
    if info["emulated"]:
        return (" · Slow: CASEFILE is running as Intel (x86-64) code translated on another chip. "
                "Rebuild it for this Mac: docker build --platform linux/arm64 -t casefile-studio .")
    if info["cpus"] <= 2:
        return (f" · Only {info['cpus']} CPU{'s' if info['cpus'] > 1 else ''} available; "
                "renders are slow (Docker Desktop: Settings → Resources gives it more).")
    return ""


def render_workers(chains: int) -> int:
    """How many scenes to encode at the same time. Each scene's FFmpeg uses about
    two cores, so a Mac with 8-12 cores rendered one scene at a time left most of
    them idle. CASEFILE_RENDER_JOBS overrides (1 = the old one-at-a-time)."""
    forced = os.environ.get("CASEFILE_RENDER_JOBS", "").strip()
    if forced:
        try:
            return max(1, min(16, int(forced), chains))
        except ValueError:
            pass
    try:  # about 250 MB per 1080p scene encoder; keep well inside the memory there is
        mem_gb = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30
    except (ValueError, OSError, AttributeError):
        mem_gb = 4.0
    return max(1, min(chains, 6, available_cpus() // 2, int(mem_gb)))


def run_scenes(steps: list, chain_of: list, workers: int, progress: Callable, cancelled: Callable):
    """Run each scene's FFmpeg commands. Scenes in one chain (a transition blends
    in the previous scene's last frame) run in order; separate chains run side
    by side, `workers` at a time."""
    import threading
    from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait

    chains: dict[int, list[int]] = {}
    for i, head in enumerate(chain_of):
        chains.setdefault(head, []).append(i)
    total = len(steps)
    lock = threading.Lock()
    stop = threading.Event()
    stopped = lambda: stop.is_set() or cancelled()
    done = [0]
    seconds = [0.0] * total
    at_once = f" · {workers} at a time" if workers > 1 else ""

    def report():
        progress(5 + int(79 * done[0] / total), f"Rendering scenes · {done[0]} of {total} done{at_once}")

    def work(chain):
        for i in chain:
            started = time.monotonic()
            for cmd in steps[i]:
                if stopped():
                    raise RuntimeError("Cancelled by you. No output was published.")
                if callable(cmd):  # v0.4.79: a step done in Python (sportsgfx.behind_step)
                    cmd(stopped)
                else:
                    run(cmd, stopped)
            seconds[i] = time.monotonic() - started
            with lock:
                done[0] += 1
                report()

    report()
    if workers <= 1:
        for chain in chains.values():
            work(chain)
        return seconds
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scene") as pool:
        futures = [pool.submit(work, c) for c in chains.values()]
        finished, _ = wait(futures, return_when=FIRST_EXCEPTION)
        first = next((f.exception() for f in futures if f.done() and f.exception()), None)
        if first:
            stop.set()
            for f in futures:
                f.cancel()
            wait(futures)
            raise first
    return seconds


def timing_report(t: dict) -> str:
    """v0.4.48: render-report.txt — where the render's time went, slowest scenes first."""
    def mmss(x):
        x = float(x)
        return f"{int(x // 60)} min {x % 60:04.1f} s" if x >= 60 else f"{x:.1f} s"
    fx = t.get("effects") or {}
    used = [f"look {t.get('look')}"]
    if fx.get("grain"):
        used.append(f"film grain {fx['grain']} (costly: noise on every pixel, and harder to encode)")
    if fx.get("vignette"):
        used.append(f"vignette {fx['vignette']}")
    if fx.get("letterbox"):
        used.append("letterbox")
    if t.get("watermark"):
        used.append("watermark")
    if t.get("cta_events"):
        used.append(f"subscribe animation x{t['cta_events']}")
    if t.get("stickers"):
        used.append(f"stickers x{t['stickers']}")
    if t.get("sound_effects"):
        used.append(f"sound effects x{t['sound_effects']}")
    if t.get("motion_graphics"):
        mg = t["motion_graphics"]
        used.append(f"motion graphics x{len(mg)} ({sum(m['drawn'] for m in mg)} new drawings, "
                    f"{sum(m['unique'] - m['drawn'] for m in mg)} from the cache)")
    rows = t.get("per_scene") or []
    lines = [
        "CASEFILE render report",
        f"Machine: {t.get('arch')}, {t.get('cpus')} CPUs, {t.get('workers')} scene(s) at a time"
        + (f", encoder {t['encoder']}" if t.get("encoder") else "")
        + (" — RUNNING TRANSLATED (Intel code on another chip)" if t.get("emulated") else ""),
        f"Video: {mmss(t.get('video_seconds', 0))} at {t.get('resolution')}, {len(rows)} scenes",
        f"Total: {mmss(t.get('total', 0))} ({float(t.get('total', 0)) / max(0.01, float(t.get('video_seconds', 0) or 0.01)):.2f} x the video's length)",
        f"  preparing {mmss(t.get('prepare', 0))} · scenes {mmss(t.get('scenes', 0))} · joining {mmss(t.get('join', 0))}"
        f" · sound and MP4 {mmss(t.get('sound_and_mp4', 0))}",
        f"Settings: {', '.join(used)}",
    ]
    if t.get("warnings"):  # v0.4.55: what was left out, also in the report
        lines += ["", "Warnings:"] + [f"  - {w}" for w in t["warnings"]]
    lines += [
        "",
        "Slowest scenes (and seconds of work for each second of video):",
    ]
    ranked = sorted(rows, key=lambda r: -r.get("seconds", 0))
    for r in ranked[:25]:
        lines.append(f"  scene {r['n']:>3}  {r.get('seconds', 0):6.1f} s for {r.get('length', 0):5.1f} s"
                     f"  ({r.get('seconds', 0) / max(0.04, r.get('length', 0)):.2f}x)  {r.get('what', '')}  · {r.get('title', '')[:50]}")
    return "\n".join(lines) + "\n"


def asset_path(asset):
    try:
        p = resolve_asset(asset.get("path"))
    except ValueError:
        raise ValueError(
            "A referenced media file is missing. Re-upload it before rendering."
        )
    if not p.is_file():
        raise ValueError(
            "A referenced media file is missing. Re-upload it before rendering."
        )
    return p


# the music dips under the voice (narration and soundbites); the editor's preview computes the
# same dip from this same compressor (sound.duck_curve)
MUSIC_DUCK = "sidechaincompress=threshold=0.03:ratio=8:attack=30:release=800"


def music_duration(asset, path=None):
    """v0.4.58 The length of a music file (seconds): the stored one, else probed."""
    try:
        d = float(asset.get("duration") or 0)
    except (TypeError, ValueError):
        d = 0.0
    if d > 0:
        return d
    try:
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
                                          str(path or asset_path(asset))], capture_output=True, text=True, timeout=40).stdout)
        return float(info["format"]["duration"])
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, TypeError):
        return 0.0


def narration_volume(project):
    """v0.4.57 The narration level (1 = as recorded / as normalised; 0..2)."""
    try:
        v = float(project.get("narration_volume", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return 1.0 if v != v else round(min(2.0, max(0.0, v)), 3)


# v0.4.60 Each scene's slice re-timed from its own sample count before the concat. A slice wholly past
# the end of the recording (e.g. a scene reordered from beyond the narration's end) is empty: apad then
# pads it with frames that have no timestamp, the concat's timeline breaks ("Invalid data found when
# processing input") and FFmpeg stops the voice there with exit code 0 — the rest of the narration
# was lost (silence in the MP4). Only timestamps change: every other slice's samples are identical.
RESTAMP = "asetpts=N/SR/TB"
TREE_MARGIN = 2.0  # seconds kept around a group's scenes by its coarse trim: many whole frames


def _split_tree(head, cuts, tree):
    """The filters handing the narration [head] to each scene's trim as [vs0], [vs1], ...
    Plain (the export): one asplit to every scene. Each scene's atrim then receives every frame
    up to its end, so a 150-scene timeline moves the recording ~75 times through the graph (about
    20 s of a 25-minute analysis), and every frame waits in up to 150 queues.
    `tree` (v0.4.60, the analysis): the scenes in groups of ~sqrt(n), in timeline order; each group
    gets a coarse atrim covering its scenes' slices plus TREE_MARGIN on both sides, then splits to
    its scenes. The coarse trim only drops frames seconds away from any scene cut, and atrim cuts
    by each frame's own pts and length (a partly dropped frame keeps pts + length), so every scene
    trim sees exactly the frames, timestamps and samples it sees in the plain graph — including the
    1-sample pts rounding of asetpts=N/SR/TB that makes the cut points depend on frame boundaries,
    which is why scene slices are not merged into fewer trims instead."""
    n = len(cuts)
    if not tree or n <= 16:
        return [f"{head},asplit={n}" + "".join(f"[vs{i}]" for i in range(n))]
    size = math.ceil(math.sqrt(n))
    groups = [list(range(k, min(n, k + size))) for k in range(0, n, size)]
    out = [f"{head},asplit={len(groups)}" + "".join(f"[vg{j}]" for j in range(len(groups)))]
    for j, members in enumerate(groups):
        lo = min(cuts[i][0] for i in members) - TREE_MARGIN
        hi = max(cuts[i][1] for i in members) + TREE_MARGIN
        trim = f"atrim=start={lo:.3f}:end={hi:.3f}" if lo > 0 else f"atrim=end={hi:.3f}"
        out.append(f"[vg{j}]{trim},asplit={len(members)}" + "".join(f"[vs{i}]" for i in members))
    return out


# v0.4.61 Soundbites (Mode O audio breaks) are normalised once each, in their own short FFmpeg pass,
# and kept as 32-bit float WAV; the voice bus (export and the editor's ducking analysis) reads them
# back. The same filters on the same decoded frames, written as float: the bus gets exactly the samples
# the in-graph chain made (tests/test_audiobreak.py compares them), but no longer holds one loudnorm
# (~110-130 MB each: it works at 192 kHz) per soundbite in memory at the same time.
SOUNDBITE_V = 2  # part of each cached file's key: bump when the chain below changes
SOUNDBITE_KEEP_MB = 2048  # the cache folder is pruned to about this (oldest first; files in use kept)
_VOICE_FMT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"


def soundbite_length(scene):
    return round(float(scene["duration"]) * FPS) / FPS


def soundbite_chain(scene):
    """The filters that make a soundbite's part of the voice bus from its clip's audio (before the
    re-timing): its trim, loudness normalisation and fades, padded to the scene's length.
    v0.4.61 Re-timed from its sample count right after the loudnorm. loudnorm stamps its frames 0.1 s
    apart even when the last one before its flush is short, so its timestamps ran up to ~0.1 s ahead of
    its samples, and the fades and the trim to the scene's length (which go by timestamps) cut the end
    of the soundbite: it was up to ~0.1 s short, and everything after it in the voice bus (the
    narration resuming, later soundbites) came that much early against the picture, adding up over a
    film. A guide export of soundbites with no music or effects could be refused as too short. Exact
    when a soundbite's length is a multiple of 0.1 s (nothing was cut there); otherwise the soundbite
    now keeps its full length and its fade-out ends on its last frame."""
    length = soundbite_length(scene)
    a = float(scene.get("trim_start", 0))
    b = a + length
    fade = min(0.08, length / 4)
    fmt = _VOICE_FMT
    return (
        f"atrim=start={a}:end={b},asetpts=PTS-STARTPTS,{fmt},"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,{fmt},{RESTAMP},afade=t=in:d={fade},"
        f"afade=t=out:st={max(0, length - fade)}:d={fade},apad,atrim=duration={length}"
    )


def soundbite_folder():
    return DATA / "cache" / "soundbites"


def soundbite_job(scene, clip_path):
    """(cached file, FFmpeg command writing it to "{OUT}") for one soundbite scene. The file's name is
    a hash of the chain (trim, length, fades), the clip file (path, size, time) and SOUNDBITE_V."""
    import hashlib

    clip_path = Path(clip_path)
    st = clip_path.stat()
    chain = soundbite_chain(scene)
    key = hashlib.sha1(
        json.dumps([chain, str(clip_path), st.st_size, int(st.st_mtime), SOUNDBITE_V]).encode()
    ).hexdigest()[:24]
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(clip_path), "-filter_complex",
           f"[0:a]{chain}[sb]", "-map", "[sb]", "-c:a", "pcm_f32le", "-f", "wav", "{OUT}"]
    return soundbite_folder() / f"{key}.wav", cmd


def soundbite_tmp(path):
    return path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")


def prune_soundbites(keep=(), limit_mb=None):
    """Remove the oldest cached soundbites beyond SOUNDBITE_KEEP_MB (never those in `keep`)."""
    limit = (SOUNDBITE_KEEP_MB if limit_mb is None else limit_mb) * 2**20
    keep = {Path(k).resolve() for k in keep}
    try:
        files = sorted(soundbite_folder().glob("*.wav"), key=lambda q: q.stat().st_mtime, reverse=True)
        total = 0
        for q in files:
            total += q.stat().st_size
            if total > limit and q.resolve() not in keep:
                q.unlink(missing_ok=True)
    except OSError:
        pass


def prepare_soundbites(scenes, clip_paths, cancelled):
    """{scene index: cached soundbite file} for the export, each made now if it is not cached yet
    (one short FFmpeg pass per soundbite, one at a time). `clip_paths`: {scene index: clip file}."""
    out = {}
    for i in sorted(clip_paths):
        path, cmd = soundbite_job(scenes[i], clip_paths[i])
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = soundbite_tmp(path)
            try:
                run([str(tmp) if c == "{OUT}" else c for c in cmd], cancelled)
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
        try:
            os.utime(path)  # recently used: kept by the pruning
        except OSError:
            pass
        out[i] = path
    prune_soundbites(keep=out.values())
    return out


def voice_graph(project, scenes, total, voice_index, insert_inputs, stems=False, tree=False, prepared=False):
    """v0.4.57 The FFmpeg filters that make the voice bus [voice] (narration, and Mode O soundbites),
    exactly as the export mixes it. The editor preview's effects ducking is computed from this same
    graph (sound.duck_curve), so what you hear while editing is what the export does.
    The narration volume is applied to the narration only (soundbites keep their level); in the
    scene-sliced path it comes after the loudness normalisation, which would otherwise undo it.
    v0.4.59 `stems` (the editor's ducking analysis only, never the export): when the narration
    pauses for soundbites, [voice] is the narration alone and [voicei] the soundbites alone (each
    silent where the other plays — they never overlap), so a narration-volume change needs no new
    analysis of the timeline (sound.duck_curve).
    v0.4.60 `tree` (the editor's ducking analysis only, never the export): the scene-sliced
    narration is split in two levels (see _split_tree) instead of 150 ways: the same scene trims on
    the same frames, the same samples out, without every scene's trim seeing the whole recording.
    v0.4.61 `prepared`: the soundbite inputs are their cached files (prepare_soundbites), already
    trimmed, normalised and faded; only the re-timing is left to do here."""
    af = []
    if voice_index is None:
        return af
    v = narration_volume(project)
    nv = f"volume={v}," if v != 1.0 else ""
    nv_after = f",volume={v}" if v != 1.0 else ""
    # v0.4.19: narration timestamps are rebuilt from the sample count
    # (asetpts=N/SR/TB) instead of trusting the file's own timestamps. The
    # recording then plays back-to-back exactly as it sounds in any player,
    # even if the file has timestamp jumps (some MP3/CapCut/phone exports
    # do), which previously could shorten or cut the narration.
    if (
        voice_index is not None
        and insert_inputs
        and (project.get("episode") or {}).get("guide")
    ):
        # Narration pauses for each audio break and resumes at the same word.
        fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        segments, span, ncur = [], None, 0.0
        for i, scene in enumerate(scenes):
            length = round(float(scene["duration"]) * FPS) / FPS
            if scene.get("insert_audio"):
                if span:
                    segments.append(("n", span[0], span[1]))
                    span = None
                segments.append(("i", i, length))
            else:
                if span is None:
                    span = [ncur, 0.0]
                span[1] += length
                ncur += length
        if span:
            segments.append(("n", span[0], span[1]))
        n_count = sum(1 for g in segments if g[0] == "n")
        if n_count == 1:
            af.append(
                f"[{voice_index}:a]asetpts=N/SR/TB,{nv}{fmt},apad[nv0]"
            )
        else:
            labels = "".join(f"[nv{k}]" for k in range(n_count))
            af.append(
                f"[{voice_index}:a]asetpts=N/SR/TB,{nv}{fmt},apad,asplit={n_count}{labels}"
            )
        order, k = [], 0
        for g in segments:
            if g[0] == "n":
                start, length = g[1], g[2]
                af.append(
                    f"[nv{k}]atrim=start={start}:end={start + length},asetpts=PTS-STARTPTS,apad,atrim=duration={length}[vn{k}]"
                )
                order.append(f"[vn{k}]")
                k += 1
            else:
                _, i, length = g
                chain = fmt if prepared else soundbite_chain(scenes[i])
                af.append(f"[{insert_inputs[i]}:a]{chain},{RESTAMP}[vi{i}]")
                order.append(f"[vi{i}]")
        if stems:
            # the same segments, each stem silent where the other plays (sample-exact: the same trims)
            for name, keep in (("voice", "n"), ("voicei", "i")):
                parts, k = [], 0
                for j, g in enumerate(segments):
                    length = g[2]
                    src = f"[vn{k}]" if g[0] == "n" else f"[vi{g[1]}]"
                    k += g[0] == "n"
                    if g[0] == keep:
                        parts.append(src)
                    else:
                        af.append(f"anullsrc=r=48000:cl=stereo,{fmt},atrim=duration={length}[z{name}{j}]")
                        parts.append(f"[z{name}{j}]")
                af.append(f"{''.join(parts)}concat=n={len(parts)}:v=0:a=1,{fmt},atrim=duration={total}[{name}]")
        else:
            af.append(
                f"{''.join(order)}concat=n={len(order)}:v=0:a=1,{fmt},atrim=duration={total}[voice]"
            )
    elif voice_index is not None and (project.get("episode") or {}).get("guide"):
        # Guide projects retain the continuous uploaded recording, not a sequence
        # of regenerated or rearranged snippets. Only the last frame is padded.
        af.append(
            f"[{voice_index}:a]asetpts=N/SR/TB,{nv}aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,apad,atrim=duration={total}[voice]"
        )
    elif voice_index is not None:
        # Slice the master voice by scene before concatenating, so scene reorder
        # and trimming affect the narration as well as the picture.
        cuts = []
        cursor = 0.0
        for i, scene in enumerate(scenes):
            start = max(0, float(scene.get("audio_start", cursor)))
            length = max(
                0.04,
                min(
                    float(scene.get("audio_duration", scene["duration"])),
                    float(scene["duration"]),
                ),
            )
            duration = round(float(scene["duration"]) * FPS) / FPS
            cuts.append((start, start + length))
            af.append(
                f"[vs{i}]atrim=start={start}:end={start + length},asetpts=PTS-STARTPTS,apad,atrim=duration={duration},{RESTAMP}[va{i}]"
            )
            cursor += float(scene["duration"])
        af[:0] = _split_tree(f"[{voice_index}:a]asetpts=N/SR/TB", cuts, tree)
        joined = "".join(f"[va{i}]" for i in range(len(scenes)))
        af.append(
            f"{joined}concat=n={len(scenes)}:v=0:a=1,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11{nv_after}[voice]"
        )
    return af


def render(
    project: dict, options: dict, out: Path, progress: Callable, cancelled: Callable
):
    if (project.get("episode") or {}).get("guide"):
        import episode

        if ((project.get("episode") or {}).get("plan") or {}).get(
            "mode"
        ) == "inspection" and (
            not options.get("draft", True) or not options.get("allow_inspection")
        ):
            raise ValueError(
                "Inspection rendering requires explicit inspection-draft consent; it cannot produce a publication-cleared export."
            )
        blocked = [i for i in episode.issues(project) if i["blocks_draft"]]
        if blocked:
            raise ValueError(
                " ".join(i["title"] + ": " + i["detail"] for i in blocked[:2])
            )
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is not installed on the server.")
    scenes = project.get("scenes", [])
    if not scenes:
        raise ValueError("Build a timeline first.")
    aspect = effects.aspect_of(project)
    width, height = effects.frame_size(options["resolution"], aspect)
    assets = {a["id"]: a for a in project.get("assets", [])}
    draft = options.get("draft", True)
    # Keep scene timings at millisecond precision (HH:MM:SS,mmm); do not round
    # them to whole seconds. Rendered frames are still snapped to the 24 fps
    # frame boundary so adjoining scenes share an exact frame boundary.
    total = sum(round(float(s["duration"]) * FPS) / FPS for s in scenes)
    warnings: list[str] = []
    began = time.monotonic()
    scene_info: list[dict] = []  # v0.4.48: for the render report
    with tempfile.TemporaryDirectory(prefix="casefile-render-") as folder:
        work = Path(folder)
        placeholder = work / "placeholder.png"
        im = Image.new("RGB", (width, height), "#151c22")
        draw = ImageDraw.Draw(im)
        draw.text(
            (width * 0.055, height * 0.67),
            "VISUAL NEEDED",
            fill="#ad997a",
            font=get_font(height * 0.025, True),
        )
        draw.text(
            (width * 0.055, height * 0.73),
            "Add a licensed image or video to this scene.",
            fill="#71808a",
            font=get_font(height * 0.02),
        )
        im.save(placeholder)
        # v0.4.29: the subscribe call-to-action, drawn once, overlaid where it falls.
        cta_events = cta.events(project)
        cta_short = cta.cut_short(project)  # v0.4.49: these end early and fade out
        cta_dir = work / "cta"
        cta_cfg = cta.normalise(project.get("cta"))
        cta_file = None
        if cta_events and cta_cfg["source"] == "file":
            # v0.4.35: your own animated file (.mov/.webm with transparency, or .gif).
            try:
                cta_file = asset_path(assets.get(cta_cfg["file_id"]))
                if not Path(cta_file).exists():
                    raise OSError("the animation file is missing")
            except (ValueError, OSError, AttributeError, TypeError) as e:
                warnings.append(f"The subscribe animation was left out: {e}")
                cta_events = []
        elif cta_events:
            banner = assets.get(cta_cfg["asset_id"])
            try:
                cta.frames(project, asset_path(banner), width, height, cta_dir)
            except (ValueError, OSError, AttributeError) as e:
                warnings.append(f"The subscribe animation was left out: {e}")
                cta_events = []
        # v0.4.36: your logo watermark, drawn once at the export size.
        wm_png = None
        wm_cfg = watermark.active(project)
        if wm_cfg:
            try:
                wm_png = watermark.layer(project, asset_path(assets.get(wm_cfg["asset_id"])), width, height, work / "watermark.png")
            except (ValueError, OSError, AttributeError, TypeError) as e:
                warnings.append(f"The logo watermark was left out: {e}")
        # v0.4.49: your stickers, drawn once for the whole timeline.
        sticker_layers = []
        if project.get("stickers"):
            try:
                total_len = sum(max(1, round(float(s["duration"]) * FPS)) for s in scenes) / FPS
                sticker_layers = stickers.prepare(project, assets, width, height, work / "stickers", total_len, asset_path)
            except (ValueError, OSError, KeyError) as e:
                warnings.append(f"The stickers were left out: {e}")
        # v0.4.52: approved motion graphics, drawn once at the export size (cached by content).
        # v0.4.53: each one is a single transparent video (no PNG frames).
        sfx_placed = []  # v0.4.56: the sound effects placed (set when the audio is mixed)
        motion_layers, motion_hide = [], []
        if motiongfx.exported(project):
            progress(4, "Drawing the motion graphics")
            try:
                def background_of(it):  # your photo, or a still from your own footage (v0.4.53)
                    return motiongfx.background_path(project, it, DATA, asset_path)

                # v0.4.55: one graphic that cannot be drawn no longer takes the others with it.
                motion_failed = []
                motion_layers = motiongfx.prepare(project, width, height, DATA, work / "motion", background_of,
                                                  cancelled=cancelled, failed=motion_failed)
                for it, e in motion_failed:
                    warnings.append(f"The {motiongfx.describe(it)} was left out: {e}")
                motion_hide = motiongfx.caption_gaps(project)
                if motion_failed:  # no caption gap where no graphic is shown
                    gone = [(f["start"], f["end"]) for f, _ in motion_failed]
                    motion_hide = [g for g in motion_hide if not any(abs(g[0] - a) < 0.05 and abs(g[1] - b) < 0.05 for a, b in gone)]
                motiongfx.prune(DATA)  # the cache stays under ~2 GB (the oldest graphics go first)
                for t0, t1 in cta_events:
                    if any(t0 < m["end"] and t1 > m["start"] for m in motion_layers):
                        warnings.append("A motion graphic is on screen with the subscribe animation; the graphic covers it.")
                        break
            except (ValueError, OSError, KeyError) as e:
                warnings.append(f"The motion graphics were left out: {e}")
                motion_layers, motion_hide = [], []
        # v0.4.79 type behind the player (sports graphics): only with the optional segmentation model; without
        # it the behind layer is shown as it is (the type is in front of the player)
        behind_ok = False
        if any(layer.get("behind") for layer in motion_layers):
            from cinegfx.sports import matte as sports_matte
            behind_ok = sports_matte.available()
        scene_start = 0.0
        name_cards = effects.effective_lower_thirds(project)
        clips = []
        # v0.4.48: every scene's FFmpeg commands are prepared first, then run
        # several scenes at a time (run_scenes). A scene with a transition
        # blends in the previous scene's last frame, so it runs after it.
        blends = [
            effects.transition_length(s, float(s["duration"])) if i > 0 and effects.xfade_name(s) else 0.0
            for i, s in enumerate(scenes)
        ]
        chain_of: list[int] = []
        for i in range(len(scenes)):
            chain_of.append(chain_of[i - 1] if blends[i] > 0 else i)
        workers = render_workers(len(set(chain_of)))
        enc_threads = str(max(2, min(8, available_cpus() // workers)))
        encoder, enc_warning = video_encoder()
        if enc_warning:
            warnings.append(enc_warning)
        scene_steps: list[list[list[str]]] = []
        progress(5, f"Preparing {len(scenes)} scenes")
        for i, scene in enumerate(scenes):
            if cancelled():
                raise RuntimeError("Cancelled by you. No output was published.")
            # Retain the scene's millisecond-precision timing (HH:MM:SS,mmm);
            # snap only the encoded frame count to the 24 fps frame boundary.
            duration = float(scene["duration"])
            frames = max(1, round(duration * FPS))
            steps: list[list[str]] = []
            asset = assets.get(scene.get("asset_id"))
            src = (
                asset_path(asset)
                if asset and asset.get("kind") in ("image", "video")
                else placeholder
            )
            overlay = work / f"overlay{i}.png"
            overlay_image(project, scene, i, width, height, draft).save(overlay)
            outclip = work / f"{i:04d}.mp4"
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-filter_complex_threads",
                "1",
            ]
            motion = scene.get("motion", "slow-zoom")
            is_video = asset and asset.get("kind") == "video"
            is_image = asset and asset.get("kind") == "image"
            # v0.4.49: your keyframes replace the fixed photo movement.
            cam_keys = picture.normalise_keyframes(scene.get("keyframes"), duration) if (is_video or is_image) else []
            if cam_keys and is_image:
                motion = "keyframes"
            trim_start = max(0.0, float(scene.get("trim_start", 0)))
            asset_dur = float(asset.get("duration", 0) or 0) if asset else 0.0
            # Use the cue's original selected crop end (trim_start + cue duration)
            # when stored on the scene; otherwise fall back to scene duration.
            source_crop_end = scene.get("source_crop_end")
            crop_end = (
                max(trim_start, float(source_crop_end))
                if source_crop_end is not None
                else trim_start + duration
            )
            crop_end = min(crop_end, asset_dur)
            crop_len = max(0.0, crop_end - trim_start)
            video_input = str(src)
            video_extra: list[str] = []
            if is_video:
                if crop_len <= 0 or trim_start >= asset_dur:
                    # The selected source crop has no valid footage to play; warn and
                    # render the placeholder instead of a short/empty clip.
                    warnings.append(
                        f"Scene '{scene.get('title','')}': source crop has no footage "
                        f"(trim={trim_start:.3f}s, crop_end={crop_end:.3f}s, asset_end={asset_dur:.3f}s); "
                        f"rendering placeholder."
                    )
                    video_input = str(placeholder)
                elif trim_start + duration > crop_end + 1e-6:
                    # Loop rule (video only): repeat the exact selected crop
                    # [trim_start, crop_end] within the scene and trim the final
                    # repetition so the clip runs exactly `duration`.
                    reps = max(1, math.ceil(duration / crop_len))
                    crop = work / f"crop{i}.mp4"
                    # v0.4.48: seek on the input (-ss before -i). After -i, FFmpeg
                    # decoded the source from 0:00 up to the crop every time.
                    # Re-encoding still makes the cut exact to the frame.
                    steps.append(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-ss",
                            str(trim_start),
                            "-i",
                            str(src),
                            "-t",
                            str(crop_len),
                            "-c:v",
                            "libx264",
                            "-preset",
                            "veryfast",
                            "-crf",
                            "20",
                            "-an",
                            str(crop),
                        ]
                    )
                    listing = work / f"croploop{i}.txt"
                    listing.write_text("\n".join(f"file '{crop.as_posix()}'" for _ in range(reps)))
                    looped = work / f"croploop{i}.mp4"
                    steps.append(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-f",
                            "concat",
                            "-safe",
                            "0",
                            "-i",
                            str(listing),
                            "-c",
                            "copy",
                            str(looped),
                        ]
                    )
                    video_input = str(looped)
                else:
                    video_extra = ["-ss", str(trim_start)]
            # v0.4.48: a still picture with no motion is decoded and scaled once and
            # the frame repeated (loop filter below). Reading it with -loop 1 decoded
            # and scaled the full-size photo again for every frame: 4-5x slower.
            # (Also a VISUAL NEEDED gap card. The empty-crop fallback of a video scene
            # keeps -loop 1: its filters include fps=, which needs a stream of frames.)
            still = motion == "none" and (is_image or (not is_video and video_input == str(placeholder)))
            if still:
                video_extra = ["-framerate", str(FPS)]  # one frame, at the export frame rate
            elif motion == "none" and video_input == str(placeholder):
                # Every still input — a bound image, a VISUAL NEEDED gap card,
                # or the empty-crop placeholder fallback — must loop for the
                # full scene. Reading one PNG is a single frame, which would
                # silently shorten the exported video and fail the final
                # narration-coverage check.
                video_extra = ["-loop", "1", "-framerate", str(FPS)]
            command += video_extra + ["-i", video_input]
            # v0.4.49: the media file's crop (only the real photo), then how the
            # scene fills the frame: cover, or the photo over a blur of itself.
            footage = (is_video or is_image) and video_input != str(placeholder)
            fit = picture.fit_of(project, scene, asset) if footage else "cover"
            vf = (picture.crop_filter(picture.crop_of(asset)) if footage else "") + picture.fit_filter(fit, width, height)
            if is_video:
                # v0.4.54: tpad holds the last frame (at most 1 s) when the
                # footage ends right at the scene's end — a looped crop, or a
                # clip used to its last frame. With "photo over a blur" the
                # overlay ends the stream at its last frame's START, so fps=
                # gave one frame too few and every later scene ran 1/24 s
                # early against the narration. -frames:v still cuts the scene
                # to its exact length, so a long enough clip is unchanged.
                vf += f",fps={FPS},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop={FPS},setsar=1"
                if cam_keys and footage:
                    vf += "," + picture.camera_filter(cam_keys, width, height, frames, still=False) + ",setsar=1"
            elif motion == "keyframes":
                vf += "," + picture.camera_filter(cam_keys, width, height, frames, still=True) + ",setsar=1"
            elif motion != "none":
                last = max(1, frames - 1)
                yp = "ih/2-ih/zoom/2"
                if motion == "pan-up":
                    z, xp, yp = "1.08", "iw/2-iw/zoom/2", f"(ih-ih/zoom)*(1-on/{last})"
                elif motion == "pan-down":
                    z, xp, yp = "1.08", "iw/2-iw/zoom/2", f"(ih-ih/zoom)*(on/{last})"
                elif motion == "ken-burns":
                    z, xp = f"1+0.1*on/{last}", f"(iw-iw/zoom)*(0.35+0.3*on/{last})"
                elif motion == "slow-zoom":
                    z = f"1+0.075*on/{last}"
                    xp = "iw/2-iw/zoom/2"
                elif motion == "slow-zoom-out":
                    z = f"1.075-0.075*on/{last}"
                    xp = "iw/2-iw/zoom/2"
                elif motion == "pan-right":
                    z = "1.08"
                    xp = f"(iw-iw/zoom)*(on/{last})"
                else:  # pan-left
                    z = "1.08"
                    xp = f"(iw-iw/zoom)*(1-on/{last})"
                vf += f",zoompan=z='{z}':x='{xp}':y='{yp}':d={frames}:s={width}x{height}:fps={FPS},setsar=1"
            else:
                vf += ",setsar=1"
            if still:
                vf += ",loop=loop=-1:size=1"
            for part in effects.picture_filters(project.get("look", "noir"), project.get("effects"), width, height):
                vf += "," + part
            command += ["-i", str(overlay)]
            # v0.4.26: the picture (with its look) is built first. A transition
            # blends the previous scene's last PICTURE frame into it, and the
            # titles and captions are drawn on top afterwards, so text never
            # blends with the previous scene's text.
            xfade = effects.xfade_name(scene)
            blend = blends[i]
            keep_last = i + 1 < len(scenes) and bool(effects.xfade_name(scenes[i + 1]))
            # Number frames in order (never drop or repeat one) so every scene
            # keeps its exact frame count, with or without a transition.
            # v0.4.54: FFmpeg 7.0 marks the frame rate unknown (1/0) after
            # setpts, and xfade refuses that ("The inputs needs to be a constant
            # frame rate"), so every export with a transition failed. fps= states
            # the rate again (the timestamps are already 1/FPS apart, so no frame
            # is dropped or repeated) and settb puts back the time base xfade
            # compares. The previous scene's frame [prev] needs neither setpts nor
            # fps: -loop 1 -framerate numbers it at FPS already, and fps= there
            # made FFmpeg 6's xfade end the blend one frame early and shift the
            # rest of the scene a frame late.
            filters = f"[0:v]{vf},format=yuv420p,settb=AVTB,setpts=N/{FPS}/TB,fps={FPS},settb=AVTB[pic0]"
            if blend > 0:
                command += ["-loop", "1", "-framerate", str(FPS), "-t", f"{blend:.3f}", "-i", str(work / f"last{i - 1}.jpg")]
                filters += (
                    f";[2:v]scale={width}:{height},setsar=1,format=yuv420p,settb=AVTB[prev]"
                    f";[prev][pic0]xfade=transition={xfade}:duration={blend:.3f}:offset=0[pic1]"
                )
            else:
                filters += ";[pic0]null[pic1]"
            if keep_last:
                filters += ";[pic1]split[pic][lastpic]"
            else:
                filters += ";[pic1]null[pic]"
            filters += ";[pic][1:v]overlay=0:0:format=auto"
            scene_len = frames / FPS
            for t0, t1 in cta_events:
                a, b = max(t0, scene_start), min(t1, scene_start + scene_len)
                if b - a < 1 / FPS:
                    continue
                k = command.count("-i")
                ra, rb = a - scene_start, b - scene_start
                # v0.4.49: a place cut short (its own length, the end of its scene
                # or the next place) fades the animation out instead of stopping.
                early = ""
                if (t0, t1) in cta_short:
                    fo = cta.fade_out_seconds(t0, t1)
                    fs = t1 - fo  # when the fade starts, on the timeline
                    if fs < b:
                        # at the export frame rate first, so a 12 or 25 fps file fades smoothly
                        early = f",fps={FPS}" + cta.fade_filter(a, t1, fo, ra)
                if cta_cfg["style"] == "blur":
                    # Blur (and slightly darken) the video behind for these seconds, fading in and out.
                    bs = cta.SPEC["blur"]
                    rad = max(2, round(min(width, height) * bs["radius"]))
                    fi = min(bs["fade_in"], (t1 - t0) / 3)
                    fo = min(bs["fade_out"], (t1 - t0) / 3)
                    fades = ""
                    if a <= t0 + 1e-6:
                        fades += f",fade=t=in:st={ra:.3f}:d={fi:.3f}:alpha=1"
                    if b >= t1 - 1e-6:
                        fades += f",fade=t=out:st={max(ra, rb - fo):.3f}:d={fo:.3f}:alpha=1"
                    filters += (
                        f"[blin{k}];[blin{k}]split[blm{k}][blb{k}];"
                        f"[blb{k}]boxblur={rad}:2,eq=brightness={bs['brightness']},format=yuva420p{fades}[blz{k}];"
                        f"[blm{k}][blz{k}]overlay=0:0:enable='between(t,{ra:.3f},{rb:.3f})':format=auto"
                    )
                if cta_file:
                    if a - t0 > 0.001:
                        command += ["-ss", f"{a - t0:.3f}"]
                    command += cta.alpha_decoder(cta_file) + ["-i", str(cta_file)]
                    fw = round(width * cta_cfg["size"] / 2) * 2
                    filters += (
                        f"[ctab{k}];[{k}:v]scale={fw}:-2:flags=lanczos,format=rgba,"
                        f"setpts=PTS-STARTPTS+{ra:.3f}/TB{early}[ctav{k}];"
                        f"[ctab{k}][ctav{k}]overlay=x='min(max(0,{cta_cfg['x']}*W-w/2),W-w)':y='min(max(0,{cta_cfg['y']}*H-h/2),H-h)':"
                        f"eof_action=pass:enable='between(t,{ra:.3f},{rb:.3f})':format=auto"
                    )
                else:
                    command += ["-framerate", str(FPS), "-start_number", str(round((a - t0) * FPS)), "-i", str(cta_dir / "f%04d.png")]
                    filters += (
                        f"[ctab{k}];[{k}:v]format=rgba,setpts=PTS-STARTPTS+{ra:.3f}/TB{early}[ctav{k}];"
                        f"[ctab{k}][ctav{k}]overlay=0:0:eof_action=pass:enable='between(t,{ra:.3f},{rb:.3f})':format=auto"
                    )
            for layer in sticker_layers:
                k = command.count("-i")
                got = stickers.overlay_filters(layer, k, scene_start, scene_len, width, height)
                if got:
                    command += got[0]
                    filters += got[1]
            behind_steps = []
            for layer in motion_layers:
                if layer.get("behind") and behind_ok:
                    # v0.4.79 a sports graphic's behind layer: the player is cut out of it on this scene's own
                    # picture (same crop, fit, zoom and look), in a step before the scene's command
                    a, b = max(layer["start"], scene_start), min(layer["end"], scene_start + scene_len)
                    if b - a >= 1 / FPS:
                        fa, fb = round((a - scene_start) * FPS), round((b - scene_start) * FPS)
                        mw, mh = sportsgfx.matte_size(width, height)
                        tag = f"{i}_{motion_layers.index(layer)}"
                        pic_raw = work / f"mpic{tag}.rgb"
                        pic_cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *video_extra, "-i", video_input,
                                   "-filter_complex", f"[0:v]{vf},format=rgb24,setpts=N/{FPS}/TB,trim=start_frame={fa}:end_frame={fb},"
                                   f"setpts=PTS-STARTPTS,scale={mw}:{mh}[m]", "-map", "[m]", "-frames:v", str(max(1, fb - fa)),
                                   "-f", "rawvideo", "-pix_fmt", "rgb24", str(pic_raw)]
                        try:
                            st = Path(src).stat()
                            src_sig = [str(src), st.st_size, int(st.st_mtime)]
                        except OSError:
                            src_sig = [str(src)]
                        key = hashlib.sha1(json.dumps([sportsgfx.ENGINE, src_sig, video_extra, video_input == str(src),
                                                       trim_start, crop_len, vf, fa, fb, mw, mh, FPS]).encode()).hexdigest()[:20]
                        cut = work / f"behind{tag}.mov"
                        behind_steps.append(sportsgfx.behind_step(layer, a, b, scene_start, pic_cmd, pic_raw, key, cut,
                                                                  width, height, DATA, warnings))
                        layer = {"start": scene_start + fa / FPS, "end": scene_start + fb / FPS, "file": cut}
                k = command.count("-i")
                got = motiongfx.overlay_filters(layer, k, scene_start, scene_len)
                if got:
                    command += got[0]
                    filters += got[1]
            if wm_png:
                k = command.count("-i")
                command += ["-i", str(wm_png)]
                filters += f"[wmb{k}];[wmb{k}][{k}:v]overlay=0:0:format=auto"
            want_captions = options.get("captions", True) and bool(scene.get("narration") or scene.get("captions"))
            if want_captions or i in name_cards:
                ass = work / f"{i}.ass"
                hide = [(max(0.0, a - scene_start), min(scene_len, b - scene_start)) for a, b in motion_hide
                        if a < scene_start + scene_len and b > scene_start]
                write_ass(scene, ass, width, height, project.get("caption_style"), want_captions, name_cards.get(i, False), hide)
                filters += "," + captionstyle.filter_arg(ass.as_posix())
            # Optional transitions (off by default). A transition fades this scene in at
            # its start and out at its end over `transition_duration` seconds. It never
            # moves the scene boundary, narration, captions, or the project duration.
            has_footage = is_video or is_image
            trans = effects.transition_id(scene.get("transition", "none"))
            trans_dur = max(0.0, min(float(scene.get("transition_duration", 0) or 0), duration))
            if trans == "fade" and trans_dur > 0 and has_footage:
                filters += f",fade=t=in:st=0:d={trans_dur:.3f}"
                fade_out_start = max(0.0, duration - trans_dur)
                filters += f",fade=t=out:st={fade_out_start:.3f}:d={trans_dur:.3f}"
            elif trans == "fade":
                warnings.append(
                    f"Scene '{scene.get('title','')}': '{trans}' cannot fade a placeholder "
                    f"or gap; no footage to apply it to."
                )
            filters += ",format=yuv420p[v]"
            command += [
                "-filter_complex",
                filters,
                "-map",
                "[v]",
                "-an",
                "-frames:v",
                str(frames),
                "-r",
                str(FPS),
                *video_codec_args(encoder, width, height, enc_threads),
                "-video_track_timescale",
                "12288",
                str(outclip),
            ]
            if keep_last:
                # The next scene blends in from this scene's last picture frame.
                # (written over on every frame, so the file ends as the last one)
                command += ["-map", "[lastpic]", "-frames:v", str(frames), "-update", "1", "-q:v", "2", str(work / f"last{i}.jpg")]
            looped = len(steps) > 1
            steps.extend(behind_steps)
            steps.append(command)
            scene_steps.append(steps)
            if is_video or is_image:
                what = f"{asset.get('width') or '?'}x{asset.get('height') or '?'} {asset['kind']}"
            else:
                what = "gap card"
            extras = [motion if not is_video else "", "looped crop" if looped else "",
                      f"transition {blend:.1f}s" if blend > 0 else ""]
            scene_info.append({"n": i + 1, "title": scene.get("title", ""), "length": frames / FPS,
                               "what": ", ".join(x for x in [what, *extras] if x and x != "none")})
            clips.append(outclip)
            scene_start += frames / FPS
        prepared = time.monotonic()
        per_scene = run_scenes(scene_steps, chain_of, workers, progress, cancelled)
        scenes_done = time.monotonic()
        for row, secs in zip(scene_info, per_scene):
            row["seconds"] = round(secs, 2)
        progress(86, "Assembling the timeline")
        listing = work / "concat.txt"
        listing.write_text("\n".join(f"file '{p.as_posix()}'" for p in clips))
        stitched = work / "picture.mp4"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                str(stitched),
            ],
            cancelled,
        )
        t_joined = time.monotonic()
        progress(92, "Mixing audio and preparing the MP4")
        narration = assets.get(project.get("narration_id"))
        music = assets.get(project.get("music_id"))
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-filter_complex_threads",
            "1",
            "-i",
            str(stitched),
        ]
        inputs = 1
        voice_index = music_index = None
        if narration and narration.get("has_audio", narration.get("kind") == "audio"):
            voice_index = inputs
            command += ["-i", str(asset_path(narration))]
            inputs += 1
        music_args, music_filters = [], []
        music_settings = musiclib.normalise(project.get("music"))
        if music:
            # v0.4.58: the music settings say where the track plays and which part of it; every
            # pass is a reference to the original file (no copies), cut to the timeline
            mpath = asset_path(music)
            mlay = musiclib.layout(music_settings, music_duration(music, mpath), total, scenes)
            music_args, music_filters = musiclib.filters(mlay, mpath, inputs, total)
            if music_filters:
                music_index = inputs
                command += music_args
                inputs += music_args.count("-i")
        # Mode O: each producer-cleared audio break plays its own clip's sound.
        insert_inputs, clip_paths = {}, {}
        for i, scene in enumerate(scenes):
            if scene.get("insert_audio"):
                clip = assets.get(scene.get("asset_id"))
                if voice_index is None or not clip or not clip.get("has_audio"):
                    raise RuntimeError(
                        "An audio break needs the narration and a linked file with an audio track."
                    )
                clip_paths[i] = asset_path(clip)
        soundbites = {}
        if clip_paths and (project.get("episode") or {}).get("guide"):
            # v0.4.61 each soundbite normalised once, in its own short pass (cached); the voice bus
            # reads them back instead of running one loudnorm per soundbite at the same time
            progress(92, "Preparing the soundbites")
            soundbites = prepare_soundbites(scenes, clip_paths, cancelled)
        for i in sorted(clip_paths):
            insert_inputs[i] = inputs
            command += ["-i", str(soundbites.get(i, clip_paths[i]))]
            inputs += 1
        # v0.4.56: the sound design layer (A4): one stem with every approved effect in place.
        sfx_index, sfx_placed = None, []
        sfx_settings = sfx.normalise(project.get("sound"))
        if sfx_settings["enabled"]:
            progress(93, "Placing the sound effects")
            try:
                stem_path, sfx_placed, gone = sfx.stem(project, DATA, total, work, cancelled)
                for it, why in gone:
                    warnings.append(f"A sound effect ({it['label'] or it['sound']}) was left out: {why}.")
                if stem_path:
                    sfx_index = inputs
                    command += ["-i", str(stem_path)]
                    inputs += 1
                sfx.prune(DATA)
            except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as e:
                warnings.append(f"The sound effects were left out: {e}")
                sfx_index, sfx_placed = None, []
        volume = min(0.5, max(0, float(project.get("music_volume", 0.12))))
        af = []
        bites_cached = bool(soundbites)  # not `prepared`: that name holds the timing mark above
        vgraph = voice_graph(project, scenes, total, voice_index, insert_inputs, prepared=bites_cached)
        if voice_index is not None and (music_index is not None or sfx_index is not None) and (
                bites_cached or any("loudnorm" in g for g in vgraph)):
            # v0.4.59 The voice bus is made first, in its own pass. loudnorm hands over its last 3 s
            # only when its input ends; mixed in the same graph as the music or the effects, the
            # compressors and amix ended with the other inputs, and the export's whole audio
            # (narration included) stopped ~2.9 s before the picture. Read back from a file it
            # arrives in step with the rest. 32-bit float: the voice samples are exactly the same.
            # v0.4.61 also with cached soundbites (their loudnorm ran in their own passes): the same
            # bus, made the same way, so the export's samples are unchanged.
            progress(94, "Preparing the narration")
            nin = {i: 1 + k for k, i in enumerate(sorted(insert_inputs))}
            pre = ["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", str(asset_path(narration))]
            for i in sorted(insert_inputs):
                pre += ["-i", str(soundbites.get(i, clip_paths[i]))]
            bus = work / "voice.wav"
            pre += ["-filter_complex", ";".join(voice_graph(project, scenes, total, 0, nin, prepared=bites_cached)) + ";[voice]aresample=48000,"
                    "aformat=sample_fmts=flt:sample_rates=48000:channel_layouts=stereo,apad,"
                    f"atrim=end_sample={round(total * 48000)}[vbus]", "-map", "[vbus]", "-c:a", "pcm_f32le", str(bus)]
            run(pre, cancelled)
            command += ["-i", str(bus)]
            vgraph = [f"[{inputs}:a]anull[voice]"]
            inputs += 1
        af += vgraph
        music_duck = music_settings["duck"]
        if music_index is not None:
            af += music_filters
            af.append(f"[mus]volume={volume}[bed]")
        if sfx_index is not None:
            # narration (and soundbites) first and untouched; the music and the effects ducked under it
            duck = sfx_settings["duck"] and voice_index is not None
            if voice_index is not None:
                outs = "[main]" + ("[side]" if music_index is not None and music_duck else "") + ("[fxkey]" if duck else "")
                af.append(f"[voice]asplit={outs.count('[')}{outs}" if outs.count("[") > 1 else "[voice]anull[main]")
            if voice_index is not None and music_index is not None:
                af.append(f"[bed][side]{MUSIC_DUCK}[ducked]" if music_duck else "[bed]anull[ducked]")
            af += sfx.mix_filters(sfx_index, total, "[fxkey]" if duck else None, duck)
            parts = (["[main]"] if voice_index is not None else []) + (
                (["[ducked]"] if voice_index is not None else ["[bed]"]) if music_index is not None else []) + ["[fx]"]
            if len(parts) > 1:
                af.append(f"{''.join(parts)}amix=inputs={len(parts)}:duration=first:normalize=0,{SFX_LIMIT}[aout]")
            else:
                af.append(f"[fx]{SFX_LIMIT}[aout]")
            audio = "[aout]"
        elif voice_index is not None and music_index is not None:
            af += [
                "[voice]asplit=2[main][side]",
                f"[bed][side]{MUSIC_DUCK}[ducked]",
                f"[main][ducked]amix=inputs=2:duration=first:normalize=0,{SFX_LIMIT}[aout]",
            ] if music_duck else [
                f"[voice][bed]amix=inputs=2:duration=first:normalize=0,{SFX_LIMIT}[aout]",
            ]
            # v0.4.58: the same transparent limiter as the effects mix — the default alimiter delayed
            # the narration and soundbites by 239 samples (5 ms) and raised them ~0.45 dB whenever
            # music played without effects
            audio = "[aout]"
        elif voice_index is not None:
            audio = "[voice]"
        elif music_index is not None:
            audio = "[bed]"
        else:
            audio = None
        command += ["-map", "0:v:0", "-c:v", "copy"]
        if audio:
            command += [
                "-filter_complex",
                ";".join(af),
                "-map",
                audio,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
            ]
        command += ["-t", str(total), "-movflags", "+faststart", str(out)]
        run(command, cancelled)
        progress(99, "Writing captions and export notes")
        mixed = time.monotonic()
    if (project.get("episode") or {}).get("guide"):
        finished = probe(out)
        video_seconds = finished.get("video_duration") or finished["duration"]
        audio_seconds = finished.get("audio_duration") or finished["duration"]
        if (
            not finished["has_audio"]
            or abs(video_seconds - total) > 1 / FPS + 0.01
            or audio_seconds < total - 0.05
        ):
            raise RuntimeError(
                "The rendered video/audio does not cover the complete planned narration. No export was accepted; inspect the source files and retry."
            )
    return {
        "duration": total,
        "resolution": options["resolution"],
        "audio": bool(audio),
        "size": out.stat().st_size,
        "warnings": warnings,
        "timing": {
            **machine(),
            "workers": workers,
            "encoder": encoder,
            "total": round(time.monotonic() - began, 1),
            "prepare": round(prepared - began, 1),
            "scenes": round(scenes_done - prepared, 1),
            "join": round(t_joined - scenes_done, 1),
            "sound_and_mp4": round(mixed - t_joined, 1),
            "video_seconds": round(total, 2),
            "resolution": options["resolution"],
            "look": project.get("look", "noir"),
            "effects": effects.normalise_effects(project.get("effects")),
            "watermark": bool(wm_png),
            "cta_events": len(cta_events),
            "stickers": len(sticker_layers),
            "motion_graphics": [{k: m[k] for k in ("id", "frames", "unique", "drawn")} for m in motion_layers],
            "sound_effects": len(sfx_placed),
            "per_scene": scene_info,
            "warnings": list(warnings),
        },
    }
