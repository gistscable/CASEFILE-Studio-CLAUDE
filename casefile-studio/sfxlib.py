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
LIB_VERSION = 2  # bump when a recipe changes: the files are made again (v0.4.57: 2)
SEED_VERSION = 1  # the random seeds: unchanged recipes make exactly the same sound as before
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


def _warm(x, drive=1.5, even=0.2):
    """Saturation with a little even-harmonic colour (asymmetric), DC removed: weight, not distortion."""
    return _band(_sat(x + even * x * x, drive), lo=24)


def _tail(n, last):
    """1 -> 0 over the final `last` seconds (squared cosine): no layer stops abruptly."""
    k = min(n, _n(last))
    w = np.ones(n)
    w[n - k:] = np.cos(np.linspace(0, np.pi / 2, k)) ** 2
    return w


def _bursts(n, rng, at, lo, hi, amp, decay=0.0008):
    """Small mechanical after-ticks (rattle) at the given times (seconds): [(t, level)]."""
    y = np.zeros(n)
    for t0, a in at:
        s = _n(t0)
        if s >= n - 8:
            continue
        k = min(n - s, _n(0.012))
        y[s:s + k] += a * amp * _band(rng.standard_normal(k), lo=lo, hi=hi) * _env(k, 0.0001, decay)
    return y


def _saw(f, t, ph, top):
    """A band-limited sawtooth (harmonics 1/k up to `top` Hz)."""
    y = np.zeros_like(t)
    for k in range(1, max(1, int(top / f)) + 1):
        y += np.sin(2 * np.pi * f * k * t + ph * k) / k
    return y


# ====================================================================== the recipes

def click(rng, tone=2600, body=180, dark=False, release=0.035, level=1.0):
    """v2: a switch, not a blip: a sharp contact, the plastic and spring ringing (inharmonic modes,
    the high ones dying first), a small body thock and a little rattle; the release is lighter and higher."""
    n = _n(0.1 + release)
    y = np.zeros(n)

    def layer(at, amp, f, bright):
        k = _n(0.03)
        burst = _band(rng.standard_normal(k), lo=f * 0.4, hi=f * (1.0 if dark else 2.6)) * _env(k, 0.0002, 0.0012 + 0.0009 * bright)
        ratios = np.array([1.0, 1.52, 2.31, 2.97, 3.84]) * (1 + rng.uniform(-0.04, 0.04, 5))
        modes = _partials(f * ratios, [0.007, 0.005, 0.0035, 0.0025, 0.0018], [0.5, 0.35, 0.22, 0.14, 0.08], k, rng)
        thock = _partials([body, body * 2.03], [0.014, 0.006], [0.6, 0.15], k) * _env(k, 0.0006, 0.02)
        s0 = burst + 0.4 * modes * _env(k, 0.0002, 0.01) + 0.55 * thock
        s0 += _bursts(k, rng, [(rng.uniform(0.0012, 0.0022), 0.22), (rng.uniform(0.003, 0.0045), 0.1)], f, f * 3, 1.0)
        s = _n(at)
        y[s:s + k] += amp * s0[: n - s]

    layer(0.004, 1.0, tone, 1.0)
    layer(0.004 + release, 0.42, tone * rng.uniform(1.08, 1.18), 0.6)
    if dark:
        y = _band(y, hi=1500)
    return _room(y * level, rng, rt=0.22, wet=0.07)


def pop(rng, f0=950, f1=260, decay=0.05):
    n = _n(decay * 4 + 0.02)
    body = _glide(f0, f1, n, 0.35) * _env(n, 0.0015, decay)
    air = _band(rng.standard_normal(n), lo=1500, hi=7000) * _env(n, 0.0005, 0.004) * 0.3
    return _room(body + air, rng, rt=0.3, wet=0.1)


# v2: every key variant is its own key (weight, pitch, rattle), not only another random seed
_KEYS = {1: (1.0, 1.0, 1.0), 2: (0.85, 1.07, 0.85), 3: (1.12, 0.94, 1.2), 4: (0.92, 1.13, 0.75), 5: (1.05, 0.9, 1.05), 6: (0.8, 1.03, 1.3)}


