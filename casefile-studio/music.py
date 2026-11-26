"""v0.4.58 Background music: where the music plays, and how it loops.

The music settings (project["music"]) only say WHERE the chosen track plays on the timeline and
WHICH part of it is used; they never change the documentary. The timeline is authoritative: the
music is cut to it, never the other way round, and the narration, soundbites, footage and the
picture are not touched.

`layout()` turns the settings into runs (stretches of the timeline with music) made of iterations
(one pass over the used part of the track). Consecutive iterations of a run overlap by the
crossfade (an equal-power quarter-sine crossfade, FFmpeg's `qsin`), so a loop has no seam. The
same function exists in web/src/music.js (the preview); tests/test_music.py checks both give the
same answer, so what you hear while editing is where the export puts it.

The export (`filters()`) reads the original file directly: each iteration is a reference to the
same file (`-ss start -t length`), joined with FFmpeg's `acrossfade` - no copies of the track and
no intermediate files. A short loop repeated many times uses FFmpeg's `aloop` instead (one period
in memory, a few seconds of audio).
"""
from __future__ import annotations

import math

FPS = 24
MODES = ("whole", "range", "once", "scenes")
DEFAULTS = {
    "mode": "whole",  # whole: the whole documentary; range: from `offset` to `until`;
    #                   once: from `offset`, the used part once (no loop); scenes: chosen chapters / scenes
    "start": 0.0,  # the used part of the track: from `start`...
    "end": None,  # ...to `end` (None = the end of the track). A longer track is cut here, not edited.
    "loop": True,  # repeat the used part when the stretch is longer than it
    "crossfade": 2.0,  # seconds of overlap between two passes
    "fade_in": 1.5,  # at the start of each stretch with music
    "fade_out": 2.0,  # at its end
    "duck": True,  # the music dips under the narration and soundbites (the export's compressor)
    "offset": 0.0,  # range / once: where on the timeline the music starts
    "until": None,  # range: where it stops (None = the end of the documentary)
    "chapters": [],  # scenes mode: every scene of these chapters
    "scenes": [],  # scenes mode: and these scenes (ids)
}
LIMITS = {"crossfade": (0.0, 10.0), "fade_in": (0.0, 15.0), "fade_out": (0.0, 15.0)}
MIN_PART = 1.0  # the shortest usable part of a track (seconds)
CHAIN_MAX = 12  # up to this many passes in one stretch: each a reference to the file; more: aloop
FMT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"


def _num(v, lo=None, hi=None, default=0.0):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x or x in (math.inf, -math.inf):
        return default
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def normalise(value):
    v = value if isinstance(value, dict) else {}
    out = {
        "mode": v.get("mode") if v.get("mode") in MODES else DEFAULTS["mode"],
        "start": round(_num(v.get("start"), 0.0, None, 0.0), 3),
        "end": None if v.get("end") in (None, "") else round(_num(v.get("end"), 0.0, None, 0.0), 3),
        "loop": bool(v.get("loop", DEFAULTS["loop"])),
        "duck": bool(v.get("duck", DEFAULTS["duck"])),
        "offset": round(_num(v.get("offset"), 0.0, None, 0.0), 3),
        "until": None if v.get("until") in (None, "") else round(_num(v.get("until"), 0.0, None, 0.0), 3),
        "chapters": [str(c)[:200] for c in (v.get("chapters") or []) if isinstance(c, str)][:100],
        "scenes": [str(s)[:64] for s in (v.get("scenes") or []) if isinstance(s, (str, int))][:400],
    }
    for k, (lo, hi) in LIMITS.items():
        out[k] = round(_num(v.get(k), lo, hi, DEFAULTS[k]), 3)
    if out["end"] is not None and out["end"] <= out["start"]:
        out["end"] = None
    return out


def _scene_spans(scenes):
    """[(id, chapter, start, end)] on the timeline (each scene a whole number of frames)."""
    out, t = [], 0.0
    for s in scenes or []:
        n = max(1, round(float(s.get("duration") or 0) * FPS))
        out.append((str(s.get("id") or ""), str(s.get("chapter") or ""), t, t + n / FPS))
        t += n / FPS
    return out


