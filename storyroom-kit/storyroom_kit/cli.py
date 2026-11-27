"""Command line: storyroom-gfx (or python -m storyroom_kit).

    storyroom-gfx plan   script.md --srt narration.srt --photos photos -o plan.json
    storyroom-gfx render plan.json -o out
    storyroom-gfx run    script.md --srt narration.srt --photos photos -o out      (plan + render)
    storyroom-gfx stills plan.json -o stills
    storyroom-gfx list                                                             (graphics and their looks)
    storyroom-gfx check                                                            (FFmpeg, fonts, engine)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ENGINE_FROM, __version__


def _plan_args(p):
    p.add_argument("script", help="the production script (Markdown: # Title, ## Chapter 1 — Name, paragraphs of narration)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--srt", help="the narration's captions (SRT): when each word is spoken")
    src.add_argument("--words", help="word timings (JSON: [{word, start, end}], Whisper segments, ...)")
    src.add_argument("--audio", help="the narration recording (timed from its pauses)")
    p.add_argument("--photos", help="a folder of real photos (with sources.json, or named after the person / place)")
    p.add_argument("--look", help="a JSON file with the plan-wide look (palettes, accent, text, background, font, size ...)")
    p.add_argument("--subject", default="", help="whose story it is, when the title does not say (\"Name Surname\")")
    p.add_argument("--offset", type=float, default=0.0, help="seconds where the narration starts on your timeline")
    p.add_argument("--wpm", type=float, default=150.0, help="reading speed for estimated timings (no SRT / words / audio)")
    p.add_argument("--fps", type=int, default=24, help="your timeline's frame rate: 24 (default, as Casefile), 25, 30, 48, 50 or 60")
    p.add_argument("--collection", default="truecrime", help="the niche (see: list)")
    p.add_argument("--categories", help="only these graphics, comma-separated (e.g. timeline,legal)")


def _render_args(p):
    p.add_argument("--only", help="graphic numbers to render, comma-separated (e.g. 1,3)")
    p.add_argument("--alpha", default="prores", choices=["prores", "qtrle", "webm", "png", "none"],
                   help="the transparent video: ProRes 4444 .mov (default), QuickTime Animation .mov, VP9 .webm, PNG sequence, none")
    p.add_argument("--no-mp4", action="store_true", help="skip the preview MP4 (over black, with sound)")
    p.add_argument("--no-wav", action="store_true", help="skip the sound-cue WAV")
    p.add_argument("--narration", help="the full narration recording: heard in the preview MP4s, and the cues duck under it")
    p.add_argument("--size", help="WIDTHxHEIGHT (default 1920x1080; a tall size gets a full-width panel)")
    p.add_argument("--workers", type=int, help="frame-drawing processes (default: all cores but one, at most 6)")
    p.add_argument("--edl-fps", type=int, help="the frame rate for timeline.edl's timecodes (default: the plan's)")


def _make_plan(a):
    from . import plan as PL
    raw = Path(a.script).read_text(encoding="utf-8")
    look = json.loads(Path(a.look).read_text()) if a.look else None
    words = json.loads(Path(a.words).read_text(encoding="utf-8")) if a.words else None
    srt = Path(a.srt).read_text(encoding="utf-8-sig") if a.srt else None
    if a.audio:
        from .media import ensure_ffmpeg
        ensure_ffmpeg()
    cats = [c.strip() for c in a.categories.split(",")] if a.categories else None
    return PL.make(raw, srt=srt, words_json=words, audio=a.audio, photos=a.photos, look=look, collection=a.collection,
                   categories=cats, subject=a.subject, offset=a.offset, wpm=a.wpm, fps=a.fps)


def _render(plan, a, out, base):
    from .export import render_plan
    only = [int(x) for x in a.only.split(",")] if a.only else None
    size = tuple(int(x) for x in a.size.lower().split("x")) if a.size else None
    rep = render_plan(plan, out, base=base, only=only, alpha=a.alpha, mp4=not a.no_mp4, wav=not a.no_wav, narration=a.narration,
                      size=size, workers=a.workers, edl_fps=a.edl_fps)
    print(f"\n{len(rep['graphics'])} graphics in {out}/ — render.json, placements.csv, timeline.edl")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="storyroom-gfx", description=f"storyroom-kit {__version__} (engine: {ENGINE_FROM})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="read the script and place the graphics; writes plan.json")
    _plan_args(p)
    p.add_argument("-o", "--out", default="plan.json")
    r = sub.add_parser("render", help="render a plan into videos, sounds and placement lists")
    r.add_argument("plan")
    r.add_argument("-o", "--out", default="out")
    _render_args(r)
    u = sub.add_parser("run", help="plan + render in one go")
    _plan_args(u)
    u.add_argument("-o", "--out", default="out")
    _render_args(u)
    s = sub.add_parser("stills", help="PNG frames of each graphic, for checking")
    s.add_argument("plan")
    s.add_argument("-o", "--out", default="stills")
    s.add_argument("--at", help="seconds from each graphic's start, comma-separated (default: at each reveal)")
    s.add_argument("--only", help="graphic numbers, comma-separated")
    sub.add_parser("list", help="the graphics this kit can make, and the looks each takes")
    sub.add_parser("check", help="check FFmpeg, the fonts and the engine")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "plan":
            from . import plan as PL
            plan = _make_plan(a)
            PL.save(PL.relocate(plan, Path(a.out).resolve().parent), a.out)
            print(PL.summary(plan))
            print(f"\nWrote {a.out}. Edit it if you like, then: storyroom-gfx render {a.out}")
        elif a.cmd == "render":
            from . import plan as PL
            _render(PL.load(a.plan), a, a.out, Path(a.plan).resolve().parent)
        elif a.cmd == "run":
            from . import plan as PL
            plan = _make_plan(a)
            Path(a.out).mkdir(parents=True, exist_ok=True)
            PL.save(PL.relocate(json.loads(json.dumps(plan)), a.out), Path(a.out) / "plan.json")
            print(PL.summary(plan) + "\n")
            _render(plan, a, a.out, Path.cwd())
        elif a.cmd == "stills":
            from . import plan as PL
            from .export import stills
            at = [float(x) for x in a.at.split(",")] if a.at else None
            only = [int(x) for x in a.only.split(",")] if a.only else None
            files = stills(PL.load(a.plan), a.out, base=Path(a.plan).resolve().parent, at=at, only=only)
            print(f"{len(files)} stills in {a.out}/")
        elif a.cmd == "list":
            from .graphics import catalog
            for c in catalog():
                print(f"{c['key']} — {c['label']}")
                for k in c["categories"]:
                    print(f"  {k['key']:<14} {k['label']}: {k['about']}")
                    print(f"  {'':<14} colour sets {', '.join(p['key'] for p in k['palettes'])}; backgrounds {', '.join(k['backgrounds'])}; "
                          f"fonts {', '.join(k['fonts'])}; size {k['size'][0]:g}–{k['size'][1]:g}"
                          + ("; can be mirrored" if k["mirror"] else "") + ("; can be made smaller / placed" if k["place"] else ""))
        elif a.cmd == "check":
            return check()
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        print(f"storyroom-gfx: {e}", file=sys.stderr)
        return 2
    return 0


def check():
    from .cinegfx import theme
    from .media import ensure_ffmpeg
    ok = True
    try:
        print("FFmpeg:", ensure_ffmpeg())
    except RuntimeError as e:
        print("FFmpeg: MISSING —", e)
        ok = False
    missing = [f for f in list(theme.FONTS.values()) if not (theme.FONT_DIR / f).is_file()]
    print("Fonts:", "all present" if not missing else "MISSING " + ", ".join(missing))
    ok = ok and not missing
    from .graphics import registry
    reg = registry()
    print("Graphics:", ", ".join(f"{k} ({len(c.categories)})" for k, c in reg.items()))
    print("Engine:", ENGINE_FROM)
    return 0 if ok else 1
