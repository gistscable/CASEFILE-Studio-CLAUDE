# cinegfx.sports: cinematic sports editorial engine (v0.4.77, preview)

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
