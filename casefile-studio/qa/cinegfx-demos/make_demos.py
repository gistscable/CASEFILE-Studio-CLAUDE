"""Build the six category demos from the Javits script + narration, end to end through the engine:

  script -> Story -> (for each narration clip) locate its sentence window -> every category's detector
  scores the window -> best category wins -> timeline from the narration audio -> Graphic -> frames +
  cues -> MP4.

Usage (from casefile-studio/):
  PATH=$PWD/.venv/bin:$PATH .venv/bin/python qa/cinegfx-demos/make_demos.py            # all six MP4s
  ... make_demos.py --stills 1-findings                                                  # QA frames only
  ... make_demos.py --preview                                                            # half-res 15 fps
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cinegfx import core, render, sfx, story as S, text as T, timing as TM  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPECT = {"1-findings": "findings", "2-timeline": "timeline", "3-contradiction": "contradiction", "4-legal": "legal",
          "5-digital": "digital", "6-turning": "turning"}


def window_for(story, narration: str):
    want = " ".join(T.tokens(narration))
    for a in range(len(story.sentences)):
        for b in range(a + 1, min(len(story.sentences), a + 6) + 1):
            if " ".join(T.tokens(story.window_text(a, b))) == want:
                return a, b
    raise ValueError("narration is not a contiguous run of script sentences")


def classify(story, coll, a, b):
    scored = []
    for cat in coll.categories.values():
        r = cat.detect(story, a, b)
        if r:
            scored.append((r[0], cat.key, r[1], r[2]))
    scored.sort(key=lambda x: -x[0])
    return scored


def main(argv):
    stills = "--stills" in argv
    preview = "--preview" in argv
    only = [a for a in argv if not a.startswith("--")]
    story = S.parse_script((HERE / "javits-script.md").read_text())
    coll = core.load_collections()["truecrime"]
    texts = json.loads((HERE / "narration" / "texts.json").read_text())
    report = {"selection_full_script": [
        {"category": bt.category, "sentences": [bt.a, bt.b], "score": bt.score, "why": bt.reasons} for bt in core.select(story, coll)], "demos": {}}
    for key, narr in texts.items():
        if only and key not in only:
            continue
        a, b = window_for(story, narr)
        scored = classify(story, coll, a, b)
        score, cat, payload, why = scored[0]
        audio = str(HERE / "narration" / f"{key}.mp3")
        tl = TM.timeline_for(audio, narr)
        (HERE / "out").mkdir(exist_ok=True)
        (HERE / "out" / f"{key}.srt").write_text(TM.to_srt(tl))
        beat = core.Beat("truecrime", cat, a, b, score, payload, why)
        spec = ("truecrime", cat, beat, tl, str(HERE / "photos"))
        entry = {"window": [a, b], "chosen": cat, "expected": EXPECT[key], "scores": {k: round(s, 3) for s, k, _, _ in scored}, "why": why}
        print(f"== {key}: sentences {a}-{b} -> {cat} {entry['scores']}", flush=True)
        if stills:
            g = render.build(spec)
            marks = sorted({0.25, 0.6} | {round(c.t + 0.35, 2) for c in g.cues} | {round(g.duration - 0.5, 2)})
            out = HERE / "out" / "stills" / key
            out.mkdir(parents=True, exist_ok=True)
            for t in marks:
                g.frame(t).convert("RGB").save(out / f"{t:06.2f}.png")
            print("   stills:", len(marks), "->", out)
            continue
        g = render.build(spec)
        wav = str(HERE / "out" / f"{key}.wav")
        sfx.mix(g.cues, audio, g.duration, wav)
        mp4 = str(HERE / f"{key}{'-preview' if preview else ''}.mp4")
        t0 = time.time()
        r = render.render(spec, mp4, wav, preview=preview)
        Path(wav).unlink()
        entry.update({"mp4": Path(mp4).name, "render_s": r["seconds"], "frames": r["frames"], "fps": r["fps"], "workers": r["workers"],
                      "duration": r["duration"], "cues": [{"t": c.t, "sfx": c.sfx, "gain_db": c.gain_db, "why": c.why} for c in g.cues]})
        print(f"   {mp4}: {r['frames']} frames in {r['seconds']} s ({r['workers']} workers)", flush=True)
        report["demos"][key] = entry
    if not stills:
        f = HERE / "out" / "report.json"
        if only and f.exists():  # partial re-render: merge into the existing report
            old = json.loads(f.read_text())
            old["demos"].update(report["demos"])
            report = old
        f.write_text(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
