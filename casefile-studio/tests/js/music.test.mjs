// v0.4.58 Real-time levels, smooth plan changes, single auditions, and the music preview.
import { test } from "node:test";
import assert from "node:assert/strict";

// ---- a minimal WebAudio / <audio> stand-in that records what the preview asks for
class Param {
  constructor(v = 1) { this.value = v; this.calls = []; }
  setTargetAtTime(v, t, tc) { this.calls.push(["target", v, t, tc]); this.value = v; }
  setValueAtTime(v, t) { this.calls.push(["set", v, t]); this.value = v; }
  linearRampToValueAtTime(v, t) { this.calls.push(["ramp", v, t]); }
  cancelScheduledValues() { this.calls.push(["cancel"]); }
}
class Node { constructor() { this.gain = new Param(1); } connect(n) { return n; } }
class Source {
  constructor(ctx) { this.ctx = ctx; this.stopped = false; }
  connect(n) { return n; }
  start(when, off, dur) { this.when = when; this.off = off; this.dur = dur; this.ctx.started.push(this); }
  stop() { this.stopped = true; this.ctx.stops++; this.onended?.(); }
}
class Ctx {
  constructor() { this.currentTime = 0; this.state = "running"; this.started = []; this.stops = 0; this.destination = new Node(); }
  createGain() { return new Node(); }
  createBufferSource() { return new Source(this); }
  createMediaElementSource() { return new Node(); }
  resume() { return Promise.resolve(); }
  decodeAudioData() { return Promise.resolve({ duration: 0.5, getChannelData: () => new Float32Array(4800) }); }
}
class FakeAudio {
  constructor() { this.paused = true; this.currentTime = 0; this.seeking = false; this.volume = 1; this.preload = ""; this.src = ""; this.plays = 0; }
  play() { this.paused = false; this.plays++; return Promise.resolve(); }
  pause() { this.paused = true; }
  load() {}
  removeAttribute() {}
}
globalThis.window = { AudioContext: Ctx };
globalThis.Audio = FakeAudio;
globalThis.fetch = () => Promise.resolve({ ok: true, arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) });

const { SfxPreview, soundUrl } = await import("../../web/src/sound.js");
const { musicLayout, musicGainAt, musicPasses, MusicPreview, approxDuck, normaliseMusic, timelineTotal, slotGain, envEvents, syncStep } = await import("../../web/src/music.js");

function withBuffers(p, sids) {
  p.ensure();
  for (const sid of sids) p.buffers.set(soundUrl("p", sid), { duration: 0.4 });
}

test("the effects volume is a real-time ramp: no new plan, nothing restarted", () => {
  const p = new SfxPreview();
  withBuffers(p, ["a"]);
  const list = [[0.1, "a", 1, { id: "x1" }], [1.0, "a", 1, { id: "x2" }]];
  p.tick("p", list, 0, true);
  const started = p.ctx.started.length;
  p.setMaster(0.5);
  const last = p.out.gain.calls.at(-1);
  assert.equal(last[0], "target");
  assert.equal(last[1], 0.5);
  assert.ok(last[3] > 0 && last[3] <= 0.05); // a short ramp, not a jump
  assert.equal(p.ctx.started.length, started);
  assert.equal(p.ctx.stops, 0);
});

test("a new plan while playing carries on: nothing restarted, nothing doubled", () => {
  const p = new SfxPreview();
  withBuffers(p, ["a", "b"]);
  const list1 = [[0.1, "a", 1, { id: "x1" }], [0.2, "a", 1, { id: "x2" }], [0.9, "a", 1, { id: "x3" }]];
  p.tick("p", list1, 0, true); // starts 0.1 and 0.2 (within 0.3 s ahead)
  assert.equal(p.ctx.started.length, 2);
  p.ctx.currentTime = 0.25;
  const list2 = [[0.1, "b", 0.5, { id: "x1" }], [0.2, "b", 0.5, { id: "x2" }], [0.9, "b", 0.5, { id: "x3" }]]; // e.g. a saved gain
  p.tick("p", list2, 0.25, true);
  assert.equal(p.ctx.stops, 0); // the sounds playing were not cut
  assert.equal(p.ctx.started.length, 2); // and not started again
  p.ctx.currentTime = 0.7;
  p.tick("p", list2, 0.7, true);
  assert.equal(p.ctx.started.length, 3); // the next one comes from the new plan
  // a seek still starts again from the new position
  p.ctx.currentTime = 0.8;
  p.tick("p", list2, 5.0, true);
  assert.ok(p.ctx.stops >= 1);
});

