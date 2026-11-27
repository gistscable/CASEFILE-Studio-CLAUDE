import test from "node:test";
import assert from "node:assert/strict";
import { normaliseItem, normaliseMotion, graphicAt, graphicsAt, cleanLook } from "../../web/src/motion.js";

// v0.4.62 the story-aware (cinematic) graphics in the editor
const cine = (over = {}) => ({
  id: "cg1", template: "cinematic", status: "suggested", start: 10, end: 0, collection: "truecrime", category: "legal",
  text: "He was held without bail.", words: [["He", 0.45, 0.6, 0, 2]], payload: {}, dur: 3.2, photos: {}, ...over,
});

test("a cinematic graphic survives the editor's normalise, its length as the server computes it", () => {
  const x = normaliseItem(cine());
  assert.equal(x.template, "cinematic");
  assert.equal(x.end, Math.round((10 + Math.round((3.2 + 0.6) * 24) / 24) * 1000) / 1000);
  assert.equal(x.hide_captions, true);
  assert.equal(normaliseItem(cine({ words: [] })), null);
  assert.equal(normaliseItem(cine({ category: "" })), null);
  // covered by the next graphic: shown up to the cut
  assert.equal(normaliseItem(cine({ cut: 30 })).end, 11.25); // 10 + 30 frames at 24 fps
  assert.equal(normaliseItem(cine({ cut: 9999 })).end, normaliseItem(cine()).end); // never longer than the graphic
  // photos keep only their fields
  const p = normaliseItem(cine({ photos: { "place:Court": { asset_id: "a1", credit: "AP", month: "Nov 2026", auto: "yes", x: 1 } } })).photos;
  assert.deepEqual(p, { "place:Court": { asset_id: "a1", credit: "AP", month: "Nov 2026", auto: false } });
});

test("classic and cinematic graphics live side by side", () => {
  const m = normaliseMotion({ enabled: true, items: [cine({ status: "approved" }), { id: "c", template: "findings", status: "approved", start: 40, end: 48, lines: [] }] });
  assert.deepEqual(m.items.map((x) => x.template), ["cinematic", "findings"]);
});

test("back to back, the preview stacks the graphics as the export does (later one on top)", () => {
  const a = cine({ id: "a", status: "approved", start: 10, cut: 60 });
  const b = cine({ id: "b", status: "approved", start: 12.3 });
  const motion = { enabled: true, items: [b, a] };
  assert.deepEqual(graphicsAt(motion, 12.4, null).map((g) => g.item.id), ["a", "b"]);
  assert.deepEqual(graphicsAt(motion, 11, null).map((g) => g.item.id), ["a"]);
  assert.deepEqual(graphicsAt(motion, 12.4, "b").map((g) => g.item.id), ["b"]); // editing one: it alone
  assert.deepEqual(graphicsAt({ ...motion, enabled: false }, 12.4, null), []);
  assert.equal(graphicAt(motion, 11, null).item.id, "a");
});

// v0.4.63 the look of the cinematic graphics
test("the project look survives the editor's normalise, keeping only the choices made", () => {
  assert.equal("look" in normaliseMotion({ enabled: true, items: [] }), false);
  const m = normaliseMotion({ enabled: true, items: [cine({ look: { palette: "B" } })], look: { vary: true, seed: "p1", palettes: { legal: "C" }, background: "footage", dim: 0.5 } });
  assert.deepEqual(m.look, { vary: true, seed: "p1", palettes: { legal: "C" }, background: "footage", dim: 0.5 });
  assert.deepEqual(m.items[0].look, { palette: "B" });
  // switching a choice off removes what depended on it
  assert.deepEqual(cleanLook({ vary: false, seed: "p1", palettes: { legal: undefined }, background: undefined, dim: 0.5, photo_id: "a", accent: "" }), {});
  assert.deepEqual(cleanLook({ background: "photo", photo_id: "a", still_at: 3 }), { background: "photo", photo_id: "a" });
  assert.deepEqual(cleanLook({ background: "still", still_at: 3, photo_id: "a", text: "own" }), { background: "still", still_at: 3, text: "own" });
});
