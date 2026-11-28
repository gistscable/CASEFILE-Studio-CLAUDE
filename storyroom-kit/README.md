# storyroom-kit

Casefile Studio's story-aware cinematic graphics as a standalone kit, for **Storyroom** or any other editor.

You give it a production script and the narration's timings. It reads the whole story and places graphics only
where the script carries real structure, such as dated events, two opposed accounts, or charges and a court. For
each one it renders a transparent video, its sound cues and a preview. A list says where on your timeline each
graphic goes.

- **The words are the script's.** Every word on screen comes from the narration. Wording the engine does not
  recognise is left out, never made up.
- **Photos are yours.** Only real photos you supply are shown, never generated or stock. An empty photo slot is
  simply not drawn, and no credit is invented.
- **Offline and free.** Python with Pillow and NumPy, plus FFmpeg. No AI keys, no cloud, no paid APIs.
- **Same output as Casefile.** The engine is a copy of Casefile Studio v0.4.66's. For the same graphic the kit
  draws Casefile's frames pixel for pixel (`tests/test_parity.py`).

## Install

You need Python 3.10 or newer, and FFmpeg (macOS: `brew install ffmpeg`).

```bash
cd storyroom-kit
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # or: pip install -e ".[ffmpeg]"  (brings its own FFmpeg)
storyroom-gfx check              # FFmpeg, fonts, engine
```

## Use

```bash
# 1. Plan: read the script and place the graphics (writes plan.json; prints what it chose and why)
storyroom-gfx plan script.md --srt narration.srt --photos photos -o plan.json

# 2. (optional) open plan.json: skip a graphic, change its look, fill its photos

# 3. Render
storyroom-gfx render plan.json -o out --narration narration.mp3
```

Or do both at once: `storyroom-gfx run script.md --srt narration.srt -o out`.

You can try it on the included examples. Without timings, the times are estimated:

```bash
storyroom-gfx run examples/sheriff/script.md -o out-sheriff     # a fictional case: all six graphics
storyroom-gfx plan examples/javits/script.md -o javits.json     # the approved Javits script
```

### Inputs

| What | Option | Notes |
|---|---|---|
| Script | *(first argument)* | Markdown. `# Title — Name Surname`, then `## Chapter 1 — Name` headings, then paragraphs of narration. Lines starting with `**`, `\|`, `---` or `>`, and sections called Sources or Producer notes, are not narration. Keep each such note on one line: a wrapped second line would be read as narration. A `**Recording date:** November 13, 2026` line anchors dates written without a year; write years in dates when you can. |
| Timings | `--srt` / `--words` / `--audio` | Give one. **SRT**: captions from CapCut, Premiere, Descript or Whisper. **Words**: JSON `[{word, start, end}]`, `{"words": [...]}`, Whisper `segments`, or `start_ms` / `end_ms`. **Audio**: the recording, timed from its pauses (less exact). With none, times are estimated at `--wpm 150`, which is good for planning; render with real timings. |
| Photos | `--photos DIR` | A folder with `sources.json` (file, subject, credit, month, people, places, tags per photo), or plain files named after the person, place or event (`okafor.jpg`). |
| Look | `--look look.json` | The look for all graphics; see below. |
| Timeline | `--offset 12.5`, `--fps 25` | Where the narration starts on your timeline, and its frame rate (24 by default, as in Casefile; also 25, 30, 48, 50 or 60). |
| Niche | `--collection`, `--categories timeline,legal` | `truecrime` (the default), `football`, `combat` (boxing, MMA, wrestling), `entertainment` and `documentary` (history, business, psychology, faith, general). `storyroom-gfx list` shows every graphic and what it can take. |

The script's spelling always wins. A transcript that writes "more" for "Moore" still times the script's
"Moore". If under 85% of the script's words are found in the timings, the plan says so.

### Outputs (in `out/`)

