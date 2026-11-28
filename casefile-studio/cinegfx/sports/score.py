"""Sound for the sports editorial engine: sports-only sfx (digital glitch, scramble roll) and a procedural
music bed that follows the story's emotional progression. Everything is synthesised here or by sfxlib
(no samples, no downloads), so it is original and the same on every machine.

Moods (the plan's 'emotional music progression'):
  nostalgic  soft piano arpeggio over a warm pad                       (early career, intros)
  minimal    low drone + sparse high notes, near silence                (flashbacks, collapse)
  tension    low pulse ostinato, dark pad                                (setbacks, the opponent leads)
  build      pulse + pad + rising toms                                   (the rise)
  peak       full pad, octave strings, drums on 1 and 3                  (the peak)
  triumph    major lift, strings, drums, long resolve                    (final victory)
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import zlib

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sfxlib  # noqa: E402

SR = sfxlib.SR


def _n(sec):
    return int(round(sec * SR))


# ------------------------------------------------------------------ sports sfx
def _glitch(rng):
    n = _n(0.26)
    t = np.arange(n) / SR
    x = np.zeros(n, np.float32)
    # stuttered bit-crushed noise bursts
    for k in range(5):
        a = int(rng.integers(0, n - _n(0.03)))
        L = min(_n(float(rng.uniform(0.012, 0.035))), n - a)
        burst = rng.standard_normal(L).astype(np.float32)
        step = int(rng.integers(6, 18))
        burst = np.repeat(burst[::step], step)[:L]
        x[a:a + L] += burst * float(rng.uniform(0.3, 0.8))
    # square blips
    for k in range(3):
        a = int(rng.integers(0, n - _n(0.02)))
        L = _n(0.018)
        f = float(rng.uniform(600, 2400))
        x[a:a + L] += 0.35 * np.sign(np.sin(2 * np.pi * f * t[:L]))
    env = np.exp(-t / 0.12)
    x = x * env
    return np.stack([x, np.roll(x, 37)]).astype(np.float32)


def _scramble(rng, count=11, gap=0.038):
    n = _n(count * gap + 0.08)
    x = np.zeros(n, np.float32)
    for k in range(count):
        a = _n(k * gap)
        c = sfxlib.click(rng, tone=float(rng.uniform(2600, 4200)), body=200, release=0.012, level=0.5 + 0.5 * rng.random())
        c = c[0] if c.ndim == 2 else c
        L = min(len(c), n - a)
        x[a:a + L] += c[:L]
    return np.stack([x, x]).astype(np.float32)


SPORTS_SFX = {"sp-glitch": (_glitch, -14.0), "sp-scramble": (_scramble, -16.0)}


@lru_cache(maxsize=64)
def sound(sid: str):
    """(float32 [2, n], sync seconds) for an sfxlib id or a sports id."""
    if sid in SPORTS_SFX:
        fn, peak_db = SPORTS_SFX[sid]
        x = fn(np.random.default_rng(zlib.crc32(sid.encode())))   # the same sound in every process (not hash())
        x *= 10 ** (peak_db / 20) / (np.max(np.abs(x)) + 1e-9)
        return x.astype(np.float32), 0.0
    return sfxlib.synth(sid)


def place(cues, n: int, bus_db: float = 0.0) -> np.ndarray:
    bus = np.zeros((2, n), np.float32)
    for c in cues:
        x, sync = sound(c.sfx)
        start = int(round((c.t - sync) * SR))
        a, b = max(0, start), min(n, start + x.shape[1])
        if b > a:
            bus[:, a:b] += x[:, a - start:b - start] * (10 ** ((c.gain_db + bus_db) / 20))
    return bus


# ------------------------------------------------------------------ music bed
A4 = 440.0
NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name: str) -> float:
    pitch, octave = name[:-1], int(name[-1])
    return A4 * 2 ** ((NOTE[pitch] + 12 * (octave + 1) - 69) / 12)


# i - VI - III - VII in D minor (Dm Bb F C); triumph lifts to the relative major order (F C Dm Bb -> Bb F C C)
PROG = [("D", ["D3", "A3", "D4", "F4"]), ("A#", ["A#2", "F3", "A#3", "D4"]), ("F", ["F3", "C4", "F4", "A4"]),
        ("C", ["C3", "G3", "C4", "E4"])]
PROG_TRIUMPH = [("A#", ["A#2", "F3", "A#3", "D4"]), ("F", ["F3", "C4", "F4", "A4"]), ("C", ["C3", "G3", "C4", "E4"]),
                ("D", ["D3", "A3", "D4", "F#4"])]
BPM = 84
BEAT = 60 / BPM
BAR = 4 * BEAT


def _lowpass_fft(x, cutoff):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / np.sqrt(1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x)).astype(np.float32)


def _pad(freqs, dur, bright=1200, detune=0.004, att=0.9, rel=1.2):
    n = _n(dur + rel)
    t = np.arange(n) / SR
    x = np.zeros(n, np.float32)
    for f in freqs:
        for d in (-detune, 0, detune):
            ff = f * (1 + d)
            ph = np.random.default_rng(int(ff * 10)).random()
            saw = 2 * ((t * ff + ph) % 1.0) - 1
            x += saw.astype(np.float32) * 0.18
    x = _lowpass_fft(x, bright)
    env = np.minimum(1, t / att) * np.where(t < dur, 1.0, np.exp(-(t - dur) / (rel / 3)))
    return x * env.astype(np.float32)


def _piano(f, dur=1.6, vel=1.0):
    n = _n(dur)
    t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) * np.exp(-t * 3) +
         0.12 * np.sin(6 * np.pi * f * t) * np.exp(-t * 5))
    env = np.exp(-t * 2.2) * np.minimum(1, t / 0.004)
    return (x * env * vel * 0.3).astype(np.float32)


def _pluck(f, dur=0.32):
    n = _n(dur)
    t = np.arange(n) / SR
    saw = 2 * ((t * f) % 1.0) - 1
    x = _lowpass_fft(saw.astype(np.float32), 500) * np.exp(-t * 9)
    return (x * 0.5).astype(np.float32)


def _tom(f0=90, dur=0.7, vel=1.0):
    n = _n(dur)
    t = np.arange(n) / SR
    f = f0 * (1 + 0.8 * np.exp(-t * 25))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 6) + 0.15 * np.random.default_rng(int(f0)).standard_normal(n) * np.exp(-t * 30)
    return (x * vel * 0.7).astype(np.float32)


def _add(buf, x, at):
    a = _n(at)
    if a >= len(buf) or a + len(x) <= 0:
        return
    b = min(len(buf), a + len(x))
    s = max(0, -a)
    buf[max(0, a):b] += x[s:b - a]


LEVELS = {  # pad, piano, pulse, drums, strings
    "nostalgic": (0.55, 0.9, 0.0, 0.0, 0.0),
    "minimal":   (0.28, 0.35, 0.0, 0.0, 0.0),
    "tension":   (0.45, 0.0, 0.8, 0.25, 0.0),
    "build":     (0.6, 0.3, 0.85, 0.6, 0.35),
    "peak":      (0.75, 0.25, 0.7, 0.9, 0.75),
    "triumph":   (0.8, 0.45, 0.4, 0.75, 0.95),
}


def bed(duration: float, sections: list[tuple[float, float, str]], seed: int = 7) -> np.ndarray:
    """Stereo float32 bed. sections: [(t0, t1, mood)] in timeline seconds; bars run continuously across
    sections (the harmony keeps moving), each section has its own instrumentation and level."""
    n = _n(duration + 2)
    L = np.zeros(n, np.float32)
    R = np.zeros(n, np.float32)
    rng = np.random.default_rng(seed)

    def mood_at(t):
        for a, b, m in sections:
            if a <= t < b:
                return m
        return None

    nbars = int(duration / BAR) + 2
    for bi in range(nbars):
        t0 = bi * BAR
        m = mood_at(t0 + 0.01) or mood_at(t0 + BAR / 2)
        if m is None:
            continue
        pad_l, pia_l, pul_l, drm_l, str_l = LEVELS[m]
        prog = PROG_TRIUMPH if m == "triumph" else PROG
        root, chord = prog[bi % 4]
        fs = [hz(c) for c in chord]
        if pad_l:
            p = _pad(fs, BAR, bright=900 if m in ("minimal", "nostalgic", "tension") else 1600) * pad_l
            _add(L, p, t0)
            _add(R, np.roll(p, 220), t0)
        if str_l:
            s = _pad([f * 2 for f in fs[1:]], BAR, bright=2600, detune=0.006, att=1.4) * str_l * 0.6
            _add(L, np.roll(s, 300), t0)
            _add(R, s, t0)
        if pia_l:
            arp = [fs[0] * 2, fs[1] * 2, fs[2] * 2, fs[3] * 2, fs[2] * 2, fs[1] * 2, fs[3] * 2, fs[2] * 2]
            step = BEAT / 2 if m != "minimal" else BEAT * 2
            k = 0
            tt = 0.0
            while tt < BAR - 1e-6:
                f = arp[k % len(arp)]
                pn = _piano(f, 2.0, vel=pia_l * (0.8 + 0.2 * rng.random()))
                pan = 0.5 + 0.3 * np.sin(k)
                _add(L, pn * (1 - pan) * 1.4, t0 + tt)
                _add(R, pn * pan * 1.4, t0 + tt)
                tt += step
                k += 1
        if pul_l:
            f = hz(root + "2")
            for e in range(8):
                pl = _pluck(f, 0.3) * pul_l * (1.0 if e % 2 == 0 else 0.7)
                _add(L, pl, t0 + e * BEAT / 2)
                _add(R, pl, t0 + e * BEAT / 2)
        if drm_l:
            for b in range(4):
                if b in (0, 2) or (m in ("peak", "triumph") and b == 3):
                    tm = _tom(70 if b == 0 else 95, 0.8, drm_l * (1.0 if b == 0 else 0.7))
                    _add(L, tm, t0 + b * BEAT)
                    _add(R, tm, t0 + b * BEAT)
    out = np.stack([L, R])[:, : _n(duration)]
    # crossfade sections: gentle level automation so mood changes breathe instead of switching
    env = np.ones(out.shape[1], np.float32)
    for a, b, m in sections:
        if m == "minimal":
            ia, ib = _n(a), _n(b)
            env[ia:ib] *= 0.55
    env = np.convolve(env, np.ones(_n(0.6)) / _n(0.6), mode="same").astype(np.float32)
    out *= env
    out /= (np.max(np.abs(out)) + 1e-9)
    return out.astype(np.float32)