def part(settings, track):
    """(start, end) of the used part of a track `track` seconds long."""
    m = normalise(settings)
    track = float(track or 0)
    if track <= 0:
        return 0.0, 0.0
    a = min(m["start"], max(0.0, track - MIN_PART))
    b = track if m["end"] is None else min(track, m["end"])
    if b - a < MIN_PART:
        b = min(track, a + MIN_PART)
    return round(a, 4), round(b, 4)


def stretches(settings, total, scenes):
    """[(start, end)] of the timeline with music, before the used part's length is considered."""
    m = normalise(settings)
    total = float(total)
    if m["mode"] == "whole":
        out = [(0.0, total)]
    elif m["mode"] in ("range", "once"):
        a = min(m["offset"], total)
        b = total if (m["mode"] == "once" or m["until"] is None) else min(total, m["until"])
        out = [(a, b)] if b - a > 0 else []
    else:
        chosen = set(m["scenes"])
        chapters = set(m["chapters"])
        out = []
        for sid, chapter, a, b in _scene_spans(scenes):
            if sid in chosen or (chapter and chapter in chapters):
                if out and abs(out[-1][1] - a) < 1e-6:
                    out[-1] = (out[-1][0], b)  # neighbouring scenes: one stretch
                else:
                    out.append((a, b))
        out = [(a, min(b, total)) for a, b in out if a < total]
    return [(round(a, 4), round(b, 4)) for a, b in out if b - a > 1e-3]


def layout(settings, track, total, scenes=()):
    """Where the music plays: {"part": [start, end], "crossfade": x, "runs": [{"at", "end",
    "fade_in", "fade_out", "iters": [{"at", "src", "len"}]}]}. Pure; mirrored by music.js."""
    m = normalise(settings)
    a, b = part(m, track)
    length = b - a
    out = {"part": [a, b], "crossfade": 0.0, "runs": []}
    if length <= 0:
        return out
    x = min(m["crossfade"], max(0.0, length / 2 - 0.01)) if m["loop"] and m["mode"] != "once" else 0.0
    x = round(x, 4)
    out["crossfade"] = x
    period = length - x
    for s, e in stretches(m, total, scenes):
        span = e - s
        iters = []
        if m["mode"] != "once" and m["loop"] and span > length + 1e-6:
            n = 1 + math.ceil((span - length) / period - 1e-9)
            for k in range(n):
                at = s + k * period
                iters.append({"at": round(at, 4), "src": a, "len": round(min(length, e - at), 4)})
        else:
            iters.append({"at": s, "src": a, "len": round(min(length, span), 4)})
        end = round(iters[-1]["at"] + iters[-1]["len"], 4)
        heard = end - s
        out["runs"].append({
            "at": s, "end": end,
            "fade_in": round(min(m["fade_in"], heard / 2), 4),
            "fade_out": round(min(m["fade_out"], heard / 2), 4),
            "iters": iters,
        })
    return out


def gain_at(lay, t):
    """The music's own envelope at timeline time t (loop crossfades and the fades of each
    stretch; not the volume or the ducking). For tests and the preview's parity check."""
    x = lay["crossfade"]
    for run in lay["runs"]:
        if not (run["at"] <= t < run["end"]):
            continue
        env = 1.0
        if run["fade_in"] > 0:
            env *= min(1.0, (t - run["at"]) / run["fade_in"])
        if run["fade_out"] > 0:
            env *= min(1.0, (run["end"] - t) / run["fade_out"])
        total = 0.0
        iters = run["iters"]
        for k, it in enumerate(iters):
            u = t - it["at"]
            if not (0 <= u < it["len"]):
                continue
            g = 1.0
            if k > 0 and x > 0 and u < x:
                g *= math.sin(math.pi / 2 * u / x)
            if k < len(iters) - 1 and x > 0 and u > it["len"] - x:
                g *= math.cos(math.pi / 2 * (u - (it["len"] - x)) / x)
            total += g * g  # equal power: the powers add to 1 across a crossfade
        return env * math.sqrt(total) if total else 0.0
    return 0.0


# ====================================================================== the export

