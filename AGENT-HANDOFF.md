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

Tests (374 passing at v0.4.22; JS: `node --test tests/js/previewClock.test.mjs`, including `tests/test_deployment.py`, which reads
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
  at 1080p here = ~6 min for 18 min of video). An hour on an M-series Mac is not explained by the
  code; it points at an emulated amd64 image or a low Docker CPU limit — ask for the checks above.
Notes: ffmpeg 7.0.2 (imageio-ffmpeg 0.6.0) fails every xfade transition ("current rate of 1/0") with
or without this change (setpts unsets the rate there); 6.0 and 9.0.2 pass. Adding `fps=24` before
xfade fixed 7.0 but changed frames at a loop seam, so it was not shipped. x264 output can differ in
the last bits between any two runs on ffmpeg 9 (PSNR 64–81 dB), so the parallel test compares PSNR.
