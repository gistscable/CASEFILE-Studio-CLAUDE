"""Sound design for graphics: every Cue lands its sfxlib sync point (transient / crest) on the frame the
visual event happens. Sounds come from the app's own procedural library (sfxlib), so there are no
samples to license or download, and the same ids give the same audio on every machine."""
from __future__ import annotations

import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

from .. import sfxlib  # noqa: E402  (storyroom-kit: the kit's own copy)

from .timing import ffbin  # noqa: E402

SR = sfxlib.SR


@lru_cache(maxsize=128)
def _sound(sid: str):
    return sfxlib.synth(sid)


def decode(path: str, loudnorm: bool = True) -> np.ndarray:
    af = "loudnorm=I=-16:TP=-1.5:LRA=11," if loudnorm else ""
    raw = subprocess.run([ffbin(), "-v", "error", "-nostdin", "-i", path, "-af", af + f"aresample={SR},aformat=sample_fmts=flt:channel_layouts=stereo",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).T.copy()


def place(cues, n: int, offset: float = 0.0, bus_db: float = 0.0) -> np.ndarray:
    bus = np.zeros((2, n), np.float32)
    for c in cues:
        try:
            x, sync = _sound(c.sfx)
        except KeyError:
            raise KeyError(f"unknown sfx id {c.sfx!r} (cue: {c.why})")
        start = int(round((c.t + offset - sync) * SR))
        a, b = max(0, start), min(n, start + x.shape[1])
        if b > a:
            bus[:, a:b] += x[:, a - start:b - start] * (10 ** ((c.gain_db + bus_db) / 20))
    return bus


def mix(cues, narration: str, duration: float, out_wav: str, narration_offset: float = 0.0, bus_db: float = 4.0):
    """Narration (loudness-normalised) + the cue bus, ducked under speech, then a gentle true-peak guard."""
    n = int(round(duration * SR))
    voice = np.zeros((2, n), np.float32)
    v = decode(narration)
    o = int(round(narration_offset * SR))
    voice[:, o:o + v.shape[1]] = v[:, : max(0, n - o)]
    bus = place(cues, n, 0.0, bus_db)
    # duck the effects 4 dB while the narrator is speaking (40 ms envelope) so words stay on top
    env = np.convolve(np.abs(voice).max(axis=0), np.ones(int(0.04 * SR)) / int(0.04 * SR), mode="same")
    speaking = np.clip(env / 0.05, 0, 1)
    bus *= (1 - speaking * (1 - 10 ** (-4 / 20))).astype(np.float32)
    out = voice + bus
    raw = out.T.astype(np.float32).tobytes()
    subprocess.run([ffbin(), "-v", "error", "-y", "-nostdin", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-af", "alimiter=limit=0.891:attack=3:release=60:level=disabled", "-c:a", "pcm_s24le", out_wav],
                   input=raw, check=True)
    return out_wav
