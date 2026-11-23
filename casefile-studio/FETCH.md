# Fetch from guide (v0.4.19)

The episode screen has a **Fetch from guide** panel (below the footage upload buttons).
It reads the guide's Source library and Base clips table and downloads the YouTube
videos for you, under the exact names the guide gives, straight into Footage & photos,
then links them to their sources (same as Match filenames).

- **Footage** (`S03.mp4`): downloaded from 0:00 to just past the last window the guide
  uses (whole video if no window), so the guide's times still match the file.
- **Base clips** (`BASE-C--location--02.mp4` with `0:40–0:52`): cut to that window.
- **Base frames** (`BASE-V--portrait--01.jpg` with a time like `1:12`, or `&t=72s`):
  one still captured at that time. A row can say "from S03, 0:30" instead of a link.
- Each YouTube video is downloaded once, even if several files come from it.
  One failed video never stops the rest; failures are listed, and a second click
  fetches only what is still missing.
- Every fetched file records its link, video ID, uploader, title, window and time.
  It never records a reuse basis, rights approval or audio clearance — those stay yours.
- First use asks you to accept a notice: downloading from YouTube may break YouTube's
  Terms of Service; copyright is separate; you are responsible.

## Downloaders

- **yt-dlp** (default, free, runs inside Docker). The image includes Deno, which yt-dlp
  needs for YouTube. If downloads start failing months later, YouTube changed something:
  rebuild with `docker build --no-cache -t casefile-studio .` to get the newest yt-dlp.
- **Apify** (optional). Paste an API token in the panel (kept in memory for the session,
  never saved to the project), or start the container with `-e APIFY_TOKEN=...`.
  Default actor: `danng/youtube-to-mp4-youtube-downloader-with-yt-dlp` (input `{"url"}`,
  output `downloadUrl`). Any actor with the same shape can be typed in.

API: `GET /api/projects/{id}/fetch` (plan + downloader status),
`POST /api/projects/{id}/fetch` `{backend, confirm_responsibility, only?, max_height?, apify_token?, apify_actor?}` → job.
Code: `fetcher.py`; tests: `tests/test_fetcher.py`.

# Audio fixes (v0.4.19)

- **Preview stutter fixed** (`web/src/previewClock.js`): the editor preview ran its own
  clock and re-seeked the narration whenever it drifted 0.3 s, so any page lag caused
  audible skips/repeats. The narration is now the master clock; the picture follows it.
  Browser test: old preview 10 re-seeks in 30 s of playback, new 0. Audio breaks pause
  the narration and play the clip's own sound in the preview.
- **Export hardening** (`renderer.py`): narration timestamps are rebuilt from the sample
  count (`asetpts=N/SR/TB`), so a narration file with internal timestamp jumps can no
  longer lose its ending. Test: `tests/test_audio_continuity.py`.

## Each file has its own bar (v0.4.27)

While fetching (Episode setup → Fetch from guide, and the Re-cut page), every file gets a row:
its own bar, percentage, speed and size ("43% · 2.1 MB/s · 18 of 42 MB"), and a status:
waiting, downloading, saving, done or failed. If a file shows no progress for 30 seconds it is
marked **stalled**. **Stop** ends the run; **Retry** on a row downloads only that file
(**Retry all** when several failed). The failure reason is shown on the row.
When yt-dlp cuts a section through ffmpeg it gives no percentage; the row then shows the size
downloaded so far with a moving bar.
