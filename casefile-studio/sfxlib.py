"""v0.4.56 The cinematic sound effects library, made on this computer.

Every sound is synthesised with NumPy (no recordings, no downloads, no new packages): filtered
noise, decaying partials, swept bands and a small generated room. The same recipe and seed always
make the same sound, so the library is identical on every machine and works offline. Nothing in it
comes from a third party, so there is nothing to license or attribute (see SOUND-DESIGN.md).

Deliberately absent: gunshots, sirens, screams, voices, police radio, footsteps — anything that
could pass for the case's own audio. The camera shutter exists for manual use on your own photo
graphics only; the automatic plan never places it.

Files: <data>/cache/sfx/lib-<LIB_VERSION>/<id>.wav (48 kHz, 16-bit stereo), made on first use.
Each sound has a designed level (a click is quieter than an impact: the levels are NOT all the same)
and a `sync` point — the moment that is lined up with the picture (a click's transient, the peak of
a whoosh, the end of a riser).
"""
from __future__ import annotations

import hashlib
import json
import threading
import wave
from pathlib import Path

import numpy as np

SR = 48000
LIB_VERSION = 1  # bump when a recipe changes: the files are made again
_LOCK = threading.Lock()


# ====================================================================== building blocks

def _rng(name):
    return np.random.default_rng(int(hashlib.sha1(name.encode()).hexdigest()[:8], 16))


def _n(sec):
    return max(1, int(round(sec * SR)))


def _t(n):
    return np.arange(n) / SR


def _noise(n, rng, color="white"):
    x = rng.standard_normal(n)
    if color == "white":
        return x
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    f[0] = f[1] if n > 1 else 1.0
    spec *= (1 / np.sqrt(f)) if color == "pink" else (1 / f)
    y = np.fft.irfft(spec, n)
    return y / (np.std(y) + 1e-12)


def _band(x, lo=None, hi=None, order=2):
    """Zero-phase filter in the frequency domain (Butterworth-shaped magnitude)."""
    n = len(x)
    m = 1 << int(np.ceil(np.log2(max(2, n * 2))))
    spec = np.fft.rfft(x, m)
    f = np.fft.rfftfreq(m, 1 / SR)
    f[0] = 1e-3
    h = np.ones_like(f)
    if hi:
        h /= np.sqrt(1 + (f / hi) ** (2 * order))
    if lo:
        h /= np.sqrt(1 + (lo / f) ** (2 * order))
    return np.fft.irfft(spec * h, m)[:n]


def _sweep(x, centers, width=0.5):
    """A band that moves: `centers` (Hz) over time, `width` in octaves (STFT, overlap-add)."""
    n, size, hop = len(x), 1024, 256
    pad = np.concatenate([np.zeros(size), x, np.zeros(size)])
    win = np.hanning(size)
    frames = 1 + (len(pad) - size) // hop
    idx = np.arange(size)[None, :] + hop * np.arange(frames)[:, None]
    spec = np.fft.rfft(pad[idx] * win, axis=1)
    f = np.fft.rfftfreq(size, 1 / SR)
    f[0] = 1.0
    pos = np.clip((np.arange(frames) * hop - size) / max(1, n - 1), 0, 1)
    c = np.interp(pos, np.linspace(0, 1, len(centers)), centers)
    gain = np.exp(-0.5 * (np.log2(f[None, :] / c[:, None]) / width) ** 2)
    out = np.fft.irfft(spec * gain, size, axis=1) * win
    y = np.zeros(len(pad))
    norm = np.zeros(len(pad))
    np.add.at(y, idx, out)
    np.add.at(norm, idx, np.broadcast_to(win ** 2, out.shape))
    y /= np.maximum(norm, 1e-3)
    return y[size:size + n]


def _env(n, attack, decay, curve=1.0):
    t = _t(n)
    a = np.clip(t / max(attack, 1e-4), 0, 1) ** 0.6
    d = np.exp(-np.maximum(0, t - attack) / max(decay, 1e-4)) ** curve
    return a * d


