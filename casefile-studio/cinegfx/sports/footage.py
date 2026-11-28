"""Shots: streamed decoding at output size, reframing, speed (slow motion with frame blending), grading and
controlled photo animation. Frames are produced sequentially per shot (one FFmpeg pipe per shot), so a
1080p timeline never has to sit in memory or on disk as raw frames."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from ..timing import ffbin

# ------------------------------------------------------------------ grades
# sat: saturation; con: contrast around mid grey; lift: black level (0-255); gain: overall; tint: per-channel gain
GRADES = {
    "natural":    dict(sat=0.95, con=1.06, lift=6, gain=1.0, tint=(1.0, 1.0, 1.0)),
    "punch":      dict(sat=1.02, con=1.12, lift=4, gain=1.0, tint=(1.02, 1.0, 0.97)),
    "warm":       dict(sat=0.88, con=1.10, lift=8, gain=0.98, tint=(1.06, 1.0, 0.90)),
    "cool_desat": dict(sat=0.30, con=1.14, lift=10, gain=0.95, tint=(0.92, 0.99, 1.10)),
    "mono_cool":  dict(sat=0.0, con=1.20, lift=8, gain=0.95, tint=(0.94, 0.99, 1.07)),
    "low_key":    dict(sat=0.22, con=1.30, lift=3, gain=0.58, tint=(1.0, 0.97, 0.98)),
    "archive":    dict(sat=0.12, con=0.96, lift=22, gain=0.96, tint=(1.10, 1.0, 0.80)),
    "cyan_fade":  dict(sat=0.10, con=0.92, lift=26, gain=0.92, tint=(0.80, 1.02, 1.10)),
}
_LUTS: dict = {}


def _lut(name):
    if name not in _LUTS:
        g = GRADES[name]
        x = np.arange(256, dtype=np.float32)
        y = (x - 128) * g["con"] + 128
        y = g["lift"] + y * (255 - g["lift"]) / 255
        y = y * g["gain"]
        _LUTS[name] = [np.clip(y * k, 0, 255).astype(np.uint8) for k in g["tint"]]
    return _LUTS[name]


def grade(rgb: np.ndarray, name: str, mix: float = 1.0) -> np.ndarray:
    if not name or name == "none" or mix <= 0:
        return rgb
    g = GRADES[name]
    f = rgb.astype(np.float32)
    if g["sat"] != 1.0:
        y = f[..., 0] * 0.2126 + f[..., 1] * 0.7152 + f[..., 2] * 0.0722
        f = y[..., None] + (f - y[..., None]) * g["sat"]
    u = np.clip(f, 0, 255).astype(np.uint8)
    L = _lut(name)
    out = np.stack([L[0][u[..., 0]], L[1][u[..., 1]], L[2][u[..., 2]]], axis=-1)
    if mix < 1.0:
        out = (rgb.astype(np.float32) * (1 - mix) + out.astype(np.float32) * mix).astype(np.uint8)
    return out


# ------------------------------------------------------------------ shots
@dataclass
class Shot:
    """A piece of footage (or a photo) on the timeline.
    src: video path; t_src: in point (s); dur: timeline duration (s); speed: 0.5 = half-speed slow motion;
    frame: (cx, cy, zoom) reframing in source coordinates (0-1); grade: GRADES key; matte: compute a person
    matte for behind-subject type; photo: a still (then `move` = ((cx,cy,zoom) start, (cx,cy,zoom) end))."""
    src: str
    t_src: float = 0.0
    dur: float = 2.0
    speed: float = 1.0
    frame: tuple = (0.5, 0.5, 1.0)
    grade: str = "natural"
    matte: bool = False
    photo: bool = False
    move: tuple | None = None
    parallax: float = 0.0          # photo: extra push on the matted subject (2.5D)
    tag: str = ""                  # what the shot shows (close-up, celebration, crowd...) - for the edit log
    start: float = 0.0             # timeline start (set by the edit)
    extra: dict = field(default_factory=dict)

    @property
    def end(self):
        return self.start + self.dur


def _vf(shot: Shot, W: int, H: int, fps: int):
    cx, cy, z = shot.frame
    crop = ""
    if z > 1.0001:
        crop = (f"crop=iw/{z}:ih/{z}:max(0\\,min(iw-iw/{z}\\,{cx}*iw-iw/{z}/2)):"
                f"max(0\\,min(ih-ih/{z}\\,{cy}*ih-ih/{z}/2)),")
    speed = ""
    if abs(shot.speed - 1.0) > 1e-3:
        speed = f"setpts=PTS/{shot.speed},"
    rate = f"framerate=fps={fps}:interp_start=0:interp_end=255:scene=100," if speed else f"fps={fps},"
    return (f"{crop}scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},"
            f"{speed}{rate}format=rgb24")


class Reader:
    """Sequential frames of a video shot at W x H. get(i) is cheap for i, i+1, ...; seeking back restarts."""

    def __init__(self, shot: Shot, W: int, H: int, fps: int):
        self.shot, self.W, self.H, self.fps = shot, W, H, fps
        self.n = max(1, int(round(shot.dur * fps)))
        self.p = None
        self.i = -1
        self.last = None

    def _open(self, first: int):
        if self.p:
            self.p.kill()
        s = self.shot
        t0 = s.t_src + first / self.fps * s.speed
        span = (self.n - first) / self.fps * s.speed + 0.5
        self.p = subprocess.Popen([ffbin(), "-v", "error", "-nostdin", "-ss", f"{max(0, t0):.4f}", "-i", s.src,
                                   "-t", f"{span:.4f}", "-an", "-vf", _vf(s, self.W, self.H, self.fps),
                                   "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.i = first - 1

    def get(self, i: int) -> np.ndarray:
        i = max(0, min(self.n - 1, i))
        if self.p is None or i <= self.i - 1 or i > self.i + 50:
            if i == self.i and self.last is not None:
                return self.last
            self._open(i)
        size = self.W * self.H * 3
        while self.i < i:
            buf = self.p.stdout.read(size)
            if len(buf) < size:  # past the end of the source: hold the last frame
                self.i = i
                break
            self.last = np.frombuffer(buf, np.uint8).reshape(self.H, self.W, 3)
            self.i += 1
        if self.last is None:
            self.last = np.zeros((self.H, self.W, 3), np.uint8)
        return self.last

    def all(self):
        for i in range(self.n):
            yield self.get(i)

    def close(self):
        if self.p:
            self.p.kill()
            self.p = None


class PhotoReader:
    """Controlled photo animation: a slow, eased move between two framings (pan/push), optionally with the
    subject (person matte) pushed a little more than the background for depth. Never blurred."""

    def __init__(self, shot: Shot, W: int, H: int, fps: int, matte=None):
        self.shot, self.W, self.H, self.fps = shot, W, H, fps
        self.n = max(1, int(round(shot.dur * fps)))
        im = Image.open(shot.src).convert("RGB")
        self.im = im
        self.matte = matte  # uint8 matte at photo size, or None

    def _view(self, img: Image.Image, cx, cy, z, resample=Image.LANCZOS):
        iw, ih = img.size
        # base scale: cover the frame
        base = max(self.W / iw, self.H / ih)
        s = base * z
        vw, vh = self.W / s, self.H / s
        x0 = min(max(0, cx * iw - vw / 2), iw - vw)
        y0 = min(max(0, cy * ih - vh / 2), ih - vh)
        return img.resize((self.W, self.H), resample, box=(x0, y0, x0 + vw, y0 + vh))

    def get(self, i: int) -> np.ndarray:
        from .. import anim
        a, b = self.shot.move or ((0.5, 0.5, 1.0), (0.5, 0.5, 1.08))
        p = anim.in_out_cubic(i / max(1, self.n - 1)) * 0.85 + 0.15 * (i / max(1, self.n - 1))
        cx, cy, z = (a[k] + (b[k] - a[k]) * p for k in range(3))
        bg = np.asarray(self._view(self.im, cx, cy, z))
        if self.matte is None or self.shot.parallax <= 0:
            return bg
        z2 = z * (1 + self.shot.parallax * p)
        fg = np.asarray(self._view(self.im, cx, cy, z2))
        m = np.asarray(self._view(Image.fromarray(self.matte), cx, cy, z2, Image.BILINEAR), np.float32)[..., None] / 255
        return (bg * (1 - m) + fg * m).astype(np.uint8)

    def all(self):
        for i in range(self.n):
            yield self.get(i)

    def close(self):
        pass


def reader(shot: Shot, W: int, H: int, fps: int, matte=None):
    return PhotoReader(shot, W, H, fps, matte) if shot.photo else Reader(shot, W, H, fps)