test("one sound's volume follows its slider live (and the sounds about to play)", () => {
  const p = new SfxPreview();
  withBuffers(p, ["a"]);
  const it = { id: "x1" };
  p.tick("p", [[0.1, "a", 0.8, it]], 0, true);
  const [g] = [...p.itemGains.get("x1").keys()];
  p.setItemGain("x1", 0.5);
  assert.deepEqual(g.gain.calls.at(-1).slice(0, 2), ["target", 0.4]);
  p.setItemGain("x1", null);
  assert.deepEqual(g.gain.calls.at(-1).slice(0, 2), ["target", 0.8]);
});

test("auditions: one at a time, stoppable, never through the mix", async () => {
  const p = new SfxPreview();
  p.ensure();
  let ended = [];
  const d1 = await p.audition("p", "whoosh-mid-1", 0.8, null, () => ended.push(1));
  assert.equal(d1, 0.5);
  const first = p.aud.src;
  await p.audition("p", "pop-soft-1", 0.8, null, () => ended.push(2));
  assert.ok(first.stopped); // the new one stopped the last
  assert.deepEqual(ended, [1]);
  p.stopAudition();
  assert.deepEqual(ended, [1, 2]);
  assert.equal(p.aud, null);
  assert.equal(p.live.length, 0); // auditions are not timeline sounds
  p.setAuditionVolume(0.3);
  assert.equal(p.audOut.gain.calls.at(-1)[1], 0.3);
});

test("music layout: loops tile the stretch exactly, equal power across seams", () => {
  const total = timelineTotal(Array.from({ length: 150 }, (_, k) => ({ id: k, duration: 10 })));
  assert.equal(total, 1500);
  const lay = musicLayout({ crossfade: 2 }, 180, total);
  const iters = lay.runs[0].iters;
  assert.equal(iters.length, 9);
  assert.equal(iters.at(-1).at + iters.at(-1).len, 1500);
  for (let t = 3; t < 1497; t += 0.37) assert.ok(Math.abs(musicGainAt(lay, t) - 1) < 1e-9, t);
  // the timeline is authoritative: nothing is ever placed past its end
  for (const m of [{}, { mode: "once", offset: 1400 }, { loop: false }, { mode: "range", offset: 100, until: 9999 }])
    for (const r of musicLayout(m, 180, total).runs) assert.ok(r.end <= total + 1e-9);
  assert.deepEqual(normaliseMusic({ crossfade: 99, mode: "nope" }).crossfade, 10);
});

test("the music preview: alternate passes on two elements, crossfaded; volume is a live gain", () => {
  const host = new SfxPreview();
  const mp = new MusicPreview(host);
  mp.setSource("/media/p/m.mp3");
  mp.setLayout(musicLayout({ crossfade: 2, fade_in: 0 }, 20, 60));
  mp.setVolume(0.2);
  mp.tick(5, true, false);
  const [a, b] = mp.els;
  assert.ok(!a.paused && b.paused); // pass 0 plays
  assert.ok(Math.abs(a.currentTime - 5) < 0.06);
  // just before the seam (pass 1 at 18 s) the second element is made ready at the part's start
  host.ctx.currentTime = 12.6;
  mp.tick(17.6, true, false);
  assert.ok(b.paused && Math.abs(b.currentTime - 0) < 0.05);
  // inside the crossfade both play, at sin / cos of the crossfade
  host.ctx.currentTime = 14;
  mp.tick(19, true, false);
  assert.ok(!a.paused && !b.paused);
  const ga = mp.nodes.pass[0].gain.value, gb = mp.nodes.pass[1].gain.value;
  assert.ok(Math.abs(ga * ga + gb * gb - 1) < 1e-9); // equal power
  assert.ok(Math.abs(b.currentTime - 1) < 0.06);
  // the volume: one ramp on the bus, nothing else touched
  const plays = a.plays + b.plays;
  mp.setVolume(0.35);
  assert.deepEqual(mp.nodes.bus.gain.calls.at(-1).slice(0, 2), ["target", 0.35]);
  assert.equal(a.plays + b.plays, plays);
  mp.tick(19.02, true, true); // muted
  assert.equal(mp.nodes.bus.gain.calls.at(-1)[1], 0);
  mp.tick(19.04, false, true);
  assert.ok(a.paused && b.paused);
  assert.equal(musicPasses(mp.lay).length, 4); // 1 + ceil((60 - 20) / 18)
});

