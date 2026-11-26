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
