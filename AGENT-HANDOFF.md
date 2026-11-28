# Agent handoff — Casefile Studio

State as of 2026-11-12 (v0.4.22). Read this before working in the repo.

## What this is

Casefile Studio: a documentary production tool. FastAPI backend
(`casefile-studio/app.py` + `episode.py`, `editorial.py`, `storage.py`),
React frontend (`casefile-studio/web/`, built bundle committed in
`web/assets/`). Version **0.4.22** (bump in `app.py`, `package.json`, and
both `?v=` refs in `web/index.html` together).

## Running it

```bash
cd casefile-studio
# ffmpeg must be on PATH. In a fresh sandbox, fetch it once:
#   pip download ffmpeg-binaries==1.1.0 --no-deps  (unpack into a dir on PATH)
.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Hosted on Render: `render.yaml` at the repo root builds
`casefile-studio/Dockerfile` with a persistent disk at `/var/data`
(`CASEFILE_DATA_DIR`). See `casefile-studio/RENDER-DEPLOY.md`. Do not run more
than one uvicorn worker — jobs and AI sessions are in-process state.

Tests (732 passing, 1 skipped at v0.4.66; 374 at v0.4.22; JS: `node --test tests/js/previewClock.test.mjs`, including `tests/test_deployment.py`, which reads
`render.yaml` from the repo root; browser/long-render ones are slow-path):

```bash
PATH=<ffmpeg-dir>:$PATH .venv/bin/python -m pytest tests/ -q \
  --ignore=tests/browser_episode.py --ignore=tests/browser_production.py \
  --ignore=tests/browser_smoke.py --ignore=tests/long_render_check.py
