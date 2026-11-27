"""The six approved Javits demo graphics (Casefile Studio qa/cinegfx-demos/make_demos.py), built from the script and
the narration clips' word timelines (tests/data/javits-demo-timelines.json, measured from the demo recordings) with
any copy of the engine: the kit's, or Casefile's when it is next to the kit."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
SCRIPT = KIT / "examples" / "javits" / "script.md"
TIMELINES = HERE / "data" / "javits-demo-timelines.json"
EXPECT = {"1-findings": "findings", "2-timeline": "timeline", "3-contradiction": "contradiction", "4-legal": "legal",
          "5-digital": "digital", "6-turning": "turning"}


def window_for(T, story, narration):
    want = " ".join(T.tokens(narration))
    for a in range(len(story.sentences)):
        for b in range(a + 1, min(len(story.sentences), a + 6) + 1):
            if " ".join(T.tokens(story.window_text(a, b))) == want:
                return a, b
    raise ValueError("narration is not a contiguous run of script sentences")


def graphics(cg, photos=None):
    """[(demo key, category, Graphic)] drawn by the engine package `cg` (a module with core, story, text, timing)."""
    story = cg.story.parse_script(SCRIPT.read_text())
    coll = cg.core.load_collections()["truecrime"]
    out = []
    for key, d in json.loads(TIMELINES.read_text()).items():
        a, b = window_for(cg.text, story, d["text"])
        scored = []
        for cat in coll.categories.values():
            r = cat.detect(story, a, b)
            if r:
                scored.append((r[0], cat.key, r[1], r[2]))
        scored.sort(key=lambda x: -x[0])
        score, cat, payload, why = scored[0]
        tl = cg.timing.Timeline(d["text"], [cg.timing.Word(*w) for w in d["words"]], d["duration"], [tuple(p) for p in d["pauses"]])
        beat = cg.core.Beat("truecrime", cat, a, b, score, payload, why)
        c = coll.categories[cat]
        out.append((key, cat, c.graphic(beat, c.theme, tl, cg.core.Assets(photos))))
    return out


def marks(g):
    """Three moments per graphic: early, the middle reveal, and settled before the exit."""
    cues = sorted({round(c.t + 0.35, 2) for c in g.cues})
    return [0.6, cues[len(cues) // 2] if cues else round(g.duration / 2, 2), round(g.duration - 0.5, 2)]
