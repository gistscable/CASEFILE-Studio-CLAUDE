# Intelligent sound design (v0.4.56, corrected in v0.4.57; palettes, live levels, audition and music in v0.4.58)

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
  pictures and narration sentences whose **context score** reaches 1.5 (v0.4.57, `sound.context`; a
  sentence's zone is ±0.8 s). No single word decides: see "Context, not keywords" below. A graphic already on screen
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

### Context, not keywords (v0.4.57)

Each narration sentence and each scene's picture gets a score from everything around it, and only a
score ≥ 1.5 silences automatic sounds there. The reasons are listed with every decision in the plan.

| Signal | Effect on the score |
|---|---|
| the sentence itself: violence (not as the name of a charge: "convicted of murder" is legal, +0.4), death, grief or memory | +2.0 / +1.8 / +1.4 |
| family words, **by whose family**: the victim's ("Maurco's mother") / unspecified / the suspect's ("Jackson's mother") | +1.4–1.8 / +0.6–1.0 / 0 |
| the victim named (and the suspect not) | +0.5 |
| the case record in the same sentence (registered, records, testified, warrant, hearing, verdict…) | −0.7 each, up to −1.4 |
| the passage: the sensitive score of the sentence before/after, in the same chapter | +0.4 × the stronger neighbour; between two sensitive sentences = inside the passage |
| the chapter: about the victim / family | +1.0 |
| the story role: a legal outcome or a finding ("matched", "traced") | −0.6 |
| the picture (scenes): a victim/memorial picture by file name (base-image buckets) or by its title/note; a personal photograph of someone sensitive; what is said over it | +1.5–2.0; +0.9; + half the sentences' average |
| a suspect, scene or case picture | −1.0 |

Victims and suspects are read from the episode guide's setup (no guide: the family rule falls back to
"unspecified"). On your gg project (`HEAD` → v0.4.57): "the vehicle registered to Duane Jackson's mother"
−1.40 and "Jackson's mother testified" −0.60 are **no longer silenced** (the suspect's family, the record);
"a mother remembering her son" 2.20, "lost three sons to gun violence" 3.80, "still Maurco's mother" 2.82 and
"the first shot was fired" 2.00 still are. Pictures protected 21 → 59 (photographs of the victim and
family, recognised by what they show), sentences 98 → 40; 37 sounds instead of 36 (gained: a low hit on
"acquitted … aggravated-murder count"). Markers over a victim photograph keep their reveal, softened.

**Honest limits.** There is still no language model: it is a weighted reading of patterns, names,
neighbours, chapters and pictures (`sound.py`, ~150 lines). It does not understand irony or a sensitive
passage phrased without any listed word. When it is unsure it errs towards silence. Review the plan;
every sound is editable.

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
   clock (no stem is rendered for it) and **ducks them exactly as the export does** (v0.4.57, see below).
7. **Select several (v0.4.57):** with a graphic's sound selected, "Apply changes to" offers *this sound
   only*, *every line in this graphic* (or every marker, every step…) and *the whole graphic* (entrance,
   divider, lines, exit…). A sound you choose goes to all of them, volume and move shift each by the same
   amount, fades are set on all, remove/restore applies to all — one undo step ("Edit 3 sound effects").
   The selected sounds are highlighted on the Sound FX lane.
8. **Narration level (v0.4.57):** Audio tab and Sound → Mix, 0–200 %. It is the export's level too
   (applied after loudness normalisation, before the music ducking and the limiter), and the preview's
   effects ducking follows it.
9. **Library:** browse by category and audition; add any sound at the playhead (it is tied to that scene);
   **Import a sound** (WAV/MP3/M4A/OGG/FLAC up to 30 s) — it is added to the media only, never rebuilds the
   timeline, never becomes narration or music.

Export warnings name any stored sound whose graphic, transition or scene no longer exists ("left out:
what it followed is no longer on the timeline").

## Files

| File | What |
|---|---|
| `sfxlib.py` | the procedural library (NumPy), cached as WAV under `cache/sfx/lib-2/` |
| `sound.py` | settings, context scores, events, protected passages, the planner, the preview's duck curve, resolving times, custom sounds, the stem, the mix filters, the editor overview |
| `motion.py` | `El.role`, the typewriter entrance (`type_chars`, drawn char by char with a cursor), `sound_events(layout)` |
| `renderer.py` | the stem as an input and the effects mix; `voice_graph` (the voice bus, shared with the duck curve); `narration_volume`; `sound_effects` in the render report |
| `app.py` | `PATCH sound`, `GET /api/sound/catalog`, `GET /api/sound/lib/{id}.wav`, `GET /api/projects/{id}/sound/plan`, `POST …/sound/generate`, `GET …/sound/custom/{asset}.wav`, `GET …/sound/duck`, upload role `sfx` |
| `history.py` | `sound` is undoable, with named steps ("Move sound effect", "Sound density"…) |
| `web/src/sound.js`, `SoundPanel.jsx`, `main.jsx`, `styles.css` | settings, presets, WebAudio preview, the Sound tab, the Sound FX lane |
| `web/src/effectsSpec.json` | `sound` (defaults, presets, limits, spacing, ducking) and the motion `type` entrance |
| `tests/test_sound.py`, `tests/js/sound.test.mjs` | 24 + 10 tests |
| `qa/sound-design/` | `index.html` (open it: every demo and every sound, playable), `demo-reel.mp4`, `make_demos.py`, `make_page.py`, `library_audit.py`, `benchmark.py`, the demos, `demo-report.json`, `library-audit.json`, `library/v1|v2/*.mp3` |

## Dependencies

None added. NumPy, Pillow and FFmpeg were already required. SciPy, soundfile, librosa and silero were
not needed: synthesis, filtering (zero-phase FFT filters with a Butterworth-shaped response, in NumPy), the stem and the measurements are
NumPy; decoding, ducking, limiting and encoding are FFmpeg.

## Library inventory and licences

All 78 sounds are **generated on your computer by `sfxlib.py`** from fixed recipes and seeds (noise
shaping, filtered sweeps, damped resonators, modal partials, FM, detuned pads, small rooms), so the same file comes out every
time, offline. **No sound was downloaded**; there is nothing from Pixabay, Mixkit or Freesound and no
third-party licence applies. The generated sounds are part of Casefile and can be used in your videos
without attribution. Sounds you import are yours: use only sounds you have the right to use.

LIB_VERSION 2 (v0.4.57: 66 sounds improved, 12 unchanged; see "v0.4.57 corrections") · 48 kHz stereo float ·
peak level as designed (headroom ≥ 6 dB) · only the sounds a timeline uses are made, once, then read from
disk; all 78 at once: ≈7 s CPU on the sandbox's 2 cores (v1: 3.5 s; the tails are longer and fuller).

| id | category | description | intensity | peak dBFS | length s | sync | automatic |
|---|---|---|---|---|---|---|---|
| `pop-soft-1` | pop | Soft pop, round | 1 | -16 | 0.31 | onset | yes |
| `pop-soft-2` | pop | Soft pop, low | 1 | -15 | 0.34 | onset | yes |
| `pop-soft-3` | pop | Soft pop, bright | 2 | -16 | 0.30 | onset | yes |
| `click-mech-1` | click | Mechanical click | 2 | -14 | 0.16 | onset | yes |
| `click-mech-2` | click | Mechanical click, tight | 2 | -15 | 0.14 | onset | yes |
| `click-mech-3` | click | Mechanical click, heavy | 3 | -13 | 0.17 | onset | yes |
| `click-muted-1` | click-muted | Muted button click | 1 | -16 | 0.18 | onset | yes |
| `click-muted-2` | click-muted | Muted click, soft | 1 | -17 | 0.17 | onset | yes |
| `click-muted-3` | click-muted | Muted click, felt | 1 | -13 | 0.18 | onset | yes |
| `type-strike-1` | typewriter | Typewriter key 1 | 2 | -15 | 0.23 | onset | yes |
| `type-strike-2` | typewriter | Typewriter key 2 | 2 | -15 | 0.24 | onset | yes |
| `type-strike-3` | typewriter | Typewriter key 3 | 2 | -15 | 0.24 | onset | yes |
| `type-strike-4` | typewriter | Typewriter key 4 | 2 | -15 | 0.24 | onset | yes |
| `type-strike-5` | typewriter | Typewriter key 5 | 2 | -15 | 0.23 | onset | yes |
| `type-strike-6` | typewriter | Typewriter key 6 | 2 | -15 | 0.23 | onset | yes |
| `type-space-1` | typewriter | Typewriter space bar | 2 | -13.5 | 0.26 | onset | yes |
| `key-soft-1` | keyboard | Keyboard key 1 | 1 | -18 | 0.21 | onset | yes |
| `key-soft-2` | keyboard | Keyboard key 2 | 1 | -18 | 0.22 | onset | yes |
| `key-soft-3` | keyboard | Keyboard key 3 | 1 | -18 | 0.22 | onset | yes |
| `key-soft-4` | keyboard | Keyboard key 4 | 1 | -18 | 0.21 | onset | yes |
| `key-soft-5` | keyboard | Keyboard key 5 | 1 | -18 | 0.22 | onset | yes |
| `key-soft-6` | keyboard | Keyboard key 6 | 1 | -18 | 0.22 | onset | yes |
| `key-space-1` | keyboard | Keyboard space bar | 1 | -18 | 0.25 | onset | yes |
| `whoosh-short-1` | whoosh | Whoosh, short | 1 | -16 | 0.89 | crest | yes |
| `whoosh-short-2` | whoosh | Whoosh, short, airy | 1 | -19.5 | 0.95 | crest | yes |
| `whoosh-mid-1` | whoosh | Whoosh, medium | 2 | -14 | 1.16 | crest | yes |
| `whoosh-mid-2` | whoosh | Whoosh, medium, dark | 2 | -13 | 1.14 | crest | yes |
| `whoosh-long-1` | whoosh | Whoosh, long | 2 | -14 | 1.58 | crest | yes |
| `whoosh-dir-r` | whoosh | Whoosh, left to right | 2 | -14 | 1.10 | crest | yes |
| `whoosh-dir-l` | whoosh | Whoosh, right to left | 2 | -14 | 1.09 | crest | yes |
| `whoosh-dir-up` | whoosh | Whoosh, rising | 2 | -14 | 1.12 | crest | yes |
| `rwhoosh-1` | reverse-whoosh | Reverse whoosh | 2 | -14 | 1.39 | end | yes |
| `rwhoosh-2` | reverse-whoosh | Reverse whoosh, long | 2 | -14 | 1.90 | end | yes |
| `rwhoosh-3` | reverse-whoosh | Reverse whoosh, short | 1 | -16 | 1.03 | end | yes |
| `thump-deep-1` | thump | Deep cinematic thump | 2 | -9 | 2.60 | onset | yes |
| `thump-deep-2` | thump | Deep thump, short | 2 | -10 | 1.60 | onset | yes |
| `thump-deep-3` | thump | Deep thump, round | 3 | -6 | 3.61 | onset | yes |
| `bass-hit-1` | bass-impact | Subtle bass impact | 2 | -8.5 | 4.82 | onset | yes |
| `bass-hit-2` | bass-impact | Bass impact, soft | 1 | -12 | 4.06 | onset | yes |
| `bass-hit-3` | bass-impact | Bass impact, wide | 2 | -8.5 | 5.98 | onset | yes |
| `pulse-low-1` | pulse | Low-frequency pulse | 1 | -9.5 | 1.09 | onset | yes |
| `pulse-low-2` | pulse | Low pulse, double | 2 | -10 | 1.49 | onset | yes |
| `pulse-low-3` | pulse | Low pulse, short | 1 | -10 | 0.92 | onset | yes |
| `notify-1` | notification | Digital notification, two notes | 1 | -20.5 | 2.25 | onset | yes |
| `notify-2` | notification | Digital notification, single | 1 | -19 | 1.69 | onset | yes |
| `notify-3` | notification | Digital notification, low | 1 | -18 | 2.18 | onset | yes |
| `scan-1` | scan | Digital scan | 1 | -17.5 | 1.26 | onset | yes |
| `scan-2` | scan | Digital scan, short | 1 | -16.5 | 0.77 | onset | yes |
| `scan-3` | scan | Digital scan, long, low | 1 | -17.5 | 1.92 | onset | yes |
| `paper-1` | paper | Paper movement | 1 | -18 | 0.64 | onset | yes |
| `paper-2` | paper | Paper movement, crisp | 1 | -18 | 0.55 | onset | yes |
| `paper-3` | paper | Paper slide | 1 | -18 | 0.81 | onset | yes |
| `doc-1` | document | Document reveal | 2 | -15 | 0.82 | onset | yes |
| `doc-2` | document | Document reveal, quick | 1 | -16 | 0.71 | onset | yes |
| `doc-3` | document | Document reveal, slow | 2 | -15 | 1.00 | onset | yes |
| `shutter-1` | shutter | Camera shutter (manual use only) | 2 | -16 | 0.26 | onset | never (manual only) |
| `shutter-2` | shutter | Camera shutter, soft (manual use only) | 1 | -16.5 | 0.25 | onset | never (manual only) |
| `tick-1` | tick | Soft tick | 1 | -20 | 0.18 | onset | yes |
| `tick-2` | tick | Soft tick, low | 1 | -20 | 0.18 | onset | yes |
| `tick-seq-1` | tick | Ticking, four seconds | 1 | -21 | 3.17 | onset | yes |
| `riser-1` | riser | Cinematic riser, two seconds | 2 | -15 | 2.83 | end | yes |
| `riser-2` | riser | Cinematic riser, three seconds | 2 | -15 | 3.80 | end | yes |
| `riser-3` | riser | Riser, short | 1 | -16 | 2.03 | end | yes |
| `sweep-up-1` | tonal-sweep | Tonal sweep, up | 1 | -19 | 1.47 | crest | yes |
| `sweep-up-2` | tonal-sweep | Tonal sweep, up, short | 1 | -19 | 1.17 | crest | yes |
| `sweep-down-1` | tonal-sweep | Tonal sweep, down | 1 | -19 | 1.54 | crest | yes |
| `swell-1` | swell | Atmospheric swell, minor | 2 | -17 | 4.33 | crest | yes |
| `swell-2` | swell | Atmospheric swell, low | 1 | -14 | 5.11 | crest | yes |
| `swell-3` | swell | Atmospheric swell, open | 2 | -14 | 3.93 | crest | yes |
| `impact-tr-1` | transition-impact | Transition impact | 2 | -6.5 | 4.23 | onset | yes |
| `impact-tr-2` | transition-impact | Transition impact, light | 1 | -9.5 | 3.54 | onset | yes |
| `impact-tr-3` | transition-impact | Transition impact, heavy | 3 | -6 | 5.01 | onset | yes |
| `bell-1` | bell | Notification bell | 1 | -17 | 3.32 | onset | yes |
| `bell-2` | bell | Notification bell, double | 2 | -17 | 3.25 | onset | yes |
| `bell-3` | bell | Bell, small | 1 | -18 | 2.44 | onset | yes |
| `cta-click-1` | cta-click | Subscribe button click | 2 | -13 | 0.17 | onset | yes |
| `cta-click-2` | cta-click | Button click, soft | 1 | -13 | 0.20 | onset | yes |
| `cta-click-3` | cta-click | Button click, bright | 2 | -14 | 0.16 | onset | yes |


## Demonstrations (`qa/sound-design/`)

**Open `qa/sound-design/index.html`** (or `demo-reel.mp4`: all seven, before then after, 4 min). The page
plays each demo before | after side by side with what to listen for, every sound placed and every moment
left silent, and the measurements; below them, every library sound playable, v0.4.56 next to v0.4.57.

Each demo is rendered **twice by the real exporter** at 720p — `demo-N-…-before.mp4` (sound design off)
and `…-after.mp4` (on, Cinematic preset), with the effects, animations, transitions, narration and the
subscribe animation together. The narration voices are AI-generated for the demos; pictures are neutral
placeholder plates (no case imagery is made up). `make_demos.py` remakes them and writes `demo-report.json`.
Because the narration is identical in both renders, after − before is what the sound design added.

v0.4.57 (library v2):

| Demo | Sounds placed | Exact placement ¹ | Onset in the AAC ² | Loudest effect vs speech | Peak (after) |
|---|---|---|---|---|---|
| 1 Bullet reveals (findings) | entrance whoosh, divider sweep, 3 line clicks (one sound for the graphic) | 0.0 ms (5) | max 2.4 ms | −10.7 dB | −3.1 dBFS |
| 2 Typing (typewriter entrance) | 84 keys over heading + 2 lines; no click/whoosh doubling the keys | 0.0 ms (84 keys) | median 0.3, p95 14.1 ms | −14.4 dB | −4.8 dBFS |
| 3 Diagram (timeline) | directional entrance, divider sweep, 3 marker ticks | 0.0 ms (5) | max 0.7 ms | −10.3 dB | −4.1 dBFS |
| 4 Transitions | slide-left → leftward whoosh; circle → tonal sweep; dip-to-black new chapter → swell; hard cut → nothing | 0.0 ms (3) | (slow shapes) | −10.9 dB | −4.1 dBFS |
| 5 Narrative development | one restrained low thump on "matched" | 0.0 ms (1) | 2.2 ms | −7.5 dB | −4.4 dBFS |
| 6 Subscribe animation | entrance whoosh, click on SUBSCRIBE, bell, exit (existing CTA settings unchanged) | 0.0 ms (4) | max 1.6 ms | −18.6 dB | −4.6 dBFS |
| 7 Family interview suppression | **nothing**: both slide transitions around the sister's soundbite and the picture after it are silenced ("original source audio") | — | — | after = before | −1.1 dBFS (both) |

v0.4.56 for comparison: effects vs speech −9.1 / −13.8 / −8.7 / −10.0 / −7.3 / −16.5 dB; peaks equal within
0.2 dB. The fuller v2 sounds sit 1–2 dB further under the voice at the same level settings.

In every demo the export lines up with the stem at **0.0 ms** lag, integrated loudness changes by
≤ 0.1 LU and **no sample reaches full scale**.

¹ Each sound's own waveform found in the mixed stem by cross-correlation (±20 ms): the true placement,
to the sample. ² The first onset detected in the delivered AAC after − before; AAC's pre-echo smears
transients by a few ms, and for typing (keys ~59 ms apart) the detector sometimes catches the tail of the
previous key — the large p95 is that, not a placement error (the placement is 0.0 ms for all 84).

## Benchmarks (your gg project, 231 scenes, 18.4 min, 5 approved graphics; sandbox: 2 cores)

v0.4.56 and v0.4.57 run back to back in the same sandbox (`benchmark.py`):

| Step | v0.4.56 | v0.4.57 | Notes |
|---|---|---|---|
| Library, all 78 sounds at once | 3.50 s | 7.10 s | never in the editor: a timeline makes only the sounds it uses, once, then reads them from disk |
| Events, first time (graphics timings) | 3.28 s | 3.28 s | motion layout, cached per graphic |
| Events, cached | 0.080 s | 0.089 s | |
| Plan | 0.089 s | 0.095 s | 257 events → 37 sounds, 99 silent; the context scores are cached per sentence |
| Resolve (times, files) | 0.166 s | 0.183 s | |
| Stem, whole 18.4 min | 2.76 s | 2.83 s | FLAC 3.7 → 4.7 MB (the tails are no longer cut) |
| Stem, unchanged plan | 0.176 s | 0.186 s | cached by content |
| One sound edited: plan / stem | 0.250 / 3.00 s | 0.272 / 3.07 s | 36/36 other sounds unchanged |
| Every sound moved and quieter: plan | 0.236 s | 0.266 s | the same 37 moments |

Peak memory with the library already made (everyday work: events, plan, stem): 84 → 90 MB. Making all 78
sounds at once peaks at 124 MB (v1: 90 MB).

**Preview ducking curve** (new): computed in the background by FFmpeg with the export's own voice bus.
Requests never wait (4 ms; cached curve 5 ms, 280 KB for 18 min). The curve is ready ≈ 65 s after an edit
that changes the voice on an 18-minute timeline (the export's `loudnorm` is most of it: 50 s), within a
second or two on short ones. One job per project at a time, at low CPU priority; an edit while it runs
stops the obsolete job (measured: three quick edits → one FFmpeg process at a time, nice 10). Until the new
curve arrives the preview keeps the previous one. Edits that do not touch the voice (graphics, sounds,
effects) reuse the cached curve.

## Tests

`tests/test_sound.py` (24): library (determinism, levels, headroom, all categories, cache), shutter never
automatic, settings in range, transition mapping, protected passages (soundbite, victim chapter, sensitive
narration), legal outcome on the word, density and spacing, shared sounds per graphic, sync to the drawn
frame, typing keys = drawn characters, moving/deleting a graphic moves/removes its sounds, editing one
sound leaves the rest, a decided sound holds its moment, the stem (sample accuracy, cache, no clipping),
the export, undo names, the API, importing a sound never touches the timeline. **v0.4.57 adds:** the
preview's duck curve = the export's gain (median 0.02 dB, p95 1.0 dB, at narration 100 % and 40 %);
narration level in the export; one duck job per project (obsolete jobs stopped, not failed); context: no
single word decides (the suspect's mother vs the victim's mother, a charge vs violence, a neutral line
inside a grief passage, pictures); **sync through edits** — a scene shortened, a transition made longer,
replaced (slide → wipe up → cut), scenes reordered, a line edited, an entrance changed to typing, a
graphic moved with a user-edited sound on it — every sound follows its element to the frame and, in the
rendered stem, each sound's waveform is found exactly where planned; bulk edits are one named undo step.
`tests/js/sound.test.mjs` (10, adds scope selection, bulk edits, duck decoding and scheduling).
Full suite: **626 passed, 1 skipped**; JS **42 pass**.

## Limitations

* The understanding is rule-based (see above). It cannot judge tone the way an editor does.
* On long timelines the preview's ducking catches up ≈ 1 min after an edit that changes the voice (see Benchmarks).
* The preview places scene-anchored sounds on the editor's scene offsets; the export on frame-rounded
  ones (they differ by less than a frame per scene where a scene's length is not a whole number of frames).
* The Sound FX lane is the last lane of the timeline: on a short timeline panel, scroll the lanes (or make
  the panel taller) to see it whole. It is labelled A3 because the editor shows narration as A1 and music as
  A2 (soundbites play from their clips); in the export the order is narration, soundbites, music, effects.
* The first plan after the server starts reads every approved graphic's layout (≈0.65 s per graphic).
* Typing sounds exist only for the new **Typewriter** entrance (Motion → Entrance); other entrances get a
  reveal click per line.
* The library is synthesised. v2 is far richer than v1 (measured below) but it is still not recorded
  foley: listen on the page before deciding. Imported sounds can replace any of them.
* Two keystroke variations (`type-strike-6`, `key-soft-6`) are 2.1–2.4 dB lighter than in v1 on purpose
  (a lighter finger in the cycle); every other changed sound is within 1.5 dB of its v1 loudness.
* (v0.4.58) The music preview plays two `<audio>` elements that follow the timeline; while playing it
  re-seeks only past 0.2 s of drift (re-seeking a playing element glitches), so a loop seam in the preview can
  sit up to ~0.1–0.2 s from the export's (the gains and levels are the export's; the export is sample-exact).
* (v0.4.58) The music duck is exact only after the background job; on a 25 min / 150-scene project that job
  takes ≈ 3.4 min (2 cores), ≈ 2.5 min of it the existing voice bus (`voice_graph`, one trim per scene), which
  the export runs as well. Meanwhile the preview applies an immediate approximation (the last exact curve
  scaled for the new narration level) and nothing waits for it.
* (v0.4.58) "Chosen scenes" music follows scene ids; chapters are steadier (a full replacement of the scene
  list gives scenes new ids).

## v0.4.57 corrections

Targeted fixes after the v0.4.56 review; the engine, the plan format and the existing behaviour are unchanged.

1. **Preview = export ducking.** `GET /api/projects/{id}/sound/duck` runs FFmpeg's `sidechaincompress` with
   the export's settings, keyed by the export's own voice bus (`renderer.voice_graph`: narration, soundbites,
   loudnorm, the narration level), on a constant 1.0, so its output *is* the gain the export applies. The
   editor gets it at 200 values/s and schedules it on a WebAudio gain node. Measured against the export:
   median 0.02 dB, p95 1.0 dB, max 2.3 dB (without it the preview was 2.7 dB off on median).
2. **Context, not keywords** — above.
3. **Library v2.** Every sound was audited (`library_audit.py`: spectral peaks, flatness, abrupt tail cuts,
   high-frequency content, stereo width, similarity between variations). 66 sounds were rebuilt, 12
   (pop, paper, tick, riser) left as they were, none added. Same ids, categories, sync points; loudness
   compensated so the mix does not shift.

   | Problem found in v1 | v1 | v2 |
   |---|---|---|
   | layers stopped abruptly (high-passed tail cut) — thump / bass hit / impact / pulse | 89–111 dB | 3–7 dB |
   | whooshes were a narrow whistling band (flatness) | −38 to −113 dB | −11 to −53 dB |
   | the low pulse was a bare sine | −137 dB | −39 to −95 dB |
   | the two camera shutters were the same sound (similarity) | 0.97 | 0.74 |
   | key variations very similar (only slightly less so in v2: typing variety comes mostly from the 6-key cycle and its strengths) | 0.94–0.97 | 0.93–0.96 |

   What changed per category is listed on `index.html`, with v1 and v2 playable side by side.
4. **Demos** made playable in one place (`index.html`, `demo-reel.mp4`) and re-rendered with v2; the
   report adds the exact placement metric.
5. **Sync through edits** verified by test (above) and in the browser.
6. **Select several:** "Apply changes to" this sound / every line / the whole graphic. **Narration level**
   0–200 %, in the export and the preview.
7. **Performance:** no dependency added (NumPy, FFmpeg). Context scores cached per sentence; the duck curve
   cached and computed one job per project at low priority.


## v0.4.58 — template palettes, live levels, audition, background music

Targeted changes after the v0.4.57 review. The sound engine, the plan format, the narration, soundbites,
footage mapping and the timeline are unchanged; the timeline's length is always the export's length.

### What existed and what was corrected

| Area | Before (v0.4.57) | v0.4.58 |
|---|---|---|
| Template sounds | one click repeated for every line / marker; same entrance family everywhere | a palette per template: findings (mechanical clicks alternating, cards pop), timelines (directional whoosh, alternating ticks), contradiction (reverse whoosh, muted statement / low pulse on the contradiction / record), legal (document reveal, heavier step click, verdict thump); typed lines start on a different key each line (`qa/sound-design/palette/palette_before.txt` → `palette_after.txt`) |
| Level sliders | each move saved the project; the effects level re-fetched the plan and restarted the sounds; the narration level restarted the server duck (~1 min on long projects); per-scene "volume" fields that nothing played | WebAudio gains with smooth ramps (time constant 20–30 ms) while dragging (`LiveRange`): no request, no plan, no duck recomputation, no re-render of the editor; one save on release (or 400 ms after the last key); the duck preview follows the narration level at once (approximation) |
| Audition | overlapping playbacks; library rows had no length or waveform | one audition at a time (play/stop), name · category · length · waveform, search + category, audition volume, variations of the selected sound with an explicit "Use", imported sounds; never touches the project |
| Music (export) | `-stream_loop -1`: hard restart at the end of the file, fixed 1.5/2 s fades, always the whole documentary | `music.py`: whole / range / once / chosen scenes or chapters; part of the track (start/end); loop with an adjustable equal-power crossfade (0–10 s); fades; ducking on/off; each pass is a reference to the original file (`-ss/-t` inputs, or for many short passes one input + `aloop`), cut to the timeline; nothing is copied |
| Music (preview) | one `<audio loop>` (hard restart, no placement) | the same layout (`web/src/music.js`, parity-tested against Python to 1e-9), two elements crossfading at the seams, a live gain for the level, the duck curve |
| Music lane | a button that shrank to its label: a box over the first minutes, the file's waveform stretched | full width; filled exactly where the music plays, every loop seam marked |
| Mix | with music and no effects the bare `alimiter` delayed the narration and soundbites by 239 samples (5 ms) and lifted them ~0.45 dB | the transparent limiter of the effects mix everywhere: voices at 0 samples, identical with or without music |

### Music settings (`project.music`)

`mode` whole · range (`offset`–`until`) · once · scenes (`chapters` / `scenes`); `start`/`end` (part of the
track, s); `loop`; `crossfade` 0–10 s; `fade_in` / `fade_out` 0–15 s; `duck`. The level stays
`project.music_volume` (0–0.5). Editor: Audio tab → music panel (and Scene inspector → Music: plays here /
silent, choose this scene or chapter); the music lane shows where it plays and every loop seam.

A pass of a looped part is `len = part − crossfade`; the next pass starts there and the two overlap by the
crossfade with `sin`/`cos` gains (equal power: constant loudness for unrelated material). Up to 12 passes
are an `acrossfade` chain (one `-ss/-t` reference per pass); beyond that the part is decoded once, the seam
is made once, and `aloop` repeats one period in memory. All trims are sample counts, and the bed is padded
and cut to exactly `timeline × 48000` samples.

### Measurements (2-core sandbox)

* **Sliders, in the browser** (headless Chromium, 25 min / 150-scene project, playing, real mouse drags):
  input → gain 0.4–0.7 ms median; 0 project saves and 0 plan requests during a drag, exactly 1 save after
  release; 60 rapid key presses → 1 save; the gain equals the slider value; playback continues; frame
  times during a drag ≈ the same playback without input (this headless renderer is slow either way).
* **Audition:** one at a time (a second stops the first), stop works, 0 project requests, the project
  unchanged; search "whoosh" 11 rows, lengths and waveforms shown.
* **Music export, 25 min, 3 min track** (`music_bench.py`, music branch alone): v0.4.57 stream_loop 2.5 s /
  15 MB; v0.4.58 crossfade chain (9 passes) 3.4–4.6 s / 56 MB; `aloop` (54 passes of a 30 s part, 1 input)
  0.8 s / 56 MB; once 0.7 s. Exact 72,000,000 samples; seams within 1.8 dB of the reference RMS.
* **Demos** (`music_demos.py`, real exporter, 720p; `music.html`): durations equal to the timeline in all 4;
  loop seams: v0.4.57 +2.3 dB level jump at every restart, v0.4.58 −0.3 to −1.3 dB; chapter-only music
  −180 dB (silence) outside the chapter; the part played is the part chosen (cross-correlation: 26.0 s for
  26.0 s, 25.0 s for 25.0 s); music −11.7 dB under narration, −5.8 dB under the soundbite, −0.5 dB in a pause;
  narration and soundbite at 0 samples and correlation 1.0 against the v0.4.57 export; render 17.9 s
  (v0.4.57: 19.0 s; without music 14.1 s) for 60 s.
* **Duck job** (25 min / 150 scenes): 205 s, 97 MB, background, cached; a music level change does not
  recompute it.

* **Tests:** full suite 638 passed, 1 skipped (v0.4.57: 626); JS 49 (v0.4.57: 42).

### Files

`music.py` (layout + FFmpeg graph), `renderer.py` (music wiring, transparent limiter), `sound.py` (palettes,
duck job makes the music's curve too), `app.py` / `history.py` (`music` field), `web/src/music.js`
(`MusicPreview`, layout), `web/src/LiveRange.jsx`, `web/src/MusicPanel.jsx`, `web/src/sound.js` (master /
per-sound live gains, plan carry-over, `audition`), `web/src/SoundPanel.jsx` (library, variations),
`web/src/main.jsx` (live levels, music lane, scene music). Tests: `tests/test_music.py` (11),
`tests/js/music.test.mjs` (7). QA: `qa/sound-design/music_demos.py`, `music_bench.py`, `music.html`.

## v0.4.59 — pre-approval corrections

Targeted corrections after the v0.4.58 practical-testing approval. The engine, the plan format, the
narration, soundbites, footage mapping and the export's sound are unchanged except where stated
(the export's narration tail, item 6). **Not finally approved**: these are measurements for your review.

### 1. Ducking analysis (the background job that makes the effects' and music's dip)

The exact curve is still FFmpeg's `sidechaincompress` with the export's settings keyed by the export's
own voice bus — nothing approximated. It is now made in two steps (`sound._duck_job`):

* **bus** — the voice bus at narration level 100 % (loudnorm, scene cuts, soundbites), reduced to what a
  `link=average` compressor detects, `(|L|+|R|)/2`, stored as 16-bit FLAC in `data/cache/sfx/duck/`
  (the latest 4 kept, `BUS_KEEP`); keyed by the timeline and the source files only;
* **curve** — the two compressors on that stored level, with the narration level applied as an exact
  scaling (the export applies the level after loudnorm, to the narration only); a few seconds.

So a narration-level change re-runs only the compressors; music/effects levels, the ducking switches and
undo to an analysed timeline cost nothing. Synthetic 25-min / 150-scene projects (`duck_bench.py`, 2 CPUs):

| step | sliced v0.4.58 | sliced v0.4.59 | guide v0.4.58 | guide v0.4.59 | inserts v0.4.58 | inserts v0.4.59 |
|---|---|---|---|---|---|---|
| first analysis | 132.8 s | 96.8 s | 19.4 s | 20.3 s | 25.0 s | 30.0 s |
| narration level changed | **103.4 s** | **11.2 s** | 18.6 s | 12.3 s | 24.0 s | 12.1 s |
| music / effects level, ducking switch, undo | 0 | 0 | 0 | 0 | 0 | 0 |
| one scene edited | 137.3 s | 97.3 s | 19.8 s | 21.3 s | 25.0 s | 29.7 s |

Curves against the v0.4.58 single pass (`duck_bench.py --minutes 3 --compare`): max difference 1 step of
255 everywhere, 97.5–100 % of values identical; the v0.4.58 sliced curve was 2.9 s short at the end
(the same tail bug as the export, below). `duck-bench-before.txt`, `duck-bench-after.txt`,
`duck-bench-compare-3min.txt`.

**Not done, and why (trade-off):** incremental per-scene recalculation. The export normalises the
narration with `loudnorm` over the whole bus, whose gain at any moment depends on everything before it;
splicing a re-analysed scene into a stored bus would not be the export's curve. Doing it exactly would
mean re-implementing loudnorm's state, which is more risk than the benefit (the job runs in the
background, the preview keeps the previous curve meanwhile, and a level change no longer needs it).

### 2. Loop timing (preview vs export)

The preview uses the export's layout (`musicLayout` = `music.layout`, parity < 1e-9), unchanged. What
changed is how the preview follows it (`web/src/music.js`):

* each element's envelope (crossfades, fades) is scheduled as gain automation on the audio clock
  (`envEvents`, ramps within 1.5 % of the exact equal-power curve) instead of being set once per frame;
* drift is trimmed with the playback rate (±3 %, pitch kept) instead of a jump only past 0.2 s; a seek
  only happens where the music is nearly silent or is more than 0.25 s off (`syncStep`);
* a pass from the top of the part calls `play()` early by the measured start-up delay.

Measured audibly (`qa/sound-design/loop-timing/`: click tracks through the real `MusicPreview`, the
output recorded with an AudioWorklet, headless Chromium; error = heard music click vs where the export
places it, narration as master clock):

| case | v0.4.58 median / max | v0.4.59 median / max |
|---|---|---|
| part from the top, crossfade 1 s | 9.1 / 19.9 ms | 3.1 / 8.3 ms |
| part from 2 s, crossfade 1 s | 9.9 / 11.8 ms | 3.9 / 7.8 ms |
| with a seek (18.3 → 9.6 s) | 7.5 / 20.0 ms | 2.0 / 13.0 ms |
| main thread blocked 150 ms every ~0.75 s, from the top | 1.6 / 19.9 ms | 3.0 / 7.9 ms |
| same, part from 2 s | 8.8 / 19.5 ms | 3.2 / 18.2 ms |

The "~200 ms" of v0.4.58 was its tolerance (no correction below 0.2 s), not a measured error; in this
headless browser neither version came near it. The export is sample-exact; the preview is now within
about 8 ms typically, 18 ms worst measured.

### 3. Chosen-scene music survives edits

`music.follow_scenes` (on every save, not on undo/redo): a scene that is new after an edit (a split, a
guide rebuild, a replaced scene) takes the music of the chosen scene whose narration or soundbite it now
plays (at least half its own audio inside that scene's); a renamed chapter keeps its music. Ids that are
gone with no successor are kept (an undo brings the music back) and reported: the save's response carries
`music_follow`, the editor shows a notice, and the music panel lists chosen scenes/chapters no longer in the
timeline with "Forget them". Browser-checked: a split at 15 s of the chosen scene 2 → both halves keep the
music, notice shown; a deleted chosen scene → the panel warning, "Forget them" saves the cleaned list.

### 4. Sound sets for every motion-graphics template

The editor has four templates: findings, chronological timeline, contradictory statements, legal outcome
(their layouts cover the diagrams — timeline, legal steps — and the sequential panels — cards, one at a
time); there is no relationship or schematic-diagram template in the editor. Every combination of template
× layout × entrance (Typewriter included) × exit, wide and tall (432), gets its own family: typed lines are
heard key by key; contradictions keep their low pulse also when typed (fixed in v0.4.59 — the pulse was
dropped for typed contradiction lines); the outcome-in-large-type legal layout keeps its thump.
`tests/test_sound.py::test_every_template_layout_and_animation_has_its_coordinated_sound_set`.

### 5. Audition, manual sounds and level sliders (real browser, `browser_sound_qa.mjs`)

* **Audition:** all 79 library sounds (78 built in + the project's own audio) auditioned and *heard*
  (recorded from the audition bus): click → sound 29–32 ms median, 96–110 ms p95, 131–206 ms max the
  first time (fetch + decode; two runs), 23–32 ms median again; 0 project changes while listening.
* **Manual sounds:** "+ at 0:12.0" saves an approved manual item anchored to its scene; it is drawn on
  the Sound FX lane and heard in playback. **The Sound FX lane was hidden behind the timeline footer at
  every common screen size** (1366×768 to 1920×1080: the timeline's default height predates the Music
  lane). Fixed: default height 296 px (a layout saved with the old default opens at the new one), and the
  lanes scroll vertically if you make the timeline smaller. Screenshots: `timeline-sfx-lane-*-before/after.png`.
* **Sliders during playback** (real mouse drags, narration and music playing): slider move → gain change
  4–9 ms median (max 9.3 ms incl. React); 0 requests while dragging, 1 save after release; playback never
  paused, 0 media seeks. Heard on the bus each controls, against the same moment untouched (two runs):
  this sound's volume −20.0 dB set → −20.6 / −21.7 dB heard; effects volume −12.1 → −12.7 / −13.0 dB;
  music level −16.0 → −15.1 / −14.1 dB (the music's own ducking moves under it). Result: `browser-sound-qa.json`. **Fixed:** after a sound edit was saved, the preview could keep the plan from *before* the edit
  (the plan was read 350 ms after the edit, the save landed at 650 ms): a sound's new volume snapped back
  in the preview until the next change. The plan is now read after the save that stores the edit.

### 6. The timeline is authoritative (music never changes its length)

`tests/test_music.py`: a matrix of whole / range / once / chosen scenes × loop on/off × crossfades 0–10 s ×
fades × track shorter / longer than the timeline → the bed is exactly `timeline × 48000` samples, nothing
after the end; real exports keep the timeline's length.

**Fixed (export):** on an ordinary (non-guide) timeline with music or sound effects, the export lost the
last ~2.9 s of narration (40 s timeline → 37.12 s): loudnorm hands over its last 3 s only when its input
ends, and in the same graph as the compressors/amix it was cut off when the finite inputs ended. The voice
bus is now rendered in its own pass (`work/voice.wav`, 32-bit float, exactly the timeline's samples) and
mixed from there. `tail_check.py`: all five cases 40.0 s (v0.4.58: 37.12 s for three); narration-only and
guide exports sample-identical to v0.4.58; with effects or music the difference is −76.6 / −67.4 dB RMS.

### Tests

Full suite 648 passed, 1 skipped (v0.4.58: 638); JS 53 (v0.4.58: 49); build OK.

### Remaining limitations

* A scene edit still re-runs the full voice-bus analysis in the background (97 s on a 25-min sliced
  timeline, 21–30 s for guides); the preview uses the previous curve until it is ready.
* Preview loop timing depends on the browser's media clock: measured ≤ 18 ms in headless Chromium; a
  slow machine or a backgrounded tab can be worse (the export is unaffected). Small drift is corrected
  by a ±3 % rate change (pitch kept), which can be faintly audible on sustained tones while it lasts.
* The first audition of a sound fetches and decodes it (≤ ~130 ms here; longer on a slow connection).
* Lost chosen scenes are kept until you choose "Forget them" (so undo works); they never play.
* The extra voice-bus pass adds one FFmpeg step to exports with music or effects (~the loudnorm time,
  which the single graph also paid).


## v0.4.60 — pre-approval: analysis speed, timeline Sound FX, sync, long timelines

Targeted corrections after the conditional approval of v0.4.59. The export's audio is unchanged
except for one bug fix (3, a narration cut off by a slice past the end of its recording). **Not finally
approved**: these are measurements for your review.

### 1. Ducking analysis — faster, same samples

The curve is still the export's own `sidechaincompress` keyed by the export's own voice bus. Three
changes, each checked sample-for-sample against the previous output:

* **Two-level narration split (analysis only).** The export hands the whole recording to every scene's
  trim (`asplit=150`): about 75 passes of the recording through the graph. The analysis now splits it
  in ~√n groups, each with a coarse trim covering its scenes ± 2 s, then to its scenes
  (`renderer._split_tree`, `voice_graph(tree=True)`). Every scene trim gets the same frames,
  timestamps and samples: **81/81 random layouts (6,822 scenes) byte-identical** to the plain graph.
  (Merging adjacent scenes into one trim was tried and rejected: 14/81 differed by a sample, because
  `asetpts=N/SR/TB` rounds cut points to frame boundaries.)
* **Pipeline (new timeline).** The bus and the two compressors run at once (`bus | curves`), the bus
  kept on disk for a later narration-level change: no second decode of the bus.
* **Compressors side by side (narration level changed).** The effects' and the music's compressor run
  as two processes on the stored bus instead of one after the other.
* **Low priority.** Every analysis process runs at nice 10 (Linux/macOS) or
  `BELOW_NORMAL_PRIORITY_CLASS` (Windows): the editor, playback and an export go first.

Synthetic 25-min / 150-scene projects, `qa/sound-design/duck_bench.py`, both versions measured back to
back on the same 2-CPU sandbox (`duck-bench-v0460-before.txt` / `-after.txt`; CPU = FFmpeg user+sys):

| step | sliced v0.4.59 | sliced v0.4.60 | guide v0.4.59 | guide v0.4.60 | inserts v0.4.59 | inserts v0.4.60 |
|---|---|---|---|---|---|---|
| first analysis | 126.9 s (cpu 130.7) | **78.4 s** (cpu 100.3) | 20.5 s | **11.0 s** | 30.5 s | **19.3 s** |
| narration level changed | 12.4 s | **7.7 s** | 12.1 s | **6.8 s** | 11.9 s | **7.0 s** |
| one scene edited | 129.3 s (cpu 133.6) | **81.3 s** (cpu 103.1) | 19.9 s | **11.2 s** | 30.3 s | **19.4 s** |
| music / effects level, ducking switch, undo | 0 | 0 | 0 | 0 | 0 | 0 |

(The sliced v0.4.59 figures are higher than the 96.8 / 97.3 s reported for v0.4.59: the sandbox was
slower on this run. Before/after here are from the same session.) Total CPU also fell (130.7 → 100.3 s):
the two-level split removes work rather than only spreading it.

Memory while the analysis runs (`--quick`, a /proc sampler every 50 ms, `duck-bench-v0460-memory-*.txt`):

| | sliced v0.4.59 | sliced v0.4.60 | inserts v0.4.59 | inserts v0.4.60 |
|---|---|---|---|---|
| FFmpeg peak RSS, first analysis | 98 MB | 144 MB (bus and curves at once) | 1,079 MB | 1,097 MB |
| FFmpeg peak RSS, narration level | 16 MB | 32 MB (two compressors) | 17 MB | 33 MB |
| server (Python) peak RSS | 69–82 MB | 57–73 MB | 82 MB | 73 MB |

**Found, not changed (pre-existing since soundbites got their own loudness normalisation):** each
soundbite's `loudnorm` costs ~110 MB in the process that makes the voice bus — the export's pre-pass and
the analysis alike (19 MB → 130 MB with one, independent of where it is; the bench's 10 soundbites →
~1.08 GB). It is freed when the job ends. An exact fix exists (normalise each soundbite once in its own
short pass, cache it, read it back as 32-bit float: the same samples, ~130 MB at most), but it changes the
export path, so it is proposed for your decision rather than made here.

### What cannot be made faster without changing the sound

* **loudnorm (70–80 s of a 25-minute sliced analysis).** The export normalises the whole narration as one
  stream; its gain at any moment depends on everything before it (integrated loudness, 3 s look-ahead,
  global state). A scene edit changes what comes before every later sample, so the normalisation cannot
  be resumed from the edit or cached per scene and stay identical — it must run over the whole timeline.
  Approximating it (per-scene normalisation, or reusing the old gain) would make the preview's ducking
  differ from the export's.
* **The two compressors (~6 s each at 48 kHz).** `sidechaincompress` is a recursive envelope follower:
  each sample's gain depends on the previous one, so it cannot be split in time or run at a lower rate
  and stay exact. They now run at the same time as the bus (new timeline) or as each other (narration
  level), which is as parallel as they go.
* **Not added:** a "coarse first, exact later" preview curve. The preview already plays the previous
  exact curve (or none) while the job runs, and an approximation would be heard as the export's ducking.

### 2. Only the latest timeline is analysed

One analysis per project. A new timeline (or narration level) stops the running job's FFmpeg processes
at once (`sound._register` kills them; a stopped job is not marked failed and is not queued); a
narration-level change during a bus that is being made waits for that bus instead of starting a second
one; returning to an analysed timeline (undo) is instant and stops any job for another version. The
editor asks 600 ms after the last edit and polls every 2 s. Test
`test_rapid_timeline_edits_only_analyse_the_latest_state`: 12 edits 150 ms apart → never more than one
job alive (two for an instant while the old one is killed), nothing left running, only the last
state's curve on disk.

### 3. Narration cut off by a slice past the end of its recording (export bug, fixed)

Found while testing v0.4.60: in a scene-sliced project, a scene whose slice lies wholly past the end of
the narration (a scene reordered or retimed past the recording's end) made an empty slice; `apad` padded
it with frames without timestamps, the concat broke ("Invalid data found when processing input") and
FFmpeg **stopped the voice there and still exited 0**. The rest of the narration was missing from the MP4.
An episode guide with a soundbite window wholly past the end of its clip (e.g. a clip replaced by a
shorter one) hit the same thing; there the export's own check then refused the export.

Fix: every scene slice and soundbite is re-timed from its own sample count before the concat
(`RESTAMP = asetpts=N/SR/TB`). Only timestamps change.

* 40 random sliced layouts: the 13 that v0.4.59 cut off (43–54 % of the narration kept) are complete;
  the other 27 are byte-identical to v0.4.59. 12 random guide layouts with soundbites (stems on and off):
  24/24 byte-identical to v0.4.59.
* Regression test `test_a_scene_sliced_past_the_end_of_the_narration_no_longer_cuts_the_rest_of_it`.

### 4. Sound FX from the timeline, without stopping playback

On the **Sound FX** lane (A3):

* **Add:** double-click the lane — the moment is pinned (dashed line), the Sound tab opens with the
  library, and each sound's "+ at" button adds there; without a pin it adds at the playhead, as before.
* **Select:** click a sound — it is selected and shown in the Sound tab. **This no longer pauses the
  playback** (v0.4.59 did); a click while stopped still moves the playhead to it.
* **Move:** drag it (whole frames).
* **Delete:** Delete / Backspace on the selected sound (as the Remove button: a sound you added is
  deleted, a planned one is removed and can be restored).
* **Audition / adjust:** the Sound button and the Volume slider of the selected sound.

Browser QA in Chromium (`browser_timeline_qa.mjs` → `browser-timeline-qa.json`), every step while
playing: still playing afterwards, the narration never paused or re-seeked by it, only `sound` saved
(no scene, storyboard or clip change), the timeline's clips unchanged; the moved sound heard at
**16.001 s** (expected 16.0) and **29.003 s** (expected 29.0) against the narration's own position.
A click or drag on the ruler still stops playback, as in every version.

### 5. Sync of narration, music and effects

The same QA, 28 operations: 12 scrubs then play, 3 playhead drags then play, 4 jumps while playing, 5
pause / play, a seek while paused, and 3 edits while playing (effects volume, music level, a sound
dragged on the lane). Each engine's timeline position read side by side 2.5 s after each:

* **effects:** −6.6 … −3.2 ms from the narration (spread 3.4 ms);
* **music:** −38.8 … +6.9 ms (σ 12.3 ms) — within one frame at 24 fps (41.7 ms).

The music used to stay wherever its last re-anchor put it while the preview clock was less than 50 ms
away; it now follows a steady small offset gradually (a tenth per tick, averaged, never a seek):
v0.4.59 −38.8 … +21.0 ms (σ 16.7) → v0.4.60 −38.8 … +6.9 ms (σ 12.3). Unit test in
`tests/js/music.test.mjs`. The export places everything sample-exactly; these figures are the preview.

### 6. Long timelines (narration tail and completeness)

`qa/sound-design/tail_check_long.py` → `tail-check-long-v0460.json`: real exports (480p draft) with a
test narration whose pitch encodes its own time, so every 0.5 s window inside every scene can be checked
for the right part of the recording (not only "something is playing"); soundbite clips likewise;
windows past the end of a recording must be silent. Music in four chapters with 2 s crossfades, 24
manual effects plus the plan's.

| timeline | version | picture | exported audio | narration windows right part | soundbite windows | should be silent | result |
|---|---|---|---|---|---|---|---|
| guide 25:52, 156 scenes, 6 soundbites (one running 3 s past its clip's end) | v0.4.60 | 1552.0 s | 1552.0 s | **2550 / 2550** | 68 / 68 | 3 / 3 | complete to 1551.3 s |
| sliced 25:12, 152 scenes in a new order, two 6 s scenes past the recording's end | v0.4.60 | 1512.0 s | 1512.0 s | **2550 / 2550** | — | 18 / 18 | complete to 1511.3 s |
| guide 31:03, 188 scenes, 8 soundbites (one wholly past its clip's end) | v0.4.60 | 1863.0 s | 1863.0 s | **3060 / 3060** | 76 / 76 | 8 / 8 | complete to 1862.3 s |
| sliced 25:12 (same) | v0.4.59 | 1512.0 s | **403.0 s** | 680 / 2550 | — | — | narration lost after 6:43, export "succeeded" |
| guide 31:03 (same) | v0.4.59 | — | — | — | — | — | **export refused** by its own check |

No window anywhere played the wrong part of the recording (the order of reordered scenes is right).
Render times on the 2-CPU sandbox: 185 s, 263 s, 240 s.

### 7. Resources (Windows 11, 16 GB, Core i7)

* Analysis processes at below-normal priority; one analysis per project, obsolete ones killed.
* CPU per 25-min sliced analysis: 130.7 → 100.3 s of FFmpeg time; wall 126.9 → 78.4 s on 2 CPUs (a
  Core i7 has 8–16 threads: the pipeline's three processes then run without competing).
* Memory: see the table above; the soundbite loudnorm cost is the one large item (proposal above).
* The preview's work in the browser is unchanged: effects are scheduled ahead on the audio clock,
  music on two media elements; nothing new runs per frame except one multiplication (music anchor).

## v0.4.61 — soundbite memory (approved proposal) + soundbite length fix

You approved the v0.4.60 proposal on condition that samples, sync, narration integrity and export quality are preserved. **Not finally approved**: these are measurements for your review.

### 1. Each soundbite is normalised once, in its own pass, and cached

**v0.4.60:** every soundbite's `loudnorm` ran inside the single voice-bus FFmpeg process. Each instance costs about 110 MB, so with 10 soundbites the process held about 1.1 GB, and every analysis repeated all ten.

**v0.4.61:** `renderer.prepare_soundbites` runs `soundbite_chain` (the same filters in the same order) per soundbite, at most 2 at a time (`SOUNDBITE_JOBS`). Each result is written as 32-bit float to `DATA/cache/soundbites/<hash>.f32`, and the voice bus reads those files in place of the in-graph loudnorm.
- The cache key covers everything that affects the samples: source, in/out points, gain, fades and `SOUNDBITE_V`.
- `voice_graph(..., prepared=True)` keeps the voice-bus pre-pass on: the pre-pass condition now includes `prepared`.

Results on the 25-minute "inserts" bench (10 soundbites), as wall time / peak FFmpeg memory:

| step | v0.4.60 | v0.4.61 |
|---|---|---|
| first analysis | 18.79 s / 1095 MB | 16.62 s / 256 MB |
| one scene edited (middle) | 19.17 s / 1095 MB | 14.97 s / 44 MB (soundbites from cache) |
| narration volume changed | 6.95 s / 32 MB | 7.03 s / 32 MB |

**Export** (6-minute guide, 10 soundbites): the voice-bus step falls from 1065 MB to 128 MB per soundbite pass, then 20 MB for the bus and 40 MB for the mix.

**Identity** (same audio as v0.4.60):

| Check | Hash |
|---|---|
| Duck curve | `0fa4cc93531ac365` |
| Music curve | `0ecb5a724100d83a` |
| Voice-bus PCM | `7fbc5685b0ca82f5` |
| Export audio, 3-min guide, integer-length bites | `3e2961f1fb6fcc39` |
| Export audio, 3-min guide, odd-length bites | `bca68a2fd56db541` |
| 6-min mix | `c8c8085070d6f1b2` |

**Test:** `test_cached_soundbites_give_the_voice_bus_exactly_the_in_graph_samples`.

### 2. Soundbites were cut up to 0.1 s short (bug, in v0.4.60 and earlier) — fixed

`loudnorm` stamps its output frames 0.1 s apart even when the last frame is shorter. The `atrim` and fades that follow went by those timestamps, so a soundbite whose length was not a whole number of 0.1 s frames lost up to 0.1 s at its end. The narration after it then started early.
- In a guide export with soundbites and no music or effects, the shortfall could get the export refused as too short.
- **Fix:** `{RESTAMP}` (`asetpts=N/SR/TB`) runs right after `loudnorm` in `soundbite_chain`, and `SOUNDBITE_V=2` invalidates caches made before the fix.
- This commit is separate (`197602b`), so it can be reverted on its own. It changes the audio only where v0.4.60 was wrong.

`tail_check_long.py guide-12min-10-odd-soundbites` (12:55, 10 soundbites of odd length):

| | narration windows | soundbite windows |
|---|---|---|
| v0.4.60 | 1197 / 1224 | 62 / 65 |
| v0.4.61 | **1224 / 1224** | **65 / 65** |
| v0.4.60, voice only (no music/effects) | export refused | — |
| v0.4.61, voice only | **1224 / 1224** | **65 / 65** |

The long cases all stay complete on v0.4.61:
- guide 25:52: 2550 / 2550, soundbites 68 / 68;
- sliced 25:12: 2550 / 2550;
- guide 31:03: 3060 / 3060, soundbites 76 / 76.

In every case, 0 windows played the wrong part of the recording.
