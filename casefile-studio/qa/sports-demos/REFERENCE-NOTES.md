# Sports engine — reference study and segmentation research

Reference: `football_clip_onl.mp4` (repo root on `main`, commit `31f78e5`).
62.57 s, 448×256 phone recording of a laptop playing the video, h264 30 fps, AAC 44.1 kHz.
Story: Alexander Isak, "resurgence or just a good month?".
Studied at 2 fps (contact sheets), then at 30 fps frame by frame for each technique
(`research/fx_*.jpg`), plus an audio spectrogram and onset analysis (`research/spec.jpg`).

**Do not copy:** the browser bar, playback controls, laptop reflections or phone-camera blur.
These come from the recording, not from the edit.

## Overall look
- Dark warm brown/red vignette, lifted blacks, film grain, dust specks, faint vertical light streaks.
- Primary type: bold condensed caps, cool-white (white → pale blue gradient), soft dark drop shadow.
- Small labels: cream/yellow, condensed, wide tracking. Yellow is an accent only.
- Footage changes about every 0.5–2 s. Graphics persist across cuts.
- Grading is per beat: cool desaturated (intro, questions), mono (questions), low-key dark (flashback), warm stadium (stats).

## The 7 families, as observed

| # | Family | Time | What happens (30 fps timing) |
|---|--------|------|------------------------------|
| 1 | Name behind subject | 0.6–2.5 s | Hard cut to a desaturated cool portrait. "ALEXANDER / ISAK" in 2 huge tight-leading lines (each ≈40 % of frame height), right of centre. The head occludes the first letters. Masked left→right wipe per line in ≈0.3 s (≈9 frames). SFX onset 0.78 s. |
| 2 | Oversized headline | 5.53–8.2 s | "RESURGENCE" slam: frame 1 oversized RGB-doubled ghost, frame 2 in place, settled after 3 frames. ≈85 % frame width. Subline "OR JUST A GOOD MONTH?" ≈0.33 s later, small. Survives a footage cut at 5.87. Exit: desaturate plus horizontal slice displacement, then a 3-frame RGB-split glitch on the next shot (onset 8.29). |
| 3 | Numbered questions | 20.33–24.3 s | Mono cool footage. Big numeral "1" (≈¼ frame height) plus a small label upper right, "IS IT REAL?". "2 WHY NOW?" at +1.0 s, "3 WHAT'S STILL MISSING?" at +3.0 s, stacked. Quick fade/rise. Survives a cut at 22.47. Each item lands on the narrator saying it. |
| 4 | Minimal transition | 28.2–31.3 s | Dissolve to a dark low-key silhouette. Small centred caps "BUT FIRST." soft letter reveal, then "WE HAVE TO GO BACK" (≈0.4 s). Audio drops to near silence (−49 dB → −65 dB), then a hard cut back. |
| 5 | Scramble labels | 38.0–38.4 s, 55.9–56.6 s | "SUMMER 2025", bottom-left, small. 12 frames: characters lock left→right while the tail cycles random glyphs ("02CS" → "SUWZ8F" → "SUMMER CNU" → "SUMMER 202&" → "SUMMER 2025"). A tick SFX per lock (onsets 38.32/38.51/38.81). Two-line variant: "MARCH 2025" then "LEAGUE CUP FINAL". Persists across cuts. |
| 6 | Cumulative stats, masked | 44.2–48.7 s | "62 GOALS" sits BEHIND Isak's head and is revealed as he moves. Survives a cut and stays behind the new subject. "109 APPEARANCES" fades in +1.5 s. Cut to a stadium wide: stacked 62 / 109 / "54 IN THE PREMIER LEAGUE" (+0.4 s). Numerals cool-white, small labels right. |
| 7 | Single-stat impact | 52.0–55.47 s | "23" very heavy and wide. Frame 1 scaled RGB-split ghost, frame 2 settles, frame 3 full. "LEAGUE GOALS" small yellow letter reveal +0.33 s. Survives a cut. Exit: fade/desaturate to cyan, then a blotchy luma-matte dissolve to the next scene. |

## Sound
- Bed loudness −22 to −28 dB RMS. Narration sits on top; music ducks under it.
- High-frequency whoosh bursts on graphic entries (≈1.0, 3.0, 4.0, 6.0, 9.0, 23.0, 36.5, 44.0, 46.5, 53 s).
- Onsets line up with graphic events to within 1–2 frames: slam = low hit plus whoosh; scramble = quick ticks; glitch = digital burst.
- The flashback section drops everything to near silence; contrast is what makes it work.

## Facts used in the reference (verified, for the demo script)
- Newcastle 2022–2025: 62 goals in 109 appearances; 54 Premier League goals.
- 2024/25: 23 Premier League goals (2nd only to Salah); 27 in all competitions.
- Joined Newcastle Aug 2022 from Real Sociedad (club record, about £63m).
- Carabao Cup final, 16 March 2025, Wembley: Newcastle 2–1 Liverpool (Burn 45', Isak 52').
  Newcastle's first major domestic trophy in 70 years.
- Joined Liverpool 1 Sept 2025 for a British-record £125m.

## Segmentation research (family 1 and 6 need a real person matte)
- **Robust Video Matting** (Lin et al. 2021, MobileNetV3, 3.7 M params) is a recurrent model.
  The recurrent state gives temporally stable mattes, which is what persistent behind-subject type needs.
- The official GitHub release asset could not be downloaded from this sandbox (the release
  redirect host is blocked). Instead it was rebuilt from the TF.js weights in the npm package
  `virtual-background-ai@1.0.0` (MIT wrapper, RVM weights). Steps:
  1. Patch `_FusedConv2D` nodes with `TArgs`/`num_args`.
  2. Rewire the `downsample_ratio` conditionals to the ratio = 1 branch.
  3. Run `tf2onnx --opset 13`, giving a 15 MB ONNX.
- Test on the reference (`research/rvm_matte_test_62goals.jpg`): a clean full-body matte, stable
  over 90 frames, even on blurry phone-recorded footage. 6.8 fps at 448×256 on the sandbox CPU.
  On an M1 (8 cores), ORT CPU should be several times faster. Masks are computed once per clip
  and cached as 8-bit PNG/NPZ, so renders never re-run the model.
- Licence note: the original RVM weights are GPL-3.0. Fine for a private tool; check before redistributing.
- Needs `onnxruntime` (a pip wheel, CPU, works on Apple Silicon). This would be a **new dependency**,
  kept optional: without it, families 1 and 6 fall back to type in front of the subject.
