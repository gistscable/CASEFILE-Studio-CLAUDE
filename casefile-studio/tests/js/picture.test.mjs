import test from "node:test";
import assert from "node:assert/strict";
import { coverBox, containBox, normaliseCrop, cameraTransform, fitOf, upsertKey, normaliseKeyframes } from "../../web/src/picture.js";
import { normaliseStickers, stickerFrameUrl, newSticker } from "../../web/src/stickers.js";

test("cover shows only the crop, filling the frame", () => {
  // a 1600x900 picture cropped to its middle 600x900 strip, in a 640x360 frame
  const b = coverBox(640, 360, 1600, 900, [0.25, 0, 0.625, 1]);
  const s = 640 / 600;
  assert.ok(Math.abs(b.width - 1600 * s) < 1e-9);
  assert.ok(Math.abs(b.left + 400 * s) < 1e-9); // the crop's left edge is at the frame's left edge
  assert.ok(Math.abs(b.top - (180 - 450 * s)) < 1e-9);
});

test("contain puts the whole crop inside the inset, centred", () => {
  const c = containBox(640, 360, 1600, 900, [0.25, 0, 0.625, 1], 0.9);
  assert.ok(Math.abs(c.box.height - 324) < 1e-9 && Math.abs(c.box.width - 216) < 1e-9);
  assert.ok(Math.abs(c.box.left - 212) < 1e-9 && Math.abs(c.img.left + 400 * 0.36) < 1e-9);
});

test("crop, fit and camera", () => {
  assert.deepEqual(normaliseCrop([0.5, 0.1, 0.2, 0.9]), [0.2, 0.1, 0.5, 0.9]);
  assert.equal(normaliseCrop([0, 0, 1, 1]), null);
  assert.equal(fitOf({ aspect: "9:16" }, {}), "legacy-blur");
  assert.equal(fitOf({}, { fit: "blur" }), "blur");
  assert.equal(cameraTransform({ zoom: 1, x: 0.5, y: 0.5 }), "translate(0.000%, 0.000%) scale(1.0000)");
  assert.equal(cameraTransform({ zoom: 2, x: 0.25, y: 0.5 }), "translate(0.000%, -50.000%) scale(2.0000)");
  const k = upsertKey([{ t: 1, zoom: 1, x: 0.5, y: 0.5 }], 1.02, { zoom: 2 }, normaliseKeyframes);
  assert.equal(k.length, 1);
  assert.equal(k[0].t, 1);
  assert.equal(k[0].zoom, 2);
});

test("stickers", () => {
  const s = normaliseStickers([newSticker("bell", 3.2, null, []), { kind: "x" }]);
  assert.equal(s.length, 1);
  assert.equal(s[0].start, 3.2);
  assert.equal(stickerFrameUrl("bell", 0.5), "/api/stickers/bell/12.png");
  assert.equal(stickerFrameUrl("bell", 1.6), "/api/stickers/bell/0.png");
  assert.equal(stickerFrameUrl("like", 9), "/api/stickers/like/0.png");
});
