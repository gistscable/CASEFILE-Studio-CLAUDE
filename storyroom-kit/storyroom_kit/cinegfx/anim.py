"""Animation primitives: fast, decisive easing (no blur, no slow fades). Everything is a pure function
of time so any frame can be rendered independently, which is what lets render.py spread frames over all
cores and lets a preview scrub to any frame without replaying the graphic."""
from __future__ import annotations

import math

FAST = 0.28      # standard reveal
SNAP = 0.16      # chips, stamps, ticks
EXIT = 0.30


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def prog(t, t0, dur):
    """0..1 progress of an animation starting at t0."""
    if dur <= 0:
        return 1.0 if t >= t0 else 0.0
    return clamp((t - t0) / dur)


def out_expo(p):
    return 1.0 if p >= 1 else 1 - 2 ** (-10 * p)


def out_smooth(p):
    """v0.4.65 the standard reveal: as quick as before (same durations) but the travel is spread over more frames.
    out_expo put about 65% of a move into the first frame at 24 fps and 95% by the third, which read as a jump;
    this puts about 47% into the first frame and reaches 95% by the fifth (of a 0.28 s reveal), so a move is seen."""
    return 1.0 if p >= 1 else (1 - 2 ** (-6 * p)) / (1 - 2 ** -6)


def out_quint(p):
    return 1 - (1 - p) ** 5


def out_cubic(p):
    return 1 - (1 - p) ** 3


def in_out_cubic(p):
    return 4 * p * p * p if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def out_back(p, s=1.25):
    """A small overshoot (stamps, chips) — kept tight so it reads as a snap, not a bounce."""
    p -= 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def lerp(a, b, p):
    return a + (b - a) * p


def ease(t, t0, dur=FAST, fn=out_smooth):
    return fn(prog(t, t0, dur))


def window(t, t_in, t_out, din=FAST, dout=EXIT, fn=out_smooth):
    """Entrance progress multiplied by exit progress (1 while held)."""
    return fn(prog(t, t_in, din)) * (1 - out_cubic(prog(t, t_out, dout)))


def typed(text, t, t0, cps=38.0):
    """Typewriter: the visible prefix of `text`."""
    if t < t0:
        return ""
    n = int((t - t0) * cps)
    return text[: max(0, min(len(text), n))]


def typed_until(text, t, t0, t1):
    """Typewriter that finishes exactly at t1 (synced to when the narration finishes the phrase)."""
    if t < t0:
        return ""
    p = clamp((t - t0) / max(0.05, t1 - t0))
    return text[: int(round(len(text) * p))]


def drift(t, total, amount=0.035):
    """Slow push-in scale for photos: linear-ish, always moving, never 'settles' into a stall."""
    return 1.0 + amount * clamp(t / max(total, 0.01))


def pulse(t, t0, period=1.2):
    if t < t0:
        return 0.0
    return 0.5 - 0.5 * math.cos((t - t0) * 2 * math.pi / period)
