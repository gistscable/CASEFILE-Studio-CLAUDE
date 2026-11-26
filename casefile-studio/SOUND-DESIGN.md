# Intelligent sound design (v0.4.56)

Optional, **off by default**. When switched on (inspector → **Sound** → "Add sound design to the export"),
Casefile plans restrained editorial sound effects from the timeline you already have and mixes them
into the export on their own layer. Nothing new is required: no new files, no script format change,
no new dependency. Narration, soundbites, music and the timeline are never changed.

## What it listens to

The plan is built from **structured events with their real times**, not from keywords alone and not
from the SRT cue start:

| Source | Events | Time used |
|---|---|---|
| Approved motion graphics (`motion.py`) | entrance, divider, title, each line/bullet, timeline markers, connectors, legal steps, the outcome, typing (each character), exit | the frame the element is first drawn (`motion.sound_events` → `ceil(t·24)/24` from the graphic's first frame) |
| Transitions (`effects.py`) | slide / wipe → directional whoosh; circle (mask) → tonal sweep; zoom → short whoosh; pixelize → scan; dip to black/white at a new chapter → swell; dip mid-chapter → low pulse; dissolve → silence (a swell only for a slow dissolve into a new chapter); cut → nothing | the visual middle of the transition |
| Chapter starts on a cut | investigation / legal / statements / chronology chapters → subtle swell | the first frame |
| Narration (word clock, captions, or the scene) | legal outcomes told (guilty, convicted, sentenced, charged…), discoveries that are findings (matched, identified, traced…), stated-vs-found contradictions, turning points | the outcome word itself (`motion._word_time`) |
| Subscribe animation (`cta.py`) | entrance whoosh, the click on SUBSCRIBE, the bell, the exit | its own keyframes (`effectsSpec.cta`) |
| Pictures and documents | document / record / warrant / receipt pictures → paper or document reveal (low priority; a photograph only at high density) | the cut or transition middle |

Then it **decides** — silence is a valid result, and every decision is shown with its reason:

* **Protected passages, no automatic sound at all:** any soundbite / audio break (±0.6 s), victim chapters,
  pictures whose title, note or file name names the victim, family, a memorial, tribute, funeral or vigil,
  and narration sentences about grief, death, violence, injury or abuse (±0.8 s). A graphic already on screen
  over such a sentence keeps its reveals but **softened** (muted clicks, −5 dB) across the whole graphic.
* **Never:** gunshots, screams, sirens, voices, reconstructions. There are no such sounds in the library.
  A camera shutter exists only for manual use (it can suggest a real police/press photograph) and is never
  placed automatically.
* **Priority vs density:** each event has a priority; it is kept only above `0.75 − 0.5 × density`.
* **Spacing:** one sound at a time (0.22 s), per-category gaps (whoosh 5 s, swell 50 s, bass impact 45 s,
  thump 30 s…), at most `4 + 10 × density` sounds in any minute (±30 s) of picture. The subscribe animation is exempt
  (it has its own switch).
* **Consistency and variation:** the lines of one graphic share one sound; elsewhere the least recently
  used variation of the category is chosen (rotation seeded by the project id, so the same project always
  gets the same plan). Typing uses the key variations in turn, with a separate space key and slightly
  varied levels — never one loop.
* **Intensity** picks quieter/fuller variations and shifts every level by `(intensity − 0.4) × 8 dB`.
  Sounds are **not** normalised to one loudness: a tick sits about 12 dB under a low impact.

**Honest limits of the understanding.** There is no language model in this: tone is read from the
chapter kind, the structure of the timeline and conservative word patterns (`sound.py` regexes). It does
not understand irony, implication or a sensitive passage phrased without any of the listed words; it can
also be over-cautious (on your gg project a picture of "the vehicle registered to … mother" is protected
because of "mother"). Silence is chosen whenever a rule is unsure. Review the plan; every sound is editable.

## The mix (FFmpeg)

The effects are written as one stem (FLAC, 48 kHz stereo, `cache/sfx/stems/<hash>.flac`), each sound at
`t − sync` to the sample (sync = onset, the crest for whooshes/sweeps/swells, the end for risers), with its
gain, fades and length; overlaps are summed and soft-limited (knee 0.6, never above 1.0). In the final mix:

```
[voice]            → asplit → [main] (untouched)  [side] (ducks the music, as before)  [fxkey]
[music]            → sidechaincompress by [side] (unchanged)
[stem]             → sidechaincompress by [fxkey] (threshold 0.035, ratio 3, 5/250 ms) → [fx]
[main][ducked][fx] → amix normalize=0 → alimiter limit=0.95 level=disabled latency=1
```

`level=disabled` + `latency=1`: the default `alimiter` adds ~0.45 dB of make-up gain and a 5 ms (239-sample)
delay; with these off, the narration in the export is identical to the export without effects (measured:
0 sample lag, RMS within 0.001 dB, correlation 0.9999995). The existing music-only path is unchanged.
Soundbites are part of the voice bus and are never processed by the effects path.

## Using it

1. Inspector → **Sound** → tick **Add sound design to the export**. Choose a preset:
   **Cinematic Investigative** (recommended, default), **Subtle Documentary**, **Intense Investigative**, or
   **Custom** (any change to intensity, density or the switches).
2. **Automatic** mode follows the timeline: move or delete a graphic, a transition or a scene and its
   sounds move or disappear with it. **Manual** mode keeps only the sounds stored in the project
   ("Generate plan" fills it).
3. The plan lists every sound (time, what it is for, the sound, why) and, under "Show the moments left
   silent", every event that was not given a sound and why. The **Sound FX** timeline lane shows each sound
   (colour by kind) and the protected passages (hatched).
4. Select a sound: **Sound** (audition), **In context** (plays from 2 s before), **Another** (next variation),
   **Remove / Restore**, **Reset** (back to the plan), replace from the library or your own sounds,
   volume (dB), move (in frames), fades. Drag it on the lane to move it (whole frames). Editing one sound
   changes only that sound (35/35 others unchanged on your gg project) and is one undo step. A sound you
   edited, moved or removed keeps its original moment in the plan, so nothing planned slips into its
   place or vanishes where you moved it. A sound you add yourself does make a planned one at the same moment
   step aside (one sound at a time).
5. **Mix:** effects volume (master), intensity, density, timing for all (± 0.2 s), dialogue protection
   (ducking), repetition prevention, and a switch per kind: motion graphics, diagrams, typing, transitions,
   investigative revelations, photographs and documents, subscribe animation.
6. **Mute / Solo** affect the preview only. The preview plays every sound with WebAudio on the editor's
   clock (no stem is rendered for it); it does not apply the ducking.
7. **Library:** browse by category and audition; add any sound at the playhead (it is tied to that scene);
   **Import a sound** (WAV/MP3/M4A/OGG/FLAC up to 30 s) — it is added to the media only, never rebuilds the
   timeline, never becomes narration or music.

Export warnings name any stored sound whose graphic, transition or scene no longer exists ("left out:
what it followed is no longer on the timeline").

## Files

| File | What |
|---|---|
| `sfxlib.py` | the procedural library (NumPy), cached as WAV under `cache/sfx/lib-1/` |
| `sound.py` | settings, events, protected passages, the planner, resolving times, custom sounds, the stem, the mix filters, the editor overview |
| `motion.py` | `El.role`, the typewriter entrance (`type_chars`, drawn char by char with a cursor), `sound_events(layout)` |
| `renderer.py` | the stem as an input and the effects mix; `sound_effects` in the render report |
| `app.py` | `PATCH sound`, `GET /api/sound/catalog`, `GET /api/sound/lib/{id}.wav`, `GET /api/projects/{id}/sound/plan`, `POST …/sound/generate`, `GET …/sound/custom/{asset}.wav`, upload role `sfx` |
| `history.py` | `sound` is undoable, with named steps ("Move sound effect", "Sound density"…) |
| `web/src/sound.js`, `SoundPanel.jsx`, `main.jsx`, `styles.css` | settings, presets, WebAudio preview, the Sound tab, the Sound FX lane |
| `web/src/effectsSpec.json` | `sound` (defaults, presets, limits, spacing, ducking) and the motion `type` entrance |
| `tests/test_sound.py`, `tests/js/sound.test.mjs` | 17 + 4 tests |
| `qa/sound-design/` | `make_demos.py`, `benchmark.py`, the demos and `demo-report.json` |

## Dependencies

None added. NumPy, Pillow and FFmpeg were already required. SciPy, soundfile, librosa and silero were
not needed: synthesis, filtering (zero-phase FFT filters with a Butterworth-shaped response, in NumPy), the stem and the measurements are
NumPy; decoding, ducking, limiting and encoding are FFmpeg.

## Library inventory and licences

All 78 sounds are **generated on your computer by `sfxlib.py`** from fixed recipes and seeds (noise
shaping, filtered sweeps, damped resonators, inharmonic partials for the bells), so the same file comes out every
time, offline. **No sound was downloaded**; there is nothing from Pixabay, Mixkit or Freesound and no
third-party licence applies. The generated sounds are part of Casefile and can be used in your videos
without attribution. Sounds you import are yours: use only sounds you have the right to use.

LIB_VERSION 1 · 48 kHz stereo float · peak level as designed (headroom ≥ 6 dB) · first build of all
78: 3.6–4.1 s CPU on the sandbox's 2 cores, then cached.

| id | category | description | intensity | peak dBFS | length s | sync | automatic |
|---|---|---|---|---|---|---|---|
| `pop-soft-1` | pop | Soft pop, round | 1 | -16 | 0.31 | onset | yes |
| `pop-soft-2` | pop | Soft pop, low | 1 | -15 | 0.34 | onset | yes |
| `pop-soft-3` | pop | Soft pop, bright | 2 | -16 | 0.30 | onset | yes |
| `click-mech-1` | click | Mechanical click | 2 | -14 | 0.19 | onset | yes |
| `click-mech-2` | click | Mechanical click, tight | 2 | -15 | 0.18 | onset | yes |
| `click-mech-3` | click | Mechanical click, heavy | 3 | -13 | 0.19 | onset | yes |
| `click-muted-1` | click-muted | Muted button click | 1 | -16 | 0.20 | onset | yes |
| `click-muted-2` | click-muted | Muted click, soft | 1 | -17 | 0.20 | onset | yes |
| `click-muted-3` | click-muted | Muted click, felt | 1 | -16 | 0.20 | onset | yes |
| `type-strike-1` | typewriter | Typewriter key 1 | 2 | -15 | 0.24 | onset | yes |
| `type-strike-2` | typewriter | Typewriter key 2 | 2 | -15 | 0.23 | onset | yes |
| `type-strike-3` | typewriter | Typewriter key 3 | 2 | -15 | 0.23 | onset | yes |
| `type-strike-4` | typewriter | Typewriter key 4 | 2 | -15 | 0.25 | onset | yes |
| `type-strike-5` | typewriter | Typewriter key 5 | 2 | -15 | 0.24 | onset | yes |
| `type-strike-6` | typewriter | Typewriter key 6 | 2 | -15 | 0.23 | onset | yes |
| `type-space-1` | typewriter | Typewriter space bar | 2 | -16 | 0.24 | onset | yes |
| `key-soft-1` | keyboard | Keyboard key 1 | 1 | -18 | 0.23 | onset | yes |
| `key-soft-2` | keyboard | Keyboard key 2 | 1 | -18 | 0.21 | onset | yes |
| `key-soft-3` | keyboard | Keyboard key 3 | 1 | -18 | 0.21 | onset | yes |
| `key-soft-4` | keyboard | Keyboard key 4 | 1 | -18 | 0.22 | onset | yes |
| `key-soft-5` | keyboard | Keyboard key 5 | 1 | -18 | 0.21 | onset | yes |
| `key-soft-6` | keyboard | Keyboard key 6 | 1 | -18 | 0.23 | onset | yes |
| `key-space-1` | keyboard | Keyboard space bar | 1 | -18 | 0.23 | onset | yes |
| `whoosh-short-1` | whoosh | Whoosh, short | 1 | -16 | 0.90 | peak | yes |
| `whoosh-short-2` | whoosh | Whoosh, short, airy | 1 | -17 | 0.90 | peak | yes |
| `whoosh-mid-1` | whoosh | Whoosh, medium | 2 | -14 | 1.17 | peak | yes |
| `whoosh-mid-2` | whoosh | Whoosh, medium, dark | 2 | -13 | 1.15 | peak | yes |
| `whoosh-long-1` | whoosh | Whoosh, long | 2 | -14 | 1.62 | peak | yes |
| `whoosh-dir-r` | whoosh | Whoosh, left to right | 2 | -14 | 1.09 | peak | yes |
| `whoosh-dir-l` | whoosh | Whoosh, right to left | 2 | -14 | 1.11 | peak | yes |
| `whoosh-dir-up` | whoosh | Whoosh, rising | 2 | -14 | 1.13 | peak | yes |
| `rwhoosh-1` | reverse-whoosh | Reverse whoosh | 2 | -14 | 1.40 | end | yes |
| `rwhoosh-2` | reverse-whoosh | Reverse whoosh, long | 2 | -14 | 1.85 | end | yes |
| `rwhoosh-3` | reverse-whoosh | Reverse whoosh, short | 1 | -16 | 1.06 | end | yes |
| `thump-deep-1` | thump | Deep cinematic thump | 2 | -9 | 1.74 | onset | yes |
| `thump-deep-2` | thump | Deep thump, short | 2 | -10 | 1.18 | onset | yes |
| `thump-deep-3` | thump | Deep thump, round | 3 | -8 | 2.49 | onset | yes |
| `bass-hit-1` | bass-impact | Subtle bass impact | 2 | -10 | 3.24 | onset | yes |
| `bass-hit-2` | bass-impact | Bass impact, soft | 1 | -12 | 2.75 | onset | yes |
| `bass-hit-3` | bass-impact | Bass impact, wide | 2 | -10 | 4.16 | onset | yes |
| `pulse-low-1` | pulse | Low-frequency pulse | 1 | -12 | 0.95 | onset | yes |
| `pulse-low-2` | pulse | Low pulse, double | 2 | -12 | 1.40 | onset | yes |
| `pulse-low-3` | pulse | Low pulse, short | 1 | -13 | 0.81 | onset | yes |
| `notify-1` | notification | Digital notification, two notes | 1 | -18 | 1.77 | onset | yes |
| `notify-2` | notification | Digital notification, single | 1 | -19 | 1.24 | onset | yes |
| `notify-3` | notification | Digital notification, low | 1 | -18 | 1.66 | onset | yes |
| `scan-1` | scan | Digital scan | 1 | -20 | 1.10 | onset | yes |
| `scan-2` | scan | Digital scan, short | 1 | -20 | 0.60 | onset | yes |
| `scan-3` | scan | Digital scan, long, low | 1 | -21 | 1.80 | onset | yes |
| `paper-1` | paper | Paper movement | 1 | -18 | 0.64 | onset | yes |
| `paper-2` | paper | Paper movement, crisp | 1 | -18 | 0.55 | onset | yes |
| `paper-3` | paper | Paper slide | 1 | -18 | 0.81 | onset | yes |
| `doc-1` | document | Document reveal | 2 | -15 | 0.78 | onset | yes |
| `doc-2` | document | Document reveal, quick | 1 | -16 | 0.67 | onset | yes |
| `doc-3` | document | Document reveal, slow | 2 | -15 | 0.97 | onset | yes |
| `shutter-1` | shutter | Camera shutter (manual use only) | 2 | -16 | 0.26 | onset | never (manual only) |
| `shutter-2` | shutter | Camera shutter, soft (manual use only) | 1 | -18 | 0.26 | onset | never (manual only) |
| `tick-1` | tick | Soft tick | 1 | -20 | 0.18 | onset | yes |
| `tick-2` | tick | Soft tick, low | 1 | -20 | 0.18 | onset | yes |
| `tick-seq-1` | tick | Ticking, four seconds | 1 | -21 | 3.17 | onset | no (manual) |
| `riser-1` | riser | Cinematic riser, two seconds | 2 | -15 | 2.83 | end | yes |
| `riser-2` | riser | Cinematic riser, three seconds | 2 | -15 | 3.80 | end | yes |
| `riser-3` | riser | Riser, short | 1 | -16 | 2.03 | end | yes |
| `sweep-up-1` | tonal-sweep | Tonal sweep, up | 1 | -19 | 1.45 | peak | yes |
| `sweep-up-2` | tonal-sweep | Tonal sweep, up, short | 1 | -19 | 1.25 | peak | yes |
| `sweep-down-1` | tonal-sweep | Tonal sweep, down | 1 | -19 | 1.53 | peak | yes |
| `swell-1` | swell | Atmospheric swell, minor | 2 | -17 | 4.42 | peak | yes |
| `swell-2` | swell | Atmospheric swell, low | 1 | -17 | 5.11 | peak | yes |
| `swell-3` | swell | Atmospheric swell, open | 2 | -17 | 3.89 | peak | yes |
| `impact-tr-1` | transition-impact | Transition impact | 2 | -9 | 2.84 | onset | yes |
| `impact-tr-2` | transition-impact | Transition impact, light | 1 | -11 | 2.49 | onset | yes |
| `impact-tr-3` | transition-impact | Transition impact, heavy | 3 | -8 | 3.32 | onset | yes |
| `bell-1` | bell | Notification bell | 1 | -17 | 3.27 | onset | yes |
| `bell-2` | bell | Notification bell, double | 2 | -17 | 3.24 | onset | yes |
| `bell-3` | bell | Bell, small | 1 | -18 | 2.44 | onset | yes |
| `cta-click-1` | cta-click | Subscribe button click | 2 | -13 | 0.20 | onset | yes |
| `cta-click-2` | cta-click | Button click, soft | 1 | -15 | 0.22 | onset | yes |
| `cta-click-3` | cta-click | Button click, bright | 2 | -14 | 0.18 | onset | yes |


## Demonstrations (`qa/sound-design/`)

Each demo is rendered **twice by the real exporter** at 720p — `demo-N-…-before.mp4` (sound design off)
and `…-after.mp4` (on, Cinematic preset). The narration voices are AI-generated for the demos; pictures
are neutral placeholder plates (no case imagery is made up). `make_demos.py` remakes them and writes
`demo-report.json`; because the narration is identical in both renders, after − before is exactly what
the sound design added, and each sound is measured in the delivered AAC audio.

| Demo | Sounds placed | Sync error (isolated transients) | Loudest effect vs speech | Peak (after) |
|---|---|---|---|---|
| 1 Bullet reveals (findings) | entrance whoosh, divider sweep, 3 line clicks (one sound for the graphic) | max 1.9 ms | −9.1 dB | −3.1 dBFS |
| 2 Typing (typewriter entrance) | 84 keys over heading + 2 lines; no click/whoosh doubling the keys | keys: median 0.3 ms, p95 6.7 ms, max 18.9 ms ¹ | −13.8 dB | −4.7 dBFS |
| 3 Diagram (timeline) | directional entrance, divider sweep, 3 marker ticks | max 0.7 ms | −8.7 dB | −4.3 dBFS |
| 4 Transitions | slide-left → leftward whoosh; circle → tonal sweep; dip-to-black new chapter → swell; hard cut → nothing | (slow shapes: placed by crest) | −10.0 dB | −4.2 dBFS |
| 5 Narrative development | one restrained low thump on "matched" ("The DNA on the receipt matched him.") | 2.5 ms | −7.3 dB | −4.4 dBFS |
| 6 Subscribe animation | entrance whoosh, click on SUBSCRIBE, bell, exit (existing CTA settings unchanged) | 1.2 ms | −16.5 dB | −4.6 dBFS |
| 7 Family interview suppression | **nothing**: both slide transitions around the sister's soundbite and the picture after it are silenced ("original source audio") | — | after = before, sample for sample | −1.1 dBFS (both) |

In every demo the export's effects line up with the stem that was mixed at **0.0 ms** lag; integrated
loudness changes by ≤ 0.1 LU (the effects are restrained); **no sample reaches full scale**. Render time
is unchanged within noise (e.g. 6.6 → 7.0 s for demo 4; the stem takes milliseconds for short demos).

¹ keys are ~59 ms apart (17 characters/s); the larger values are the detector catching the tail of the
previous key in its ±20 ms window. The placement itself is sample-exact (`test_stem_is_sample_accurate…`)
and the key times equal the drawn characters' frames (`test_typing_keys_match_the_typed_characters`).

## Benchmarks (your gg project, 231 scenes, 18.4 min, 5 approved graphics; sandbox: 2 cores)

| Step | Wall | CPU | Notes |
|---|---|---|---|
| Library, all 78 sounds, first time ever | 3.73 s | 3.73 s | then cached on disk |
| Events, first time (graphics timings) | 3.30 s | 3.30 s | motion layout (Pillow text measuring), cached per graphic in memory |
| Events, cached | 0.08 s | 0.08 s | |
| Plan | 0.09 s | 0.09 s | 256 events → 36 sounds, 119 left silent |
| Resolve (times, files) | 0.17 s | 0.17 s | |
| Stem, whole 18.4 min | 2.96 s | 0.73 s | 10 s blocks, FLAC 3.7 MB; added to the export |
| Stem, unchanged plan | 0.18 s | 0.18 s | cached by content |
| One sound edited: plan | 0.30 s | 0.30 s | 35/35 other sounds unchanged |
| One sound edited: stem | 3.06 s | 0.93 s | only at export |
| Every sound moved 5 frames and 3 dB quieter: plan | 0.25 s | 0.25 s | the same 36 moments, nothing added or dropped |

Peak memory 88 MB for the whole benchmark (process RSS). The plan endpoint runs in a worker thread, the
preview never renders audio, and the stem is only written at export.

## Tests

`tests/test_sound.py` (17): library (determinism, levels, headroom, all categories, cache), shutter never
automatic, settings in range, transition mapping, protected passages (soundbite, victim chapter, sensitive
narration), legal outcome on the word, density and spacing, shared sounds per graphic, sync to the drawn
frame, typing keys = drawn characters, moving/deleting a graphic moves/removes its sounds, editing one
sound leaves the rest, a decided sound holds its moment (edit, new variation, removal, move either way, and a
sound of your own next to a planned one), the stem (sample accuracy, cache, no clipping with four loud sounds at master 1.5),
the export (off: the effects code is never reached; on: whoosh present, narration unchanged, no clipping,
warnings for lost sounds), undo names, the API, importing a sound never touches the timeline.
`tests/js/sound.test.mjs` (4). Full suite: **619 passed, 1 skipped**; JS **39 pass**.

## Limitations

* The understanding is rule-based (see above). It cannot judge tone the way an editor does.
* The preview does not duck the effects under the voice; the export does.
* The preview places scene-anchored sounds on the editor's scene offsets; the export on frame-rounded
  ones (they differ by less than a frame per scene where a scene's length is not a whole number of frames).
* The Sound FX lane is the last lane of the timeline: on a short timeline panel, scroll the lanes (or make
  the panel taller) to see it whole. It is labelled A3 because the editor shows narration as A1 and music as
  A2 (soundbites play from their clips); in the export the order is narration, soundbites, music, effects.
* The first plan after the server starts reads every approved graphic's layout (≈0.65 s per graphic).
* Typing sounds exist only for the new **Typewriter** entrance (Motion → Entrance); other entrances get a
  reveal click per line.
* The library is synthesised: clean and consistent, but not as rich as recorded foley. Imported sounds
  can replace any of them.