def key(rng, typewriter=False, space=False, k=1):
    """One keystroke: a typewriter type-bar strike, or a soft keyboard key (v2: the finger on the key,
    the strike, the mechanism's rattle and, on a typewriter, the carriage stepping on)."""
    vel, pitch, rattle = _KEYS.get(k, (1.0, 1.0, 1.0))
    if typewriter:
        n = _n(0.2)
        pre = _n(rng.uniform(0.009, 0.014))  # the key top is touched a moment before the bar lands
        y = np.zeros(n)
        y += 0.16 * _band(rng.standard_normal(n), lo=500, hi=2500) * _env(n, 0.0003, 0.002)
        m = n - pre
        tm = _t(m)
        strike = _band(rng.standard_normal(m), lo=700, hi=5500 * pitch) * _env(m, 0.0002, 0.004 + 0.002 * vel)
        metal = _partials(rng.uniform([1900, 2900, 4100, 5200], [2300, 3400, 4700, 6000]) * pitch, [0.028, 0.02, 0.012, 0.008],
                          [0.32, 0.22, 0.12, 0.07], m, rng) * _env(m, 0.0004, 0.03)
        platen = (_partials([rng.uniform(135, 175) * pitch], [0.03], [0.9], m) * (tm > 0.0012)
                  + 0.5 * _band(rng.standard_normal(m), lo=100, hi=600) * _env(m, 0.001, 0.015))
        mech = _bursts(m, rng, [(rng.uniform(0.016, 0.022), 0.5), (rng.uniform(0.028, 0.036), 0.3)], 1800, 6500, 0.25 * rattle)
        carriage = _bursts(m, rng, [(rng.uniform(0.05, 0.065), 1.0)], 1200, 4500, 0.12, decay=0.0015)
        y[pre:] += vel * (strike + metal + 0.7 * platen) + mech + carriage
        if space:
            y = _band(y, hi=2200) * 1.1
    else:
        n = _n(0.11)
        down = _band(rng.standard_normal(n), lo=1300, hi=6200 * pitch) * _env(n, 0.0003, 0.0035)
        plate = _partials(rng.uniform([1300, 2100, 3300], [1600, 2600, 3900]) * pitch, [0.006, 0.004, 0.003], [0.25, 0.15, 0.08], n, rng)
        thock = _partials([rng.uniform(220, 290) / pitch], [0.014 * vel], [0.8], n)
        y = vel * (down + 0.5 * plate * _env(n, 0.0003, 0.008) + 0.6 * thock)
        up = _n(rng.uniform(0.045, 0.07))
        y[up:] += 0.33 * _band(rng.standard_normal(n - up), lo=1900, hi=7000) * _env(n - up, 0.0002, 0.0025)
        y += _bursts(n, rng, [(rng.uniform(0.006, 0.01), 0.4)], 2500, 7000, 0.12 * rattle)
        if space:
            y = _band(y, hi=2500) * 1.2
    return _room(y, rng, rt=0.3, wet=0.07)


def whoosh(rng, length=0.7, f_lo=350, f_hi=2600, peak=0.55, direction=0.0, reverse=False, air=0.6):
    """v2: moving air, not a whistle: a broad band that sweeps (v1's narrow band rang like a tone),
    a quieter airy top an octave up and a little low body, all on the same envelope."""
    n = _n(length)
    centers = np.concatenate([np.geomspace(f_lo, f_hi, 16)[: int(16 * peak)], np.geomspace(f_hi, f_lo * 0.8, 16)[int(16 * peak):]])
    y = _sweep(_noise(n, rng, "pink"), centers, width=0.85 + 0.45 * air)
    y += (0.3 + 0.3 * air) * _sweep(_noise(n, rng, "white"), centers * 2.3, width=0.8)
    y += 0.22 * _band(_noise(n, rng, "pink"), lo=45, hi=max(120, f_lo * 0.7))
    e = _shape(n, [(0, 0), (peak * 0.6, 0.25), (peak, 1.0), (min(0.98, peak + 0.25), 0.25), (1, 0)]) ** 1.4
    y *= e
    if reverse:
        y = y[::-1]
    pos = np.linspace(-direction, direction, n) if direction else 0.0
    st = _pan(y, pos) if direction else _stereo(y)
    out = np.stack([_room(st[0], rng, rt=0.7, wet=0.22)[0], _room(st[1], rng, rt=0.7, wet=0.22)[1]])
    return out


