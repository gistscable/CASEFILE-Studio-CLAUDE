# Plugging the kit into Storyroom

This is the same engine and the same rules as Casefile Studio's Motion → Cinematic section, packaged so Storyroom
can call it. It only adds graphics. It never changes the narration, the footage, the cuts or the timeline.

## The flow

```
script.md + narration timings ──► plan.json ──► (producer reviews) ──► render ──► out/
                                    │                                        ├─ NN-category.mov   transparent video
                                    │                                        ├─ NN-category.wav   sound cues
                                    │                                        ├─ render.json       where each goes
                                    └─ graphics: category, start/end,        └─ placements.csv, timeline.edl
                                       words, reasons, photo slots, look
```

Two ways to call it:

- **Command line** (any language): `storyroom-gfx plan …` then `storyroom-gfx render …`. Then read `plan.json` and
  `out/render.json`.
- **Python** (a Python backend): `make_plan(...)`, `save_plan(...)`, `load_plan(...)` and `render_plan(...)` from
  `storyroom_kit`. Rendering uses worker processes, so call it from a script or job, not inside a request handler.

## What Storyroom should give the kit

| Kit input | From Storyroom |
|---|---|
| Script | The locked narration script, as Markdown with chapter headings (format in the README). |
| Timings | The narration's word times: an SRT, or a JSON word list from the transcriber (best), or the recording. |
| `--offset` | Where the narration starts on Storyroom's timeline, in seconds. |
| `--fps` | The timeline's frame rate: 24, 25, 30, 48, 50 or 60. |
| `--photos` | The project's photos. Use a folder with `sources.json` to give credits, or files named after people and places. |

## What to show the producer (from `plan.json`)

Each entry in `graphics` is one proposed graphic:

| Field | Show it as |
|---|---|
| `label`, `category` | Its name, e.g. "Mar 3 · 10:12–11:05 PM" (Timeline). |
| `start`, `end` | Where it sits, in seconds on the timeline. |
| `text`, `sentences` | The narration it illustrates, and which sentences (1-based). |
| `reason`, `score` | Why it was placed there, and how strongly. |
| `slots` | The photos it can show: `{key, kind: person\|place\|tag, value, label}`. Let the producer fill them into `photos`: `{"<slot key>": {"file": "...", "credit": "...", "month": "..."}}`. |
| `style.notes` | Any look choice it could not take, in plain words. |
| `status` | Set it to `"skipped"` to leave the graphic out. |

`storyroom-gfx list` (or `graphics.catalog()` in Python) lists every graphic with the colour sets, backgrounds,
fonts and sizes it takes, so Storyroom can offer exactly those.

**After an edit,** save `plan.json` and run `render` again. To re-render one graphic only, use `--only N`. A
graphic's reveals are timed from its own start, so if the narration moves, plan again from the new timings rather
than dragging `start`.

## Placing the results on the timeline (from `render.json`)

For each entry in `graphics`:

1. **Video:** put `files.video` on a track above the footage at `start` (seconds), for `frames` frames at the
   plan's `fps`. Its fades are in its transparency, so don't add a transition.
2. **Sound:** put `files.sound` on an effects track at the same `start`. It is effects only; the narration stays
   on its own track. It is ducked under the narration when the render was given `--narration`.
3. **Captions:** hide burned-in captions while a graphic is on (`hide_captions: true`). The graphic shows the words
   itself.
4. **Back to back:** when `covered_by_next` is true, the next graphic starts before this one ends and covers it.
   This one's video already stops once covered, so just stack the next one above it. When `fades_under_next` is
   true, the next graphic is see-through, and this one fades out under it.
5. **See-through graphics:** when `background` is `footage`, the video is partly transparent everywhere. Your
   footage shows through, darkened, so it must be on the track below.

`placements.csv` holds the same information with timecodes for people. `timeline.edl` imports into Premiere or
Resolve.

## Keeping it in step with Casefile

The engine lives in `storyroom_kit/cinegfx/`, with its sound library `storyroom_kit/sfxlib.py` and the fonts in
`storyroom_kit/fonts/`. It is a copy of Casefile Studio's, and only two layout lines differ, both about where the
fonts and sounds live.

When Casefile's engine improves, inside the CASEFILE-Studio repository run:

```bash
python tools/sync_engine.py --write && pytest
```

The tests check that the kit still draws Casefile's exact frames. `storyroom_kit/ENGINE_SOURCE.json` records the
commit the copy came from.

The kit never imports Casefile, and Casefile never imports the kit. Changing one cannot break the other.

## Not in the kit (yet)

- **Casefile's automatic presentation proposals** (full screen, over the footage, or partial). They read
  Casefile's footage guide and shot notes. In the kit, set the presentation yourself with `look.background` and
  `look.place`.
- **The "still from the footage" background.** Give a photo or exported frame as the `photo` background instead.
- **Niches other than true crime.** Adding one is a single module; see `storyroom_kit/cinegfx/README.md`.
