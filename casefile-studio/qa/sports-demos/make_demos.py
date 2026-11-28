"""v0.4.77 sports editorial demos: 7 standalone family demos + 1 combined football documentary (~78 s).

Story: Lionel Messi's four goals against Arsenal, 6 April 2010 (every fact sourced in script.json).
Narration: generated narrator voice (narration/*.flac) aligned word by word with Whisper (narration/words.json).
Footage (not in git, copyrighted broadcast material, used here for an internal approval demo only):
  work/sources/messi_ars.mp4    UEFA highlights, 1080p25 (github.com/brandonjabr/goal-net input_videos/)
  work/sources/ballon_dor_2009.jpg   Messi with the 2009 Ballon d'Or (press photo, France Football backdrop)

Run from casefile-studio/:  .venv/bin/python qa/sports-demos/make_demos.py [--only combined|name|...] [--preview]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from cinegfx.sports import edit as E  # noqa: E402
from cinegfx.sports import semantics as S  # noqa: E402
from cinegfx.sports.footage import Shot  # noqa: E402

SRC = HERE / "work" / "sources"
MATCH = str(SRC / "messi_ars.mp4")
PHOTO = str(SRC / "ballon_dor_2009.jpg")


def words_and_elements():
    sc = json.loads((HERE / "script.json").read_text())
    wj = json.loads((HERE / "narration" / "words.json").read_text())
    segs = [{"text": g["text"], "at": g["at"], "heard": [{"word": x["w"], "start": x["s"], "end": x["e"]} for x in wj[g["id"]]]}
            for g in sc["segments"]]
    words = S.timeline(segs)
    return sc, words, S.analyse(words)


def build(W=1920, H=1080, fps=25):
    sc, words, els = words_and_elements()

    def w(text, after=0.0):
        key = text.lower()
        for x in words:
            if x.s >= after - 1e-6 and S.clean(x.text).lower() == key:
                return x.s
        raise KeyError(text)

    e = E.Edit(W, H, fps, cache_dir=HERE / "work" / "cache")
    for g in sc["segments"]:
        e.narration.append((str(HERE / "narration" / f"{g['id']}.flac"), g["at"]))
    # the final quote sits behind the player for depth (the bookend of the opening name)
    for el in els:
        if el.family == "headline" and el.data.get("quote"):
            el.data["behind"] = True
    e.set_elements(els)
    nat = []

    def shot(t_src, until, grade="natural", tag="", speed=1.0, matte=False, frame=(0.5, 0.58, 1.16), crowd=None, **kw):
        s = e.add(Shot(MATCH, t_src, 1.0, speed=speed, grade=grade, matte=matte, frame=frame, tag=tag, **kw))
        e.cut_at(until)
        if crowd is not None:
            nat.append(E.Natural(MATCH, t_src, s.start, s.dur * speed, crowd))
        return s

    # match footage is reframed 16% (frame=(0.5, 0.58, 1.16)) so the broadcaster logo stays out of shot
    # ---- intro: name behind the player -------------------------------------------------------------
    shot(124.4, w("Lionel"), "punch", "stadium at night, cold open", crowd=-14)
    shot(144.05, w("already"), "cool_desat", "close-up, fists clenched (name behind him)", speed=0.8, matte=True)
    shot(37.25, w("The", 6.0), "warm", "close-up, Messi on the pitch")
    # ---- date + venue scramble -----------------------------------------------------------------------
    shot(124.9, w("Camp"), "punch", "Camp Nou wide at night", crowd=-16)
    shot(12.7, w("A", 10.0), "punch", "Camp Nou crowd", crowd=-15)
    shot(66.6, 14.62, "natural", "centre circle wide (kick-off)")
    # ---- flashback: minimal type, low-key silhouettes, then the archive photo -------------------------
    shot(91.7, 18.62, "low_key", "silhouettes against the floodlit pitch", speed=0.8)
    e.add(Shot(PHOTO, 0, 1.0, grade="archive", photo=True, matte=True, parallax=0.035,
               move=((0.5, 0.66, 1.18), (0.5, 0.30, 1.42)), tag="photo: 2009 Ballon d'Or (controlled photo animation)"))
    e.cut_at(w("Back", 26.0))
    # ---- back at Camp Nou: Arsenal lead ---------------------------------------------------------------
    shot(108.3, w("Arsenal", 30.0) - 1.56, "punch", "match wide, open play", crowd=-18)
    shot(44.25, w("one-man") - 1.08, "cool_desat", "Camp Nou crowd, tense", speed=0.8, crowd=-17)
    shot(9.05, w("one-man"), "natural", "Messi from behind, number 10")
    # ---- headline: one-man show (persists across three shots, glitches out) ---------------------------
    shot(49.0, w("By", 35.0), "punch", "celebration, arms raised", crowd=-12)
    shot(15.4, w("Arsenal", 38.0), "punch", "team-mates celebrate with Messi", crowd=-13)
    shot(46.6, els_end(els, "headline", 0), "punch", "Messi walks back, arms up", crowd=-14)
    # ---- numbered: the four goals, in monochrome, cut on each spoken number ---------------------------
    shot(21.6, w("Two", 44.0), "mono_cool", "goal 1, 21': strike from the edge of the box (replay)")
    shot(61.3, w("Three", 48.0), "mono_cool", "goal 2, 37': past Almunia")
    shot(99.7, w("Four", 52.0), "mono_cool", "goal 3, 42': the chip (stadium clock reads 41)")
    shot(138.7, w("Four", 56.0), "mono_cool", "goal 4, 88': through his legs")
    # ---- single-stat impact: 4 goals ------------------------------------------------------------------
    shot(131.3, w("one", 57.0) + 0.6, "warm", "celebrations", crowd=-12)
    shot(79.95, els_end(els, "impact", 0), "warm", "close-up celebrating", matte=True, crowd=-14)
    # ---- cumulative stats behind the player -------------------------------------------------------------
    shot(118.9, w("Thirty-four") - 0.3, "warm", "close-up smiling (stats behind him)", matte=True)
    shot(125.8, w("Xavi"), "punch", "Camp Nou wide, stats stacked", crowd=-17)
    # ---- the quote: bookend on the opening close-up, half speed -------------------------------------------
    shot(87.2, w("A", 69.0), "warm", "team pile-on, Xavi (6) in shot", crowd=-13)
    shot(144.0, 77.6, "cool_desat", "close-up, fists clenched (slow motion bookend)", speed=0.45, matte=True)
    e.natural = nat
    e.auto_transitions()
    e.music = [(0.0, 14.62, "nostalgic"), (14.62, w("Back", 26.0), "minimal"), (w("Back", 26.0), w("one-man"), "tension"),
               (w("one-man"), 44.6, "build"), (44.6, 59.9, "peak"), (59.9, w("Xavi"), "build"), (w("Xavi"), 80.0, "triumph")]
    from cinegfx.core import Cue
    e.cues += [Cue(w("one-man"), "riser-2", -10, "rise into the one-man show"),
               Cue(w("December", 18.0), "projector-1", -14, "archive photo"),
               Cue(w("one-man"), "crowd-cheer-1", -10, "the crowd erupts")]
    return e, words, els


def els_end(els, family, k):
    return [x for x in els if x.family == family][k].t_out


DEMOS = {  # standalone family demos: (file, label family key, start, end)
    "name": ("1-behind-subject-name.mp4", 0.0, 4.95),
    "headline": ("2-oversized-headline.mp4", 32.4, 41.1),
    "numbered": ("3-numbered-points.mp4", 39.7, 56.5),
    "minimal": ("4-minimal-transition.mp4", 14.1, 26.9),
    "label": ("5-scramble-labels.mp4", 6.9, 12.2),
    "cumulative": ("6-cumulative-stats-masked.mp4", 59.4, 68.2),
    "impact": ("7-single-stat-impact.mp4", 56.1, 60.6),
}


def main():
    args = sys.argv[1:]
    only = args[args.index("--only") + 1].split(",") if "--only" in args else None
    t0 = time.time()
    e, words, els = build()
    print(f"{len(e.shots)} shots, {e.duration:.2f} s, {len(els)} graphics")
    for el in els:
        print(f"  {el.family:10s} {el.t_in:6.2f}-{el.t_out:6.2f}  {el.why}")
    for i, tr in sorted(e.trans.items()):
        if tr.kind != "cut":
            print(f"  transition into shot {i} at {e.shots[i].start:.2f}: {tr.kind} ({tr.why})")
    e.prepare_mattes()
    out = HERE
    if not only or "combined" in only:
        E.export(e, str(out / "0-combined-messi-arsenal.mp4"), 0, e.duration, fade=0.0)
        print(f"combined done {time.time() - t0:.0f}s")
    for key, (fn, a, b) in DEMOS.items():
        if only and key not in only:
            continue
        E.export(e, str(out / fn), a, b, fade=0.25)
        print(f"{fn} done {time.time() - t0:.0f}s")
    # edit decision list for review
    edl = [{"start": round(s.start, 2), "end": round(s.end, 2), "source": Path(s.src).name, "in": s.t_src, "speed": s.speed,
            "grade": s.grade, "matte": s.matte, "shows": s.tag,
            "transition_in": E.asdict(e.trans[k]) if k in e.trans else None} for k, s in enumerate(e.shots)]
    (out / "EDL.json").write_text(json.dumps({"shots": edl, "graphics": [
        {"family": x.family, "in": x.t_in, "out": x.t_out, "data": x.data, "why": x.why} for x in els],
        "cues": [{"t": round(c.t, 3), "sfx": c.sfx, "why": c.why} for c in E.all_cues(e)]}, indent=1, default=str))


if __name__ == "__main__":
    main()