| File | What |
|---|---|
| `01-timeline.mov` | The graphic with transparency (ProRes 4444; `--alpha qtrle\|webm\|png\|none` for QuickTime Animation, VP9 WebM, a PNG sequence or nothing). The 0.2 s fade-in and 0.3 s fade-out are in its transparency. |
| `01-timeline.wav` | Its sound cues alone (48 kHz, 24-bit), from time 0 of the graphic, ducked under the narration when `--narration` is given. |
| `01-timeline-preview.mp4` | Over black, with the cues and the narration: for watching, or for editors without transparency. |
| `render.json` | For software: every graphic's start and end (seconds on your timeline), files, background, whether the next graphic covers it, its cues, notes and text. |
| `placements.csv` | The same for people: one row per graphic, with timecodes. |
| `timeline.edl` | A CMX 3600 edit list: graphics on V, sounds on A, at their times. Imports into Premiere and Resolve (relink to the files). |
| `plan.json` | (`run` only) the plan it rendered. |

Other options: `--size 1080x1920` (a tall video gets the graphic as a full-width panel), `--only 1,3`,
`--workers N`, `--no-mp4`, `--no-wav`. Check frames without rendering with `storyroom-gfx stills plan.json -o stills`.

### Looks

These go in `plan.json` under `"look"` (all graphics) or a graphic's own `"look"`. Use only the keys you need:

```json
{"palettes": {"timeline": "B", "legal": "C"}, "vary": true, "seed": "episode-12",
 "accent": "#3FA7FF", "text": "#FFFFFF",
 "background": "footage", "dim": 0.62,
 "font": "serif", "size": 1.1, "mirror": true,
 "place": {"scale": 0.86, "x": 0.6, "y": 0.0}}
```

| Key | What it does |
|---|---|
| `palettes` | Each graphic's tested colour sets (A is the approved design). |
| `vary` | Picks a tested set automatically from `seed`. |
| `accent`, `text` | Your own colours. Each is checked for readability and moved to the nearest readable shade if needed. |
| `background` | `own` (the design's), `footage` (see-through: your video shows through, darkened by `dim`), or `photo` plus `"photo": "path.jpg"`. |
| `font`, `size`, `mirror` | Type and layout. |
| `place` | Draws the graphic smaller and to one side of the footage. |

A choice a graphic cannot take is replaced by the nearest it can, and said in its `style.notes`. For example,
Conflicting accounts always keeps its own background.

## Python

```python
from storyroom_kit import make_plan, render_plan, save_plan
plan = make_plan(open("script.md").read(), srt=open("narration.srt").read(), photos="photos", fps=25)
save_plan(plan, "plan.json")
render_plan(plan, "out", narration="narration.mp3")
```

## The graphics (true crime)

| Graphic | When |
|---|---|
| Investigative Findings | What an investigator said, each point with its status. |
| Chronological Timeline | Three or more dated events, or exact times on one day. |
| Conflicting Accounts | Two attributed accounts that oppose each other. |
| Legal Outcome | Charges, court, judge and the outcome, as a docket with a stamp. |
| Digital Evidence | Evidence items and a route. |
| Turning Point | The moment the case turned, and how long it took. |

The plan is chosen as a whole:
- Windows never overlap, and at most 2 graphics go in a chapter.
- Two weak graphics never displace one strong one.
- Back to back, the later graphic covers the earlier one.

See `storyroom_kit/cinegfx/README.md` for the rules, and for how to add a niche (football, boxing, history and so on).

## Speed

Frames are drawn in parallel, using all cores but one, at most 6. On a 2-core machine a 12-second graphic takes
about 45 s at 1920x1080 in ProRes 4444. An 8-core MacBook Air M1 is several times faster.

## Tests

```bash
pip install -e ".[test]" && pytest
```

`test_reference` checks the six approved Javits graphics against stills drawn by Casefile. Inside the
CASEFILE-Studio repository, `test_parity` also checks two things:
- The engine copy matches Casefile's.
- The kit draws Casefile's exact frames for every look.

Run `python tools/sync_engine.py` to check the copy, and `--write` to copy again after the engine changes in
Casefile.

## Licences

Fonts: see `storyroom_kit/fonts/LICENSES.md` and `DM-Sans-LICENSE.txt` (SIL OFL 1.1, Apache 2.0, DejaVu). The
sounds are synthesised by code (`sfxlib.py`), with no samples. The Javits press photos are **not** included.