def filters(lay, path, first_input, total):
    """(input arguments, filters ending in [mus]) for the music on a `total`-second timeline,
    before its volume and ducking. Every pass reads the original file; nothing is copied."""
    args, f = [], []
    idx = first_input
    pieces, cursor = [], 0.0
    x = lay["crossfade"]
    a, b = lay["part"]
    length = b - a
    for r, run in enumerate(lay["runs"]):
        if run["at"] - cursor > 1e-4:
            f.append(f"anullsrc=r=48000:cl=stereo,atrim=end_sample={round((run['at'] - cursor) * 48000)}[mg{r}]")
            pieces.append(f"[mg{r}]")
        iters = run["iters"]
        heard = run["end"] - run["at"]
        if len(iters) <= CHAIN_MAX:
            labels = []
            for k, it in enumerate(iters):
                args += ["-ss", f"{it['src']:.6f}", "-t", f"{it['len']:.6f}", "-i", str(path)]
                f.append(f"[{idx}:a]{FMT},asetpts=PTS-STARTPTS[mi{r}_{k}]")
                labels.append(f"[mi{r}_{k}]")
                idx += 1
            cur = labels[0]
            for k in range(1, len(labels)):
                nxt = f"[mc{r}_{k}]"
                f.append(f"{cur}{labels[k]}acrossfade=d={x:.6f}:c1=qsin:c2=qsin{nxt}" if x > 0 else
                         f"{cur}{labels[k]}concat=n=2:v=0:a=1{nxt}")
                cur = nxt
        else:
            # many short passes: the first pass, then one period with its seam made (the tail of
            # a pass crossfaded into the head of the next) looped in memory. The part is decoded
            # once, from one seek at its start, and cut at exact samples (a seek inside the part
            # would decode its first frame without the encoder's reservoir: a click at full level)
            period = length - x
            ps, xs, ls = round(period * 48000), round(x * 48000), round(length * 48000)
            args += ["-ss", f"{a:.6f}", "-t", f"{length:.6f}", "-i", str(path)]
            src = f"[{idx}:a]{FMT},asetpts=N/SR/TB"
            idx += 1
            cur = f"[mc{r}]"
            if x > 0:
                f.append(f"{src},asplit=4[ma{r}][mb{r}][md{r}][me{r}]")
                f.append(f"[ma{r}]atrim=end_sample={ps}[mf{r}]")
                f.append(f"[mb{r}]atrim=end_sample={xs},afade=t=in:d={x:.6f}:curve=qsin[mh{r}]")
                f.append(f"[md{r}]atrim=start_sample={ps}:end_sample={ls},asetpts=PTS-STARTPTS,afade=t=out:d={x:.6f}:curve=qsin[mt{r}]")
                f.append(f"[me{r}]atrim=start_sample={xs}:end_sample={ps},asetpts=PTS-STARTPTS[mm{r}]")
                f.append(f"[mh{r}][mt{r}]amix=inputs=2:normalize=0:duration=longest[ms{r}]")
                f.append(f"[ms{r}][mm{r}]concat=n=2:v=0:a=1,aloop=loop=-1:size={ps}[ml{r}]")
                f.append(f"[mf{r}][ml{r}]concat=n=2:v=0:a=1{cur}")
            else:  # no seam to make: the pass itself loops
                f.append(f"{src},atrim=end_sample={ps},aloop=loop=-1:size={ps}{cur}")
        fades = ["asetpts=N/SR/TB", f"atrim=end_sample={round(heard * 48000)}", "asetpts=PTS-STARTPTS"]
        if run["fade_in"] > 0:
            fades.append(f"afade=t=in:d={run['fade_in']:.6f}")
        if run["fade_out"] > 0:
            fades.append(f"afade=t=out:st={max(0.0, heard - run['fade_out']):.6f}:d={run['fade_out']:.6f}")
        f.append(f"{cur}{','.join(fades)}[mr{r}]")
        pieces.append(f"[mr{r}]")
        cursor = run["end"]
    if not lay["runs"]:
        return [], []
    f.append(f"{''.join(pieces)}concat=n={len(pieces)}:v=0:a=1,{FMT},asetpts=N/SR/TB,apad,atrim=end_sample={round(total * 48000)}[mus]")
    return args, f
