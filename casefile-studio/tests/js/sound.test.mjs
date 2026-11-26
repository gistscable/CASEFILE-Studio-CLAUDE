import test from "node:test";
import assert from "node:assert/strict";
import { normaliseSound, withPreset, editItem, schedule, soundUrl, SFX } from "../../web/src/sound.js";

test("sound design is off by default and settings stay in range", () => {
  const s = normaliseSound(undefined);
  assert.equal(s.enabled, false);
  assert.equal(s.preset, "cinematic");
  const t = normaliseSound({ enabled: true, master: 9, density: -1, mode: "x" });
  assert.equal(t.master, SFX.limits.master[1]);
  assert.equal(t.density, 0);
  assert.equal(t.mode, "auto");
});

test("a preset sets intensity, density and kinds; custom keeps yours", () => {
  const s = normaliseSound({ enabled: true, intensity: 0.9 });
  const subtle = withPreset(s, "subtle");
  assert.equal(subtle.intensity, 0.25);
  assert.equal(subtle.kinds.moments, false);
  assert.equal(withPreset(s, "custom").intensity, 0.9);
});

test("editing one planned sound stores only that sound", () => {
  const s = normaliseSound({ enabled: true });
  const planned = { id: "sx1", anchor: "tr:a", kind: "transitions", sound: "whoosh-dir-l", gain: -4, status: "approved", source: "auto", t: 5.3, level: -6 };
  const a = editItem(s, planned, { gain: -10 });
  assert.equal(a.items.length, 1);
  assert.equal(a.items[0].gain, -10);
  assert.equal(a.items[0].edited, true);
  assert.equal(a.items[0].t, undefined); // derived fields are not stored
  const b = editItem(a, planned, { offset: 0.0417 });
  assert.equal(b.items.length, 1);
  assert.equal(b.items[0].gain, -10);
  assert.equal(b.items[0].offset, 0.0417);
});

test("the preview schedule: approved and placed only, one entry per typed key", () => {
  const items = [
    { id: "a", status: "approved", t: 2.0, start: 1.8, sound: "whoosh-mid-1", level: -6, kind: "motion" },
    { id: "b", status: "removed", t: 3.0, start: 3.0, sound: "pop-soft-1", level: 0, kind: "motion" },
    { id: "c", status: "approved", t: null, start: null, sound: "pop-soft-1", level: 0, kind: "motion" },
    { id: "d", status: "approved", t: 4.0, start: 3.998, sound: "type-strike-1", level: 0, kind: "typing",
      keys: [[4.0, "type-strike-1", 1], [4.06, "type-space-1", 0.8]] },
  ];
  const s = schedule(items);
  assert.deepEqual(s.map((x) => x[1]), ["whoosh-mid-1", "type-strike-1", "type-space-1"]);
  assert.ok(Math.abs(s[0][2] - Math.pow(10, -6 / 20)) < 1e-9);
  assert.ok(Math.abs(s[1][0] - 3.998) < 1e-9 && Math.abs(s[2][0] - 4.058) < 1e-9);
  assert.equal(soundUrl("p1", "a:abc123"), "/api/projects/p1/sound/custom/abc123.wav");
});

// ------------------------------------------------------------------ v0.4.57
import { duckEvents, decodeDuck, scopeItems, editItems, graphicOf } from "../../web/src/sound.js";

test("preview ducking follows the export's curve on the editor clock", () => {
  // 200 values a second: full level, then -12 dB (0.25) from 1.0 s, back up at 2.0 s
  const rate = 200, g = new Float32Array(600).fill(1);
  for (let i = 200; i < 400; i++) g[i] = 0.25;
  const duck = { rate, gain: g };
  const ev = duckEvents(duck, 0.5, 10.0, 4);
  // starts at "now" with the value at timeline 0.5 s, then one point every 5 ms
  assert.equal(ev[0][0], 10.0);
  assert.ok(Math.abs(ev[0][1] - 1) < 1e-6);
  const at = (tl) => ev.find(([t]) => t >= 10 + (tl - 0.5) - 1e-9);
  assert.ok(Math.abs(at(1.5)[1] - 0.25) < 1e-6, "ducked in the middle of the speech");
  assert.ok(Math.abs(at(2.6)[1] - 1) < 1e-6, "back to full after it");
  // times are context times: timeline t -> now + (t - 0.5); strictly increasing
  for (let k = 1; k < ev.length; k++) assert.ok(ev[k][0] > ev[k - 1][0]);
  // the curve's points are window centres: point i at (i + 0.5) / rate
  const p = ev.find(([t]) => Math.abs(t - (10 + (200.5 / rate - 0.5))) < 1e-9);
  assert.ok(p && Math.abs(p[1] - 0.25) < 1e-6);
  // past the end, or no curve: full level
  assert.deepEqual(duckEvents(duck, 99, 3, 4), [[3, 1]]);
  assert.deepEqual(duckEvents(null, 1, 3, 4), [[3, 1]]);
});

test("the server's curve decodes to 0..1", () => {
  const bytes = Buffer.from([255, 128, 0]).toString("base64");
  const d = decodeDuck({ status: "ready", rate: 200, gain: bytes });
  assert.equal(d.rate, 200);
  assert.deepEqual(Array.from(d.gain).map((x) => Math.round(x * 1000) / 1000), [1, 0.502, 0]);
  assert.equal(decodeDuck({ status: "working" }), null);
});

test("one change for a whole motion graphic, or every line of it", () => {
  const plan = [
    { id: "a", anchor: "mg:g1:background:0", kind: "motion", sound: "whoosh-mid-1", gain: -5 },
    { id: "b", anchor: "mg:g1:line:0", kind: "motion", sound: "click-mech-1", gain: -2 },
    { id: "c", anchor: "mg:g1:line:1", kind: "motion", sound: "click-mech-1", gain: -2 },
    { id: "d", anchor: "mg:g2:line:0", kind: "motion", sound: "click-mech-1", gain: -2 },
    { id: "e", anchor: "tr:s3", kind: "transitions", sound: "whoosh-dir-l", gain: -4 },
  ];
  assert.deepEqual(graphicOf(plan[1]), { gid: "g1", role: "line" });
  assert.equal(graphicOf(plan[4]), null);
  assert.deepEqual(scopeItems(plan, plan[1], "this").map((x) => x.id), ["b"]);
  assert.deepEqual(scopeItems(plan, plan[1], "role").map((x) => x.id), ["b", "c"]);
  assert.deepEqual(scopeItems(plan, plan[1], "graphic").map((x) => x.id), ["a", "b", "c"]);
  assert.deepEqual(scopeItems(plan, plan[4], "graphic").map((x) => x.id), ["e"]); // not a graphic: only itself
  const s0 = { items: [] };
  const s1 = editItems(s0, scopeItems(plan, plan[1], "role"), { sound: "pop-soft-2" });
  assert.deepEqual(s1.items.map((x) => [x.id, x.sound, x.edited]), [["b", "pop-soft-2", true], ["c", "pop-soft-2", true]]);
  // relative volume: each keeps its balance
  const s2 = editItems(s1, scopeItems(plan, plan[1], "graphic"), (it) => ({ gain: (it.gain || 0) - 3 }));
  assert.deepEqual(Object.fromEntries(s2.items.map((x) => [x.id, x.gain])), { a: -8, b: -5, c: -5 });
  assert.ok(!s2.items.some((x) => x.id === "d" || x.id === "e")); // the other graphic and the transition are untouched
});