```

Frontend rebuild after editing `web/src/`: `npm install && npm run build`
inside `casefile-studio/`, then restart the server. Browsers cache the
bundle — version bumps exist so a plain refresh picks it up.

## Hosting

The app deploys to Render as a Docker service: `casefile-studio/Dockerfile`
+ `casefile-studio/docker-entrypoint.sh` + `render.yaml` (repo root) +
`casefile-studio/RENDER-DEPLOY.md`. Deploy via Render's Blueprint flow
(New → Blueprint), not a hand-made Web Service. The storage root is
relocatable via `CASEFILE_DATA_DIR` (`storage.resolve_asset`); the
entrypoint seeds a fresh data volume from the image on first boot.
Optional HTTP basic auth via `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD`
env vars (`tests/test_basicauth.py`) — off unless both are set; the app
has no login of its own, so keep it on for any public URL.

## Data conventions

The storage root is `CASEFILE_DATA_DIR` if set, otherwise `casefile-studio/data`
(`storage.DATA`). Render points it at the mounted disk. Asset paths are stored
relative to the code root when inside it, absolute when on the disk; resolve
them with `storage.resolve_asset` / `renderer.asset_path`, never
`ROOT / path`.

- `data/projects/*.json` — project state, **committed**.
- `data/exports/<id>/` — rendered outputs, **committed** (each ~90 MB MP4;
  keep individual files under GitHub's 100 MB limit).
- `data/media/<project-id>/` — uploaded source files, **not in git**
  (ignored). Originals live on the producer's Mac. A fresh clone cannot
  re-render without re-uploading media.
- `data/jobs/` — render job records, committed.
- `data/browser-sessions/`, `data/recovery-backups/` — ignored, transient.

## Current project state

| Project | id | State |
|---|---|---|
| **Bismilah** | `1a5bbba59d244274` | Producer-signed-off, reviewed plan, **final (no-banner) 480p export done**: `data/exports/1a938f1e9bf64f99/` |
| Tampa… | `4791316c6fae4722` | earlier project |
| Blackwater (demo) | `1b06752858c94e67` | demo |

Also in the repo root: `Bismilah-unreviewed-inspection.mp4` — the same
episode as an inspection draft **with** the burned-in disclosure banner
(pending the producer's confirmation to delete). Git tag `NyRA-Backup` +
GitHub Release of the same name = pre-sign-off backup point.

History note: the original Bismilah entry (`8e7a2f9d34074b1b`) was
deleted by a "clear session" action; `1a5bbba59d244274` (the former NyRA
Backup copy) is the live project and was repaired to point at its own
media copies. Do not resurrect the old id.

## Behavior rules that matter

- **Guide loop rule #8** (`episode.guide.raw` is authoritative over docs):
  gap scenes inherit the cue's selected crop and loop it to fill the
  scene — own beginning, final repetition trimmed, picture only, no
  substitutions/speed/freeze/spill. Never remove this. **Exception (v0.4.17):**
  when the project has `BASE-` files and base fill is on, the clip plays once and
  a relevant base image covers the rest instead of looping (producer request).
  With no `BASE-` files, or the switch off, the loop rule applies exactly as
  before (`tests/test_basefill.py::test_no_base_files_leaves_the_plan_unchanged`).
- **Producer sign-off**: `POST /api/projects/{id}/signoff {"confirmed":true}`
  marks sources reviewed, notes reuse responsibility, approves placements,
  rebuilds the reviewed plan, confirms digests, ticks attestations, covers
  a sub-0.25 s lead-in, and records the same standard reuse note on every
  uploaded `BASE-` file. It is the producer's explicit click — never flip
  these flags silently server-side. Tests: `tests/test_signoff.py`.
- **Inspection banner**: drafts (`draft:true`) and inspection-mode plans
  always burn it in. Only a reviewed plan + attestations + preflight-clean
  final render omits it. Never bypass the banner for unreviewed content.
- **"Clear session"** (`DELETE /api/projects/{id}/session`) deletes the
  project, its media, and its exports from the server. It is destructive;
  the producer has been burned by it once.

## Base-image fill (v0.4.17)

A pool of real `BASE-V/S/C--tag--n` images/clips (victim / suspect / scene)
covers narration that has no matching clip: gaps, fill-only guide cards, and the
tail of a clip shorter than its scene. Full description: `casefile-studio/BASE-FILL.md`
(example guide in `casefile-studio/examples/base-fill/`).

- Code: `basefill.py` (naming, hints, Project setup, seeded relevance picker,
  shot splitting, readiness); `episode.build()` calls it (`push_span`);
  `episode.parse_guide()` reads `**Fill:**`, fill-only cards (no Source ID needed),
  `## Project setup`, and the BASE- file list; `renderer.py` adds `slow-zoom-out`
  and `pan-right`; `app.py` adds options `base_fill/base_seed/reshuffle/base_hold/
  base_label` and `GET /episode/base-report`.
- Behavior: relevance first (hint tags, year tags, `!exclude`), then variety (least
  used, 90 s spacing, max 4 uses, never back-to-back); suspect images never under
  victim/family lines; scene limit 400 kept by lengthening base shots; scenes carry
  a `base_fill` marker and the label "Archive image, not footage of the narrated
  event". `issues()` skips base-fill scenes in guide-source checks.
- UI: `web/src/BaseImages.jsx` (mounted in `EpisodeSetup.jsx` above the plan result).
- Tests: `tests/test_basefill.py` (65).

## Audio breaks, Mode O (v0.4.18)

The narration can pause while a clip plays with its **own sound**, then resume at the same word. Source
audio is otherwise still always muted. Full description: `casefile-studio/AUDIO-BREAKS.md`.

- Guide: card field `**Audio break:** 0:20–0:32` (2–30 s window inside the card's source file); parsed in
  `episode.parse_guide` via `audiobreak.parse`.
- Clearance: binding flag `audio_cleared`, set only by the explicit per-source tick (`bind_source`); it needs
  `rights_confirmed` and an audio track, resets when the file or notes change, and **sign-off never sets it**.
- `episode.build()` pushes an insert scene (`insert_audio: True`, no narration, `audio_start` = narration
  position) before the cue's first scene via `push_insert`; uncleared/invalid breaks go to
  `plan["audio_breaks_skipped"]`. Insert scenes are excluded from the cue-crop (loop/tail) map, sign-off windows,
  and the generic scene-vs-cue checks; `issues()` validates them separately and its narration-continuity check
  skips them (the narration cursor ignores inserts). `plan["duration"]` stays the narration length;
  `plan["total_duration"]` adds `insert_seconds`.
- Renderer: for guide projects with inserts the voice track is rebuilt as narration slices + the clip's audio
  (loudnorm + fades) concatenated in scene order; without inserts the continuous-voice path is unchanged.
- UI: tick on the source row (`SourceRow`) and a summary line in the plan result. Tests: `tests/test_audiobreak.py` (27).

## Frontend anchors (web/src/main.jsx)

`api()` ~line 172; `acceptProject()` ~line 394; Review & export tab:
sign-off button + confirm modal in the Editorial review card; "Make final
video" button in the page header (opens ExportModal with the draft toggle
off; 480p/720p/1080p choice). ExportModal ~line 4842.


## Fetch from guide + audio fixes (v0.4.19)

See `casefile-studio/FETCH.md`. `fetcher.py` downloads guide sources/base items with
yt-dlp (Deno in the image) or an Apify actor; `app.py` `/fetch` endpoints run it as a
`fetch` job and import files like uploads (`import_fetched`, `link_filenames`).
This reverses the old "guide links are never auto-fetched" rule **only** on the
producer's explicit click after accepting the notice (`episode.fetch_ack`). Never
auto-fetch silently; never set license/rights/audio-clearance from a fetch.
Preview playback: narration is the master clock (`web/src/previewClock.js`) — do not
reintroduce the wall-clock + 0.3 s re-seek loop. Renderer narration uses
`asetpts=N/SR/TB`.


## Case Desk (v0.4.20)

See `casefile-studio/CASE-DESK.md`. `casedesk.py` (pure checks + paste-ready packets for the
producer's script gates 1-8), `discovery.py` (yt-dlp YouTube search; candidates only, human
approves, nothing downloaded), `/casedesk` endpoints in `app.py`, `web/src/CaseDesk.jsx`.
State lives in `data/casedesk/<id>.json`, not in the project file. Rules: no AI model and no
paid service in this feature; never auto-approve a gate or a footage candidate; the producer's
prompts in `prompts/` are his wording, do not rewrite them. Next planned stages: guide gates
GV1-GV4 with still-frame contact sheets and base-frame capture; SRT/JSON correction check;
SEO/competitor data collection.


## Voice and timing (v0.4.21)

See `casefile-studio/VOICE-AND-TIMING.md`. Both are ADDITIONS, never replacements: uploading
your own recording and CapCut's SRT/JSON must keep working. `voicegen.py` calls a local
OpenAI-compatible speech server (VoiceStudio); `autotiming.py` runs faster-whisper locally and
keeps the SCRIPT's spelling with Whisper's times. faster-whisper is an optional install in the
Dockerfile (the build must never fail because of it). Not yet built: the fully automatic mode
(an AI key doing research, writing and review end to end); it will reuse these two pieces.


## Re-cut and Delete project (v0.4.22)

See `casefile-studio/RECUT-AND-DELETE.md`. Re-cut works on a FINISHED video: at each insert
the clip plays and the narrated version of the same words (at..until) is skipped, so a line is
never said twice and is separate from guide audio breaks (Mode O), which still exist. The per-insert
"I may play this clip's original audio" tick must stay a human action. `DELETE /api/projects/{id}`
needs the exact title and removes the project's files from the data folder; keep the check that
spares files other projects reference.
Case desk approval: `set_status("approved")` refuses while a check fails or the pasted
reviewer reply says APPROVE WITH CHANGES / SEND BACK; only an explicit, recorded producer
override passes. Do not weaken this.


## Re-cut fetch + free Google Colab voice (v0.4.23)

Re-cut page: `recut.fetch_items()` turns the loaded list into one download per source ID
(link from the list row, else the guide's source library; `need` = last clip end + 10 s).
`POST /api/projects/{id}/recut/fetch` reuses `fetcher.run` and `import_fetched`, saving `S01.mp4`
etc. so `recut_sources()` finds them. The download notice is accepted once (`fetch_ack` in the
case-desk state, or the episode's). Clips without any YouTube link are listed as "upload by hand".

Colab voice: see `casefile-studio/COLAB-VOICE.md` and `colabvoice.py`. Casefile NEVER connects to
Colab: the free tier forbids driving it from another app's UI (remote control / web UI). Casefile
makes a voice pack (narration.txt, parts.json, voice.wav 24 kHz mono <= 20 s, settings.json);
the 2-cell notebook (`GET /api/voice/colab-notebook`) installs + restarts (cell 1), then reads the
pack, makes every part with Chatterbox, joins and downloads the MP3 (cell 2, resumable per pack hash).
`POST /voice/colab/result` imports the MP3 as the narration and starts Make the timing.
Cell 2 is plain Python (no `!` lines) and the test suite executes it with stand-ins for
google.colab, torch, soundfile and Chatterbox: keep it that way.
Cell 1 was proven on a real Colab T4 (Python 3.13, Nov 2026): install chatterbox-tts, uninstall
torchvision + torchao, then os.kill to restart. Do not import torch before the install.
`voicegen.spoken_text` now also drops `[VISUAL]` lines, whole-line `(notes)` such as re-cut
markers, leading `(setup — …)` / `[RE-HOOK]` tags and trailing `[callback …]` tags; on the real
Javits v1.1 script it gives exactly the 3,214 words of the hand-made narration file.


## Edit page, CapCut-style layout (v0.4.24) — stage 1 of 3

`web/src/editLayout.js` (tested in tests/js/editLayout.test.mjs) holds the pure parts: saved panel
sizes (`casefile-edit-layout` in localStorage, always passed through `normaliseLayout`), ruler
ticks, caption blocks for the T1 track, zoom-around-pointer. In main.jsx the edit grid gets its
column/row sizes inline (only above 1070 px; below that the old mobile CSS rules), three
`.splitter` handles (left panel, inspector, timeline height; double-click resets), panel hide/show
and compact-header buttons in the monitor header, a closable direction bar (default shown: tests
use `#direction`), a full-width timeline with Captions (T1) / Visuals (V1) / Narration (A1) /
Music (A2), ruler + playhead scrubbing, a log zoom slider (1–20x) and Ctrl/⌘+scroll zoom.
The timeline follows the playhead while playing. Track label heights must match lane heights
(28/60/40/34 under a 26 px ruler).
Next stages, not built yet: 2) caption style presets + size/position/font, rendered identically by
the exporter (ASS/libass); 3) effects and transitions.


## Caption styles (v0.4.25) — stage 2 of 3

One style per project in `project["caption_style"]`, always through `captionstyle.normalise`
(Python) / `normaliseStyle` (web/src/captionStyle.js). Both read `web/src/captionPresets.json`:
fonts, defaults, 10 presets, limits. Sizes are fractions of the video height. `size` is the CSS
font size; libass sizes fonts by winAscent+winDescent, so ASS Fontsize = size / ratio (ratios
checked against the font files in tests). Fonts are bundled in `web/assets/fonts` (served at
/assets/fonts for the preview, passed to ffmpeg as `subtitles=...:fontsdir=...`), so the Docker
image needs no extra font packages. The default preset reproduces the pre-0.4.25 look exactly.
Chunking (words on screen) and word timing (even by word length) are the same in Python and JS;
`test_preview_and_export_split_captions_the_same_way` runs both. Word highlight = one ASS
event per word with a `\c` override on the active word. Captions tab in the Edit inspector;
the captions can be dragged up/down on the preview (saves `position`). The T1 track shows the
same chunks. Next: stage 3, effects and transitions.


## Effects and transitions (v0.4.26) — stage 3 of 3

`effects.py` + `web/src/effects.js`, both reading `web/src/effectsSpec.json` (transitions, motions,
looks, effect defaults, lower-third layout). Rules that must hold:
- A transition goes INTO a scene and never moves a boundary. The renderer builds each scene's
  picture first (`[pic0]`, frames renumbered with `setpts=N/FPS/TB` so none are dropped), blends
  the previous scene's last PICTURE frame (`last{i}.jpg`, written as a second output only when the
  next scene has a transition) with `xfade` at offset 0 (the still lasts exactly the blend length),
  and only then draws the overlay, captions and name card. Text never blends with old text, and
  `test_moving_photos_with_transitions_keep_every_frame` checks frame counts.
- Legacy names: "cross-dissolve" → dissolve, "cut" → none; "fade" keeps the old fade in/out to black.
- Looks (10), grain, vignette and letterbox are filters on the picture (`picture_filters`), under
  titles and captions. Project fields: `look`, `effects` {grain, vignette, letterbox}.
- Lower third: `scene.lower_third` {name, role}, drawn by libass in the scene's ASS file (style
  LowerThird, bundled Inter), 0.3 s to 5 s, slide + fade. Rendered even when captions are off.
- Preview: transitions/looks/grain/vignette/bars/name card are CSS approximations of the same
  numbers (motion transforms are derived from the zoompan formulas). Effects tab in the inspector;
  transition diamonds on V1 open it. Transition/movement moved out of the Scene tab.


## Per-file download progress (v0.4.27)

`fetcher._run` streams stdout lines (`on_line`) and ticks (`on_tick`); yt-dlp runs with
`--newline --progress-template "download:CFPROG done|total|estimate|speed|vcodec"` parsed by
`parse_progress`; when no template lines come (section downloads via ffmpeg) the file size on
disk is reported instead. Apify reports streamed bytes. `fetcher.run(..., on_status=)` reports
each item: waiting → downloading → saving → done | failed. In app.py `FileProgress` keeps
`job["files"]` = {id: {save_as, status, done, total, speed, attempt, error, at}} (throttled to
~2.5 updates/s); GET /jobs adds `idle` (seconds since the file last moved); the UI calls a
download "stalled" after 30 s. Retry = POST the same fetch endpoint with `only: [ids]`.
Re-cut clip downloads use job kind "clip-fetch" (guide fetch stays "fetch") so each page follows
its own job. UI: web/src/DownloadRows.jsx (rows + `useFetchJob`), used by FetchPanel and Recut.
Next agreed: 9:16, the CTA banner overlay, name-card spacing + optional name cards from the guide.


## 9:16 vertical (v0.4.28)

Project fields `aspect` ("16:9" | "9:16") and `vertical_fit` ("blur" default | "crop"), set from the
format menu on the stage nav (top right). `effectsSpec.json` → `formats` holds sizes per resolution
(480p = 480x854 tall), `text_scale` (9:16 text = width x 1.4; 16:9 = height, unchanged), the
caption safe bottom (20% in 9:16, for the Shorts/TikTok/Reels buttons), name-card bottom (48%)
and footage-label top (54%). Vertical stack from the bottom: captions → footage label → name card.
Blur fit: split → blurred, darker cover copy + the whole picture scaled to fit, centred (stills
then get zoompan on the composed frame). No cinema bars in a tall frame. Every text size in the
renderer overlay goes through `effects.text_unit`, which equals the height for 16:9, so wide
exports are byte-for-byte the same layout as before (test_sixteen_nine_is_unchanged).


## Subscribe call-to-action (v0.4.29)

`cta.py` + `web/src/cta.js` + `web/src/CtaOverlay.jsx`, timing numbers in `effectsSpec.json` → `cta`.
Project field `cta` {enabled, asset_id (an uploaded image), button [x0,y0,x1,y1] fractions,
opacity (banner, default 0.5), seconds (3–8, default 5), mode "auto" | "scenes"}; scene field
`cta: true` for "scenes" mode. Choosing a new banner (PATCH cta.asset_id) runs `detect_button`:
the biggest solid red rectangle (fill > 60%, aspect 1.6–10) on a 256-px copy, so thin red frame
lines and pins are ignored; on the real The Last Timeline banner it lands within 2 px. If none,
a red SUBSCRIBE button is drawn. Auto mode: the first scene whose chapter/title says
subscribe/CTA and whose narration says "subscribe", starting 0.5 s before the caption with
"subscribe". Export: Pillow draws the frames once (banner at opacity, the button crop at full
strength, cursor, click ripple, SUBSCRIBED + bell, fades) and each scene overlays the part that
falls inside it (`-start_number` + setpts), so it carries across scene cuts. It sits over the
titles and under captions/name cards. Next: name-card spacing + optional name cards from the guide.


## Name cards: spacing and optional auto-fill (v0.4.30)

- Spacing: when a scene shows a footage label (`source_label` + a visual), the card is lifted to
  `effects.lower_third_bottom(..., lift=True)` = above the label's top + a 3% gap (16:9: 27%,
  9:16: 49%). Same rule in `web/src/effects.js` (`lowerThirdBottom`).
- Auto-fill is OFF by default (project `name_cards` {auto, people {S01: {name, role, on}}}).
  Switching it on pulls suggestions from GET /api/projects/{id}/name-cards = the re-cut list's
  Who column (`split_who`: "Dedrick Hilton (father)" → name + "Father"); the producer edits them.
  `effective_lower_thirds(project)`: a card typed on a scene always wins; otherwise the FIRST
  scene whose `guide_source_id` is that person's clip gets the card. Computed at render/preview
  time, so it survives guide rebuilds (which regenerate scenes).
- Re-cut page: optional "Add a name card when each person first speaks" — the first chosen insert
  per clip gets editable name/role (pre-filled from Who); recut.render burns it onto that clip
  with the same ASS look (temporary .ass files are removed).
Never name anyone the guide's standing rules forbid (e.g. the unnamed 17-year-old): names only
come from what the producer confirms.


## Re-cut memory fix (v0.4.31)

The re-cut used ONE filter graph that `split` the whole base video into one branch per kept
piece; ffmpeg buffers decoded frames for every later branch while concat consumes the first, so a
16-min 1080p video with 13 inserts ran Docker out of memory (empty error, then "stuck at 1%").
`recut.render` now makes each piece on its own (`-ss` before `-i`, re-encoded: h264 + PCM in .mkv)
and joins them with the concat demuxer (video copied, audio encoded once to AAC, so no gaps).
Same cuts, fades, loudnorm and name cards. Measured: 16.5-min 1080p + 13 inserts → 4 min here,
peak child memory ≈ 580 MB, length correct to 0.02 s, audio/video end together. A process killed
by the system now says so ("usually for lack of memory") instead of an empty message.


## v0.4.33: home page, choices that survive guide rebuilds, Replace picture, full delete

- Guide projects rebuild their scenes on every scenes PATCH (app.py, `episode.build` after the
  patch), which used to wipe transitions and swapped pictures ("transition always goes back to
  none"). Now `episode.record_overrides` stores the producer's changes per `scene_key`
  (guide cue id | narration start frame | insert flag) in `episode.overrides`, and
  `episode.apply_overrides` re-applies them inside `build` BEFORE the plan digest, so the plan
  stays current. Fields: transition, transition_duration, motion, lower_third, cta, asset_id,
  trim_start, replaced, source_label. POST /episode/restore-scene removes a replacement.
- Replace picture: web/src/ReplacePicker.jsx (filters, search, upload, clip start). Sets
  `replaced: true` and clears the footage label (it described the old picture).
- Home page: web/src/Home.jsx + GET /api/home (thumbnail, length, size, exports, re-cuts). The
  app opens on it; `?project=ID` skips it. Browser tests step past it (`.home-continue`).
- Delete also removes saved job records, recovery backups and browser-session snapshots.
- Whisper: `autotiming.unavailable_reason()` is shown in Episode setup and in the timing error;
  the Dockerfile prints "Whisper ready" or the reason. ctranslate2 has cp313 aarch64 wheels.
- Known stale test: tests/browser_episode.py expects `gap_seconds > 0` after "Preview episode
  plan", but base-fill images now fill those gaps (also fails on v0.4.32). Update the test's
  fixture to have uncovered time, or assert on the base-fill instead.


## v0.4.34: a real percentage for cut-section downloads

`--download-sections` makes yt-dlp hand the download to ffmpeg, which prints no byte totals but
does print `time=HH:MM:SS.ss` on stderr. `fetcher._run(..., on_err=)` streams stderr lines;
`fetcher.ffmpeg_seconds` parses them; the file reports `secs` / `secs_total` (the section length)
and DownloadRows shows "43% · 1:12 of 2:48 of video · 12.0 MB so far". Full downloads keep
yt-dlp's byte percentage. The fake yt-dlp in tests prints ffmpeg-style `\r` stats for sections.


## v0.4.35: your own subscribe animation file, and a blurred video behind the CTA

Effects → Subscribe animation now has two choices:
- What to show: "Casefile animates my banner" (the v0.4.29 banner + cursor + click), or
  "My own animation file": a .mov (ProRes 4444), .webm (VP9 with alpha) or .gif uploaded with
  "Upload animation". `.gif` is now allowed by the upload endpoint (probed as video).
- Behind it: "See-through banner" / "Video as it is", or "Blur the video behind".

`cta.normalise` adds `style` (overlay|blur), `source` (casefile|file), `file_id` (must be a
video asset; PATCH passes `files=` the video ids), `size` (width fraction 0.25–1) and `y`
(centre height 0.15–0.85). Spec: `effectsSpec.json["cta"]` `blur` (radius 0.03 of the short
side, brightness -0.1, fade in 0.4 s / out 0.5 s) and `file_max_seconds` 15. With your own file
the CTA lasts the file's length (`cta.file_seconds`, 1–15 s) and plays once.

Renderer, per scene the CTA touches (it can cross a cut):
- blur: `split → boxblur,eq,format=yuva420p,fade alpha in/out → overlay enable=between(t,…)`,
  fades only on the scene holding the CTA's start/end;
- own file: `-ss` offset when continuing into the next scene, `cta.alpha_decoder()` puts
  `-c:v libvpx-vp9` before `-i` for alpha WebM (ffmpeg's native vp9 decoder drops alpha),
  scale to `size*W`, overlay centred at `y`, `eof_action=pass`;
- Casefile banner in blur style is drawn as a solid rounded card with a shadow (`cta.card`).
All of it sits before subtitles, so captions stay on top; the MP4 from Download is final.

Preview: CtaOverlay uses CSS backdrop-filter for the blur and a muted <video> synced to the
preview clock (or <img> for GIFs). Chrome previews WebM alpha; Safari previews ProRes/HEVC alpha.
The export works for all three either way.

Tests: tests/test_cta_file.py builds real .mov/.webm/.gif with transparency and checks the
rendered pixels (solid animation in the middle, blurred stripes through the transparent part,
across a scene cut, gone afterwards), plus the banner card over blur.


## v0.4.36: logo watermark; home page titles no longer overlap

Effects → Logo watermark: tick "Show my logo on the whole video", Upload logo (PNG/WebP/JPEG),
tap one of nine spots on the mini frame (corners, middle of each edge, centre), size and
opacity sliders, and a "YouTube default" button (bottom right, 150 px wide at 1080p, 85%).
`watermark.py` / `web/src/watermark.js` share `effectsSpec.json["watermark"]`. `size` is the
logo's width as a share of the frame's SHORT side (so 16:9 and 9:16 match; 0.14 = 151 px at
1080p); tall logos are capped at that height; margin 0.035 of the short side.
Renderer: `watermark.layer()` draws one full-frame PNG at the export size; every scene overlays
it after the CTA and before subtitles (captions and name cards stay on top; a CTA blur does not
blur the logo). Re-cut: `recut.render(..., logo=callback)` puts it on inserted clips only (the
base video already has it when exported with one). PATCH field `watermark`.
Home page: `.home-card { min-width: 0 }` and a 2-line clamp on titles (they overflowed the grid
cell into the next card); full title in the tooltip.
Tests: tests/test_watermark.py (nine spots, default, a real export), a re-cut test with a logo.


## v0.4.37: prompts v2 (Re-cut planned in the research) and a re-cut list fix

- recut.parse: several inserts in one chapter were collapsing into one (cuts/clips were keyed by
  the chapter number). Now an RC / ID column (exact header "RC", "ID", "Insert"…) pairs cut rows
  with clip rows; without one, the n-th cut of a chapter takes the n-th clip of that chapter.
- prompts/ now holds the three full docs (0 Gate Reviewer, 1 Script Workflow A/B/C, 2 Guide-Writer)
  and the split files the Case desk pastes (script_prompt_a/b/c.md, script_resume.md,
  gate_reviewer.md, guide_writer.md) extracted from their code blocks. Change the full docs, then
  re-extract. The research now builds a Footage & Soundbite Map, one Source ID per video from
  Phase 1, Re-cut slots in the script (setup → clip → follow-up, placeholder for v1.0), and a locked
  package with recut_plan.md; the Guide-Writer writes recut_list.md (both tables with an RC column,
  Cut from = end of last word before, Cut to = start of first word after) and no Audio break lines.
- Case desk: G4 is "Footage & Soundbite Map"; the G8 lock message asks for the package files; the
  start prompt fills the new Target line.
- Test: the recut_list.md format in the Guide-Writer prompt is parsed by tests/test_recut_delete.py.


## v0.4.38: picture cutaways on long Re-cut clips

While a real clip plays with its own sound, the picture can leave the speaker to show what they
talk about, then come back. Sound never changes.
- `cutaways.py`: `parse_show` (base hint `V / portrait`, `BASE-…` filename, footage `S06 21:10–21:16`,
  "face"), `auto_plan` (clips >= 12 s with no rows; v0.4.46: `speaker` → family | defendant | defence |
  court | police | other, `topic` scores the clip's words (victim/suspect names from the guide setup,
  son/baby…, vigil/funeral…, house/street…, police/arrest…) when Words holds words, not a count;
  else the speaker: family/court → V, defence → S, defendant/police/other → C/location; every auto C
  excludes `court` (never a courtroom picture), no S under family or the defendant; each cut carries
  `alts` (V ↔ C/location) that `resolve` tries when a bucket is empty, and `why`; face 3 s first, 4.5 s with a
  name card; 4.5 s shots, 3 s face between, at most 50%), `clean` (face >= 2.5 s first / 1.5 s last,
  1–8 s each, <= 60% of the clip, no S under a family speaker; drops rows with a sentence why),
  `resolve` (rotates base pictures across the whole re-cut, footage windows from the S-ID files,
  kind "asset" = the producer's pick).
- recut.parse reads a third table `| RC | From | To | Show | Words |` (times inside the clip,
  paired by the RC column) into `insert["cutaways"]`; inserts also carry `rc`.
- recut.render: each clip piece is one filter graph: clip → cutaway overlays (images get a slow
  push-in via a time-based crop; videos `-ss` into their window) → logo → name card; `-map 0:a:0`
  so a cutaway's own sound is never used; the name card is cut short at the first cutaway.
- app: `recut_cutaways(p, raw_inserts, auto)` shared by `POST /recut/cutaways` (the page's preview:
  plans with thumbs, warnings, speaker, and the picture list) and `/recut/render` (`auto_cutaways`,
  per insert `cutaways`, `off`, `pick`). Base pool honours the guide's Avoid tags. Re-cut records
  store a cutaway count per insert.
- Re-cut page: one "I may play the original audio of all N ticked inserts" tick (v0.4.46, sets each
  insert's own tick; the server still checks every insert), "Cut away … on long clips" (off by default) and a Cutaways strip
  per insert (thumbnail, time, picture menu without S pictures for family speakers, × to stay on
  the speaker, turn back on).
- Prompts: Script Workflow (rule 14d, cutaway rules, Phase 4 cutaway points, recut_plan cutaway
  table, Prompt C check 3b), Guide-Writer (cutaway table in recut_list.md with Show made concrete,
  base list covers cutaway tags, GV2/GV4 audits), Gate Reviewer (facts, G4/G8/GV2 checks, failure
  modes). Split files re-extracted.
- Tests: tests/test_cutaways.py (parse, rules, real render with photo + footage cutaways keeping the
  speaker's 2500 Hz tone, resolve rotation, API, prompt formats).


## v0.4.39: Re-cut picture check, clip preview, automatic cutaways off by default

User report: "the soundbite only shows images/base fills, not the clip" (also before v0.4.38).
Investigation: recut.render was re-tested frame by frame with H.264 30/60 fps, AV1, VP9 25 fps,
yt-dlp-style section copies (fragmented source) and a video track starting 1.5 s late: every frame
of every insert came from its clip (0 mismatches). The v0.4.36 list bug (several clips in one
chapter collapsing/pairing wrongly, fixed in v0.4.37) and v0.4.38's automatic cutaways (base images
over up to half a clip, then on by default) both produce "images instead of the clip".
Changes so it can never be silent again:
- recut.picture_check: after the join, for each clip, 2 spots outside cutaways (avoiding the name
  card) — output frame vs the source clip frame (±1 frame), 64x36 grey centre crop, mean diff
  <= 22 passes (correct clips measure 0–5; wrong picture 55–77). A spot that cannot be read does
  not count; a clip with no readable spot fails. Any failure raises RecutError and nothing is saved.
  Also fails if the joined picture and sound tracks differ by more than 0.5 s.
- render(..., proof_dir, checks): one proof frame per clip saved to media/<id>/recut/<rid>-check/;
  records keep `checks` [{n, ok, at, proof}]; GET /recut/check/{rid}/{name} serves them; the page
  shows "Picture check passed" with a frame per clip that jumps the player there.
- Re-cut page: "See this clip" plays exactly the file window each insert will use (the source's URL
  with #t=start,end, paused at the end), so news packages whose own picture is a photo are visible
  before rendering. Automatic cutaways now default OFF.
- Sources in the recut view carry url and thumbnail.


## v0.4.40: Re-cut clips froze (still picture, sound playing) — rebuilt the re-cut join

User report: in every re-cut, every inserted clip showed a still picture while its sound played;
the Re-cut page preview of the same file played normally; v0.4.39's picture check passed (it only
compared one frame per clip). Reproduced here with a source whose frame times jump (a download
with broken timestamps): `-ss` + `setpts=PTS-STARTPTS,fps=24` repeats one frame across the jump.
Changes in recut.render:
- Built like the main export: video-only MP4 pieces with an exact `-frames:v` count
  (libx264 veryfast crf 19, yuv420p, 24 fps, timescale 12288) and WAV sound pieces trimmed to the
  same exact length; joined as one picture track + one sound track, then muxed (aac 192k,
  faststart). No more MKV pieces (Matroska has no DTS; the old join stream-copied h264+pcm MKVs).
- `_clip_command(..., attempt)`: "timestamps" (setpts=PTS-STARTPTS) first; `_longest_still` scans
  the made piece; if it stands still >= 1.5 s, the clip is made again with "frame-count"
  (`setpts=N/(src_fps*TB)`, src_fps from ffprobe) and the version that moves more is kept. A clip
  whose own picture is a still photo stays still (both versions agree) and is not an error.
- Input `-t` on the clip removed (it used the broken frame times and cut the read short).
- tests/test_recut_motion.py: broken-timing source moves (>= 95% of frames change) with its sound;
  a still-photo stretch stays still and the moving part moves; output has equal picture/sound
  lengths and rising DTS. App run with 4 clips (one broken-timing source): every clip frame moves.
Not yet changed: the main renderer still uses `fps=24` on source timestamps for footage scenes;
if users report frozen footage in the main export, apply the same still-detection/frame-count
retry per source there.


## v0.4.41: ROOT CAUSE of "re-cut clips are still pictures": H.264 4:4:4 clip pieces

Proven by the user's own diagnostic (run inside their container): every clip in their v0.4.39
re-cut has 72 different frames out of 72, i.e. the FILE moves; their browser (DuckDuckGo = WebKit,
Apple's VideoToolbox decoder) showed a still picture with the sound playing. Reproduced: the clip
piece chain `...format=yuv420p[cv];[cv][logo]overlay=0:0:format=auto` (logo watermark, v0.4.36+)
without `-pix_fmt` makes libx264 encode **High 4:4:4 Predictive (yuv444p)**; base pieces were
High 4:2:0. Apple's decoders do not decode H.264 4:4:4, so every clip froze; ffmpeg/Chrome decode
it, which is why all tests and the picture check passed. The main export ends its chain with
`format=yuv420p`, so it was never affected.
Fix (recut.py): every piece is encoded identically — `-profile:v high -pix_fmt yuv420p`, bt709 tv
tags, `keyint=48:min-keyint=24:scenecut=0`, 24 fps, timescale 12288 — and after each piece
ffprobe must read `h264,High,<w>,<h>,yuv420p` or the re-cut stops with a clear message.
Also: v0.4.40's speculative "broken timestamps" retry was removed (the user's files have clean
CFR timestamps: VP9 1080p30 and AV1 720p30); a 3-minute no-progress watchdog stops a stuck step
with a message (STALL_SECONDS). The user's v0.4.40 re-cut was never saved (cause not seen; the
watchdog will name the step if it recurs).
Tests: tests/test_recut_motion.py checks logo + name-card pieces are High/yuv420p/bt709 and move.
Lesson: Playwright Chromium is not Safari. Check H.264 profile/pix_fmt of anything users play on Macs.


## v0.4.47: your own CTA .MOV shows in the edit preview; fullscreen preview keeps overlays in place

Two preview-only bugs (exports were fine):
1. A transparent .MOV CTA (ProRes 4444, QuickTime Animation/qtrle, PNG-in-MOV…) showed nothing in
   the edit preview: the page put the original file in a `<video>`, and browsers cannot decode those
   codecs (Chromium: MEDIA_ERR_SRC_NOT_SUPPORTED). No transparent *video* format plays with its
   alpha in every browser (VP9-alpha WebM is Chrome/Firefox; HEVC-alpha needs Apple's encoder;
   the user browses with DuckDuckGo = WebKit), so the preview now uses **WebP stills**:
   - `renderer.probe` also returns `codec` and `alpha`; `needs_preview` = video codec not in
     {h264, vp8, vp9, av1}; `preview_frames(path, folder)` = first 15 s at 15 fps, ≤640 px wide,
     `<stem>-frames/0000.webp…` with alpha (Pillow WebP).
   - Upload: such videos up to 60 s get `asset.preview_frames = {count, fps, width, height, base}`.
   - `POST /api/projects/{id}/assets/{asset_id}/preview`: for uploads from before v0.4.47 (no
     `codec`); probes, makes the stills if needed, stores `codec`/`alpha` (so it is asked once).
   - CtaOverlay `FramesCta` shows still `floor(t * fps)` (in step when paused/scrubbed), preloads
     all; old uploads show "Preparing your animation for the preview…" until the stills arrive.
   - The export still uses the original file (renderer unchanged).
2. Fullscreen preview: `requestFullscreen` was called on `.video-frame`, which grew to the screen,
   but every overlay (watermark, CTA, captions, titles, name cards) is placed in pixels from
   `frameSize`, computed by the ResizeObserver on `.monitor-screen` — unchanged in fullscreen, so
   overlays stayed where the small frame was. Now `.monitor-screen` goes fullscreen; its observer
   recomputes `frameSize` for the screen (no 40 px margin when fullscreen), 16:9/9:16 kept, black bars.
Verified in a real Chromium (headless, @sparticuz/chromium + playwright): CTA stills on screen with
solid box / transparent corner pixels, stills advance at 15 fps with the clock; fullscreen 1900x1100
→ frame 1900x1069, watermark at the top-right at full scale, CTA centred at 62%; exit restores.
Note: headless Chromium here does not paint `<video>` frames into screenshots or canvases; read
`currentSrc`/`readyState` for videos and pixels only from images.


## v0.4.48: faster export (same frames), and a warning when the machine itself is the problem

User: "Why is my rendering so slow?" Both Export and Re-cut; Docker on an Apple-silicon Mac;
18-minute 1080p 16:9 video takes over an hour. Measured in a 2-vCPU sandbox (`/tmp/bench/bench.py`
timed every ffmpeg call of `renderer.render`, 6 × 10 s mixed scenes at 1080p):
- **A still photo with motion "none"** was read with `-loop 1`, so the full-size photo was decoded
  and scaled again for every frame: 23.5 s for a 10 s scene vs ~5 s for a zoompan scene. Now it is
  read once (`-framerate 24`, no `-loop`) and repeated with `loop=loop=-1:size=1` → 3.9 s. (The
  `-framerate` matters: without it the link is 25 fps and xfade into the scene fails.)
- **A looped video crop** used `-i src -ss trim` (decodes from 0:00 to the crop). Now `-ss` before
  `-i`; identical frames (framemd5), 9.6 s → 1.3 s at 5.5 min into a source.
- **Scenes ran one at a time**, each FFmpeg capped at `-threads 2` + `-filter_complex_threads 1`
  (~1.8 cores busy), so a 8–12-core Mac sat mostly idle. Scene commands are now built first and run
  by `run_scenes()`: `render_workers()` = min(chains, 6, cpus // 2, RAM GB), `CASEFILE_RENDER_JOBS`
  overrides; x264 gets `max(2, min(8, cpus // workers))` threads. A scene with an xfade transition
  needs the previous scene's `last{i-1}.jpg`, so such scenes form a chain run in order; chains run
  in parallel. A failure or cancel stops the other scenes (shared `stopped()` passed to `run`).
- Old vs new on the bench project with transitions: 79.3 s → 38.6 s on 2 cores, **picture
  bit-identical (PSNR inf) and audio identical (md5)**. More cores → more gain (not measurable here).
- `renderer.machine()` / `machine_note()`; `app.with_machine_note(progress)` wraps Export and
  Re-cut progress: warns when running as x86-64 on an ARM kernel (`/proc/cpuinfo` has
  "CPU implementer"/no `vendor_id`) or with ≤2 CPUs. `Local Runs.md` has the Docker checks.
- Re-cut itself is unchanged: it already uses all cores (x264 auto threads, 1.93 of 2 busy, 75 fps
  at 1080p here). The user then corrected: Re-cut takes 5-6 min (18 → 22 min video) — fine; only
  the Export takes over an hour. Their Docker is fine: `linux/arm64`, `aarch64`, 8 CPUs (MacBook Air).
  Re-cut ≈ 96 fps on their 8 CPUs vs 75 fps on 2 sandbox vCPUs, so their cores are slow per core
  (Air efficiency cores, VM, no fan) — and the old Export used only ~2 of them. That is the likely
  main cause; v0.4.48 runs 4 scenes at a time there. Not yet confirmed on their Mac.
- Rebuilt their older 158-scene guide episode (`data/projects/1a5bbba59d244274.json`) with
  synthetic media of the same resolutions/lengths (`/tmp/bench/replica.py`): old code 0.64x
  realtime on 2 vCPUs. Feature costs per 10 s 1080p video scene (old code, incl. ~3 s final mux):
  base 5.2 s, watermark 5.9, **grain 0.5 13.3 (2.5x)**, vignette 7.3, letterbox 5.5. Gap cards
  (VISUAL NEEDED, motion none) now also take the decode-once path: 5.6 → 4.0 s, identical frames.
- **Render report**: `render()` returns `timing` (machine, workers, prepare/scenes/join/sound
  seconds, settings, per-scene seconds + what it is); `write_export` pops it, writes
  `exports/<id>/render-report.txt` (`renderer.timing_report`, slowest scenes first) and stores
  `render_seconds` + `render_report_url` on the export; the export list shows "rendered in …"
  and a "Render report" link. Ask the user for this file after their next export.
Notes: ffmpeg 7.0.2 (imageio-ffmpeg 0.6.0) fails every xfade transition ("current rate of 1/0") with
or without this change (setpts unsets the rate there); 6.0 and 9.0.2 pass. Adding `fps=24` before
xfade fixed 7.0 but changed frames at a loop seam, so it was not shipped. x264 output can differ in
the last bits between any two runs on ffmpeg 9 (PSNR 64–81 dB), so the parallel test compares PSNR.

## v0.4.49: CTA places and lengths, Stickers, Adjust crop, keyframes

User asked for four things in one release (all agreed in an ask_user round):
1. **CTA timing**: "My CTA .MOV only knows the entry point … it lingers to the next scene."
   `cta.spots(project)` (mirrored by `ctaSpots` in `web/src/cta.js`, tested equal) lists every
   place: chapter heads ∪ narration containing "subscri" ∪ old `cta: true` scenes (key `"s:<scene id>"`),
   plus `cta.extra` = places added at the playhead (`{id, start, …}`). Each has `on`, `nudge`
   (−30..30 s), `length` (0.5..15 s or None = the animation's own length) and `scene_end`. Only the
   first found place is on by default (as before). start = scene offset + cue_start + nudge; end =
   min(start + min(natural, length), scene end if scene_end, total). A place overlapping the previous
   shown one is skipped and the UI says "overlaps the one before". When cut short it **fades out**
   (`fade_out_seconds` = min(spec, length/3)); the export fades the overlay at the export frame rate
   (`fps=24` before `fade`, so a 12/25 fps .MOV fades smoothly through a scene cut — tested with a
   ProRes 4444 alpha .mov). `cta.x` (left↔right) is new. UI: Effects → "Where it shows".
2. **Stickers** (`stickers.py`, `web/src/stickers.js`, StickerDialog/StickerPanel/StickerLayer):
   `project.stickers = [{id, kind, asset_id?, start, length, x, y, size, opacity, keyframes}]`
   (x/y centre, size = fraction of frame width, keyframe t relative to the sticker start). Built-ins are
   drawn with PIL (`CATALOG`; animated ones cycle at 24 fps), served as
   `GET /api/stickers/{kind}/{frame}.png`, "Yours" = uploaded images flagged `asset.sticker`. Stickers
   show at once (no fade in, so they appear where they were added) and fade out briefly at their end.
   Drag in the preview; −/+ in the Stickers inspector tab; "Stickers" button on the monitor.
3. **Adjust crop** (`picture.py`, `web/src/picture.js`, CropDialog, PictureLayer): the crop belongs
   to the media file, `asset.crop = [x0, y0, x1, y1]` (normalised; whole picture = key removed).
   `POST /api/projects/{id}/assets/{aid}/autocrop` finds black bars / plain borders (images and
   videos). Each scene picks `scene.fit`: "cover" or "blur" (photo centred over a darker blur of
   itself). **A cropped file defaults to "blur"** unless the scene picks cover; 9:16 projects keep the
   old blurred background ("legacy-blur") when the scene has not chosen. Scene motion runs after the
   fill. Base-fill scenes are ordinary scenes, so the crop applies to them too (tested).
4. **Keyframes**: `scene.keyframes = [{t, zoom, x, y, ease}]` (x/y = view centre) replaces the fixed
   motion; sticker keyframes `[{t, x, y, size, opacity, ease}]`. `picture.interpolate` /
   `interpolate` in JS are the same (linear or smooth), FFmpeg gets `picture.expr` (tested by
   evaluating the expression in Python against the JS values).
Tests: `tests/test_overlays_v049.py` (18, incl. real renders), `tests/js/picture.test.mjs`. Full suite
482 passed, 1 skipped; JS 34 pass. Checked in Chromium (Playwright + @sparticuz/chromium): CTA places,
length/fade label, add at playhead; sticker add, drag (moves exactly with the mouse), −/+, upload;
Automatic crop, drag a corner, save; fill select; picture keyframe — no page errors.

## v0.4.50: sharp CTA .MOV in the edit preview

User: "Why is the CTA .MOV not sharp… low quality? Is that from the engine or do I have to render first?"
Measured (1920x1080 ProRes 4444 alpha test file with small text and 1 px lines):
- **Export was already sharp**: original file, lanczos to the card size, x264 CRF 20; 33.8 dB vs the
  file composited perfectly (40.1 dB is the yuv420p ceiling), visually identical. Unchanged.
- **The edit preview was soft**: since v0.4.47 a transparent .MOV is shown as WebP stills, which were
  ≤640 px wide, 15/s, lossy q80 (4:2:0, smears red edges). The CTA (size 0.62) is drawn ~950 device
  px wide on a Retina monitor and ~1800 fullscreen, i.e. 1.5x / 2.8x enlarged.
Fix (`renderer.preview_frames`, v2 stills, `cta.preview_version` in effectsSpec.json):
- a quick pass at 480 px finds the part of the frame the animation ever draws on (alpha > 0, union
  over all frames, small margin; whole frame if never transparent): `box` as frame fractions;
- that part is cut at the file's own resolution (≤ PREVIEW_MAX_PIXELS = 1280x720 per still), 24/s
  (the export rate), streamed from ffmpeg as raw RGBA (no PNGs), saved **lossless** WebP; once a still
  is > 400 KB (noisy/photo-like) the rest of that file is lossy q80; encoded on ≤4 threads.
- CtaOverlay `FramesCta` places the still with `ctaStillBox(card, frames)`; URLs carry `?v=<version>`
  so cached old stills are never reused; FileCta asks `POST …/preview` once for old (version < 2)
  stills, which the endpoint now remakes (old ones show meanwhile).
Numbers (2-vCPU sandbox): typical CTA 1.4 s, 0.24 MB for 48 stills; fullscreen Retina 31.2 → 41.7 dB,
monitor 33.4 → 36.3 dB vs the real file. Worst case (15 s full-frame 1080p noise): 72 s / 44 MB (old
code 41 s / 2.8 MB); ~27 s of that is just decoding the ProRes. Browser check (Chromium, DPR 2): old
stills shown, one POST, swapped to 904x212 v2 stills placed exactly per `box`, no errors.
Known, pre-existing: overlays are laid out from `frameSize` (the frame incl. its 1 px border) inside
a layer 2 px smaller, so every overlay sits ~1 px off in the preview (0.3%); exports unaffected.
Tests: test_cta_file.py (sharp lossless stills, opaque file = whole frame, pixel budget, old stills
remade), tests/js/cta.test.mjs. Suite 484 passed, 1 skipped; JS 35 pass.

## v0.4.51: Undo and Redo for every edit

User: "Now we need to work on the undo and redo button." Before: no redo; 8 steps; only script/scene
edits and a few actions made a step (CTA, stickers, crop, effects, watermark, caption style… could not
be undone); undo jumped the playhead to 0:00; the 8 whole copies lived inside the project file
(Bismilah: 15.9 MB of its 18.4 MB, written on every save and sent to the browser after every edit).
Now (`history.py`; `storage.checkpoint(p, label)` begins a step, `storage.save_project` finishes it):
- **Every edit** is a step: every PATCH field, asset PATCH (crop, rename), reuse-timings, the action
  endpoints (named: "Build timeline", "Upload", "Delete media", "Approve script", "Build episode"…),
  "Direct your edit", and a whole Make-video run as one step. Nothing changed (incl. only the guide
  rebuild's `plan.built_at`) = no step. Sources, exports, messages are not undone (approval safety).
- Only what changed is stored: whole fields; scenes by id; assets by id and only `name/license/crop/
  sticker` (`ASSET_KEYS`, so remade preview stills/thumbnails never come back old); episode by key.
- Steps live in `data/history/<id>.json` (git-ignored; deleted with the project; not in exports,
  downloads, recovery backups). The project keeps only names: `project.history = {undo:[…], redo:[…]}`.
  50 undo steps (`LIMIT`), 40 MB cap. A new edit clears redo. The same control again within
  `MERGE_SECONDS` 1.5 s (−/+ clicks, typing, a slider) merges into one step; an edit that returns to
  where it started removes the step. v0.4.50 `undo` copies become "Earlier edit" steps on first load.
- Names come from the change: "Scene 4 · title card", "Move sticker", "Resize CTA", "Crop · photo.jpg".
- `POST /undo`, `POST /redo` (400 when empty). Approval is cleared if the restored script no longer matches.
Front end: Undo + Redo buttons ("Undo: Move sticker (⌘Z)"), ⌘Z / ⇧⌘Z / Ctrl+Z / Ctrl+Shift+Z /
Ctrl+Y (ignored only while typing in a text box; works after clicking a button or slider), pending
edits saved first, playhead stays, toast "Undone: …". The timeline trim drag saved on every move: it
now saves once on release (`gesture` ref), so a drag is one step (stickers/CTA/captions already did).
Found while testing on Bismilah (pre-existing, fixed): every scene save on a guide project rebuilds
the timeline, which (a) gave all scenes new ids (the editor lost the selected scene; undo saw 158 new
scenes) → `episode.keep_scene_ids` keeps the id of the same scene (scene_key); (b) reset "Show scene
title" (not in OVERRIDE_FIELDS) → added. Note: the first save of an old guide project also settles its
inspection flags (`inspection_only`, `source_window_basis`) — that rides along in that first step.
Speed (Bismilah, 158 scenes): edit 0.3 s, scene edit with rebuild 0.45 s, undo 0.2 s; project file
1.9 MB + history 1.5 MB; responses 1.2 MB (were ~11 MB).
Browser check (Chromium, copy of Bismilah in CASEFILE_DATA_DIR): toggle → "Undo: Scene 4 · title card",
Ctrl+Z / Ctrl+Shift+Z / buttons / Ctrl+Y, playhead stays 00:14:07; 6 s slow trim drag = 0 saves during,
1 on release, 1 step. Tests: tests/test_history.py (12). Suite 496 passed, 1 skipped; JS 35 pass.

## v0.4.52: Motion graphics (stage 1 of the "Intelligent Cinematic Motion Graphics Engine" spec)

User: a friend's spec ("Storyroom" = Casefile) — "This is it… let's make it work with Casefile spec".
Constraints kept: Python + Pillow/NumPy + FFmpeg only (no Remotion/Node/JS renderer, no paid APIs, no
cloud), fully offline, **off by default**, never changes narration, soundbites, source timestamps,
footage ids, clip ranges or the timeline; never invents case imagery or words.
`motion.py` (new; spec block `"motion"` in web/src/effectsSpec.json; Oswald fonts, SIL OFL):
- Data `project.motion = {enabled: False, items: [...]}`; item = template (findings | timeline |
  contrast | legal), status (suggested | draft | approved), start/end (timeline s), heading, title,
  layout, lines [{text, label, kind, emphasis, at}], background (charcoal | footage | photo from the
  project's own images), dim, font, size, accent, text_color, align, x, y, speed, enter, exit,
  hide_captions, source, reason. `normalise` clamps everything (limits in the spec). Only
  `status == approved` items render, and only while `enabled` (`exported()`).
- Word sync: `timeline_words` maps the narration's words to timeline seconds — guide projects from
  `episode.timings.words` (exact, via each scene's audio_start), else each caption's words spread over
  it, else the scene's narration over the scene; soundbites (`insert_audio`) have no words.
  `sentences()` (handles "p.m. Trial…" vs "3 p.m. on Friday"). Each line's `at` = when the narrator
  starts that sentence.
- `draft(project, template, start, end)`: lines are the narration's own sentences (never cut — the
  layout shrinks instead); timeline lifts a date/time out only when it opens the sentence, ranges
  "2:41–3:27 P.M.", inherits a.m./p.m.; legal labels from LEGAL patterns (none if none — never made up);
  contrast kinds statement/finding (+ emphasis on "but/however/never…").
- `suggest(project)`: reads every chapter; windows of 2–7 consecutive narration sentences (8–45 s),
  no soundbite inside; skipped: cold open/hook, first/last 8 %, CTA places ±2 s, soundbites ±1 s,
  emotional/family/tribute words, a sentence ending ":" (introduces a speaker), any sentence too long
  to show whole. Scores timeline (≥3 dated events), legal (≥2 outcomes), contrast (stated vs records
  with a contradiction word, **never courtroom arguments** — prosecution/defense/jury passages are not
  shown as "found"), findings (≥3 investigative sentences). ≥75 s apart, ≤5, ≤2 of one template;
  none when nothing qualifies. Bismilah (15 min): 3 (CCTV timeline ch.3, surveillance findings ch.5,
  escape ch.8); trial contradiction correctly rejected; legal outcome sits in the closing guard
  (user can make it manually).
- Drawing (`build` places elements, `frame(lay, n)` draws one RGBA frame): charcoal background with
  soft light, vignette, faint smoke and a slow accent glow (steps of 1/6 s), or the footage darkened
  (gradient on the text side), or a blurred project photo with a slow push-in. Heading with bar,
  masked title rise, divider wipe, per-line reveals (mask / slide with motion blur / fade), bullets
  pop, timeline red line grows to each dot, legal tags (ALLEGED outline grey, CHARGED/ARRESTED
  outline, PLEA/VERDICT/CONVICTED solid red, SENTENCED solid light, ACQUITTED/DISMISSED grey), exit
  last-in-first-out then background out. Auto-fit: shrinks until inside the frame and nothing cut.
  16:9 and 9:16. ~20 ms per 1080p frame (+ PNG encode at export).
- Identical frames drawn once (`plan`: frame key = background alpha/phase + every element's state).
- Cache by content: `data/cache/motion/<item_hash>/` (ENGINE, item minus status/id, size). Export
  `prepare()` draws only missing unique frames (≤4 threads), hard-links `mgN/%05d.png`; `prune` keeps
  it ≤2 GB. `overlay_filters` = sticker pattern.
renderer.py: prepares after stickers; per scene overlays after CTA + stickers, before the watermark
and captions (logo and captions stay on top); `hide_cues` takes captions out of a graphic's window
(`write_ass(…, hide=)`); report line "motion graphics xN (new drawings, from the cache)"; warning
if a graphic overlaps the subscribe animation. The SRT sidecar is unchanged.
app.py: PATCH `motion` (normalised); `GET …/motion/narration` (sentences + times), `POST …/motion/draft`
(not saved), `POST …/motion/suggest` (replaces unapproved suggestions; one undo step), `POST
…/motion/plan` (preview frames list; warms in the background, paused while an export runs), `GET
/api/motion/<hash>/<k>.webp` (on demand, ≤2 drawings at a time). history.py: field `motion`, names
"Suggest 3 motion graphics", "Approve motion graphic", "Motion graphic text/timing/style", "Motion
graphics on"…
Front end: inspector tab **Motion** (`MotionPanel.jsx`): "Add approved graphics to the export"
(off), "Suggest from the narration", "New from a passage" (template + click first/last sentence near
the playhead), list with status badges and "why here", Play it / Approve / Unapprove / Regenerate
(keeps style) / Reject / Remove, template + layout, heading/title/line text, labels (legal list,
dates), statement/finding + emphasis, per-line "set to playhead", add/remove lines, start/end, speed,
entrance/exit, hide captions, background/photo/darken, font, size, accent/text swatches, align, x/y.
`MotionLayer.jsx` draws the server's frames on a canvas (1280 px WebP, 24 fps, preloads 2 s, keeps
the last frame until the next arrives). The preview shows the selected graphic (tagged "Preview · not
approved") or the approved ones; captions hidden as in the export; timeline marks (striped =
unapproved, solid = approved).
Measured (2-vCPU sandbox, 60 s 1080p export, 10 photo scenes, captions on): without 38.8 s (CPU
ffmpeg 60 s, python RSS 58 MB); with 2 graphics (30 s timeline + 16 s legal) first export 80.3 s
(+36 s python drawing 447 unique frames, RSS 235 MB); same again 44.2 s (0 drawn); one title edited
52.4 s (only that graphic redrawn); cache 120 MB. Headless Chromium note: the canvas paints black with
GPU canvas; use `--disable-gpu --disable-accelerated-2d-canvas` for screenshots.
Demo: `casefile-studio/qa/motion-graphics-demo.mp4` (720p, 63 s, all four templates, Bismilah
narration verbatim, neutral background — made with the real export).
Next stages (not done): more layouts per template, suggestions tuned per chapter type, a background
render worker for long graphics, 2K/4K (Casefile exports ≤1080p).
Tests: tests/test_motion.py (27). Suite 523 passed, 1 skipped; JS 35 pass.

## v0.4.53 — Motion graphics, stage 2

Still optional and off by default; scenes, narration, soundbites, source timestamps, footage ids and
clip ranges are never touched. No new dependencies.

**More layouts** (`effectsSpec.json` motion `layouts`, version 2): findings stack / split / centre /
**cards** (numbered, two columns when wide) / **focus** (one finding at a time, large, counter +
progress strip); timeline across / down / **focus** (one date at a time in large type, a strip with
every date below); contrast columns / rows / **quote** (what was said as a quotation, then "THE
RECORD"); legal list / **steps** (tags on a line across) / **verdict** (earlier steps small, the
outcome in large type). `layouts_tall` maps wide-only layouts to their upright counterpart in 9:16.
`motion.resolve_layout(item, tall)` resolves "auto" (legal with a final outcome → verdict);
`layout_options` lists the layouts that look different for an item; `vary_layout` gives a second
graphic of the same template another layout (suggestions and new drafts in `POST …/motion/draft`).
One-at-a-time layouts use `El.early` (an element leaves before the next line comes in).
Fix: the exit stagger now fits in a fixed time (with many wrapped lines the last pieces were still on
screen at the end of the graphic — also in v0.4.52).

**Smarter suggestions.** `chapter_kind(title)` → opening | victim | closing | legal | statements |
investigation | chronology | general. Chapters about the victim/family ("…AND THE PEOPLE AROUND
HIM", "A FAMILY'S APPEAL", "REMEMBERING…") get no graphics; chapter type adds to the score
(chronology → timeline, investigation → findings, statements → contrast, legal → legal; findings in
legal chapters −2). **Legal outcome** (`_outcome_candidates`): a sentence that tells an outcome
(`OUTCOME`: pleaded guilty, found guilty/not guilty, sentenced … to, charges dismissed; never with
`HYPOTHETICAL` words — faced, asked, sought, could, would, argued, a question) anchors a legal graphic
that may sit in the protected closing (not in a soundbite, the CTA, an emotional sentence or a victim
chapter). `draft("legal")` on a passage with an outcome recaps the steps already told
(`_milestones`: the first charge — or arrest when no charge —, earlier outcomes; outside the cold open;
verbatim; never cut) — they come in one after another (`RECAP_STEP` 0.7 s) and the outcome appears on
its spoken word. One recap for the final outcome (another only ≥ `recap_gap` 180 s earlier). It
returns to the footage before the next emotional sentence (≥1.2 s after the outcome is said).
Fix: CHARGED pattern `counts? of` matched "accounts of" → `\bcounts? of`.
Bismilah now: timeline APRIL 17 (191 s), findings WHAT SURVEILLANCE SHOWED (355 s, split), findings
ESCAPE, SEARCH AND RECAPTURE (516 s, stack — varied), **legal SENTENCING 843.6–851.3 s: CHARGED
("…announced a first-degree murder charge"), CONVICTED (744.8 s sentence), SENTENCED at 847.1 s
("Goudie sentenced Moore to fifty-five years…")**.

**Footage stills as backgrounds.** Background `still` + `still_at` (timeline seconds, default the
graphic's start). `footage_at(project, t)` maps the timeline to the source exactly like the export
(scene asset, trim_start, source_crop_end, looped crop; a picture is itself; gaps/cards → None).
`background_path(project, item, data, asset_path)` returns the photo, or a JPEG still taken once with
FFmpeg into `data/cache/motion/stills/` (keyed by file, size, mtime, time); None → charcoal (nothing
made up). The picture path is part of `item_hash`. Used by app (`_motion_photo`) and renderer.

**Faster export.** `motion.encode()` draws each unique frame once and pipes raw RGBA to FFmpeg →
one lossless transparent QuickTime Animation video per graphic (`qtrle`, argb, GOP 24) cached as
`data/cache/motion/<hash>/export.mov` (no PNG files). `overlay_filters` reads it with `-ss` half a
frame early (exact to the frame — tested by pixel equality) and `-t`. Drawing threads: 1 on ≤4 CPUs,
2 above; read-ahead workers+1 (measured: a second thread on 2 vCPUs added ~180 MB and no speed).
`ENGINE = 3`.
Measured (same 2-vCPU sandbox, same run, 60 s 1080p, 10 photo scenes, 30 s timeline + 16 s legal,
captions off; v0.4.52 code from main vs this):
| run | v0.4.52 | v0.4.53 |
|---|---|---|
| no graphics | 22.3 s | 22.0 s |
| first export | 62.8 s (drawing 33.8 s, python CPU 34.2 s, RSS 233 MB) | 39.3 s (drawing 11.6 s, CPU 9.4 s, RSS 237 MB) |
| again (cached) | 29.6 s | 25.4 s |
| one graphic edited | 43.1 s (13.1 s drawing) | 28.5 s (3.8 s) |
| cache | 161 MB | 94 MB |
(The v0.4.52 numbers in its section were another sandbox and captions on.) PNG encoding was the cost:
57 ms per 1080p frame vs 19 ms to draw.

**Editor.** "Another layout" (cycles `plan.layouts`; the plan now returns `layout`, `layouts`,
`background`); Regenerate takes another layout when the words come out the same; the Layout menu shows
what "Automatic" resolves to; a colour picker next to the accent/text presets (commits 350 ms after you
stop); background "A still from your footage" with "Still from" + "set to playhead" and a note when no
footage plays there. `planFor` is exported from `MotionLayer.jsx` (one request shared with the preview).
Fixed during QA: the Motion tab crashed with no graphic selected (`undefined === undefined`).

Demo: `casefile-studio/qa/motion-graphics-layouts-v0.4.53.mp4` (720p, 54 s, the six new layouts;
Bismilah narration, the contrast sample is the fictional test text — labelled SAMPLE).
Tests: tests/test_motion.py now 66 (+39: chapter kinds, outcome strictness, the recap on a synthetic
case and on Bismilah, victim chapters, every layout × 16:9/9:16, one-at-a-time, layout variety, footage
stills with a generated video, frame-exact export video). Suite 562 passed, 1 skipped; JS 35 pass.
Browser (Chromium 131, GPU off): suggest → 4 incl. the legal outcome; Automatic shows "(outcome in
large type)"; Another layout → list; colour picker → #1f8a8a saved; still background → the no-footage
note (the sandbox has no media); undo; no page errors.
Not done: footage stills were verified with generated test video only (no real footage in the
sandbox); 2K/4K.

## v0.4.54 — Exports with transitions work on FFmpeg 7

**The failure (user report, Docker on Apple Silicon, v0.4.53):** "Make updated draft video" and "Make
final video" both stopped with `[Parsed_xfade_13] The inputs needs to be a constant frame rate;
current rate of 1/0 is invalid` → "Error reinitializing filters!" → "Nothing was written". Any scene
with a transition failed. **Cause, from the FFmpeg source:** `setpts` sets the output frame rate to 1/0
unconditionally in FFmpeg 7.0 and 7.1.x (`libavfilter/setpts.c`; 8.0 made it the `strip_fps` option,
off by default), and `xfade` refuses 1/0. The scene step renumbers frames with `setpts=N/24/TB` right
before the blend. The Dockerfile installs Debian's ffmpeg (python:3.13-slim → 7.1). The sandbox has
6.0, so it never showed. Reproduced with a static 7.0.2 (`pip install imageio-ffmpeg==0.6.0`). 7.0.2 →
7.1 changes to setpts/xfade/fps/settb are only the FilterLink API rename (diffed the sources).

**Fix (renderer.py, scene step):**
* `[pic0]`: `…,settb=AVTB,setpts=N/24/TB,fps=24,settb=AVTB` — fps states the rate again (the
  timestamps are already 1/24 apart, so no frame dropped or repeated); settb puts back the time base
  xfade compares between its inputs.
* `[prev]` (the previous scene's last frame): `…,format=yuv420p,settb=AVTB` — no setpts, no fps.
  `-loop 1 -framerate 24` already numbers it. **Do not add fps= here:** FFmpeg 6's xfade treats the
  blend as over as soon as its first input *reports* EOF (vf_xfade.c, `ff_outlink_get_status`), and
  fps= reports EOF together with its last frame — the 12th blend frame was dropped and the rest of the
  scene stamped one frame late (found by showinfo; the final MP4 still had the right frame count, so
  only a raw-frame timestamp check catches it).
* Video scenes: `tpad=stop_mode=clone:stop=24` after `fps=24,setpts=PTS-STARTPTS`. Separate, older
  bug (FFmpeg 6 too): a looped crop (or a clip used to its last frame) shown "over a blur of itself"
  came out one frame short — the blur's overlay ends the stream at its last frame's *start*, so fps=
  produced 71 of 72 frames and every later scene ran 1/24 s early. `-frames:v` still cuts each scene to
  its length. (`stop_duration=1` does NOT work under `-frames:v` on 7.0.2 — use the frame count.)

**Verified:** 3 FFmpeg builds (6.0, 7.0.2, 9.0.2) × fit cover/blur × video 30/25 fps, looped crop,
photo still/zoom/keyframes, VISUAL NEEDED card, with a look + vignette + grain + letterbox: every export
24/1 fps and the exact frame count; every transition type on 7.0.2. Against v0.4.53 on FFmpeg 6.0 the
blended picture is identical except transition frames 1, 4, 7, 10 (≤2 of 255 levels on ~0.5% of
pixels: the microsecond time base rounds 41666.67 µs differently), so the encode differs at ~47–51 dB.
**Tests:** `tests/test_transition_rate.py` (16 on the PATH ffmpeg; set `CASEFILE_EXTRA_FFMPEG=dir:dir`
to also run them on other builds — 46 with 7.0.2 + 9.0.2). Checks the command (rate stated after the
last setpts, prev untouched), the blend's RAW frame timestamps 0..n-1 per picture kind, every
transition, and the looped crop. On the v0.4.53 renderer 15 of them fail (all 7.0.2 renders + the
looped crop with blur on 6.0); with fps= on [prev] 7 fail on 6.0. Full suite 578 passed, 1 skipped on
6.0 **and** on 7.0.2.
Not done: no 7.1/8.x binary can be downloaded in the sandbox (GitHub release assets are blocked); 7.1
covered by the source diff above, 9.0.2 by tests.

## v0.4.55 — approved motion graphics missing from the export (photo backgrounds)

**Report:** "the approved motion graphics do not render with the video" (project with 5 approved
graphics, 1080p export; preview showed them). The export record carried the warning
`The motion graphics were left out: box offset can't be negative`, which the UI never displayed.

**Cause (motion.py `frame()`):** a photo/still background is fitted once to `int(W*1.08) x int(H*1.08)`
(`build`), but each frame cropped a box `W*1.08/z` wide around the centre. At the first frames
(z = 1 → ~1.0003) the box was a fraction of a pixel wider than the photo (1920 → photo 2073 px, box
2073.6 px: offset −0.3), and Pillow ≥ 11 raises `ValueError` for a negative box offset. Any W where
W*1.08 is not a whole number (1920, 1280, 854, 640, all portrait sizes) failed on frames 0..~15.
* The **export** draws frame 0 first → exception → `renderer.py` dropped **all** graphics (the whole
  preparation was one try block), including the footage-background ones that were fine.
* The **preview** asks for frames one by one; the few failing first frames (during the background
  fade-in, 4–16 frames) just 404'd and the layer kept the previous picture, so it looked right.
* Earlier tests missed it: the still-background test draws frame 48, and render tests used footage or
  charcoal backgrounds.

**Fix:**
* `frame()`: the crop is `photo size / z`, clamped to the photo.
* `motion.prepare(..., failed=[])`: a graphic that cannot be drawn is skipped on its own and reported
  as `(item, error)`; the others are still made. A cancel is never swallowed; without `failed` it
  raises as before. `renderer.py` turns each into a warning naming it (`motion.describe`: template,
  title, m:ss), and drops its caption gap.
* Warnings are shown: under each export in Review (`.export-warnings`), in the "export ready" toast
  (error tone with a count), and in `render-report.txt` ("Warnings:" section; `timing["warnings"]`).

**Verified:** the user's 5 exact items (from their project JSON, with a 1920x1080 photo) draw every
frame at 1920x1080 and at the preview size (before: both photo items failed at frame 0). 1080p
end-to-end on FFmpeg 7.0.2 with a photo-background legal graphic + a footage one: both in the MP4,
no warnings. **Tests** (`tests/test_motion.py`, +24): photo background from frame 0 at 7 sizes × 3
photo shapes; a failing graphic leaves the others (prepare and full render, warning text checked);
report lists warnings. All 22 photo tests fail with the old crop. Full suite 602 passed, 1 skipped;
JS 35 pass.

## v0.4.56 — intelligent cinematic sound design (optional, off by default)

**Request:** a friend's "Intelligent Cinematic Sound Design Engine" spec, "make it work with Casefile specs":
a local library, context-aware placement from the real timeline, frame-accurate sync, a mix that keeps
speech first, strict authenticity rules, an editor UI, presets, tests, demos and benchmarks; no
Remotion/Node/cloud; never change narration, soundbites or the timeline. Full write-up:
`casefile-studio/SOUND-DESIGN.md` (inventory, licences, demos, benchmarks, limitations, usage).

**What was built**
* `sfxlib.py`: 78 procedural sounds (NumPy, fixed seeds, 48 kHz stereo) in 27 categories, cached as
  WAV in `cache/sfx/lib-1/`. No downloads, no third-party licence. Shutter is manual-only; no gunshot,
  scream, siren or voice exists.
* `sound.py`: settings (`normalise`), events from approved motion graphics (`motion.sound_events`, the
  frame each element is first drawn; typed characters), transitions, chapter starts, narration
  outcomes/discoveries/contradictions on the word, CTA keyframes, documents; protected zones (soundbites
  ±0.6 s, victim chapters, sensitive pictures, sensitive sentences ±0.8 s); the planner (priority vs
  density, spacing per category, per-minute cap, shared sound per graphic, least-recently-used variation
  seeded by project id); `effective` (auto = fresh plan + your decisions; manual = stored only);
  `resolve` (anchors → times; `gone` with reasons); the stem (sample-accurate, soft-limited FLAC,
  content-hashed cache); `mix_filters` (sidechain duck under the voice; `alimiter level=disabled
  latency=1` — the default alimiter adds 0.45 dB and a 239-sample delay).
* Anchors: `mg:<gid>:<role>:<k>`, `tr:<scene>`, `ch:<scene>`, `doc:<scene>`, `mo:<scene>:<sec>`,
  `cta:<key>:enter|click|bell|exit`, `sc:<scene>:<sec>` (added at the playhead), `t:<sec>`. Custom sound
  ids `a:<assetId>` (upload role `sfx`, ≤ 30 s, returns before any timeline rebuild).
* A decided sound (edited, moved, removed) is not planned again but **holds its original moment and
  category** in the planner (`_held`), so editing one sound never adds, drops or moves another. Found in
  the browser: before this, a new variation of a marker tick brought back a second tick on the same frame,
  and moving it left a new one where it was. A manual sound makes a planned one at the same moment step aside.
* `motion.py`: `El.role`, the **Typewriter** entrance (`type_chars`, 17 cps with a repeatable uneven rhythm,
  a cursor), `sound_events`. Other entrances draw exactly as before (ENGINE stays 3; the cache key includes
  the item).
* `renderer.py`: stem at progress 93, effects mix branch, `sound_effects` in the report, warnings for
  sounds left out. `app.py`: PATCH `sound`, catalog, library WAV, plan, generate, custom WAV, upload `sfx`.
  `history.py`: undoable with named steps.
* UI: inspector **Sound** tab (`SoundPanel.jsx`, `sound.js`): enable, preset, auto/manual, plan again,
  mute/solo (preview only), mix sliders, per-kind switches, plan list with reasons, silenced list, per-sound
  editor (audition, in context, another, remove/restore, reset, replace, volume, move, fades), library
  browser, import. **Sound FX** lane (A3) with draggable marks and hatched protected zones. WebAudio preview
  on the editor clock (no ducking in preview). Inspector tabs auto-scroll; the timeline lanes scroll so
  the extra lane is reachable.

**Verified**
* 7 before/after demos rendered by the real exporter (`qa/sound-design/`, `demo-report.json`): sync of
  isolated transients ≤ 2.5 ms, typing keys median 0.3 ms / p95 6.7 ms, export vs stem 0.0 ms, loudness
  change ≤ 0.1 LU, no sample at full scale, interview demo after = before.
* Narration sample-identical with effects on (0 lag, RMS within 0.001 dB).
* gg benchmark (231 scenes, 18.4 min): plan 0.09 s, one edit 0.30 s, full stem 2.96 s (0.73 s CPU),
  peak 88 MB.
* Browser (headless Chromium): Sound tab, plan list, per-sound editor, audition requests, Another (only
  that sound changes), drag (+10 frames, nothing else changes), Ctrl+Z, library add at playhead; no page
  errors.
* Tests: `tests/test_sound.py` 17, `tests/js/sound.test.mjs` 4. Full suite 619 passed, 1 skipped; JS 39 pass.
* `tests/conftest.py`: the `isolated` teardown now waits for the motion preview warm thread before removing
  its folder (pre-existing race in `test_api_motion_flow`: "Directory not empty" in `cache/motion`, a
  `qa/test-*` folder left behind). 3/3 reruns clean.

**Not done / limits:** rule-based understanding (regexes + structure), no ducking in the preview,
`SENSITIVE_PICTURE` is broad (protects e.g. "vehicle registered to … mother"), the first plan after a
server start lays out every approved graphic (~0.65 s each). Tuning ideas: narrower picture rule, fewer
document/photo sounds by default.

## v0.4.57 — sound design corrections (narration level, select several, preview ducking, context, library v2)

**Request:** narration volume control; "select all" on a motion graphic so one sound applies to the whole
part; and before final approval of v0.4.56: preview/export ducking parity, contextual (not keyword)
decisions, a quality review of all 78 sounds (improve, don't add), playable demos, sync verified through
edits, no new dependencies, targeted fixes only. **Not finally approved yet** — the user reviews the demos
first (`casefile-studio/qa/sound-design/index.html`). Write-up: `SOUND-DESIGN.md` ("v0.4.57 corrections").

**What changed**
* `renderer.py`: `voice_graph()` (the voice bus, factored out unchanged so the duck curve uses the exact
  same filters) and `narration_volume` (0–2, after loudnorm). `app.py`: PATCH/validation, render option,
  `GET /api/projects/{id}/sound/duck`. `history.py`: field + "Edit N sound effects" for bulk edits.
* `sound.py`: `context()` scores sentences and pictures (sentence evidence by whose family / charge vs
  violence / case record, neighbours in the same chapter, chapter kind, story role, picture bucket, title,
  what is said over it); `protected`/`events` use it; `_evidence` is lru-cached. Duck curve: `_duck_job` /
  `duck_curve` (sidechaincompress on aevalsrc=1 keyed by the voice bus → uint8 at 200/s, cached under
  `cache/sfx/duck/`); one FFmpeg job per project (`_DUCK_LATEST`/`_DUCK_PROC`, obsolete jobs killed, nice 10).
* `sfxlib.py`: LIB_VERSION 2 (`cache/sfx/lib-2/`), SEED_VERSION 1 (unchanged recipes are bit-identical);
  66 sounds rebuilt with new helpers (`_room`, `_tail`, `_partials`, `_saw`…), 12 unchanged, levels
  compensated (RMS within 1.5 dB of v1 except type-strike-6/key-soft-6, lighter on purpose).
* UI: `SoundPanel.jsx` "Apply changes to" (this / every line / whole graphic; `scopeItems`/`editItems` in
  `sound.js`), lane highlight (`onSelectMany`, keyed by ids), duck note; `main.jsx` duck effect (polls
  `/sound/duck`, keeps the previous curve while working), narration slider (Audio tab + Sound → Mix).
* QA: `library_audit.py`, `make_page.py` (index.html, demo-reel.mp4, library/v1|v2 MP3s,
  library-audit.json), `make_demos.py` adds `exact_placement_error_ms`.

**Verified**
* Duck curve vs export gain: median 0.02 dB, p95 1.0, max 2.3 dB (nv 1.0); max 0.48 dB (nv 0.4).
* gg context diff: planned 36→37, silenced 119→99 (pictures 21→59, text 98→40); suspect's-mother lines no
  longer silenced; grief/violence lines still are.
* Demos re-rendered with v2: exact placement 0.0 ms for all 102 sounds/keys, export vs stem 0.0 ms, no full
  scale; AAC onset p95 14.1 ms on typing is a pre-echo measurement artifact.
* Benchmark v0.4.56 vs v0.4.57 same sandbox: plan 0.089→0.095 s, one edit 0.250→0.272 s, stem 2.76→2.83 s;
  everyday peak 84→90 MB. All-78 library build 3.5→7.1 s (lazy per sound, once). Duck curve 18 min ≈ 65 s
  in background (loudnorm ≈ 50 s of it).
* Browser (headless Chromium): Sound tab, scope options (3 lines / whole graphic 5), bulk replace saved to
  all 3 lines, narration slider saved 1.4, duck note, no page errors.
* Tests: `test_sound.py` 24, `sound.test.mjs` 10; full suite 626 passed, 1 skipped; JS 42.
  `test_audio_continuity` source check now reads `render` + `voice_graph`.

**Limits:** still rule-based; on long timelines the preview's ducking lags an edit by ~1 min; key
variations remain fairly similar (0.93–0.96) — variety comes from the cycle and strengths.

## Sound refinement and background music (v0.4.58)

**Request:** template-specific sound palettes synced to real animation events; fix slow narration /
music / effects / per-sound volume sliders (real-time WebAudio, save on release, no rebuilds); manual
audition (one at a time, never modifies the project); background music: loop whole / range / once /
chapters or scenes, part of a track, seamless adjustable crossfade, fades, ducking, the timeline
authoritative; efficient FFmpeg rendering (references, no copies); tests and measured performance.
**Not finally approved** — the user reviews `casefile-studio/qa/sound-design/music.html` and
`index.html` first. Write-up: `SOUND-DESIGN.md` ("v0.4.58").

**What changed**
* `music.py` (new): `normalise`, `layout` (runs → passes `{at, src, len}`), `gain_at`, `filters`
  (≤ 12 passes: `acrossfade` qsin chain, one `-ss/-t` reference per pass; more: one input, seam made
  once, `aloop`); all trims in samples, the bed exactly `timeline × 48000` samples. `renderer.py` uses it
  (`MUSIC_DUCK`, `music_duration`) and the transparent limiter (`SFX_LIMIT`) in every mix — the bare
  `alimiter` delayed the voices 239 samples when music played without effects.
* `sound.py`: per-template palettes (`PALETTES`, motion branch, variation, `_typing_keys` rotation);
  `_duck_job` also makes the music's curve (`.m.u8`, response field `music`).
* `app.py` / `history.py`: `music` field (PATCH, episode options, diagnostics, history label).
  `scene.narration_volume` and the per-scene `music_*` fields were never played; the per-scene narration
  "Volume" control is now the documentary's live narration level.
* Frontend: `LiveRange.jsx` (live `onLive`, one `onCommit` on release — never mid-drag — compares with the
  value at the start of the gesture); `music.js` (`MusicPreview`: two elements, live bus gain, duck);
  `MusicPanel.jsx`; the music lane (full width, runs + seams); `sound.js` (`setMaster`, `setItemGain`, plan carry-over without restarts,
  `audition`/`stopAudition`/`setAuditionVolume`, `peaks`); `SoundPanel.jsx` (library: search, category,
  lengths, waveforms, audition volume, variations with "Use"); `main.jsx` (live handlers, `scenesSig` so a
  save's new arrays do not re-fetch the plan/duck, music lane runs/seams, scene music checkboxes;
  `window.__casefileQA` hook only when a test defines it).

**Verified** (numbers in `SOUND-DESIGN.md`)
* Tests: full suite 638 passed, 1 skipped (was 626); JS 49 (was 42); `test_music.py` 11 incl. Python↔JS
  layout/gain parity (< 1e-9), 25-min loop exact length, aloop = chain, full render.
* Browser (headless Chromium, 25 min / 150 scenes, playing): input → gain ≈ 0.4 ms; 0 saves during drags,
  1 after; audition one at a time, 0 project requests.
* Demos (`music_demos.py`, `--old` renders "before" with the v0.4.57 exporter from `git archive c6ec51e`):
  durations = timeline; seams −0.3…−1.3 dB (v0.4.57: +2.3 dB jumps); voices 0 samples / corr 1.0 vs v0.4.57.

**Limits:** preview seam timing within ~0.2 s (export exact); exact duck on 25 min / 150 scenes ≈ 3.4 min
in the background (mostly the existing per-scene voice bus); "scenes" music follows scene ids.

## Pre-approval corrections (v0.4.59)

**Request:** after conditional approval of v0.4.58 for practical testing: (1) faster ducking analysis
without changing the audio, never a full analysis for a volume change; (2) preview/export loop timing;
(3) chosen-scene music must survive reorders/edits/replacements; (4) a sound set for every
motion-graphics template; (5) audition and live sliders verified in real playback; (6) music never
changes the timeline's length; and "audio manual overlay missing?" (= the manual SFX). Targeted fixes
only, no new dependencies. **Not finally approved.** Write-up with all numbers: `SOUND-DESIGN.md`
("v0.4.59").

**What changed**
* `sound.py`: `_duck_job` returns `{bus, bus_key, curve}`; `_bus` makes / reuses the voice-bus level
  (FLAC in `data/cache/sfx/duck/`, `BUS_KEEP`=4, one maker per bus via `_BUS_BUSY`), the curve step runs
  the two compressors with the narration level as an exact scaling; constant 1.0 source via `aloop`.
  Typed contradiction lines keep their pulse.
* `renderer.py`: `voice_graph(..., stems=True)` (narration and soundbites as separate outputs for the
  analysis); export: with music or effects and a loudnorm'd voice, the voice bus is rendered first to
  `work/voice.wav` (pcm_f32le, `apad,atrim=end_sample`) and mixed from there — the single graph lost the
  last ~2.9 s of narration on non-guide timelines (loudnorm's tail vs the finite inputs).
* `music.py` `follow_scenes`; `storage.save_project(follow=True)` applies it (undo/redo pass
  `follow=False`) and puts `music_follow` `{followed, lost}` in that response only.
* Frontend: `music.js` (`slotGain`, `envEvents`, `syncStep`; envelopes as audio-clock automation, rate
  trimming, early `play()`); `main.jsx` (`music_follow` notice from `api()`; `PLAN_FIELDS` + `planSaved`:
  the sound plan is fetched after the save that stores the edit, never before — stale levels in the
  preview otherwise; scrub ignores a zero-width timeline); `MusicPanel.jsx` (missing scenes/chapters +
  "Forget them"); `editLayout.js` (timeline 296 px, migrates the old 262 default; `lanes: 5`);
  `styles.css` (lanes scroll vertically; `.toast.warning`, `.link-btn`).

**Verified**
* Duck bench 25 min / 150 scenes: narration-level change 103.4 → 11.2 s (sliced), 18.6 → 12.3 (guide),
  24.0 → 12.1 (inserts); volume/ducking/undo 0 s; curves within 1/255 of v0.4.58.
* Loop timing, heard (AudioWorklet): median 2–4 ms, max 8–18 ms (v0.4.58: 7.5–9.9 / 12–20 ms).
* Browser (`qa/sound-design/browser_sound_qa.mjs` + `qa_app_project.py`): 79/79 sounds heard in audition,
  manual sound saved and on the Sound FX lane, sliders 4–9 ms to gain, heard changes within ~2 dB of the
  slider (music ducking moves under it), 0 requests while dragging, 1 save, playback never interrupted.
* Export tail (`tail_check.py`): 40.0 s in all 5 cases (v0.4.58: 37.12 s in 3).
* Tests: full suite 648 passed, 1 skipped (was 638); JS 53 (was 49); build OK.

**Limits:** a scene edit still re-runs the whole voice-bus analysis (97 s sliced / 21–30 s guides, in
the background); preview timing depends on the browser's media clock; lost chosen-scene ids are kept until
"Forget them".


## Pre-approval corrections (v0.4.60)

Conditional approval of v0.4.59 → speed, sync and timeline-SFX checks. Full write-up and numbers:
`casefile-studio/SOUND-DESIGN.md` § v0.4.60. Not finally approved.

* **Ducking analysis** (`sound.py`): `_duck_job` returns `{"chain", "bus_key", "curve_pipe", "curve"}`;
  `_analyse` runs a new timeline as one pipeline (bus → FLAC on disk + s16le → both compressors) and a
  stored bus as two compressor processes side by side (`{BUS}` / `{OUT}` placeholders). Runner:
  `_popen` (nice 10 / BELOW_NORMAL_PRIORITY_CLASS), `_register` (one job per project, kills the obsolete
  one), `_finish`, `_pipeline`, `_parallel`. `_BUS_BUSY` makes a second job for the same timeline wait.
* **`renderer.voice_graph(tree=True)`** (analysis only, never the export): `_split_tree` groups the scene
  trims (~√n groups, ±`TREE_MARGIN` 2 s). Byte-identical to the plain graph; do not "simplify" it into
  merged trims (1-sample differences).
* **`RESTAMP` (export + analysis)**: `asetpts=N/SR/TB` after each scene slice and soundbite. Fixes a
  silent truncation (FFmpeg exits 0 after "Invalid data found when processing input") when a slice lies
  wholly past the end of its recording. Never rely on FFmpeg's exit code alone for completeness.
* **Timeline Sound FX** (`main.jsx` lane): double-click pins `sfxPin` (passed to SoundPanel as `pin`, its
  "+ at" adds there); selecting a mark no longer calls `setPlaying(false)`; Delete/Backspace on a focused
  mark removes it. The ruler still pauses (deliberate).
* **Music sync** (`music.js` `tick`): under 50 ms the anchor slews 10 %/tick toward the preview clock.
* **Known, not changed:** each soundbite `loudnorm` ≈ 110 MB in the voice-bus process (export pre-pass and
  analysis). Exact fix proposed (per-soundbite normalisation pass, cached as f32) pending the user's
  decision. loudnorm (70–80 s / 25 min) and the compressors (~6 s each) are the floor of an exact analysis.
* QA: `qa/sound-design/duck_bench.py [--quick]` (now with a /proc RSS sampler), `browser_timeline_qa.mjs`
  (run from a folder with puppeteer-core), `tail_check_long.py [cases] [--code DIR]`.


## Soundbite memory (v0.4.61)

Approved v0.4.60 proposal. Write-up and numbers: `casefile-studio/SOUND-DESIGN.md` § v0.4.61. Not finally approved.

* **`renderer.prepare_soundbites(project, ...)`**:
  - Each soundbite goes through `soundbite_chain` (loudnorm → `{fmt}` → `{RESTAMP}` → afade) in its own FFmpeg pass, at most `sound.SOUNDBITE_JOBS` = 2 at once.
  - Output is f32 in `DATA/cache/soundbites/`. The key includes `SOUNDBITE_V`, so bump it whenever the chain changes.
  - `voice_graph(..., prepared=True)` reads the cached files. The export pre-pass condition must include `prepared`; without it, odd-length exports were refused.
* **`sound._duck_job`** prepares soundbites before building the bus; `bus_key` is v4.
* **Bug fixed** (commit `197602b`, revertable alone): loudnorm stamps frames 0.1 s apart, so trims and fades after it cut soundbites short by up to 0.1 s. `RESTAMP` now follows loudnorm.
* **QA:** `tail_check_long.py` has `guide-12min-10-odd-soundbites[-voice-only]`; `duck_bench.py inserts` reports peak FFmpeg RSS.

## cinegfx — story-aware cinematic graphics (integrated in v0.4.62)

`casefile-studio/cinegfx/` (see its README) is the engine; it never imports `motion.py` or any app module.
`casefile-studio/cinematic.py` is the only bridge between it and the app.
- **In the app:** Motion → "Cinematic (story-aware)". The item template is `"cinematic"`.
  - `motion.normalise_item`, `describe`, `photo_files`, `preview_plan`, `preview_frame` and `prepare` dispatch to `cinematic`.
  - The classic four templates are unchanged and live side by side with cinematic items.
- **Routes:** `GET /api/motion/catalog`; `POST /api/projects/{id}/motion/options {start, end, collection}`;
  `/motion/draft {template: "cinematic", category: "auto"|key, start, end, window?, id?}` (422 with an explanation when the
  passage has no such category); `/motion/suggest {engine: "cinematic", collection}` (replaces only same-engine suggestions).
- **The server owns the content:** words, payload, timing and length (`end = start + frames_of/24`) come from the narration.
  The editor changes status, category (a remake of the same sentences, `window`), hide-captions and photo slots
  (project images only, with credit and month).
- **Back to back** (allowed since v0.4.62's selection fix): `cinematic.handoffs` runs in `motion.normalise`.
  - The next *approved* cinematic graphic covers the earlier one: it fades in fully opaque over it.
  - The earlier one gets `cut` (frames = cover start + 0.2 s): no exit fade, and no cues after the cover.
  - `suggest` shortens the later graphic's lead-in (≥ 0.1 s) so the earlier last word holds about 0.7 s.
  - The editor preview stacks both, as the export does (`graphicsAt`).
- **Timing:** each graphic holds its last word at least 1.0 s (`LAST_HOLD`) before its exit.
- **Same code for preview and export:** frames are drawn at 1920×1080 and resized (Lanczos). Export goes through qtrle via a spawn
  Pool: workers = cores − 1, at most 6, 1 when ≤ 2 CPUs or < 96 frames; override with `CASEFILE_CINEMATIC_WORKERS`.
  - The cache key covers the engine versions, the content, the size and the photo files.
  - `tests/test_cinematic.py` checks exported frames against preview frames (lossless) and parallel output against serial (identical).
- **Sound:** `sound._cine_events` sends each designed cue through `sound.plan` with its exact library id (`sid`) and designed gain.
  - Your intensity setting still offsets the gain (0 at the default 0.4).
  - One graphic is one `layer`: its own cues are exempt from the spacing between them.
  - Typed labels become one typed run at the designed key level.
  - Over a sensitive sentence or victim picture (a cue that would play), the whole graphic is treated as sensitive:
    reveals are softened (muted clicks, quieter keys) and hits are dropped. A graphic is never half loud.
- **Export encoder:** `CASEFILE_VIDEO_ENCODER=videotoolbox` uses `h264_videotoolbox` for the scene clips. It is probed with a tiny test
  encode, and if that fails the export uses libx264 with a warning. The render report names the encoder.
- **Tests:** `tests/test_cinegfx_engine.py` (20, moved from `qa/cinegfx-demos/`), `tests/test_cinematic.py` (11) and
  `tests/js/motion.test.mjs` (3).

### v0.4.63 Look of the cinematic graphics (colours and backgrounds)

- **Data:** the project look is `motion.look` = `{vary, seed, palettes: {category: set key}, accent, text, background, photo_id, dim}`;
  a graphic's own changes are `item.look` = `{palette, accent, text ("own" = the design's colour over the project's), background,
  photo_id, still_at, dim}`. Both keep only the choices made (`cinematic.normalise_look`; client `cleanLook`).
- **Resolution:** `motion.normalise` sets `item.style = cinematic.style_of(item, look)` on every cinematic item (graphic > project >
  automatic variation > the design). The plan route resolves it with the look the editor sends (`{item, look}`), so the preview follows
  an unsaved change. `style` is derived: what is sent is ignored and recomputed. It is part of the cache key.
- **Engine:** `cinegfx/look.py` (niche-agnostic): `Category.looks` declares tested sets (`palettes`, first = the approved design),
  `backdrops` it can take, `backdrop_note`, `on_accent` (colours written on the accent). `resolve()` applies the readability check
  (text 4.5:1, accent 3:1 against the background, or a darkened mid-grey over a picture; nearest readable shade of the same hue) and
  says in `notes` what it changed. `theme_for` returns the category's own Theme object for the approved colours (pixel-identical).
  Variant themes get unique names (sprite caches key on `th.name`; the legal stamp now keys on its accent).
- **True crime:** 3 tested sets per category plus the other surface (light versions of findings, timeline, contradiction; the dark
  docket for legal). Contradiction takes no picture (its columns fill the screen). A light set over a picture becomes the category's
  first dark set (legal: the dark docket). Turning: the accent must also hold white text (3:1). Findings' fade under the name is now
  the theme's background (was the navy literal = the approved bg), so a light set keeps the name readable.
- **Backgrounds:** `footage` is see-through (a dark layer at `dim`, the video shows through); `still` / `photo` are drawn into the
  frame (`files["__backdrop__"]` via `motion.background_path`, darkened, 4% push-in); not found = its own background (`plan.backdrop`).
  A see-through graphic does not cover: `handoffs` sets `cut_fade` on the earlier one, which fades out over the 0.2 s fade-in.
- **Not offered in v0.4.63:** font, text size, alignment and position. Added in v0.4.64 (below), on the user's approval.
- **Tests:** `tests/test_cinematic_look.py` (12, including an export over footage and over a photo, and a still from a real video), `tests/js/motion.test.mjs` (4).
  - The approved Javits stills must stay pixel-identical. Check with `make_demos.py --stills` against a saved baseline.
- **Demos, photo provenance and crops:** `qa/cinegfx-demos/`; provenance in `photos/sources.json`.
  - The vigil photo is cropped below faces.
  - The Freeman St photo is cropped so the No. 2 train isn't presented as the No. 5.
- **Look options page:** `qa/cinegfx-demos/make_looks.py` (add `--clips` for the 5 narrated MP4s) writes `qa/cinegfx-demos/looks/`
  with the app's own look code; serve with `qa/cinegfx-demos/serve.py` (port 8001, `/looks/`). Overview image: `qa/look-options-gallery.jpg`.
- **Kit extraction for Storyroom** comes after the user approves the integrated version (user: "not yet", 2026-11-27).

### v0.4.64 Type and layout of the cinematic graphics; crowded timeline; legal darker over pictures

- **Data:** project and graphic looks gain `font` (a `look.STYLES` key; a graphic may store `"design"`), `size` (0.85–1.15),
  `mirror` (bool; a graphic's `false` = as designed over the project's `true`) and `place` `{scale 0.8–1, x -1..1, y -1..1}`
  (a graphic's full-size place = as designed). The project keeps only non-default values. Client: `cleanLook` keeps `mirror: false`.
- **Resolution:** `style_of` adds `style.type = {font, fonts, size, mirror, place}` (graphic > project > design) via
  `look.resolve_type`, which clamps to what the category declares and says it in `notes` ("keeps its own font", "fills the screen",
  "cannot be mirrored"; no note when the project's mirror simply does not apply to a category).
- **Engine:** the type goes into the Theme (`look.theme_for(cat, colors, type)`): font roles swapped; Text size as a font-key suffix
  (`"inter-bold@1.1"`, read by `draw.font`/`draw.scale_of`) on heading/body/label only; display type is composed and fitted
  (`fit_size` on titles, names, charges, judge, chapter). Line steps that follow text use `D.lead(key, n)` (= n at 100%: pixel-identical).
  `traits["mirror"]` flips findings (photo right), legal (courthouse right, stamp in the docket) and turning (photo left, both phases).
  Place is drawn in `cinematic._placed`: the layout on its own layer, Lanczos-downscaled, over the full-frame background.
- **Declared per category** (`LOOKS[...]`): `fonts` (styles that passed the layout check), `size` (all 0.85–1.15), `mirror` (label),
  `place` (all but contradiction), `dim` (legal 0.75: its red labels are 2.8:1 over a mid-grey picture at 62%, 3.5:1 at 75%).
  Contradiction does not offer Typewriter (its statements overlapped at 115%).
- **Layout check:** `tests/cinegfx_layout.py` records every `D.text` (`draw.RECORD`) at the graphic's settled moments and reports
  overlap / clipped / outside. `test_every_offered_font_and_size_fits_its_layout` runs it for every offered font × size ends × mirror.
- **Timeline:** 5+ events (spacing < 346 px) narrow the cards (spacing − 32), the labels (30 px) and fit the dates; ≤ 4 events as before.
- **Digital:** a long station credit now ends inside the frame (it ran off the right edge); a station's sub-label follows the heading size.
- **Legal:** the outcome stamp moves down under the judge when larger text pushes the judge line down (at 100% it stays at y 905).
- The layout check also reports `touching` (stacked texts of different blocks less than 5 px apart; wrapped lines of one paragraph excepted).
- `cinematic.ENGINE` 3 (cached frames remade). Approved Javits stills: 97/97 pixel-identical.
- **Tests:** `tests/test_cinematic_type.py` (10), `tests/js/motion.test.mjs` (+1).
- **Demo page:** `qa/cinegfx-demos/make_type.py` (`--clips` for 5 narrated MP4s) writes `qa/cinegfx-demos/type/`; served on port 8001 at `/type/`.

### v0.4.65 Visual refinements, automatic presentation (optional), faster text layout, the motion check

- **Smoother reveals, same speed:** `anim.out_smooth` is the default easing of `ease`/`window` (was `out_expo`). Same durations
  (FAST 0.28 s): about 47% of a move lands in the first frame at 24 fps (was 65%), 95% by the fifth, so a move is seen, not a jump.
  Settled frames are unchanged; only frames mid-entrance differ.
- **Contradiction:** `_fit()` picks the largest statement size (44–56 px) at which the fuller column ends above y 990, and centres the
  block in the space left (`dy`, at most 140 px). Very long statements: 44 px at the old top (as before).
- **Digital:** muted text brighter (A `#8DBDB7` 9.6:1, B `#BCA67F`, C `#86BC98`; were about 5:1); detail 23 px; route sub-labels 18 px.
- **Photo movement:** timeline thumbnails settle (`out_cubic` over 3 s, was linear over 4 s); the digital station tile gets a 4% push-in as
  the place is named. Findings / legal / turning keep their push-ins.
- **Automatic presentation** (`presentation.py`, `POST /api/projects/{id}/motion/present`): off unless `motion.present` is ticked in Motion.
  Proposes full screen (`own`), over the footage, or partial (footage + place 0.86 to one side) per cinematic graphic, from the category's
  `looks["present"]` (`prefer`, `lock`, `anchor`, `why`), the shots under it (picture or not, cuts ≥ 4 = busy, a whole scripted shot hidden
  for ≥ 9 s) and the guide's chapter and Show notes (a graphic opening a chapter stays full screen when its design prefers it). Without
  `apply` nothing is saved; `{"apply": [ids]}` writes it as each graphic's own look (checkpointed: Undo works). No content rules.
- **Speed:** `draw.measure`, `draw.wrap` (via `_wrap`) and `draw.fit_size` are cached (pure). Legal fitted its lines on every frame:
  71.5 → 8.7 ms per frame. Stills identical before/after the cache.
- **Motion check:** `qa/motion_check.py [--project ID] [--apply] [--data DIR]` runs suggest → present → export layers → review MP4s on a real
  project (a copy in memory, never saved) and writes `qa/motion-check/<id>/report.md` with every decision and timing. It is the M1 benchmark.
- `cinematic.ENGINE` 4. `APP_VERSION` in `main.jsx` was stale (0.4.60); now follows the release.
- **Tests:** `tests/test_presentation.py` (9).

### v0.4.66 The six true-crime detectors read more than the Javits wording

All in `cinegfx/collections/truecrime.py`. Every addition is tried **only when the original Javits-tuned form finds
nothing**, so the Javits plan and graphics are unchanged (97/97 stills pixel-identical; Javits candidates, best payloads and
selection identical). The words on screen are still the script's own; what is not recognised is left out.

- **Findings:** `STATUS_MORE` (persons of interest, "do not believe … was involved", cleared, remains under investigation,
  identified, implicated, confirmed, "a detail … that had not been publicly released", found/recovered/obtained + evidence with
  ", along with A, B and C"; the status is the verb). `_ACTION` reads what investigators did, told as fact ("In December, police
  identified Moore as one of them."). "No arrest had been announced" also inside a sentence. Ranks as the whole role (`RANKS`: Chief,
  Lieutenant …). A pull quote also from "X described the killing as “…”" (only words in quotation marks). The agency follows the lead's
  role (SHERIFF’S OFFICE, FBI, STATE POLICE). "Police"/"Detectives" as the source: `payload.person = False`, no portrait slot, and the
  findings column centres when there is no portrait. A long label shrinks so it never runs under its chip.
- **Timeline:** `EVENT_SPLIT` + occurred / was reported / was found / was discovered / was last seen; "On March 3, 2025, …" labels no
  longer keep "On,"; clock events read "at 9:30 that morning / that night"; more attributions stripped (deputies, authorities …).
- **Contradiction:** `OPPOSED` + alone vs with others, unarmed vs armed, fled vs stayed, strangers vs knew each other, at home vs at the
  scene (each pair names its own topic). The context quote falls back to the earliest quoted account sharing the accounts' words.
- **Legal:** `CRIMES` + aggravated, carjacking, battery, sexual assault, stalking, child abuse. `CHARGE_MORE` (pleaded … to, indicted on,
  convicted of, accused of, "a … charge"), `OUTCOME_MORE` (pleaded guilty/not guilty/no contest, held without bond, held on $X bond → stamp
  BOND / $X, released on recognizance, mistrial, dismissed, plea deal), more hearings (sentencing, plea, bond hearing, trial). Judges by
  `JUDGE_ROLE` (Circuit/District Judge, Magistrate …; `payload.judge_title` when the script does not say "Judge X"). An adult the script
  names with an adult age ("41-year-old Thomas Reed") is the defendant; a juvenile never is. No "DEFENDANT DEFENDANT".
- **Digital:** more evidence kinds (camera footage, fingerprints, financial records, texts, emails, computer, ballistics, weapon, 911
  call); `_ev_status` gives each item what its own sentence says ("OBTAINED BY POLICE", "RECOVERED BY DEPUTIES", "MATCHED", "NEVER
  RECOVERED", "SHOWN BY PROSECUTORS"); `MOVES_MORE` (headed to, walked to, got into, entered …) when the original moves make no route;
  the incident's place/time from "between X Street and Y Avenue", "corner of", "just after 3:30 p.m." (incident sentences only); the
  source line names the agency ("AS DESCRIBED BY SHERIFF’S OFFICE").
- **Turning:** `_subject_age` reads word ages ("was fourteen", "fourteen-year-old Jevario"); `_elapsed` accepts "N days later", "after N
  days" and "nearly / more than N months|years" — only when the dates agree (a span the dates do not confirm is never shown); the span is
  then the narration's own words (`payload.span_label`, "MORE THAN FIVE MONTHS AFTER THE KILLING"). Sentenced / pleaded guilty / found
  guilty are decisive too; the charge when the same two sentences say it.
- `story.ROLE_TITLES` + Circuit Judge, District Judge, Magistrate (Judge), Trooper, Undersheriff.
- **Known limit (not changed):** a date without its year resolves to the latest one up to the recording date unless that is > 400 days
  from the story's last date. A case told within ~13 months ("March 3, 2025 … On March 4" recorded Nov 2026) gets the recording year.
  Javits depends on this rule (its "October 29" is the anniversary, 2026), so the fixture states its years.
- **Third script:** `tests/fixtures/sheriff-script.md` (fictional). Before: timeline + legal. After: all six placed.
- **Bismilah:** gains Findings ("What detectives said": records, social media messages, notes, search history — FOUND; Moore —
  IMPLICATED); turning reads age 14; digital moves one beat later (the findings take its window).
- `cinematic.ENGINE` 5. **Tests:** `tests/test_truecrime_wider.py` (17).
- **v0.4.65 leftovers closed:** the empty defense column / charges field in the motion-check frame at 9 s (`mc1.jpg`) is not a
  bug: the words type in when they are spoken (Bismilah's contradiction fills its defense card at ~10 s; the legal docket's
  "MURDER" is said last, at ~11.5 s). JS test: `normaliseMotion` keeps `present` only when it is a real `true` (`motion.test.mjs`).
- **Seen, not changed:** a *partial* (placed, scale 0.86) graphic encodes at ~12 fps: `cinematic._placed` Lanczos-resizes the whole
  1920×1080 layer every frame (the drawing itself is ~10 ms). Cropping the layer to its drawn box before the resize would cut it.

## storyroom-kit 0.1.0 (separate folder, Casefile unchanged)

User: "Storyroom. a folder inside this one … Just keep separate and also zip it for me here." `storyroom-kit/` at the
repo root (+ `storyroom-kit.zip`, the same folder zipped) is Casefile's cinematic engine on its own for the friend's
Storyroom editor: script + narration timings (SRT / word JSON / audio / estimated) → `plan.json` → per graphic a
transparent video (ProRes 4444 default; qtrle, VP9 WebM, PNG), its cue WAV, a preview MP4, and `render.json`,
`placements.csv`, `timeline.edl`. CLI `storyroom-gfx plan|render|run|stills|list|check`.
- **Nothing in `casefile-studio/` changed**; the kit never imports Casefile and Casefile never imports the kit.
- **Engine copy:** `storyroom_kit/cinegfx/`, `sfxlib.py`, fonts, copied by `storyroom-kit/tools/sync_engine.py`
  with 3 layout lines patched (font folder, dm-sans path, sfxlib import). After changing `casefile-studio/cinegfx/`,
  run `python storyroom-kit/tools/sync_engine.py --write`, then the kit's tests, and rebuild the zip.
- **`storyroom_kit/graphics.py`** is `cinematic.py`'s item/look/drawing code without the app (same names and
  arithmetic). Default 24 fps like Casefile (`--fps` 25/30/… allowed).
- **Tests** (`cd storyroom-kit && pytest`, 29; standalone: 21 pass, the 8 parity checks skip): `test_parity` (in-repo only) checks byte-identical frames against
  `cinematic.frame` for 5 looks and 2 sizes, the same suggestions as `cinematic.suggest`, the Javits demos with
  photos, and the copy; `test_reference` checks the six Javits demos against Casefile-drawn stills (no photos: the
  press photos are not shipped).

## v0.4.67 — the Edit page laid out like CapCut desktop (step 1 of 4: the frame)

User: "rebuild the interphase to something like this so it easily accessible and understandable to anyone" (18 CapCut
desktop screenshots). Agreed: Edit page first, keep Casefile's gold accent (not CapCut cyan), the other pages in the top
bar. Promise: nothing that works is lost, no fake buttons (CapCut's paid AI tools — avatar, remove BG, retouch, enhance —
are not imitated). Four PRs: 1 the frame (this), 2 per-tab grids, 3 contextual inspector + Director, 4 Mac-size polish.
- **Layout (`main.jsx`, Edit tab):** `header.topbar.cc-topbar` (menu ☰ with Home / projects / backups / help / settings,
  title + project switch, "Auto saved: hh:mm:ss", the pages as `nav.stage-nav.cc-pages`, Connect AI / Produce draft /
  Export) → `.edit-grid` with `section.cc-left` (icon tabs + sub-nav + content), `section.monitor-panel` (player head,
  frame, `.cc-transport`), `aside.inspector` (Video: Basic / Picture / Story / Tracks; Audio: Voice / Music),
  `section.timeline` (`.cc-tl-toolbar`, track heads `.track-labels.cc-heads`, an Overlays lane of `button.fx-clip`s for
  the subscribe animation, graphics and stickers) and the floating `div.cc-pilot` (Director: history + `#direction`).
- **Left tabs (`LEFT_TABS`):** media (scenes/all/video/image/audio), audio (music/sfx/voice), text (titles/names),
  stickers, effects (video/logo/subscribe), transitions, captions, filters, graphics (motion). The old panels are reused:
  `Effects` got an `only` prop (`looks fx watermark namecards cta transitions picture lowerthird`) so each tab shows
  its part. Clicking a timeline clip switches the inspector (music/narration → Audio, picture → Video) or opens the
  matching left tab (sticker → Stickers, graphic → Graphics, subscribe → Effects › Subscribe).
- **Styles:** all new rules in `web/src/capcut.css` (imported last; `--cc-*` variables). Above 1070 px the CapCut grid;
  ≤1070 the old `styles.css` column plus overrides (left 300 px, sub-nav as chips), ≤800 left 250 px, ≤580 stacked.
  Track head heights must match lane heights (overlay 28, captions 28, video 60, narration 40, music 34, sfx 31).
- **`editLayout.js`:** defaults left 440 / right 340 / timeline 326, director closed, `cc: 1`; a saved layout without
  `cc` gets the new left/right/director (one-time migration). Tests in `tests/js/editLayout.test.mjs`.
- **Moved, not removed:** the timeline footer's timing hint + "Space plays" are the `.cc-tl-hint` in the tool row (full
  text in its tooltip); "Narration level" lives in Audio › Voice; the direction history is in the Director panel.
- **Not a bug:** at 0:00 the player is black when scene 1 has "Fade in and out" — it fades in from black like the export.
- **Stale, before this PR:** `tests/browser_smoke.py` looks for a button "Undo last saved edit"; `main` already labels
  it with `historyLabel` ("Undo: … (Ctrl+Z)"). Browser tests need Playwright's chromium (not in the sandbox).
- **Testing tip:** `data/projects/*.json` are tracked; click-testing against them changes them. Run the app with
  `CASEFILE_DATA_DIR=/tmp/cfdata` (a copy of `data/`).

## v0.4.68 — Search, separate kinds of audio, full screen in an embedded preview (same PR as v0.4.67)

User: "add search button to search what i can't find. allow audio (Narration different from music, music different
from sfx). Fullscreen is unavailable in this embedded preview. fix"
- **Search:** top-bar `button.cc-search-btn` ("Search") or Ctrl+K / ⌘K on any page opens `SearchPalette.jsx`.
  `searchIndex.js` (pure, tested in `tests/js/searchIndex.test.mjs`) indexes the tools (left tabs, inspector tabs, with
  the words people use: "watermark" → Effects › Logo, "subtitles" → Captions, "crop" → Video › Picture), every look and
  transition, the pages, the actions (export, undo, split, import a voice-over, full screen, ratio …), the scenes with
  words of their narration (a snippet shows why), and the media files. Each result has a `go` that `runSearch` in
  `main.jsx` performs. No result → "Ask the Director" (fills `#direction`).
- **Kinds of audio:** an asset may carry `audio_role` = `narration` | `music` | `sfx`. Upload takes the form field
  `audio_role` (sort only: no episode, no timeline rebuild; `sfx` = the v0.4.56 sound-effect upload, ≤ 30 s, sets
  `sfx: true`). `PATCH /assets/{id}` with `audio_role` moves a file (`set_audio_role`): the file a role uses now
  cannot move, a sound effect must be audio ≤ 30 s, `null` = not sorted. Choosing a file as `narration_id` /
  `music_id` (project PATCH or Episode setup) sorts it under that role; the project PATCH refuses one file as both
  ("Narration and music must be different files."). AI narration and recorded voice get `audio_role: narration`.
  `audioRoles.js` (tested) gives each file its kind (the role using it wins) and the lists; the Audio tab shows only
  its own kind, a "Not sorted yet" box for audio imported from the Media tab (videos with sound are footage: listed
  only once sorted), a kind picker on every row and in the media library; the Sound panel's "your sounds" leave out
  narration and music. The first voice-over / music imported in the Audio tab goes straight on its track.
  Tests: `tests/test_audio_roles.py`.
- **Full screen:** `fullscreen()` asks for real fullscreen; where the page may not (an iframe without permission, as
  the Arena preview) the monitor gets `.full-window` (fixed, the whole window). Both show `.full-bar` (play, time,
  scrub, exit); Esc or the button leaves. The size watcher treats `.full-window` like fullscreen.

## v0.4.69 — CapCut step 2: a grid in every left tab

User: "Step 2" / "proceed" (the four-step CapCut rebuild; step 1 = v0.4.67). Nothing removed; every old control stays
below its grid.
- **Filters:** `Effects.jsx` looks are `.cc-tile`s with the look's CSS on your scene picture (inner `.fx-look-img`,
  so the gold tick keeps its colour). Pointing at (or focusing) a look tries it on the player: `onHoverLook` →
  `hoverLook` in `main.jsx`, the `.video-frame` gets `look-<id>` + `.look-trying` with a "Trying: …" label. It is
  cleared on mouse leave, click, tab change (`useEffect([leftTab])`) and when `Effects` unmounts.
- **Transitions:** `TransitionTile` draws the previous scene's picture (`prevThumb`) under this one's with the same
  `transitionStyle` / `transitionUnder` as the player, still at 50 %, playing on hover/focus (requestAnimationFrame,
  off with prefers-reduced-motion). "Use “…” on every scene" (`.fx-all`, `onAllScenes`) saves `scenes` in one PATCH
  (one undo step). aria labels unchanged: "Transition <label>", "Look <label>".
- **Video effects:** tiles "Film grain tile", "Vignette tile", "Cinema bars tile" (aria-pressed) above the old
  sliders; on = grain 35 % / vignette 45 % / bars.
- **Effects and Text › Name cards:** `featureCards()` in `main.jsx`: a card per overlay (Video effects, Logo,
  Subscribe, Name cards) with a mini preview, its state and, for Logo / Subscribe, a `Toggle` ("Logo on the video",
  "Subscribe on the video") that flips `watermark.enabled` / `cta.enabled`. Clicking a card opens its settings.
  Name cards have no quick switch (turning automatic ones on fetches the names; the checkbox below does that).
- **Stickers:** sub-tabs Subscribe / Arrows & shapes / Yours show `StickerGallery` (exported from
  `StickerDialog.jsx`, shared with the dialog) inline; "On your video" is the old `StickerPanel` (list, size, timing,
  keyframes). Adding a sticker jumps to "On your video" with it selected. Upload is `uploadSticker()`.
- **Captions:** sub-tabs Styles (on/off + the preset gallery) / Text / Box & position: `CaptionStyles` takes
  `section`; without it everything shows as before.
- **Media:** the side list is Scenes + Library (the old `video` / `image` / `audio` sub keys still work, e.g. from
  search); chips All / Videos / Photos / Audio (counts) + "Not used yet", and "Sort media": order in the edit, newest,
  oldest, name, longest — `mediaSort.js` (assets have no timestamp: import order), tested in
  `tests/js/mediaSort.test.mjs`.
- **CSS:** end of `capcut.css` (`.cc-tiles`, `.cc-tile*`, `.tile-check`, `.tr-stage`, `.fx-demo-*`,
  `.cc-sticker-grid`, `.cc-feature*`, `.cc-chip`, `.cc-sort`); phone (≤ 580 px): 3-column tiles, the four overlay
  cards in one row.
- **Checked:** eslint (no errors), `node --test` 71/71, pytest, puppeteer at 1512×900, 1280×760 and 390×844 (every
  tab, hover previews, toggles / transition on all scenes / sticker / sort saved to the project, no page errors).
- **Next:** step 3 — the right panel follows what is selected (clip, sticker, caption, audio) and the Director;
  step 4 — polish for Mac screen sizes (the phone left panel is short).
