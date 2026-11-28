"""The sports edit: shots + context-aware transitions + persistent graphics -> frames, sound and an MP4.

Compositing order per frame (independent foreground / type / background):
  footage (graded per shot, transition between shots)
  -> BEHIND type layer, multiplied by (1 - person matte): the player occludes it
  -> FRONT type layer
  -> frame fx requested by graphics (RGB split, glitch) and by transitions
  -> film finish (warm vignette, lifted blacks, grain, dust, faint streaks)

Speed (Apple M1, 8 cores): the timeline is cut into chunks at shot boundaries; each chunk is rendered by its
own worker straight into an H.264 segment (VideoToolbox when FFmpeg has it, else libx264) and cached under a
hash of everything that affects its pixels. Changing one graphic re-renders only the chunks it touches; the
segments are joined without re-encoding. Mattes are cached per shot (matte.py). Audio is mixed once at
48 kHz from the same timeline, so picture and sound cannot drift.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .. import anim
from ..core import Cue
from ..timing import ffbin
from . import families as F
from . import footage as FT
from . import fx as FX
from . import matte as M
from . import score as SC

ENGINE_VERSION = "sports-0.4.77-3"
MATTE_H = 360


@dataclass
class Transition:
    kind: str = "cut"          # cut | dissolve | luma | push | dip | glitch
    dur: float = 0.0
    direction: int = 1
    why: str = ""


@dataclass
class Natural:
    src: str
    t_src: float
    at: float
    dur: float
    gain_db: float = -18.0


class Edit:
    def __getstate__(self):  # the memoised mix stays in the parent process (workers only draw frames)
        d = dict(self.__dict__)
        d.pop("_mix_memo", None)
        return d

    def __init__(self, W=1920, H=1080, fps=25, cache_dir="cache"):
        self.W, self.H, self.fps = W, H, fps
        self.cache = Path(cache_dir)
        self.shots: list[FT.Shot] = []
        self.trans: dict[int, Transition] = {}     # index i: the transition INTO shot i
        self.elements = []                          # semantics.Element
        self.families = []
        self.narration: list[tuple[str, float]] = []
        self.music: list[tuple[float, float, str]] = []
        self.natural: list[Natural] = []
        self.cues: list[Cue] = []
        self.handle = 0.6                           # seconds of source kept either side of each shot
        self._mattes = {}

    # ---------------------------------------------------------------- building
    def add(self, shot: FT.Shot, transition: Transition | None = None, at: float | None = None):
        shot.start = at if at is not None else (self.shots[-1].end if self.shots else 0.0)
        if transition:
            self.trans[len(self.shots)] = transition
        self.shots.append(shot)
        return shot

    def cut_at(self, t: float):
        """Snap the end of the last shot to t (cuts are placed on words, not on shot lengths)."""
        self.shots[-1].dur = round(t - self.shots[-1].start, 4)

    def set_elements(self, elements):
        self.elements = elements
        self.families = [F.make(e, self.W, self.H, self.fps) for e in elements]

    @property
    def duration(self):
        return self.shots[-1].end if self.shots else 0.0

    @property
    def nframes(self):
        return int(round(self.duration * self.fps))

    # ---------------------------------------------------------------- transitions (context-aware)
    def auto_transitions(self):
        """Fill in transitions that were not set by hand, from the story context at each cut:
        into a minimal/flashback beat -> slow dissolve; out of it -> hard cut (with an impact);
        after a headline exits -> RGB glitch on the incoming shot; out of an impact stat -> luma matte;
        into archive/photo material -> dip; otherwise a hard cut (the default in this style)."""
        for i in range(1, len(self.shots)):
            if i in self.trans:
                continue
            c = self.shots[i].start
            prev, nxt = self.shots[i - 1], self.shots[i]
            fam_in = [f for f in self.families if f.t_in - 0.6 <= c <= f.t_in + 0.6]
            fam_out = [f for f in self.families if f.t_out - 0.1 <= c <= f.t_out + 0.6]
            if any(f.el.family == "minimal" for f in fam_in) or nxt.grade == "low_key" and prev.grade != "low_key":
                self.trans[i] = Transition("dissolve", 0.5, why="into a quiet storytelling beat")
            elif nxt.photo and not prev.photo:
                self.trans[i] = Transition("dissolve", 0.6, why="into archive material")
            elif prev.photo and not nxt.photo:
                self.trans[i] = Transition("cut", why="back to the present: hard cut")
                self.cues.append(Cue(c, "impact-tr-2", -6, "hard cut back to the match"))
            elif any(f.el.family == "headline" and not f.d.get("quote") for f in fam_out):
                self.trans[i] = Transition("glitch", 0.12, why="headline exit")
            elif any(f.el.family == "impact" for f in fam_out):
                self.trans[i] = Transition("luma", 0.28, why="out of the single-stat impact")
            else:
                self.trans[i] = Transition("cut", why="hard cut")

    # ---------------------------------------------------------------- mattes
    def prepare_mattes(self, log=print, compute=True, progress=None):
        """Person mattes for the shots marked `matte` (cached). compute=False uses only cached ones."""
        if not M.available():
            log(f"mattes off: {M.unavailable_reason()} (type is drawn in front instead)")
            return
        todo = [k for k, s in enumerate(self.shots) if s.matte]
        for n, k in enumerate(todo):
            s = self.shots[k]
            if progress:
                progress(n, len(todo))
            if s.photo:
                im = Image.open(s.src).convert("RGB")
                w = M.MATTE_W
                h = int(im.height * w / im.width)
                small = np.asarray(im.resize((w, h), Image.BILINEAR))
                key = M.cache_key(s.src, os.path.getsize(s.src), w, "still")
                f = self.cache / f"matte-{key}-{M.net().id}.npy"
                if not f.exists():
                    if not compute:
                        continue
                    self.cache.mkdir(parents=True, exist_ok=True)
                    np.save(f, M.still(small))
                a = np.load(f)
                self._mattes[k] = ("photo", np.asarray(Image.fromarray(a).resize(im.size, Image.BILINEAR)))
                continue
            pre, post = self._handles(k)
            hs = FT.Shot(**{**asdict(s), "t_src": s.t_src - pre * s.speed, "dur": s.dur + pre + post})
            mw, mh = M.MATTE_W, MATTE_H

            def frames_fn(hs=hs, mw=mw, mh=mh):
                r = FT.Reader(hs, mw, mh, self.fps)
                return list(r.all())
            path = M.shot_mattes(frames_fn, self.cache, (s.src, os.path.getsize(s.src), round(hs.t_src, 4), round(hs.dur, 4),
                                                         s.speed, s.frame, self.fps), compute=compute)
            if path is not None:
                self._mattes[k] = ("video", path, int(round(pre * self.fps)))
                log(f"  matte ready: shot {k} ({s.tag})")

    def _handles(self, k):
        s = self.shots[k]
        pre = min(self.handle, max(0.0, s.t_src / max(1e-6, s.speed)))
        return pre, self.handle

    # ---------------------------------------------------------------- frame
    def shot_at(self, t):
        for k, s in enumerate(self.shots):
            if s.start <= t < s.end:
                return k
        return len(self.shots) - 1

    def _matte_small(self, k, local_i):
        m = self._mattes.get(k)
        if not m or m[0] != "video":
            return None
        arr = _load(m[1])
        j = max(0, min(len(arr) - 1, local_i + m[2]))
        return arr[j]

    def occlusion(self, t, box):
        """Share of the normalised box (x0, y0, x1, y1) hidden by the matted person at t (0 with no matte)."""
        k = self.shot_at(t)
        s = self.shots[k]
        a = self._matte_small(k, int(round((t - s.start) * self.fps)))
        if a is None:
            return 0.0
        h, w = a.shape[:2]
        x0, y0, x1, y1 = box
        sub = np.asarray(a[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))],
                         np.float32)
        return float(sub.mean()) / 255 if sub.size else 0.0

    def subject(self, t):
        """{"head_x", "head_y", "cover"} of the matted person in the shot at t (normalised), or None."""
        k = self.shot_at(t)
        s = self.shots[k]
        a = self._matte_small(k, int(round((t - s.start) * self.fps)))
        if a is None:
            return None
        a = np.asarray(a, np.float32) / 255
        cover = float(a.mean())
        if cover < 0.02:
            return None
        rows = np.nonzero(a.max(axis=1) > 0.5)[0]
        if not len(rows):
            return None
        top = rows[0]
        band = a[top: top + max(4, int(a.shape[0] * 0.18))]
        xs = np.nonzero(band.max(axis=0) > 0.5)[0]
        hx = float(xs.mean()) / a.shape[1] if len(xs) else 0.5
        x0 = float(xs.min()) / a.shape[1] if len(xs) else hx
        x1 = float(xs.max()) / a.shape[1] if len(xs) else hx
        return {"head_x": hx, "head_x0": x0, "head_x1": x1, "head_y": top / a.shape[0], "cover": cover}


@lru_cache(maxsize=16)
def _load(path):
    return np.load(path, mmap_mode="r")


# ====================================================================== rendering (worker side)
class _Renderer:
    def __init__(self, edit: Edit):
        self.e = edit
        self.readers = {}

    def _reader(self, k):
        if k not in self.readers:
            e = self.e
            s = e.shots[k]
            pre, post = e._handles(k)
            hs = FT.Shot(**{**asdict(s), "t_src": s.t_src - pre * s.speed, "dur": s.dur + pre + post})
            matte = e._mattes.get(k)
            r = FT.reader(hs, e.W, e.H, e.fps, matte[1] if matte and matte[0] == "photo" else None)
            self.readers[k] = (r, int(round(pre * e.fps)))
        return self.readers[k]

    def shot_frame(self, k, t):
        e = self.e
        s = e.shots[k]
        r, off = self._reader(k)
        i = int(round((t - s.start) * e.fps))
        img = r.get(i + off)
        return FT.grade(img, s.grade)

    def matte(self, k, t):
        e = self.e
        s = e.shots[k]
        a = e._matte_small(k, int(round((t - s.start) * e.fps)))
        if a is None:
            m = e._mattes.get(k)
            if m and m[0] == "photo":
                return None
            return None
        return M.refine(a, e.W, e.H)

    def frame(self, fi):
        e = self.e
        t = fi / e.fps
        k = e.shot_at(t)
        img = self.shot_frame(k, t)
        mat = self.matte(k, t)
        req = {"rgb": 0, "glitch": 0.0, "type_alpha": 1.0, "grade": None}
        # transitions around this frame
        for i, tr in e.trans.items():
            c = e.shots[i].start
            if tr.kind in ("dissolve", "luma", "push", "dip") and tr.dur > 0 and c - tr.dur / 2 <= t < c + tr.dur / 2:
                p = (t - (c - tr.dur / 2)) / tr.dur
                a = self.shot_frame(i - 1, t)
                b = self.shot_frame(i, t)
                if tr.kind == "dissolve":
                    img = FX.dissolve(a, b, anim.in_out_cubic(p))
                elif tr.kind == "luma":
                    img = FX.luma_dissolve(a, b, p, seed=i)
                elif tr.kind == "push":
                    img = FX.push(a, b, p, tr.direction)
                else:
                    img = FX.dip(a, b, p)
                ma, mb = self.matte(i - 1, t), self.matte(i, t)
                if ma is not None or mb is not None:
                    za = ma if ma is not None else 0
                    zb = mb if mb is not None else 0
                    mat = za * (1 - p) + zb * p
                else:
                    mat = None
            if tr.kind == "glitch" and c <= t < c + max(tr.dur, 3 / e.fps):
                req["glitch"] = max(req["glitch"], 1 - (t - c) / max(tr.dur, 3 / e.fps) * 0.5)
        # graphics
        behind = Image.new("RGBA", (e.W, e.H), (0, 0, 0, 0))
        front = Image.new("RGBA", (e.W, e.H), (0, 0, 0, 0))
        any_b = any_f = False
        for f in e.families:
            if not f.active(t):
                continue
            f.draw(t, behind, front, e)
            any_b = any_b or f.behind_subject or bool(f.d.get("behind"))
            any_f = True
            r = f.fx(t)
            req["rgb"] = max(req["rgb"], r.get("rgb", 0))
            req["glitch"] = max(req["glitch"], r.get("glitch", 0))
            req["type_alpha"] = min(req["type_alpha"], r.get("type_alpha", 1.0))
            if r.get("grade"):
                req["grade"] = r["grade"]
        if req["grade"]:
            img = FT.grade(img, req["grade"][0], req["grade"][1])
        out = img.astype(np.float32)
        if any_b:
            b = np.asarray(behind, np.float32)
            a = b[..., 3:4] / 255
            if mat is not None:
                a = a * (1 - mat[..., None])
            out = out * (1 - a) + b[..., :3] * a
        if any_f:
            fr = np.asarray(front, np.float32)
            a = fr[..., 3:4] / 255 * req["type_alpha"]
            out = out * (1 - a) + fr[..., :3] * a
        img = np.clip(out, 0, 255).astype(np.uint8)
        if req["rgb"]:
            img = FX.rgb_split(img, int(req["rgb"]))
        if req["glitch"] > 0:
            img = FX.glitch(img, fi, req["glitch"])
        s = e.shots[k]
        return FX.finish(img, fi, grain=8.0 if s.photo else 5.5)

    def close(self):
        for r, _ in self.readers.values():
            r.close()


def encoder_args(hw: bool | None = None, delivery: bool = False):
    """H.264 settings: VideoToolbox on a Mac when FFmpeg has it (hardware encoder, frees the CPU for frames),
    libx264 otherwise. Both are 4:2:0 yuv, BT.709, so segments from either join cleanly."""
    if hw is None:
        hw = os.environ.get("CASEFILE_HWENC", "auto") != "0" and _has_videotoolbox()
    common = ["-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if hw:
        rate = ["-b:v", "14M", "-maxrate", "16M"] if delivery else ["-b:v", "18M", "-maxrate", "24M"]
        return ["-c:v", "h264_videotoolbox"] + rate + ["-profile:v", "high"] + common
    if delivery:  # the exported file: film grain would otherwise push crf 16 to ~40 Mbit/s
        return ["-c:v", "libx264", "-preset", os.environ.get("CASEFILE_X264_PRESET", "medium"), "-crf", "18",
                "-maxrate", "16M", "-bufsize", "32M", "-tune", "grain"] + common
    return ["-c:v", "libx264", "-preset", os.environ.get("CASEFILE_X264_PRESET", "medium"), "-crf", "16"] + common


@lru_cache(maxsize=1)
def _has_videotoolbox():
    try:
        out = subprocess.run([ffbin(), "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
        return "h264_videotoolbox" in out
    except Exception:
        return False


def _chunk_job(args):
    edit, a, b, path = args
    r = _Renderer(edit)
    tmp = path + ".tmp.mp4"
    p = subprocess.Popen([ffbin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{edit.W}x{edit.H}",
                          "-r", str(edit.fps), "-i", "-"] + encoder_args() + ["-r", str(edit.fps), tmp], stdin=subprocess.PIPE)
    for fi in range(a, b):
        p.stdin.write(np.ascontiguousarray(r.frame(fi)).tobytes())
    p.stdin.close()
    p.wait()
    r.close()
    os.replace(tmp, path)
    return path


def _chunks(edit: Edit, a: int, b: int, max_len: int = 90):
    """Chunk boundaries at shot cuts (so a reader never seeks), split further when long."""
    cuts = sorted({int(round(s.start * edit.fps)) for s in edit.shots} | {a, b})
    cuts = [c for c in cuts if a <= c <= b]
    out = []
    for x, y in zip(cuts, cuts[1:]):
        while y - x > max_len:
            out.append((x, x + max_len))
            x += max_len
        if y > x:
            out.append((x, y))
    return out


def _chunk_key(edit: Edit, a: int, b: int) -> str:
    t0, t1 = a / edit.fps, b / edit.fps
    shots = [(k, asdict(s), asdict(edit.trans.get(k, Transition())), asdict(edit.trans.get(k + 1, Transition())))
             for k, s in enumerate(edit.shots) if s.start - 1 < t1 and s.end + 1 > t0]
    els = [(e.family, e.t_in, e.t_out, e.data) for e in edit.elements if e.t_in - 1 < t1 and e.t_out + 1 > t0]
    blob = json.dumps([ENGINE_VERSION, edit.W, edit.H, edit.fps, a, b, shots, els, sorted(edit._mattes.keys()),
                       encoder_args()], sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


class Cancelled(Exception):
    pass


def render_video(edit: Edit, out_mp4: str, a: int = 0, b: int | None = None, workers: int | None = None, log=print,
                 on_chunk=None, cancelled=None):
    """Concatenate the timeline's chunks that overlap frames [a, b) (rendering only those not cached).
    Chunks always follow the whole timeline's boundaries, so every window reuses the same cache.
    on_chunk(done, todo, cached) after each chunk; cancelled() is checked between chunks (raises Cancelled).
    Returns the frame number the output starts at."""
    b = edit.nframes if b is None else b
    cdir = edit.cache / "chunks"
    cdir.mkdir(parents=True, exist_ok=True)
    for stale in cdir.glob("*.tmp.mp4"):          # left by a render that was stopped mid-chunk
        if time.time() - stale.stat().st_mtime > 600:
            stale.unlink(missing_ok=True)
    jobs, paths = [], []
    span = [(x, y) for x, y in _chunks(edit, 0, edit.nframes) if y > a and x < b]
    for x, y in span:
        p = str(cdir / f"c-{_chunk_key(edit, x, y)}.mp4")
        paths.append(p)
        if not os.path.exists(p):
            jobs.append((edit, x, y, p))
    log(f"  {len(paths)} chunks, {len(jobs)} to render ({len(paths) - len(jobs)} cached)")
    cached = len(paths) - len(jobs)
    if on_chunk:
        on_chunk(0, len(jobs), cached)
    if jobs:
        n = workers or max(1, min(len(jobs), (os.cpu_count() or 2)))
        if n == 1:
            for k, j in enumerate(jobs):
                if cancelled and cancelled():
                    raise Cancelled()
                _chunk_job(j)
                if on_chunk:
                    on_chunk(k + 1, len(jobs), cached)
        else:
            with mp.get_context("spawn").Pool(n) as pool:
                for k, _ in enumerate(pool.imap_unordered(_chunk_job, jobs)):
                    log(f"    chunk {k + 1}/{len(jobs)}")
                    if on_chunk:
                        on_chunk(k + 1, len(jobs), cached)
                    if cancelled and cancelled():
                        pool.terminate()
                        raise Cancelled()
    lst = cdir / f"list-{os.getpid()}.txt"
    lst.write_text("".join(f"file '{os.path.abspath(p)}'\n" for p in paths))
    subprocess.run([ffbin(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", out_mp4], check=True)
    lst.unlink()
    return span[0][0]


# ====================================================================== sound
def _decode(path, t_src=0.0, dur=None, loudnorm=False):
    args = [ffbin(), "-v", "error", "-nostdin", "-ss", f"{t_src:.4f}", "-i", path]
    if dur:
        args += ["-t", f"{dur:.4f}"]
    af = ("loudnorm=I=-16:TP=-1.5:LRA=11," if loudnorm else "") + f"aresample={SC.SR},aformat=sample_fmts=flt:channel_layouts=stereo"
    raw = subprocess.run(args + ["-af", af, "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy()


def all_cues(edit: Edit):
    out = list(edit.cues)
    for f in edit.families:
        out += f.cues()
    for i, tr in edit.trans.items():
        c = edit.shots[i].start
        if tr.kind == "glitch":
            out.append(Cue(c, "sp-glitch", -8, "glitch transition"))
        elif tr.kind == "push":
            out.append(Cue(c, "whoosh-dir-r" if tr.direction > 0 else "whoosh-dir-l", -6, "push"))
        elif tr.kind == "luma":
            out.append(Cue(c, "whoosh-mid-2", -10, "luma dissolve"))
    return sorted(out, key=lambda c: c.t)


def _movavg(x, k):
    """Centred moving average (same length), O(n) via a cumulative sum."""
    k = max(1, int(k))
    c = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
    lo = np.clip(np.arange(len(x)) - k // 2, 0, len(x))
    hi = np.clip(lo + k, 0, len(x))
    return ((c[hi] - c[lo]) / k).astype(np.float32)


def mix(edit: Edit, out_wav: str, a: float = 0.0, b: float | None = None, music_db=-19.0, duck_db=7.0, log=print):
    """Mix the whole timeline once (memoised on the edit) and write [a, b) to out_wav."""
    b = edit.duration if b is None else b
    key = json.dumps([edit.narration, [asdict(x) for x in edit.natural], edit.music, music_db, duck_db,
                      [(c.t, c.sfx, c.gain_db) for c in all_cues(edit)], edit.duration], default=str)
    memo = getattr(edit, "_mix_memo", None)
    if memo and memo[0] == key:
        out = memo[1]
    else:
        out = _mix_all(edit, music_db, duck_db)
        edit._mix_memo = (key, out)
    return _write_wav(out, out_wav, a, b)


def _mix_all(edit: Edit, music_db, duck_db):
    n = int(round(edit.duration * SC.SR))
    voice = np.zeros((2, n), np.float32)
    for path, at in edit.narration:
        v = _decode(path, loudnorm=True)
        o = int(round(at * SC.SR))
        L = min(v.shape[1], n - o)
        voice[:, o:o + L] += v[:, :L]
    nat = np.zeros((2, n), np.float32)
    for x in edit.natural:
        try:
            v = _decode(x.src, x.t_src, x.dur)
        except subprocess.CalledProcessError:   # footage without a sound track: nothing to add
            continue
        if v.shape[1] == 0:
            continue
        o = int(round(x.at * SC.SR))
        L = min(v.shape[1], n - o)
        fade = np.ones(L, np.float32)
        k = min(L // 2, int(0.15 * SC.SR))
        if k > 0:
            fade[:k] = np.linspace(0, 1, k)
            fade[-k:] = np.linspace(1, 0, k)
        nat[:, o:o + L] += v[:, :L] * fade * 10 ** (x.gain_db / 20)
    music = SC.bed(edit.duration, edit.music) * 10 ** (music_db / 20) if edit.music else np.zeros((2, n), np.float32)
    music = music[:, :n] if music.shape[1] >= n else np.pad(music, ((0, 0), (0, n - music.shape[1])))
    sfx = SC.place(all_cues(edit), n)
    env = _movavg(np.abs(voice).max(axis=0), int(0.05 * SC.SR))
    speaking = np.clip(env / 0.04, 0, 1)
    speaking = _movavg(speaking, int(0.25 * SC.SR))  # smooth ducking
    duck = (1 - speaking * (1 - 10 ** (-duck_db / 20))).astype(np.float32)
    out = voice + music * duck + nat * (1 - speaking * 0.5) + sfx * (1 - speaking * 0.3)
    peak = np.max(np.abs(out)) + 1e-9
    if peak > 0.89:
        out = np.tanh(out / peak * 1.4) / np.tanh(1.4) * 0.89
    return out


def _write_wav(out, out_wav, a, b):
    ia, ib = int(round(a * SC.SR)), int(round(b * SC.SR))
    seg = out[:, ia:ib].copy()
    k = int(0.03 * SC.SR)
    seg[:, :k] *= np.linspace(0, 1, k)
    seg[:, -k:] *= np.linspace(1, 0, k)
    import wave
    pcm = (np.clip(seg, -1, 1).T * 32767).astype("<i2")
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SC.SR)
        w.writeframes(pcm.tobytes())
    return out_wav


def export(edit: Edit, out_mp4: str, a: float = 0.0, b: float | None = None, fade: float = 0.0, log=print, workers=None,
           overlay: str | None = None, on_chunk=None, cancelled=None, music_db: float = -19.0):
    """Render [a, b) of the edit to out_mp4 with its mixed sound (chunks reused from the cache).
    overlay: a full-frame transparent PNG laid over the picture in the final encode (the project's logo)."""
    b = edit.duration if b is None else b
    fa, fb = int(round(a * edit.fps)), int(round(b * edit.fps))
    tmpdir = edit.cache / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    stem = Path(out_mp4).stem
    vid = str(tmpdir / f"{stem}.v.mp4")
    first = render_video(edit, vid, fa, fb, workers=workers, log=log, on_chunk=on_chunk, cancelled=cancelled)
    if cancelled and cancelled():
        raise Cancelled()
    wav = mix(edit, str(tmpdir / f"{stem}.wav"), fa / edit.fps, fb / edit.fps, music_db=music_db, log=log)
    dur = (fb - fa) / edit.fps
    vf = []
    if fade:
        vf.append(f"fade=t=in:st=0:d={fade},fade=t=out:st={max(0, dur - fade):.3f}:d={fade}")
    # explicit layouts: loudnorm after a guessed WAV layout fails to negotiate with the AAC encoder otherwise
    af = ["aformat=channel_layouts=stereo", "loudnorm=I=-14:TP=-1.5:LRA=11", f"aresample={SC.SR}",
          "aformat=sample_fmts=fltp:channel_layouts=stereo"]
    if fade:
        af.insert(1, f"afade=t=in:st=0:d={fade / 2},afade=t=out:st={max(0, dur - fade):.3f}:d={fade}")
    cmd = [ffbin(), "-v", "error", "-y", "-ss", f"{(fa - first) / edit.fps:.4f}", "-i", vid, "-i", wav]
    if overlay:
        cmd += ["-loop", "1", "-i", overlay, "-t", f"{dur:.4f}",
                "-filter_complex", f"[0:v]{','.join(vf) if vf else 'null'}[b];[b][2:v]overlay=0:0:shortest=1,format=yuv420p[v]",
                "-map", "[v]", "-map", "1:a"]
    else:
        cmd += ["-t", f"{dur:.4f}", "-map", "0:v", "-map", "1:a", "-vf", ",".join(vf) if vf else "null"]
    cmd += encoder_args(delivery=True)
    cmd += ["-af", ",".join(af), "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out_mp4]
    subprocess.run(cmd, check=True)
    return out_mp4