def thump(rng, f0=110, f1=48, decay=0.32, grit=0.15, tail=0.9):
    """v2: every layer dies away on its own (v1 stopped the sub at -27 dB: an audible cut), with the
    air of the hit (a low skin of noise), a soft beater and warm harmonics instead of a bare sine."""
    n = _n(decay * 9)
    t = _t(n)
    body = _glide(f0, f1, n, 0.25) * _env(n, 0.004, decay)
    sub = np.sin(2 * np.pi * f1 * 0.98 * t) * _env(n, 0.03, decay * 1.6) * 0.5
    skin = _band(_noise(n, rng, "pink"), lo=60, hi=420) * _env(n, 0.002, decay * 0.3) * (0.22 + grit)
    hit = _band(rng.standard_normal(n), lo=60, hi=900) * _env(n, 0.001, 0.02) * grit * 3
    beater = _band(rng.standard_normal(n), lo=1500, hi=5000) * _env(n, 0.0003, 0.003) * grit * 0.8
    y = _warm(body + sub + skin + hit + beater, 1.5, 0.18) * _tail(n, decay * 3)
    return _room(y, rng, rt=tail, wet=0.15, bright=1800)


def pulse(rng, f=55, length=0.6, double=False):
    """v2: a felt low thud (a soft pitch drop on the onset, warm harmonics and a breath of low noise)
    instead of a sine test tone; the double one is a heartbeat-like lub-dub."""
    n = _n(length + 0.35)

    def beat(m, amp):
        t = _t(m)
        ph = 2 * np.pi * np.cumsum(f * (1 + 0.35 * np.exp(-t / 0.025))) / SR
        e = _env(m, 0.06 * length, 0.32 * length)
        tone = (np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)) * e
        breath = _band(_noise(m, rng, "pink"), lo=f * 0.8, hi=f * 6) * _env(m, 0.01, 0.2 * length) * 0.5
        knock = _band(rng.standard_normal(m), lo=250, hi=900) * _env(m, 0.001, 0.012) * 0.25
        return amp * (tone + breath + knock)

    y = beat(n, 1.0)
    if double:
        k = _n(length * 0.42)
        y[k:] += beat(n - k, 0.6)
    y = _band(_warm(y, 1.4, 0.15), hi=750) * _tail(n, 0.2)
    return _room(y, rng, rt=0.8, wet=0.12, bright=900)


def chime(rng, base=880, ratios=(1.0, 1.5), spacing=0.11, decay=0.35, soft=True):
    """v2: a glassy, friendly tone: an FM attack that settles into a pure note, a slow beating
    partner (shimmer), a fast-dying upper partial and the soft tap of a mallet."""
    n = _n(spacing * len(ratios) + decay * 4)
    y = np.zeros(n)
    for k, r in enumerate(ratios):
        s = _n(spacing * k)
        m = n - s
        t = _t(m)
        f = base * r
        index = 2.0 * np.exp(-t / (decay * 0.22))
        env = _env(m, 0.002, decay * 1.6)
        tone = np.sin(2 * np.pi * f * t + index * np.sin(2 * np.pi * f * 3.5 * t)) * env
        tone += 0.22 * np.sin(2 * np.pi * f * 1.0035 * t + rng.uniform(0, 6.28)) * env
        tone += 0.1 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t / (decay * 0.3))
        tone += 0.25 * _band(rng.standard_normal(m), lo=f * 1.5, hi=f * 6) * _env(m, 0.0003, 0.003)
        y[s:] += tone
    if soft:
        y = _band(y, hi=5000)
    return _room(y, rng, rt=1.1, wet=0.25)