test("an immediate ducking estimate when the narration level moves", () => {
  const curve = { rate: 200, gain: new Float32Array([1, 0.5, 0.25, 1]) };
  assert.equal(approxDuck(curve, 1, 8), curve);
  const up = approxDuck(curve, 2, 8); // +6 dB of voice: more reduction where it dips
  assert.equal(up.gain[0], 1);
  assert.ok(up.gain[1] < 0.5 && up.gain[2] < 0.25);
  assert.ok(Math.abs(20 * Math.log10(0.5 / up.gain[1]) - 20 * Math.log10(2) * (1 - 1 / 8)) < 1e-4);
  const down = approxDuck(curve, 0.25, 8);
  assert.ok(down.gain[1] > 0.5);
  assert.ok(approxDuck(curve, 0, 8).gain.every((v) => v === 1)); // silent voice: no dip
});

// ---- v0.4.59 loop timing: the preview's envelope on the audio clock, trimmed rather than jumped
test("v0.4.59 the preview's pass envelopes, scheduled as ramps, trace the export's crossfades and fades", () => {
  for (const [m, track, total] of [[{ crossfade: 2, fade_in: 1.5, fade_out: 3 }, 20, 75], [{ crossfade: 0.5, start: 2 }, 8, 40], [{ crossfade: 10 }, 21, 90]]) {
    const lay = musicLayout(m, track, total);
    // the two elements together are the export's envelope everywhere (two passes of one parity never overlap)
    for (let t = 0; t < total; t += 0.013) assert.ok(Math.abs(Math.hypot(slotGain(lay, 0, t), slotGain(lay, 1, t)) - musicGainAt(lay, t)) < 1e-9, `${t}`); // equal power
    // linear ramps between the scheduled points: within 1.5 % of the exact curve (≈ 0.13 dB)
    for (const slot of [0, 1]) for (let t0 = 0; t0 < total - 3; t0 += 2.9) {
      const ev = envEvents(lay, slot, t0, 100, 3);
      for (let i = 1; i < ev.length; i++) {
        const [a, va] = ev[i - 1], [b, vb] = ev[i];
        for (const f of [0.25, 0.5, 0.75]) {
          const at = a + (b - a) * f, want = slotGain(lay, slot, t0 + at - 100);
          assert.ok(Math.abs(va + (vb - va) * f - want) < 0.015, `${slot} ${t0} ${at}`);
        }
      }
    }
  }
});

test("v0.4.59 drift is trimmed with the playback rate; a seek only where it is silent or far off", () => {
  assert.deepEqual(syncStep(0.004, 1, 5), { rate: 1 });
  const late = syncStep(-0.05, 1, 5), early = syncStep(0.05, 1, 5);
  assert.ok(late.rate > 1 && late.rate <= 1.03 && early.rate < 1 && early.rate >= 0.97);
  assert.deepEqual(syncStep(0.05, 0.05, 5), { seek: 5 }); // quiet: an inaudible re-seek
  assert.deepEqual(syncStep(0.4, 1, 5), { seek: 5 }); // far off (a jump): seek even when loud
  // the v0.4.58 preview let an audible pass run up to 0.2 s off before it re-seeked
  assert.ok(syncStep(0.19, 1, 5).rate < 1);
});

test("v0.4.59 a pass from the top of the part starts on time: play() is called early by the measured delay", () => {
  const host = new SfxPreview();
  const mp = new MusicPreview(host);
  mp.setSource("/media/p/m.mp3");
  mp.setLayout(musicLayout({ crossfade: 2, fade_in: 0 }, 20, 60));
  mp.lat = 0.04;
  host.ensure();
  host.ctx.currentTime = 1;
  mp.tick(17.9, true, false); // pass 1 starts at 18 s from the part's top: 0.1 s away, waiting
  const b = mp.els[1];
  assert.ok(b.paused && b.currentTime === 0);
  host.ctx.currentTime = 1.065;
  mp.tick(17.965, true, false); // 35 ms before the seam, delay 40 ms: started now
  assert.ok(!b.paused);
  // the volume and the envelope are separate: a level change never re-schedules the envelope
  const calls = mp.nodes.pass[1].gain.calls.length;
  mp.setVolume(0.4);
  assert.equal(mp.nodes.pass[1].gain.calls.length, calls);
});
