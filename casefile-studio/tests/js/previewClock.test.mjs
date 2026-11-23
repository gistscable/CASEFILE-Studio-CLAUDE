// Run from casefile-studio/: node --test tests/js/previewClock.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { speechAt, timelineFromSpeech, nextTime, sceneIndexAt } from "../../web/src/previewClock.js";

const offsetsOf = (sc) => { let t = 0; return sc.map((s) => { const n = t; t += s.duration; return n; }); };
const guide = [
  { duration: 4, audio_start: 0, audio_duration: 4 },
  { duration: 3, audio_start: 4, audio_duration: 3 },
  { duration: 5, audio_start: 7, audio_duration: 5, insert_audio: true }, // Mode O break
  { duration: 2, audio_start: 7, audio_duration: 2 },
];
const off = offsetsOf(guide);

test("speechAt maps timeline to narration and is silent during a break", () => {
  assert.equal(speechAt(guide[1], off[1], 5.5), 5.5);
  assert.equal(speechAt(guide[2], off[2], 9), null);
  assert.equal(speechAt(guide[3], off[3], 12.5), 7.5); // resumes at the same word
});

test("following the audio crosses scene boundaries without a seek", () => {
  assert.equal(timelineFromSpeech(guide, off, 0, 4.25), 4.25);
});

test("narration reaching an audio break stops at the break's start", () => {
  assert.equal(timelineFromSpeech(guide, off, 1, 7.01), off[2]);
});

test("after a break the narration position maps past the break", () => {
  assert.equal(timelineFromSpeech(guide, off, 3, 8), off[3] + 1);
});

test("clock follows audio when playing, even after a long stall", () => {
  // The page froze for 0.9 s but the audio kept playing: time jumps to the audio.
  const t = nextTime(guide, off, 1.0, 0.15, { paused: false, seeking: false, ready: true, currentTime: 1.9 });
  assert.equal(t, 1.9);
});

test("clock never re-targets on a far-away audio position (that is a seek)", () => {
  const t = nextTime(guide, off, 1.0, 0.1, { paused: false, seeking: false, ready: true, currentTime: 6.5 });
  assert.equal(t, 1.1);
});

test("buffering audio holds the picture instead of drifting ahead", () => {
  const t = nextTime(guide, off, 2.0, 0.1, { paused: false, seeking: false, ready: true, currentTime: 2.0 });
  assert.equal(t, 2.0);
});

test("wall clock runs during a break or with no narration", () => {
  assert.equal(nextTime(guide, off, 9, 0.1, { paused: true, seeking: false, ready: true, currentTime: 7 }), 9.1);
  assert.equal(nextTime(guide, off, 9, 0.1, null), 9.1);
});

test("manual projects with a silent tail hold at end of speech", () => {
  const manual = [
    { duration: 5, audio_start: 0, audio_duration: 3 },
    { duration: 4, audio_start: 10, audio_duration: 4 },
  ];
  const o = offsetsOf(manual);
  assert.equal(timelineFromSpeech(manual, o, 0, 3.05), 3);
  assert.equal(sceneIndexAt(manual, o, 6), 1);
});