def scan(rng, length=1.1, f0=900, f1=3200, rate=34):
    """v2: a train of soft grains (raised-cosine, each a little different in level and timing) over
    a gliding FM tone, instead of v1's hard square gate (which clicked on every edge)."""
    n = _n(length)
    am = np.zeros(n)
    period = 1.0 / rate
    w = _n(period * 0.6)
    at = 0.0
    while at < length:
        s = _n(max(0.0, at + rng.uniform(-0.08, 0.08) * period))
        if s < n:
            am[s:s + w] += rng.uniform(0.6, 1.0) * np.hanning(w)[: n - s]
        at += period
    f = f0 * (f1 / f0) ** np.linspace(0, 1, n)
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sin(ph + 0.7 * np.sin(2.01 * ph)) * 0.35
    grain = _band(rng.standard_normal(n), lo=2500, hi=9000) * 0.45
    e = _shape(n, [(0, 0), (0.12, 1), (0.85, 0.8), (1, 0)])
    y = _band((tone + grain) * (0.12 + 0.88 * np.minimum(am, 1.0)) * e, lo=500, hi=8000)
    st = _pan(y, np.linspace(-0.4, 0.4, n))
    return np.stack([_room(st[0], rng, rt=0.35, wet=0.08)[0], _room(st[1], rng, rt=0.35, wet=0.08)[1]])


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


