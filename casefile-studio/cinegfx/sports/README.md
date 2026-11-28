# cinegfx.sports: cinematic sports editorial engine (v0.4.77; in the app since v0.4.78)

A sports documentary engine inside the multi-niche cinegfx engine. It cuts real footage and composites
narration-driven motion graphics in three layers (footage, type **behind** the subject, type **in front**). It is
separate from the six true-crime graphics, which it does not touch. It also stays separate from the v0.4.76 niche
collections (`cinegfx/collections/`), which overlay graphics on a finished episode. This package **edits**:
it picks shots, grades them, places transitions, masks the player and mixes the sound.

The benchmark is the reference clip `football_clip_onl.mp4` (see `qa/sports-demos/REFERENCE-NOTES.md`).
It is studied for proportions, timing, layering and pace, not copied. Laptop reflections and screen-recording
artefacts are not reproduced.

## Pipeline

```
narration audio + script ──► semantics.timeline()  word-level times (number-aware alignment: "One." = heard "1")
                         └─► semantics.analyse()   Elements: which family, when, which words (never invented)
footage ──► footage.Shot / Reader      FFmpeg pipe, reframe, speed (slow motion by frame blending), grade
        └─► matte (optional)           RVM person mattes, cached per shot (matte-<sha>.npy), temporally stable
Edit: shots + cuts on words + auto_transitions() (context rules) + elements + music sections + natural sound
  └─► export()  chunked parallel render (cache/chunks, hash-keyed), concat; mix(): VO loudnorm, music ducked
                7 dB under the voice, crowd sound from the footage, event sfx; mux, AAC 256k, +faststart
```

## The seven families (`families.py`)

| # | family | what triggers it (semantics) | layer |
|---|---|---|---|
| 1 | `name` behind-subject kinetic name | a sentence that is only a name, opening a segment | behind the player |
| 2 | `headline` oversized + independent statements | a short declarative phrase plus the numbers that prove it, or a quote with its speaker | front (or behind for close-ups) |
| 3 | `numbered` sequential points | lone spoken numbers 1, 2, 3… each followed by its point | front |
| 4 | `minimal` storytelling / flashback | "but first", "go back", "years earlier"… | front, near silence |
| 5 | `label` date / season / venue / event scramble | a spoken date with its venue or event | front |
| 6 | `cumulative` stacked stats | several `<number> <noun>` pairs in one passage | behind the player |
| 7 | `impact` single-statistic reveal | a sentence carried by one number | front, luma exit |

Every family is timed from narration words (`t` of the word that says it), not from fixed durations or SRT
blocks. A graphic lives in **narration time**, so it persists across footage cuts. Each family also reports its
sound cues (`cues()`: ticks on scramble locks, impacts on reveals, glitch on exits).

## Editing rules (`edit.Edit.auto_transitions`)

- Hard cut by default, placed on the spoken word.
- Dissolve into quiet storytelling beats and into archive or photo material.
- Glitch (RGB split + slice displacement) only where a headline exits.
- Luma dissolve out of a single-stat impact.
- Directional push for a change of direction (available, used sparingly).

Grades (`footage.GRADES`): natural, punch, warm, cool_desat, mono_cool (the numbered goals), low_key
(flashback), archive (photo), cyan_fade (impact exit). The finish adds a warm vignette, lifted blacks and grain.

## Segmentation (optional)

`matte.py` uses Robust Video Matting (MobileNetV3, GPL-3.0) through onnxruntime when **both** are present:
`pip install onnxruntime` and an ONNX model in `casefile-studio/models/` (or set `CASEFILE_RVM_MODEL`). Mattes are
computed once per shot at 640 px, using the recurrent state so edges don't flicker, and cached. Without them,
everything still renders and behind-subject type is drawn in front instead (`matte.unavailable_reason()` says why).
The model is gitignored; see `qa/sports-demos/README.md` for how the demo's copy was produced.

## Apple M1 (8 cores)

- `encoder_args()` uses `h264_videotoolbox` when FFmpeg has it (`CASEFILE_HWENC=0` forces libx264 crf 16).
- Rendering is chunked at shot cuts (≤ 90 frames) across a process pool (`os.cpu_count()` workers).
  Each chunk is keyed by a hash of everything that goes into it (shots, transitions, graphics data, mattes, encoder,
  `edit.ENGINE_VERSION`), so changing one graphic re-renders only its chunks. Bump `ENGINE_VERSION` when drawing
  code changes.
- RVM on CoreML can be slower than CPU for this model; the CPU execution provider is used by default, with
  mattes cached.
- Audio is mixed separately from the video at sample accuracy and muxed once, so sync can't drift.

## Copyright

Broadcast footage and commentary are usually restricted. Being on YouTube does not grant reuse rights. The demo
footage is used for internal approval only and is not in git. Use licensed or owned footage in production.


## In the app: Sports edit (v0.4.78)

Football, boxing & MMA and wrestling projects get a **Sports edit** page (`web/src/SportsEdit.jsx`, backend
`casefile-studio/sportsedit.py`, routes `/api/projects/{id}/sportsedit…`). True-crime and other projects are untouched.

1. **Inputs, all from the project:** the narration audio (`narration_id`), the script (`narration_sources`, same text as
   the timing step) and the word timing (`episode.timings.words`, re-aligned number-aware with `align_words`; the script's
   paragraphs become narration segments). Footage and photos are the project's own video/image assets (not the narration,
   music or logo). Nothing is fetched or invented.
2. **Footage analysis** (`shots.py`): one small decode per file (160x90, 12.5 fps) finds the cuts and describes each shot
   from its pixels (pitch share, brightness, movement, texture, and person share when the matte model is installed):
   wide / action / close / crowd / dark. Cached per file in `DATA/media/{id}/sportsedit/cache/shots-*.json`.
3. **Planner** (`planner.py`): storytelling style (Emotional cinematic, Investigative, Historical retrospective,
   High-energy, Analytical, Automatic) sets shot length, grade, slow motion, footage sound level and the music arc. Cuts
   land on words (sentence starts, graphic entrances, every spoken number of a list); each piece asks for the shot its
   graphic needs (close-up for type behind the player, action for goals, low-key for a flashback, wide for a date/place).
   Photos only where their file name matches the words spoken over them (or the graphic's own words under a name or
   stats graphic). Graphics too close to a stronger one are offered switched off. Every choice carries a reason.
4. **Review:** graphics on/off, cut times moved, shots swapped (any detected shot or photo, any in-point). Saved as
   `project.sports_edit.overrides`, keyed by the cut's planned time; a change that no longer matches a cut is listed as
   stale, never applied elsewhere. Text is never editable here: it always comes from the narration.
5. **Render:** a `sportsedit` job (`RENDER_LOCK`, machine note, cancellable between chunks) through `edit.export` with
   the project's logo overlay. Chunks are cached in `DATA/media/{id}/sportsedit/cache/chunks`, so a review change
   re-renders only the chunks it touches. Output `DATA/media/{id}/sportsedit/{rid}.mp4`; the last 6 are kept.
6. **Segmentation status:** the page says whether text-behind-the-player is available and how to enable it
   (`pip install onnxruntime` + `rvm_mobilenetv3_fp32.onnx` in `casefile-studio/models/`). Without it the type is in front.

Optional *Crop in slightly* reframes footage 14% so a broadcaster's corner logo leaves the frame (off by default).