def _shape(n, points):
    """Amplitude through (position 0..1, level) points, smoothed."""
    xs, ys = zip(*points)
    e = np.interp(np.linspace(0, 1, n), xs, ys)
    k = max(1, _n(0.004))
    return np.convolve(e, np.ones(k) / k, mode="same")


def _glide(f0, f1, n, curve=1.0):
    p = np.linspace(0, 1, n) ** curve
    f = f0 * (f1 / f0) ** p
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def _partials(freqs, decays, amps, n, rng=None):
    t = _t(n)
    y = np.zeros(n)
    for f, d, a in zip(freqs, decays, amps):
        ph = rng.uniform(0, 2 * np.pi) if rng is not None else 0.0
        y += a * np.sin(2 * np.pi * f * t + ph) * np.exp(-t / d)
    return y


def _room(x, rng, rt=0.6, wet=0.18, bright=5000, width=1.0):
    """A small generated room (convolution with decaying, darkening noise), stereo out."""
    m = _n(rt * 1.2)
    t = _t(m)
    decay = np.exp(-6.9 * t / rt)
    outs = []
    for ch in range(2):
        ir = rng.standard_normal(m) * decay
        ir = _band(ir, lo=120, hi=bright)
        ir[: _n(0.008)] *= np.linspace(0, 1, _n(0.008))  # a short pre-delay feel
        ir /= np.sqrt(np.sum(ir ** 2)) + 1e-12
        L = len(x) + m - 1
        size = 1 << int(np.ceil(np.log2(L)))
        y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:L]
        outs.append(y)
    dry = np.concatenate([x, np.zeros(m - 1)])
    wl, wr = outs
    mid, side = (wl + wr) / 2, (wl - wr) / 2 * width
    return np.stack([dry + wet * (mid + side), dry + wet * (mid - side)])


def _pan(mono, pos):
    """pos -1 (left) .. 1 (right), a number or an array over time; equal power."""
    p = (np.asarray(pos, dtype=float) + 1) * np.pi / 4
    return np.stack([mono * np.cos(p), mono * np.sin(p)])


def _stereo(x):
    return x if x.ndim == 2 else np.stack([x, x])


