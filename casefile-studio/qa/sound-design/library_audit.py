"""v0.4.57 Objective audit of every sound in the library (no listening needed to find the problems,
though it does not replace listening). For each sound:

  peaks     spectral peaks within 30 dB of the strongest (richness: a bare sine has 1-2)
  flat_db   spectral flatness of the loudest 100 ms (very low = a pure test tone; ~0 = plain noise)
  cut_db    a click in the tail (a layer that stops abruptly instead of dying away): the largest jump
            of the differentiated signal over its recent median, from 100 ms after the peak (only for
            sounds with a tail; short transients and designed second hits are not tails)
  hf_spike  energy above 12 kHz created by discontinuities (hard gating, clicks), relative to the sound
  width     1 - correlation of left and right (0 = mono)
  twin      the highest similarity to another sound of the same category (1.0 = the same sound)

    cd casefile-studio && .venv/bin/python qa/sound-design/library_audit.py [out.json]
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sfxlib  # noqa: E402

SR = sfxlib.SR
# (scan is a train of designed grains: every grain is an onset, so it has no tail to check)
TAILED = {"whoosh", "reverse-whoosh", "thump", "bass-impact", "pulse", "notification", "document", "riser", "tonal-sweep",
          "swell", "transition-impact", "bell"}


def bands(x):
    """Energy in 1/3-octave bands 40 Hz..16 kHz (dB), the sound's spectral fingerprint."""
    m = x.mean(axis=0)
    spec = np.abs(np.fft.rfft(m, 1 << 17)) ** 2
    f = np.fft.rfftfreq(1 << 17, 1 / SR)
    edges = 40 * 2 ** (np.arange(0, 28) / 3)
    e = np.array([spec[(f >= a) & (f < b)].sum() + 1e-12 for a, b in zip(edges[:-1], edges[1:])])
    return 10 * np.log10(e / e.max())


def envelope(x, hop=0.005):
    m = np.abs(x).max(axis=0)
    k = int(hop * SR)
    n = len(m) // k
    return np.sqrt((m[: n * k].reshape(n, k) ** 2).mean(axis=1) + 1e-12)


def metrics(x):
    mono = x.mean(axis=0)
    env = envelope(x)
    i = int(np.argmax(env))
    k = int(0.005 * SR)
    seg = mono[max(0, i * k - 2400): i * k + 2400]
    if len(seg) < 4800:
        seg = np.pad(seg, (0, 4800 - len(seg)))
    p = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    band = p[(f > 30) & (f < 16000)] + 1e-20
    flat = 10 * np.log10(np.exp(np.mean(np.log(band))) / np.mean(band))
    # peaks: local maxima within 30 dB of the strongest, at least 3 bins apart
    db = 10 * np.log10(band / band.max())
    loc = np.nonzero((db[1:-1] > db[:-2]) & (db[1:-1] >= db[2:]) & (db[1:-1] > -30))[0]
    peaks = 0
    last = -10
    for j in loc:
        if j - last >= 3:
            peaks += 1
            last = j
    # a cut-off: a layer that stops abruptly leaves a broadband click in the tail. Above 2 kHz, each
    # 2.5 ms window against the median of the 50 ms before it (from 100 ms after the peak, before the
    # final 40 ms fade). A natural decay never jumps up; a cut does.
    hp = sfxlib._band(mono, lo=1500, order=4)  # a click is broadband; the low tail is left out
    k2 = int(0.0025 * SR)
    m2 = len(hp) // k2
    eh = np.sqrt((hp[: m2 * k2].reshape(m2, k2) ** 2).mean(axis=1) + 1e-20)
    start, stop = i * 2 + 40, m2 - 16
    jumps = [20 * np.log10(eh[j] / (np.median(eh[j - 20:j - 1]) + 1e-20)) for j in range(max(start, 21), stop)
             if eh[j] > eh.max() * 10 ** (-70 / 20)]
    drop = max(jumps) if jumps else 0.0
    # discontinuities: energy of the second difference above 12 kHz relative to the whole
    spec = np.abs(np.fft.rfft(mono)) ** 2
    ff = np.fft.rfftfreq(len(mono), 1 / SR)
    hf = 10 * np.log10(spec[ff > 12000].sum() / (spec.sum() + 1e-20) + 1e-12)
    corr = float(np.corrcoef(x[0], x[1])[0, 1]) if np.std(x[0]) > 0 and np.std(x[1]) > 0 else 1.0
    rms = float(np.sqrt(np.mean(x ** 2)))
    return {"rms_db": round(20 * np.log10(rms + 1e-12), 1), "seconds": round(x.shape[1] / SR, 2), "peaks": peaks, "flat_db": round(float(flat), 1), "cut_db": round(float(drop), 1),
            "hf_db": round(float(hf), 1), "width": round(1 - corr, 3)}


def main(out=None):
    rows = {}
    fps = {}
    envs = {}
    for c in sfxlib.CATALOG:
        x, sync = sfxlib.synth(c[0])
        rows[c[0]] = {"category": c[1], **metrics(x), "sync": sync}
        if c[1] not in TAILED:
            rows[c[0]]["cut_db"] = None
        fps[c[0]] = bands(x)
        envs[c[0]] = envelope(x)
    for sid, r in rows.items():
        best = 0.0
        for oid, o in rows.items():
            if oid == sid or o["category"] != r["category"]:
                continue
            a, b = fps[sid], fps[oid]
            spec_sim = 1 - np.mean(np.abs(a - b)) / 30  # 1 = same spectrum (mean band difference in 30 dB units)
            ea, eb = envs[sid], envs[oid]
            n = min(len(ea), len(eb))
            env_sim = float(np.corrcoef(ea[:n], eb[:n])[0, 1]) if n > 3 else 1.0
            len_sim = min(len(ea), len(eb)) / max(len(ea), len(eb))
            best = max(best, round(float(spec_sim * 0.5 + env_sim * 0.3 + len_sim * 0.2), 3))
        r["twin"] = best
    print(f"{'id':16s} {'cat':18s} {'sec':>5s} {'peaks':>5s} {'flat':>6s} {'cut':>6s} {'hf':>6s} {'width':>6s} {'twin':>6s}")
    for sid, r in rows.items():
        print(f"{sid:16s} {r['category']:18s} {r['seconds']:5.2f} {r['peaks']:5d} {r['flat_db']:6.1f} {(r['cut_db'] if r['cut_db'] is not None else float('nan')):6.1f} {r['hf_db']:6.1f} "
              f"{r['width']:6.3f} {r['twin']:6.3f}")
    if out:
        Path(out).write_text(json.dumps({"lib_version": sfxlib.LIB_VERSION, "count": len(rows), "sounds": rows}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
