import test from "node:test";
import assert from "node:assert/strict";
import { normaliseLayout, timelineHeight, rulerTicks, captionBlocks, zoomScroll, LAYOUT_DEFAULTS } from "../../web/src/editLayout.js";

test("layout survives bad or partial saved values", () => {
  assert.deepEqual(normaliseLayout(null), LAYOUT_DEFAULTS);
  assert.deepEqual(normaliseLayout("{not json"), LAYOUT_DEFAULTS);
  const v = normaliseLayout(JSON.stringify({ left: 9999, right: 10, timeline: "300", showLeft: false, compact: "yes", cc: 1 }));
  assert.equal(v.left, 620);
  assert.equal(v.right, 280);
  assert.equal(v.timeline, 300);
  assert.equal(v.showLeft, false);
  assert.equal(v.compact, true);
});

test("the timeline never squeezes the preview away", () => {
  assert.equal(timelineHeight(500, 600), 370);
  assert.equal(timelineHeight(100, 600), 150);
  assert.equal(timelineHeight(260, 900), 260);
});

test("ruler ticks follow the zoom", () => {
  const wide = rulerTicks(600, 1200);
  assert.equal(wide.step, 60);
  assert.deepEqual(wide.major.slice(0, 3), [0, 60, 120]);
  const close = rulerTicks(600, 24000);
  assert.equal(close.step, 5);
  assert.ok(close.minor.length > close.major.length);
  assert.deepEqual(rulerTicks(0, 1000).major, []);
});

test("caption blocks use exact captions, else 9-word chunks", () => {
  const scenes = [
    { id: "a", duration: 10, captions: [{ start: 1, end: 3, text: "Exact one" }, { start: 4, end: 20, text: "Clipped" }] },
    { id: "b", duration: 6, narration: "one two three four five six seven eight nine ten eleven" },
    { id: "c", duration: 4, narration: "" },
  ];
  const out = captionBlocks(scenes, [0, 10, 16]);
  assert.deepEqual(out.map((c) => [c.sceneId, c.start, c.end, c.text]), [
    ["a", 1, 3, "Exact one"],
    ["a", 4, 10, "Clipped"],
    ["b", 10, 13, "one two three four five six seven eight nine"],
    ["b", 13, 16, "ten eleven"],
  ]);
});

test("zooming keeps the moment under the pointer in place", () => {
  assert.equal(zoomScroll(0, 100, 1, 2), 100);
  assert.equal(zoomScroll(300, 200, 2, 4), 800);
  assert.equal(zoomScroll(0, 0, 2, 1), 0);
});

test("v0.4.59 the timeline opens with room for all five lanes (the Sound FX lane was hidden)", () => {
  // a layout saved before v0.4.59 with the old default height opens at the new one
  assert.equal(normaliseLayout(JSON.stringify({ timeline: 262, left: 300 })).timeline, LAYOUT_DEFAULTS.timeline);
  assert.equal(normaliseLayout(JSON.stringify({ timeline: 262, left: 330, cc: 1 })).left, 330);
  // a height you chose is kept, also the old default once saved again by v0.4.59
  assert.equal(normaliseLayout(JSON.stringify({ timeline: 240 })).timeline, 240);
  assert.equal(normaliseLayout(JSON.stringify({ timeline: 262, lanes: 5 })).timeline, 262);
});

test("v0.4.67 CapCut-style panels: a wide left panel, the Director closed until opened", () => {
  assert.equal(LAYOUT_DEFAULTS.left, 440);
  assert.equal(LAYOUT_DEFAULTS.right, 340);
  assert.equal(LAYOUT_DEFAULTS.timeline, 326);
  assert.equal(LAYOUT_DEFAULTS.director, false);
  // a layout saved before v0.4.67 (narrow scene list, open direction bar) opens at the new panel sizes;
  // the timeline height and the hidden/shown panels you chose are kept
  const old = normaliseLayout(JSON.stringify({ left: 240, right: 300, timeline: 400, director: true, showRight: false, lanes: 5 }));
  assert.deepEqual([old.left, old.right, old.director, old.timeline, old.showRight, old.cc], [440, 340, false, 400, false, 1]);
  // once saved by v0.4.67, your own sizes and an open Director are kept
  const mine = normaliseLayout(JSON.stringify({ ...old, left: 520, director: true }));
  assert.deepEqual([mine.left, mine.director], [520, true]);
});