def _fade(x, fin=0.002, fout=0.02):
    x = _stereo(x).copy()
    a, b = min(_n(fin), x.shape[1] // 2), min(_n(fout), x.shape[1] // 2)
    if a:
        x[:, :a] *= np.linspace(0, 1, a)
    if b:
        x[:, -b:] *= np.linspace(1, 0, b) ** 2
    return x


def _sat(x, drive=1.5):
    return np.tanh(x * drive) / np.tanh(drive)


# ====================================================================== the recipes

def click(rng, tone=2600, body=180, dark=False, release=0.035, level=1.0):
    n = _n(0.09 + release)
    y = np.zeros(n)

    def tick(at, amp, f):
        k = _n(0.012)
        burst = _band(rng.standard_normal(k), lo=f * 0.5, hi=f * (1.0 if dark else 2.4)) * _env(k, 0.0003, 0.0022)
        ring = _partials([f, f * 1.47], [0.006, 0.004], [0.5, 0.25], k, rng)
        thock = _partials([body], [0.012], [0.6], k)
        s = _n(at)
        y[s:s + k] += amp * (burst + 0.35 * ring + 0.5 * thock)[: n - s]

    tick(0.004, 1.0, tone)
    tick(0.004 + release, 0.45, tone * 1.12)
    if dark:
        y = _band(y, hi=1500)
    return _room(y * level, rng, rt=0.25, wet=0.08)


def pop(rng, f0=950, f1=260, decay=0.05):
    n = _n(decay * 4 + 0.02)
    body = _glide(f0, f1, n, 0.35) * _env(n, 0.0015, decay)
    air = _band(rng.standard_normal(n), lo=1500, hi=7000) * _env(n, 0.0005, 0.004) * 0.3
    return _room(body + air, rng, rt=0.3, wet=0.1)


def key(rng, typewriter=False, space=False):
    """One keystroke: a typewriter type-bar strike, or a soft keyboard key."""
    n = _n(0.16 if typewriter else 0.09)
    t = _t(n)
    if typewriter:
        strike = _band(rng.standard_normal(n), lo=900, hi=5200) * _env(n, 0.0003, 0.006)
        metal = _partials(rng.uniform([2100, 3150, 4400], [2500, 3600, 5000]), [0.03, 0.02, 0.012], [0.35, 0.22, 0.12], n, rng)
        platen = _partials([rng.uniform(140, 175)], [0.03], [0.9], n) * (t > 0.0015)
        y = strike + metal * _env(n, 0.0005, 0.03) + 0.7 * platen
        if space:
            y = _band(y, hi=2200) * 1.1
    else:
        down = _band(rng.standard_normal(n), lo=1400, hi=6500) * _env(n, 0.0003, 0.0035)
        thock = _partials([rng.uniform(230, 300)], [0.014], [0.8], n)
        y = down + 0.6 * thock
        up = _n(rng.uniform(0.045, 0.06))
        y[up:] += 0.35 * _band(rng.standard_normal(n - up), lo=2000, hi=7000) * _env(n - up, 0.0002, 0.0025)
        if space:
            y = _band(y, hi=2500) * 1.2
    return _room(y, rng, rt=0.3, wet=0.07)


def whoosh(rng, length=0.7, f_lo=350, f_hi=2600, peak=0.55, direction=0.0, reverse=False, air=0.6):
    n = _n(length)
    x = _noise(n, rng, "pink")
    centers = np.concatenate([np.geomspace(f_lo, f_hi, 16)[: int(16 * peak)], np.geomspace(f_hi, f_lo * 0.8, 16)[int(16 * peak):]])
    y = _sweep(x, centers, width=0.45 + 0.4 * air)
    e = _shape(n, [(0, 0), (peak * 0.6, 0.25), (peak, 1.0), (min(0.98, peak + 0.25), 0.25), (1, 0)]) ** 1.4
    y *= e
    if reverse:
        y = y[::-1]
    pos = np.linspace(-direction, direction, n) if direction else 0.0
    st = _pan(y, pos) if direction else _stereo(y)
    out = np.stack([_room(st[0], rng, rt=0.7, wet=0.22)[0], _room(st[1], rng, rt=0.7, wet=0.22)[1]])
    return out


def thump(rng, f0=110, f1=48, decay=0.32, grit=0.15, tail=0.9):
    n = _n(decay * 5)
    body = _glide(f0, f1, n, 0.25) * _env(n, 0.004, decay)
    sub = np.sin(2 * np.pi * f1 * 0.98 * _t(n)) * _env(n, 0.03, decay * 1.6) * 0.5
    hit = _band(rng.standard_normal(n), lo=60, hi=900) * _env(n, 0.001, 0.02) * grit * 3
    y = _sat(body + sub + hit, 1.3)
    return _room(y, rng, rt=tail, wet=0.15, bright=1800)


def pulse(rng, f=55, length=0.6, double=False):
    n = _n(length)
    e = _shape(n, [(0, 0), (0.08, 1), (0.5, 0.35), (1, 0)])
    y = np.sin(2 * np.pi * f * _t(n)) * e + 0.25 * np.sin(2 * np.pi * f * 2 * _t(n)) * e ** 2
    if double:
        k = _n(length * 0.42)
        y2 = np.zeros(n)
        y2[k:] = y[: n - k] * 0.6
        y = y + y2
    return _room(_sat(y, 1.2), rng, rt=0.8, wet=0.1, bright=900)


def chime(rng, base=880, ratios=(1.0, 1.5), spacing=0.11, decay=0.35, soft=True):
    n = _n(spacing * len(ratios) + decay * 4)
    y = np.zeros(n)
    for k, r in enumerate(ratios):
        s = _n(spacing * k)
        m = n - s
        tone = _partials([base * r, base * r * 2.01, base * r * 3.0], [decay, decay * 0.4, decay * 0.2], [1, 0.18, 0.06], m, rng)
        y[s:] += tone * _env(m, 0.004, decay * 2)
    if soft:
        y = _band(y, hi=5000)
    return _room(y, rng, rt=1.1, wet=0.25)


def scan(rng, length=1.1, f0=900, f1=3200, rate=34):
    n = _n(length)
    t = _t(n)
    tone = _glide(f0, f1, n, 1.0) * 0.4
    grain = _band(rng.standard_normal(n), lo=2500, hi=9000) * 0.5
    am = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * rate * t)) * 0.8
    e = _shape(n, [(0, 0), (0.12, 1), (0.85, 0.8), (1, 0)])
    y = (tone + grain) * am * e
    y = _band(y, lo=500, hi=8000)
    return _pan(y, np.linspace(-0.4, 0.4, n))


