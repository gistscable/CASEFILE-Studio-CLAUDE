# Music loop timing: preview vs export (v0.4.59)

`harness.js` (bundled with esbuild together with the v0.4.58 and v0.4.59 `web/src/music.js`, as
`old_music.js` / `new_music.js`) plays a click track as the narration (the editor's master clock, as
in `main.jsx`) and a click track as the music, through the real `MusicPreview`, and records what is
actually output with an AudioWorklet (`rec-worklet.js`). `timing2.mjs` (puppeteer-core, headless
Chromium) compares each heard music click with where the export places it (`musicLayout`, the same
layout as `music.py`): + = the preview is late.

    track.wav : 8 s, a click every 0.5 s from 0.25 s     narr.wav : 42 s, a click every 1 s from 0.1 s
    esbuild harness.js --bundle --format=iife --outfile=bundle.js   (+ index.html loading it)
    node timing2.mjs 1 result.json         # steady
    JANK=1 node timing2.mjs 1 result.json  # the main thread blocked 150 ms about every 0.75 s

Results: `result-steady.json`, `result-busy-main-thread.json`.
