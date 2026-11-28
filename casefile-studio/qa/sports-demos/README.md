# Sports editorial demos (v0.4.77): for approval

Seven standalone family demos plus one combined football documentary (~78 s). The story is Lionel Messi's four goals
against Arsenal (6 April 2010), with his 2009–10 season around it.

| file | family | window |
|---|---|---|
| `0-combined-messi-arsenal.mp4` | the whole documentary | 0–77.6 s |
| `1-behind-subject-name.mp4` | name behind the player (masked) | 0–4.95 |
| `2-oversized-headline.mp4` | ONE-MAN SHOW + word-synced statement, glitch exit | 32.4–41.1 |
| `3-numbered-points.mp4` | the four goals, 1–4, in monochrome | 39.7–56.5 |
| `4-minimal-transition.mp4` | "But first… we have to go back", into the archive photo | 14.1–26.9 |
| `5-scramble-labels.mp4` | 6 APRIL 2010 / CAMP NOU scramble | 6.9–12.2 |
| `6-cumulative-stats-masked.mp4` | 47 / 53 / 34 stacked behind the player | 59.4–68.2 |
| `7-single-stat-impact.mp4` | 4 GOALS, ONE NIGHT, luma exit | 56.1–60.6 |

`EDL.json` lists every shot (source in-point, speed, grade, what it shows, transition and why), every graphic
(and the narration words that triggered it) and every sound cue.

## Inputs

- **Script** (`script.json`): every fact has a source (ESPN match 290169 and the AP match report for the night;
  Wikipedia "Career of Lionel Messi" and goal.com for the season totals and the Ballon d'Or). The Xavi quote was
  re-checked on 2026-11-24 against two copies of the AP report.
- **Narration** (`narration/a–h.flac`): generated narrator voice, chosen by the user from two candidates.
  `narration/words.json` holds Whisper word timings per segment. Graphics use the script's words at those times.
- **Footage** (`work/sources/`, gitignored, not committed):
  - `messi_ars.mp4`: UEFA highlights of the match (1080p25), from the public GitHub repo `brandonjabr/goal-net`.
  - `ballon_dor_2009.jpg`: press photo of Messi with the 2009 Ballon d'Or.
  - Both are **copyrighted**. They are used here only to show the engine to its owner. Don't publish these renders.
- **Mattes**: `models/rvm_mobilenetv3_r1.onnx` (gitignored). This is Robust Video Matting (GPL-3.0), MobileNetV3,
  converted from the official TF.js release with tf2onnx. onnxruntime is optional.

## Reproduce

```
cd casefile-studio
.venv/bin/pip install onnxruntime          # optional: without it the "behind" type sits in front
.venv/bin/python qa/sports-demos/make_demos.py            # all eight
.venv/bin/python qa/sports-demos/make_demos.py --only combined,impact
```

Renders are cached by content (`work/cache/chunks`), so a change re-renders only the chunks it touches.
Mattes are cached per shot.

## Review gallery

```
.venv/bin/python qa/sports-demos/serve.py      # http://0.0.0.0:8020 (SPORTS_DEMOS_PORT to change)
```

A page with all eight demos (seekable), what to look for in each, and the edit decision list. It runs next to
Casefile Studio (port 8010) and doesn't touch the app.