def paper(rng, length=0.55, slide=False, crisp=0.6):
    n = _n(length)
    x = _noise(n, rng, "pink")
    # crackle: random short bursts riding on a soft rustle
    bursts = np.zeros(n)
    count = int(length * (60 + 120 * crisp))
    for s in rng.integers(0, max(1, n - _n(0.02)), count):
        k = _n(rng.uniform(0.003, 0.012))
        bursts[s:s + k] += rng.uniform(0.3, 1.0) * np.hanning(k)
    y = _band(x, lo=900, hi=7500) * (0.25 + bursts)
    e = _shape(n, [(0, 0), (0.15, 1), (0.6, 0.7), (1, 0)])
    if slide:
        y = _sweep(y, [1200, 3500, 2200], 1.0)
    return _room(y * e, rng, rt=0.35, wet=0.1)


def document(rng, length=0.7):
    a = paper(rng, length * 0.75, slide=True, crisp=0.4)
    land = thump(rng, f0=160, f1=90, decay=0.05, grit=0.4, tail=0.3) * 0.5
    out = np.zeros((2, max(a.shape[1], _n(length * 0.6) + land.shape[1])))
    out[:, : a.shape[1]] += a
    s = _n(length * 0.6)
    out[:, s:s + land.shape[1]] += land
    return out


def shutter(rng):
    n = _n(0.18)
    y = np.zeros(n)
    for at, amp, f in ((0.0, 1.0, 3000), (0.055, 0.7, 2400)):
        k = _n(0.03)
        s = _n(at)
        y[s:s + k] += amp * (_band(rng.standard_normal(k), lo=f * 0.5, hi=f * 2) * _env(k, 0.0003, 0.004)
                             + 0.4 * _partials([f * 0.6], [0.008], [1], k))
    spring = _band(rng.standard_normal(n), lo=3000, hi=8000) * _env(n, 0.01, 0.03) * 0.15
    return _room(y + spring, rng, rt=0.3, wet=0.08)


def tick(rng, f=3400, count=1, gap=1.0, tock=True):
    n = _n(gap * (count - 1) + 0.08)
    y = np.zeros(n)
    for k in range(count):
        s = _n(gap * k)
        m = _n(0.05)
        ff = f * (0.82 if (tock and k % 2) else 1.0)
        y[s:s + m] += (_partials([ff, ff * 1.9], [0.004, 0.002], [1, 0.4], m, rng)
                       + 0.3 * _band(rng.standard_normal(m), lo=2000) * _env(m, 0.0002, 0.0015))[: n - s]
    return _room(y, rng, rt=0.25, wet=0.06)


def riser(rng, length=2.0, f0=180, f1=1400):
    n = _n(length)
    x = _noise(n, rng, "pink")
    y = _sweep(x, np.geomspace(f0 * 2, f1 * 3, 24), 0.8) * 0.6
    tone = (_glide(f0, f1, n, 1.6) + 0.5 * _glide(f0 * 1.5, f1 * 1.5, n, 1.6)) * 0.25
    e = _shape(n, [(0, 0), (0.6, 0.35), (0.95, 1), (1, 0)]) ** 1.5
    return _room((y + tone) * e, rng, rt=1.0, wet=0.25)