def shutter(rng, soft=False):
    """Two curtains and the mirror (v2: the soft one is a different, darker single-curtain shutter)."""
    n = _n(0.2)
    y = np.zeros(n)
    hits = ((0.0, 1.0, 2200), (0.04, 0.35, 1700)) if soft else ((0.0, 1.0, 3000), (0.055, 0.7, 2400))
    for at, amp, f in hits:
        k = _n(0.03)
        s = _n(at)
        y[s:s + k] += amp * (_band(rng.standard_normal(k), lo=f * 0.5, hi=f * 2) * _env(k, 0.0003, 0.004)
                             + 0.4 * _partials([f * 0.6, f * 0.97], [0.008, 0.004], [1, 0.3], k, rng))
    y += _bursts(n, rng, [(0.012, 0.4), (0.07 if not soft else 0.05, 0.25)], 2500, 7000, 0.3)
    spring = _band(rng.standard_normal(n), lo=3000, hi=8000) * _env(n, 0.01, 0.03) * (0.06 if soft else 0.15)
    y = y + spring
    if soft:
        y = _band(y, hi=3500)
    return _room(y, rng, rt=0.3, wet=0.08)


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
    """v2: a soft, slightly breathy tone (odd harmonics, a gentle vibrato and a detuned partner)
    that glides, instead of three pure sine glides."""
    n = _n(length)
    t = _t(n)
    a, b = (f0, f1) if up else (f1, f0)
    f = a * (b / a) ** np.linspace(0, 1, n) * (1 + 0.003 * np.sin(2 * np.pi * 5.5 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR

    def tri(p):
        return np.sin(p) - np.sin(3 * p) / 9 + np.sin(5 * p) / 25

    y = tri(ph) + 0.6 * tri(ph * 1.004 + 1.3) + 0.25 * np.sin(2 * ph)
    y *= _shape(n, [(0, 0), (0.3, 1), (0.7, 0.8), (1, 0)])
    air = _sweep(_noise(n, rng, "pink"), [a * 2, b * 2], 0.8) * 0.3 * _shape(n, [(0, 0), (0.5, 1), (1, 0)])
    return _room(_band(y + air, hi=6000), rng, rt=0.9, wet=0.25)


def swell(rng, length=3.5, root=110.0, minor=True, bright=1400):
    """v2: a pad, not sines: each note a band-limited saw in three detuned voices, through a filter
    that opens as the swell grows (it gets brighter as it gets louder), with low air underneath."""
    n = _n(length)
    t = _t(n)
    chord = [1, 1.189 if minor else 1.26, 1.498, 2.0]
    y = np.zeros(n)
    for r in chord:
        for det in (-0.005, 0.0, 0.006):
            f = root * r * (1 + det)
            y += _saw(f, t, rng.uniform(0, 6.28), min(bright * 3, f * 14))
    y /= 12
    e = _shape(n, [(0, 0), (0.55, 1), (0.75, 0.75), (1, 0)]) ** 1.3
    y = _band(y, hi=bright * 0.35) * (1 - e) + _band(y, hi=bright) * e
    air = _band(_noise(n, rng, "pink"), lo=120, hi=bright * 1.5) * 0.1
    return _room((y + air) * e, rng, rt=1.6, wet=0.3)


def impact(rng, weight=1.0):
    """v2: the body, a low-mid boom and the crack, each with its whole tail (v1 cut the crack's room
    off after 0.25 s)."""
    body = thump(rng, f0=95 + 20 * weight, f1=42, decay=0.38 + 0.15 * weight, grit=0.25, tail=1.3)
    m = _n(0.6)
    crack = _band(rng.standard_normal(m), lo=700, hi=5000) * _env(m, 0.0008, 0.03) * 0.25
    boom = _band(_noise(m, rng, "pink"), lo=120, hi=700) * _env(m, 0.002, 0.09) * 0.3 * (0.6 + 0.4 * weight)
    layer = _room((crack + boom) * _tail(m, 0.2), rng, rt=1.2, wet=0.4)
    out = np.zeros((2, max(body.shape[1], layer.shape[1])))
    out[:, : body.shape[1]] += body
    out[:, : layer.shape[1]] += layer
    return out


def bell(rng, base=1320, decay=0.9, strikes=1):
    """v2: struck metal: each partial a slowly beating pair (real bells are never perfectly round),
    higher partials dying faster, and the tap of the striker."""
    n = _n(decay * 3 + 0.25 * strikes)
    y = np.zeros(n)
    ratios, amps = [0.5, 1.0, 1.183, 1.506, 2.0, 2.74], [0.25, 1.0, 0.5, 0.35, 0.3, 0.15]
    decays = [decay * d for d in (1.4, 1, 0.7, 0.5, 0.4, 0.25)]
    for k in range(strikes):
        s = _n(0.18 * k)
        m = n - s
        f = [base * r * (1 + rng.uniform(-0.002, 0.002)) for r in ratios]
        beat = [x * (1 + 0.0012 * (i + 1)) for i, x in enumerate(f)]
        # each pair starts in phase (the strike is the loudest moment) and drifts apart slowly
        tone = _partials(f, decays, [a * 0.75 for a in amps], m) + _partials(beat, decays, [a * 0.3 for a in amps], m)
        tap = 0.3 * _band(rng.standard_normal(m), lo=base * 0.8, hi=base * 6) * _env(m, 0.0002, 0.004)
        y[s:] += (0.75 ** k) * (tone * _env(m, 0.002, 10) + tap)
    return _room(_band(y, hi=7000), rng, rt=1.0, wet=0.2)


# ---------------------------------------------------------------- v0.4.74 phone & app sounds
# Short alert sounds in the style of phone notifications, made here like everything else: nothing
# is copied from a phone maker's or an editing app's library (those recordings belong to them).

def _mallet(f, m, decay, rng, hard=1.0, wood=False):
    """A struck bar: an FM bite that settles into the note, a high partial (wood: marimba-like,
    else glassy) that dies first, and the soft tap of the mallet."""
    t = _t(m)
    bite = hard * 2.4 * np.exp(-t / 0.012)
    y = np.sin(2 * np.pi * f * t + bite * np.sin(2 * np.pi * f * (3.0 if wood else 2.0) * t))
    y += 0.35 * np.sin(2 * np.pi * f * (3.93 if wood else 4.0) * t) * np.exp(-t / max(1e-3, decay * 0.18))
    y *= _env(m, 0.001, decay)
    y += 0.2 * hard * _band(rng.standard_normal(m), lo=f, hi=f * 5) * _env(m, 0.0002, 0.002)
    return y


def _notes(notes, rng, total, **kw):
    """[(at seconds, Hz, decay, level)] struck one after another, mono."""
    n = _n(total)
    y = np.zeros(n)
    for at, f, d, a in notes:
        s = _n(at)
        y[s:] += a * _mallet(f, n - s, d, rng, **kw)
    return y * _tail(n, min(0.4, total / 3))  # rings out, never cut off


def trio(rng, root=1568.0):
    """Three quick bright notes, up and back down a step: the classic text-message alert shape."""
    notes = [(0.0, root, 0.09, 1.0), (0.095, root * 1.335, 0.09, 0.9), (0.19, root * 1.122, 0.24, 0.95)]
    return _room(_band(_notes(notes, rng, 1.1, wood=True), hi=9000), rng, rt=0.35, wet=0.1)


def chirp(rng, count=2):
    """A small bird: quick upward whistles with a flutter."""
    n = _n(0.11 * count + 0.2)
    y = np.zeros(n)
    for k in range(count):
        s = _n(0.11 * k + rng.uniform(0, 0.004))
        m = _n(0.075 if k < count - 1 else 0.09)
        p = np.linspace(0, 1, m)
        f = 2500 + 2300 * np.sin(np.pi * 0.5 * p) ** 1.5 + 160 * np.sin(2 * np.pi * 42 * p * m / SR)
        ph = 2 * np.pi * np.cumsum(f) / SR
        tone = (np.sin(ph) + 0.15 * np.sin(2 * ph)) * np.sin(np.pi * p) ** 1.2
        y[s:s + m] += tone[: n - s]
    return _room(y, rng, rt=0.3, wet=0.12)


def glow(rng, root=784.0):
    """A soft shimmering arpeggio that rises and rings out in a big space."""
    ratios = [1.0, 1.26, 1.5, 2.0, 2.52]
    notes = [(0.075 * i, root * r, 0.9, 0.75 - 0.07 * i) for i, r in enumerate(ratios)]
    y = _notes(notes, rng, 2.2, hard=0.35)
    y *= 1 + 0.25 * np.sin(2 * np.pi * 5.5 * _t(len(y)))  # the shimmer
    return _room(_band(y * _tail(len(y), 0.6), hi=7000), rng, rt=1.8, wet=0.35, width=1.2)


def strum(rng, root=523.25):
    """A quick plucked major chord, low to high."""
    n = _n(1.3)
    y = np.zeros(n)
    for i, r in enumerate((1.0, 1.26, 1.5, 2.0)):
        s = _n(0.018 * i)
        m = n - s
        f = root * r
        y[s:] += _partials([f, 2 * f, 3 * f, 4.01 * f], [0.5, 0.25, 0.12, 0.07], [1, 0.45, 0.25, 0.12], m, rng)
        y[s:] += 0.12 * _band(rng.standard_normal(m), lo=f * 2, hi=f * 8) * _env(m, 0.0003, 0.003)
    return _room(_band(y * _tail(n, 0.4), hi=8000), rng, rt=0.7, wet=0.15)


def bounce(rng, f=1180.0):
    """A ball bouncing to rest: three falling-pitch blips, each sooner, higher and softer."""
    n = _n(0.7)
    y = np.zeros(n)
    for at, a, ff in ((0.0, 1.0, f), (0.15, 0.62, f * 1.06), (0.25, 0.38, f * 1.12)):
        s = _n(at)
        m = min(_n(0.3), n - s)
        tone = _glide(ff * 1.25, ff, m, 0.25) * _env(m, 0.001, 0.055)
        tone += 0.3 * _glide(ff * 2.5, ff * 2, m, 0.25) * _env(m, 0.001, 0.025)
        y[s:s + m] += a * tone
    return _room(y, rng, rt=0.35, wet=0.1)


def pin(rng, count=1, gap=0.055):
    """A tiny bright tick (a pin dropping onto a map, a counter rolling over)."""
    n = _n(gap * (count - 1) + 0.07)
    y = np.zeros(n)
    for k in range(count):
        s = _n(gap * k)
        m = min(_n(0.06), n - s)
        f = 5200 * (1 + (0.04 if k % 2 else 0)) * rng.uniform(0.985, 1.015)
        y[s:s + m] += (0.9 ** k) * (_partials([f, f * 1.52, f * 0.5], [0.0035, 0.002, 0.006], [1, 0.5, 0.35], m, rng)
                                    + 0.5 * _band(rng.standard_normal(m), lo=3000) * _env(m, 0.0001, 0.0008))
    return _room(y, rng, rt=0.15, wet=0.05)


# search words for the library (styles people know these sounds by)
TAGS = {
    "phone-trio": "tri-tone tritone text message imessage sms alert",
    "phone-chirp": "tweet bird twitter chirp",
    "phone-glow": "aurora shimmer magic",
    "phone-chord": "note chord strum guitar",
    "phone-bounce": "rebound boing ball",
    "phone-ding": "bell ding desk reception",
    "phone-pin": "pin ticker tick click 181779",
    "phone-pin-seq": "pin ticker counter rolling ticking",
}

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
    ("click-muted-3", "click-muted", "Muted click, felt", 1, lambda r: click(r, 1900, 200, dark=True, release=0.025), -13),
    *[(f"type-strike-{k}", "typewriter", f"Typewriter key {k}", 2, (lambda k: lambda r: key(r, typewriter=True, k=k))(k), -15) for k in range(1, 7)],
    ("type-space-1", "typewriter", "Typewriter space bar", 2, lambda r: key(r, typewriter=True, space=True), -13.5),
    *[(f"key-soft-{k}", "keyboard", f"Keyboard key {k}", 1, (lambda k: lambda r: key(r, k=k))(k), -18) for k in range(1, 7)],
    ("key-space-1", "keyboard", "Keyboard space bar", 1, lambda r: key(r, space=True), -18),
    ("whoosh-short-1", "whoosh", "Whoosh, short", 1, lambda r: whoosh(r, 0.45, 500, 3200, 0.5), -16),
    ("whoosh-short-2", "whoosh", "Whoosh, short, airy", 1, lambda r: whoosh(r, 0.5, 700, 4200, 0.55, air=0.9), -19.5),
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
    ("thump-deep-3", "thump", "Deep thump, round", 3, lambda r: thump(r, 95, 40, 0.45), -6),
    ("bass-hit-1", "bass-impact", "Subtle bass impact", 2, lambda r: thump(r, 80, 38, 0.6, grit=0.05, tail=1.6), -8.5),
    ("bass-hit-2", "bass-impact", "Bass impact, soft", 1, lambda r: thump(r, 70, 36, 0.5, grit=0.02, tail=1.2), -12),
    ("bass-hit-3", "bass-impact", "Bass impact, wide", 2, lambda r: thump(r, 90, 41, 0.75, grit=0.08, tail=2.0), -8.5),
    ("pulse-low-1", "pulse", "Low-frequency pulse", 1, lambda r: pulse(r, 55, 0.6), -9.5),
    ("pulse-low-2", "pulse", "Low pulse, double", 2, lambda r: pulse(r, 50, 0.9, double=True), -10),
    ("pulse-low-3", "pulse", "Low pulse, short", 1, lambda r: pulse(r, 62, 0.4), -10),
    ("notify-1", "notification", "Digital notification, two notes", 1, lambda r: chime(r, 880, (1.0, 1.5)), -20.5),
    ("notify-2", "notification", "Digital notification, single", 1, lambda r: chime(r, 1046, (1.0,), decay=0.25), -19),
    ("notify-3", "notification", "Digital notification, low", 1, lambda r: chime(r, 660, (1.0, 1.335), 0.09), -18),
    ("scan-1", "scan", "Digital scan", 1, lambda r: scan(r, 1.1), -17.5),
    ("scan-2", "scan", "Digital scan, short", 1, lambda r: scan(r, 0.6, 1200, 3600, 40), -16.5),
    ("scan-3", "scan", "Digital scan, long, low", 1, lambda r: scan(r, 1.8, 600, 2200, 26), -17.5),
    ("paper-1", "paper", "Paper movement", 1, lambda r: paper(r, 0.5), -18),
    ("paper-2", "paper", "Paper movement, crisp", 1, lambda r: paper(r, 0.4, crisp=0.9), -18),
    ("paper-3", "paper", "Paper slide", 1, lambda r: paper(r, 0.7, slide=True, crisp=0.3), -18),
    ("doc-1", "document", "Document reveal", 2, lambda r: document(r, 0.7), -15),
    ("doc-2", "document", "Document reveal, quick", 1, lambda r: document(r, 0.5), -16),
    ("doc-3", "document", "Document reveal, slow", 2, lambda r: document(r, 1.0), -15),
    ("shutter-1", "shutter", "Camera shutter (manual use only)", 2, lambda r: shutter(r), -16),
    ("shutter-2", "shutter", "Camera shutter, soft (manual use only)", 1, lambda r: shutter(r, soft=True), -16.5),
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
    ("swell-2", "swell", "Atmospheric swell, low", 1, lambda r: swell(r, 4.5, 82.4, True, 900), -14),
    ("swell-3", "swell", "Atmospheric swell, open", 2, lambda r: swell(r, 3.0, 98, False, 1600), -14),
    ("impact-tr-1", "transition-impact", "Transition impact", 2, lambda r: impact(r, 1.0), -6.5),
    ("impact-tr-2", "transition-impact", "Transition impact, light", 1, lambda r: impact(r, 0.4), -9.5),
    ("impact-tr-3", "transition-impact", "Transition impact, heavy", 3, lambda r: impact(r, 1.6), -6),
    ("bell-1", "bell", "Notification bell", 1, lambda r: bell(r, 1320, 0.9), -17),
    ("bell-2", "bell", "Notification bell, double", 2, lambda r: bell(r, 1175, 0.8, 2), -17),
    ("bell-3", "bell", "Bell, small", 1, lambda r: bell(r, 1760, 0.6), -18),
    ("cta-click-1", "cta-click", "Subscribe button click", 2, lambda r: click(r, 2300, 200, release=0.06), -13),
    ("cta-click-2", "cta-click", "Button click, soft", 1, lambda r: click(r, 1800, 180, dark=True, release=0.05), -13),
    ("cta-click-3", "cta-click", "Button click, bright", 2, lambda r: click(r, 3000, 230, release=0.05), -14),
    # v0.4.74 phone & app sounds (manual use: the automatic plan never picks the "phone" category)
    ("phone-trio", "phone", "Three-note alert (text message)", 1, lambda r: trio(r), -16),
    ("phone-chirp", "phone", "Bird chirp alert", 1, lambda r: chirp(r), -17),
    ("phone-glow", "phone", "Glow chime, shimmering", 1, lambda r: glow(r), -17),
    ("phone-chord", "phone", "Soft chord alert", 1, lambda r: strum(r), -16),
    ("phone-bounce", "phone", "Bounce alert", 1, lambda r: bounce(r), -16),
    ("phone-ding", "phone", "Bell ding", 1, lambda r: bell(r, 2093, 1.1), -16),
    ("phone-pin", "phone", "Pin tick", 1, lambda r: pin(r), -18),
    ("phone-pin-seq", "phone", "Pin ticker, rolling", 1, lambda r: pin(r, 9), -19),
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
    x = _fade(recipe(_rng(f"casefile-sfx-{SEED_VERSION}-{sid}")))
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
    return [{"id": c[0], "category": c[1], "label": c[2], "intensity": c[3], **({"tags": TAGS[c[0]]} if c[0] in TAGS else {})} for c in CATALOG]
