import test from "node:test";
import assert from "node:assert/strict";
import { normaliseWatermark, watermarkBox } from "../../web/src/watermark.js";

test("defaults are YouTube's: bottom right, 150 px at 1080p", () => {
  const w = normaliseWatermark({ enabled: true });
  assert.equal(w.position, "bottom-right");
  const b = watermarkBox(1920, 1080, 500, 500, w.position, w.size);
  assert.deepEqual([Math.round(b.x), Math.round(b.y), Math.round(b.w), Math.round(b.h)], [1731, 891, 151, 151]);
});

test("positions and limits match watermark.py", () => {
  assert.equal(normaliseWatermark({ position: "nope", size: 9, opacity: 0 }).position, "bottom-right");
  assert.equal(normaliseWatermark({ size: 9 }).size, 0.4);
  assert.equal(normaliseWatermark({ opacity: 0 }).opacity, 0.2);
  const t = watermarkBox(1080, 1920, 500, 500, "top-center", 0.14);
  assert.deepEqual([Math.round(t.x), Math.round(t.y)], [464, 38]);
  const c = watermarkBox(1920, 1080, 600, 200, "center", 0.14);
  assert.deepEqual([Math.round(c.x), Math.round(c.y), Math.round(c.w), Math.round(c.h)], [884, 515, 151, 50]);
  const ml = watermarkBox(1920, 1080, 100, 100, "middle-left", 0.14);
  assert.equal(Math.round(ml.x), 38);
});