def sweep_tone(rng, length=0.8, f0=300, f1=1100, up=True):
    n = _n(length)
    a, b = (f0, f1) if up else (f1, f0)
    y = _glide(a, b, n, 1.0) + 0.6 * _glide(a * 1.004, b * 1.004, n, 1.0) + 0.25 * _glide(a * 2, b * 2, n, 1.0)
    y *= _shape(n, [(0, 0), (0.3, 1), (0.7, 0.8), (1, 0)])
    air = _sweep(_noise(n, rng, "pink"), [a * 2, b * 2], 0.6) * 0.25 * _shape(n, [(0, 0), (0.5, 1), (1, 0)])
    return _room(_band(y + air, hi=6000), rng, rt=0.9, wet=0.25)


def swell(rng, length=3.5, root=110.0, minor=True, bright=1400):
    n = _n(length)
    t = _t(n)
    chord = [1, 1.189 if minor else 1.26, 1.498, 2.0]
    y = np.zeros(n)
    for r in chord:
        for det in (-0.004, 0.0, 0.0045):
            y += np.sin(2 * np.pi * root * r * (1 + det) * t + rng.uniform(0, 6.28))
    y = _band(y, hi=bright) / 12
    air = _band(_noise(n, rng, "pink"), lo=200, hi=bright * 1.5) * 0.08
    e = _shape(n, [(0, 0), (0.55, 1), (0.75, 0.75), (1, 0)]) ** 1.3
    return _room((y + air) * e, rng, rt=1.6, wet=0.3)


def impact(rng, weight=1.0):
    body = thump(rng, f0=95 + 20 * weight, f1=42, decay=0.38 + 0.15 * weight, grit=0.25, tail=1.3)
    crack = _band(rng.standard_normal(_n(0.25)), lo=700, hi=5000) * _env(_n(0.25), 0.0008, 0.03) * 0.25
    out = body.copy()
    out[:, : crack.shape[0]] += _room(crack, rng, rt=1.2, wet=0.4)[:, : crack.shape[0]]
    return out


def bell(rng, base=1320, decay=0.9, strikes=1):
    n = _n(decay * 3 + 0.25 * strikes)
    y = np.zeros(n)
    ratios, amps = [0.5, 1.0, 1.183, 1.506, 2.0, 2.74], [0.25, 1.0, 0.5, 0.35, 0.3, 0.15]
    for k in range(strikes):
        s = _n(0.18 * k)
        m = n - s
        y[s:] += (0.75 ** k) * _partials([base * r for r in ratios], [decay * d for d in (1.4, 1, 0.7, 0.5, 0.4, 0.25)], amps, m, rng) * _env(m, 0.002, 10)
    return _room(_band(y, hi=7000), rng, rt=1.0, wet=0.2)


