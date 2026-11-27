# cinegfx — story-aware cinematic graphics (demo stage)

This is a new engine, separate from `motion.py`, which it never imports. It is native Python (Pillow + numpy) plus FFmpeg. There are no paid APIs and no new dependencies.
**Status:** six demos are awaiting approval. The engine is **not wired into the app** yet.

## Layers

| Layer | Module | Job |
|---|---|---|
| Text | `text.py` | Tokens, syllables, sentence split that knows abbreviations ("No. 5", "St. Barnabas") |
| Story intelligence | `story.py` | Whole-script model: chapters, sentences, people + roles, organisations, places, dates (relative dates resolved: "that day", "the following day's"), attributed claims with polarity and relays ("Crump said prosecutors told…") |
| Timing | `timing.py` | Word timeline from an SRT, or from the narration's own pauses (silencedetect) aligned to punctuation; SRT export |
| Core | `core.py` | `Collection` / `Category` registry, `select()` (where a graphic is meaningful), `Graphic` base, `Assets` (authentic photos with provenance) |
| Niche collections | `collections/*.py` | One module per niche. `truecrime.py` = 6 categories (detector + theme + graphic) |
| Design | `theme.py` | Palette + type roles as data; repo fonts only |
| Motion | `anim.py` | Fast easing (expo/quint, tight overshoot); every frame is a pure function of time |
| Drawing | `draw.py` | Cached text sprites, supersampled shapes, sharp photo resampling (never blurred) |
| Sound | `sfx.py` | Places `sfxlib` sounds so each sync point (transient or crest) lands on its visual event; ducks the effects under speech |
| Render | `render.py` | Parallel frame workers (spawn-safe for macOS) stream to one FFmpeg; preview = same code at half size / 15 fps |

## Adding a niche (football, boxing, history…)

Create `collections/football.py`:

```python
from ..core import Category, Collection, Graphic, register
class Scoreline(Graphic): ...            # build(): times + cues from self.tl; draw(canvas, t)
def detect_scoreline(story, a, b): ...    # -> (score, payload, reasons) | None
class Football(Collection):
    key, label = "football", "Football"
    def __init__(self):
        super().__init__()
        self.add(Category("scoreline", "Scoreline", THEME, detect_scoreline, Scoreline))
register(Football())
```

The core finds the new module automatically (`load_collections()`). Nothing else changes. `test_engine.py::test_new_niche_registers_without_touching_core` checks this.

## Selection rules (`core.select`)

1. Every window of every chapter is offered to every category.
2. Candidates are taken best-first, subject to these limits:
   - windows never overlap;
   - beats are at least 2 sentences apart;
   - at most 2 beats per chapter;
   - each re-use of a category decays its score (×0.7), so compositions don't repeat;
   - beats below 0.6 are dropped, so a graphic appears only where the script carries real structure (dated events, opposed claims, charges + court…).

## Speed on a MacBook Air M1 (8-core)

- **Frames:** each frame is independent, so `render()` uses `cpu_count()-1` worker processes. The `spawn` start method is the macOS default, and each worker rebuilds the graphic from a picklable spec.
- **Encoding:** set `CINEGFX_ENCODER=h264_videotoolbox` to encode on the M1's media engine, which leaves all CPU cores free for drawing. The default is `libx264` (CRF 15).
- **Cost per frame:** text and shapes are rasterised once and cached per worker, so a frame is a handful of blits.
- **Photos:** each is cover-cropped and graded once. The push-in is a single sharp resample from that cached source.
- **Sound edits:** a sound-design change only remixes audio and remuxes it with the video stream copied (`qa/cinegfx-demos/remix.py`). It never re-renders.