# id, category, label, intensity 1..3, recipe, designed peak (dBFS)
CATALOG = [
    ("pop-soft-1", "pop", "Soft pop, round", 1, lambda r: pop(r, 900, 280, 0.045), -16),
    ("pop-soft-2", "pop", "Soft pop, low", 1, lambda r: pop(r, 620, 190, 0.06), -15),
    ("pop-soft-3", "pop", "Soft pop, bright", 2, lambda r: pop(r, 1400, 420, 0.035), -16),
    ("click-mech-1", "click", "Mechanical click", 2, lambda r: click(r, 2600, 190, release=0.03), -14),
    ("click-mech-2", "click", "Mechanical click, tight", 2, lambda r: click(r, 3300, 220, release=0.022), -15),
    ("click-mech-3", "click", "Mechanical click, heavy", 3, lambda r: click(r, 2100, 150, release=0.04), -13),
    ("click-muted-1", "click-muted", "Muted button click", 1, lambda r: click(r, 1600, 170, dark=True, release=0.03), -16),
    ("click-muted-2", "click-muted", "Muted click, soft", 1, lambda r: click(r, 1200, 140, dark=True, release=0.04), -17),
    ("click-muted-3", "click-muted", "Muted click, felt", 1, lambda r: click(r, 1900, 200, dark=True, release=0.025), -16),
    *[(f"type-strike-{k}", "typewriter", f"Typewriter key {k}", 2, (lambda k: lambda r: key(r, typewriter=True))(k), -15) for k in range(1, 7)],
    ("type-space-1", "typewriter", "Typewriter space bar", 2, lambda r: key(r, typewriter=True, space=True), -16),
    *[(f"key-soft-{k}", "keyboard", f"Keyboard key {k}", 1, (lambda k: lambda r: key(r))(k), -18) for k in range(1, 7)],
    ("key-space-1", "keyboard", "Keyboard space bar", 1, lambda r: key(r, space=True), -18),
    ("whoosh-short-1", "whoosh", "Whoosh, short", 1, lambda r: whoosh(r, 0.45, 500, 3200, 0.5), -16),
    ("whoosh-short-2", "whoosh", "Whoosh, short, airy", 1, lambda r: whoosh(r, 0.5, 700, 4200, 0.55, air=0.9), -17),
    ("whoosh-mid-1", "whoosh", "Whoosh, medium", 2, lambda r: whoosh(r, 0.8, 300, 2400, 0.55), -14),
    ("whoosh-mid-2", "whoosh", "Whoosh, medium, dark", 2, lambda r: whoosh(r, 0.85, 220, 1600, 0.5), -13),
    ("whoosh-long-1", "whoosh", "Whoosh, long", 2, lambda r: whoosh(r, 1.3, 200, 2000, 0.6), -14),
    ("whoosh-dir-r", "whoosh", "Whoosh, left to right", 2, lambda r: whoosh(r, 0.7, 350, 2800, 0.55, direction=0.7), -14),
    ("whoosh-dir-l", "whoosh", "Whoosh, right to left", 2, lambda r: whoosh(r, 0.7, 350, 2800, 0.55, direction=-0.7), -14),
    ("whoosh-dir-up", "whoosh", "Whoosh, rising", 2, lambda r: whoosh(r, 0.7, 250, 3800, 0.6, air=0.8), -14),
    ("rwhoosh-1", "reverse-whoosh", "Reverse whoosh", 2, lambda r: whoosh(r, 1.0, 250, 2600, 0.3, reverse=True), -14),
    ("rwhoosh-2", "reverse-whoosh", "Reverse whoosh, long", 2, lambda r: whoosh(r, 1.6, 180, 2000, 0.25, reverse=True), -14),
    ("rwhoosh-3", "reverse-whoosh", "Reverse whoosh, short", 1, lambda r: whoosh(r, 0.6, 400, 3500, 0.3, reverse=True), -16),
    ("thump-deep-1", "thump", "Deep cinematic thump", 2, lambda r: thump(r, 110, 46, 0.32), -9),
    ("thump-deep-2", "thump", "Deep thump, short", 2, lambda r: thump(r, 130, 55, 0.2, tail=0.6), -10),
    ("thump-deep-3", "thump", "Deep thump, round", 3, lambda r: thump(r, 95, 40, 0.45), -8),
    ("bass-hit-1", "bass-impact", "Subtle bass impact", 2, lambda r: thump(r, 80, 38, 0.6, grit=0.05, tail=1.6), -10),
    ("bass-hit-2", "bass-impact", "Bass impact, soft", 1, lambda r: thump(r, 70, 36, 0.5, grit=0.02, tail=1.2), -12),
    ("bass-hit-3", "bass-impact", "Bass impact, wide", 2, lambda r: thump(r, 90, 41, 0.75, grit=0.08, tail=2.0), -10),
    ("pulse-low-1", "pulse", "Low-frequency pulse", 1, lambda r: pulse(r, 55, 0.6), -12),
    ("pulse-low-2", "pulse", "Low pulse, double", 2, lambda r: pulse(r, 50, 0.9, double=True), -12),
    ("pulse-low-3", "pulse", "Low pulse, short", 1, lambda r: pulse(r, 62, 0.4), -13),
    ("notify-1", "notification", "Digital notification, two notes", 1, lambda r: chime(r, 880, (1.0, 1.5)), -18),
    ("notify-2", "notification", "Digital notification, single", 1, lambda r: chime(r, 1046, (1.0,), decay=0.25), -19),
    ("notify-3", "notification", "Digital notification, low", 1, lambda r: chime(r, 660, (1.0, 1.335), 0.09), -18),
    ("scan-1", "scan", "Digital scan", 1, lambda r: scan(r, 1.1), -20),
    ("scan-2", "scan", "Digital scan, short", 1, lambda r: scan(r, 0.6, 1200, 3600, 40), -20),
    ("scan-3", "scan", "Digital scan, long, low", 1, lambda r: scan(r, 1.8, 600, 2200, 26), -21),
    ("paper-1", "paper", "Paper movement", 1, lambda r: paper(r, 0.5), -18),
    ("paper-2", "paper", "Paper movement, crisp", 1, lambda r: paper(r, 0.4, crisp=0.9), -18),
    ("paper-3", "paper", "Paper slide", 1, lambda r: paper(r, 0.7, slide=True, crisp=0.3), -18),
    ("doc-1", "document", "Document reveal", 2, lambda r: document(r, 0.7), -15),
    ("doc-2", "document", "Document reveal, quick", 1, lambda r: document(r, 0.5), -16),
    ("doc-3", "document", "Document reveal, slow", 2, lambda r: document(r, 1.0), -15),
    ("shutter-1", "shutter", "Camera shutter (manual use only)", 2, lambda r: shutter(r), -16),
    ("shutter-2", "shutter", "Camera shutter, soft (manual use only)", 1, lambda r: shutter(r), -18),
    ("tick-1", "tick", "Soft tick", 1, lambda r: tick(r, 3400), -20),
    ("tick-2", "tick", "Soft tick, low", 1, lambda r: tick(r, 2500), -20),
    ("tick-seq-1", "tick", "Ticking, four seconds", 1, lambda r: tick(r, 3000, 4, 1.0), -21),
    ("riser-1", "riser", "Cinematic riser, two seconds", 2, lambda r: riser(r, 2.0), -15),
    ("riser-2", "riser", "Cinematic riser, three seconds", 2, lambda r: riser(r, 3.0, 140, 1100), -15),
    ("riser-3", "riser", "Riser, short", 1, lambda r: riser(r, 1.2, 240, 1800), -16),
    ("sweep-up-1", "tonal-sweep", "Tonal sweep, up", 1, lambda r: sweep_tone(r, 0.8, 300, 1100), -19),
    ("sweep-up-2", "tonal-sweep", "Tonal sweep, up, short", 1, lambda r: sweep_tone(r, 0.5, 420, 1500), -19),
    ("sweep-down-1", "tonal-sweep", "Tonal sweep, down", 1, lambda r: sweep_tone(r, 0.9, 280, 1000, up=False), -19),
    ("swell-1", "swell", "Atmospheric swell, minor", 2, lambda r: swell(r, 3.5, 110, True), -17),
    ("swell-2", "swell", "Atmospheric swell, low", 1, lambda r: swell(r, 4.5, 82.4, True, 900), -17),
    ("swell-3", "swell", "Atmospheric swell, open", 2, lambda r: swell(r, 3.0, 98, False, 1600), -17),
    ("impact-tr-1", "transition-impact", "Transition impact", 2, lambda r: impact(r, 1.0), -9),
    ("impact-tr-2", "transition-impact", "Transition impact, light", 1, lambda r: impact(r, 0.4), -11),
    ("impact-tr-3", "transition-impact", "Transition impact, heavy", 3, lambda r: impact(r, 1.6), -8),
    ("bell-1", "bell", "Notification bell", 1, lambda r: bell(r, 1320, 0.9), -17),
    ("bell-2", "bell", "Notification bell, double", 2, lambda r: bell(r, 1175, 0.8, 2), -17),
    ("bell-3", "bell", "Bell, small", 1, lambda r: bell(r, 1760, 0.6), -18),
    ("cta-click-1", "cta-click", "Subscribe button click", 2, lambda r: click(r, 2300, 200, release=0.06), -13),
    ("cta-click-2", "cta-click", "Button click, soft", 1, lambda r: click(r, 1800, 180, dark=True, release=0.05), -15),
    ("cta-click-3", "cta-click", "Button click, bright", 2, lambda r: click(r, 3000, 230, release=0.05), -14),
]
BY_ID = {c[0]: c for c in CATALOG}
CATEGORIES = sorted({c[1] for c in CATALOG})
# where the sound lines up with the picture: "peak" (loudest moment) or "end" (risers, reverse whooshes)
SYNC_AT_END = {"riser", "reverse-whoosh"}
SYNC_AT_PEAK = {"whoosh", "tonal-sweep", "swell"}  # the loudest moment meets the picture


def folder(data):
    return Path(data) / "cache" / "sfx" / f"lib-{LIB_VERSION}"


def synth(sound_id):
    """The sound as float32 [2, n] at its designed level, and its sync point in seconds."""
    sid, cat, _, _, recipe, peak_db = BY_ID[sound_id]
    x = _fade(recipe(_rng(f"casefile-sfx-{LIB_VERSION}-{sid}")))
    # trim the silent tail (the room can leave a long near-silent end)
    mag = np.max(np.abs(x), axis=0)
    loud = np.nonzero(mag > mag.max() * 10 ** (-60 / 20))[0]
    x = _fade(x[:, : max(loud[-1] + _n(0.01), _n(0.03))] if len(loud) else x, 0.0005, 0.03)
    x *= 10 ** (peak_db / 20) / (np.max(np.abs(x)) + 1e-12)
    env = np.convolve(np.max(np.abs(x), axis=0), np.ones(_n(0.01)) / _n(0.01), mode="same")
    if cat in SYNC_AT_END or cat in SYNC_AT_PEAK:
        sync = float(np.argmax(env)) / SR  # the crest (just before the end for a riser)
    else:
        sync = float(np.argmax(env > env.max() * 0.5)) / SR  # the transient (half-way up the attack)
    return x.astype(np.float32), round(sync, 4)


def _write(path, x):
    pcm = (np.clip(x, -1, 1).T * 32767).astype("<i2")
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    tmp.replace(path)


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        n, ch = w.getnframes(), w.getnchannels()
        raw = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32767
    return raw.reshape(-1, ch).T if ch > 1 else np.stack([raw, raw])


def ensure(data, ids=None):
    """Make the library files that are missing; returns the manifest {id: entry}."""
    root = folder(data)
    root.mkdir(parents=True, exist_ok=True)
    man_path = root / "manifest.json"
    with _LOCK:
        manifest = json.loads(man_path.read_text()) if man_path.exists() else {}
        changed = False
        for sid in ids or BY_ID:
            path = root / f"{sid}.wav"
            if sid in manifest and path.exists():
                continue
            x, sync = synth(sid)
            _write(path, x)
            c = BY_ID[sid]
            rms = float(np.sqrt(np.mean(x ** 2)))
            manifest[sid] = {
                "id": sid, "category": c[1], "label": c[2], "intensity": c[3],
                "seconds": round(x.shape[1] / SR, 3), "sync": sync,
                "peak_db": c[5], "rms_db": round(20 * np.log10(rms + 1e-9), 1),
                "source": "Generated by Casefile (procedural synthesis, sfxlib.py)",
                "license": "No third-party material. Made by this program; free to use, change and publish (CC0-equivalent).",
                "attribution": "None required.",
            }
            changed = True
        if changed:
            man_path.write_text(json.dumps(manifest, indent=1))
    return manifest


def path_of(data, sound_id):
    if sound_id not in BY_ID:
        raise KeyError(sound_id)
    p = folder(data) / f"{sound_id}.wav"
    if not p.exists():
        ensure(data, [sound_id])
    return p


def catalog():
    """[{id, category, label, intensity}] without making any file."""
    return [{"id": c[0], "category": c[1], "label": c[2], "intensity": c[3]} for c in CATALOG]
