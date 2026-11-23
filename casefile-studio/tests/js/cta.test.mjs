import test from "node:test";
import assert from "node:assert/strict";
import { ctaState, ctaPlacement, ctaEvents, normaliseCta } from "../../web/src/cta.js";

test("the preview timeline matches the export's", () => {
  assert.equal(ctaState(0, 5).fade, 0);
  assert.equal(ctaState(1, 5).fade, 1);
  assert.equal(ctaState(2, 5).subscribed, true);
  assert.equal(ctaState(1.4, 5).subscribed, false);
  assert.ok(ctaState(4.9, 5).fade < 0.3);
});

test("banner placement and events", () => {
  assert.deepEqual(ctaPlacement(1280, 720, 2048, 1152), { x: 0, y: 0, w: 1280, h: 720 });
  const tall = ctaPlacement(720, 1280, 2048, 1152);
  assert.ok(Math.abs(tall.w - 662.4) < 0.01 && tall.y > 400);
  const scenes = [
    { duration: 4, narration: "Hi", chapter: "HOOK" },
    { duration: 6, narration: "Please subscribe.", chapter: "SUBSCRIBE CTA" },
  ];
  const caps = (s) => (s.narration.includes("subscribe") ? [{ start: 2, end: 6, text: "Please subscribe." }] : []);
  assert.deepEqual(ctaEvents({ scenes, cta: { enabled: true, asset_id: "b" } }, [0, 4], caps), [[5.5, 10]]);
  assert.deepEqual(ctaEvents({ scenes, cta: { enabled: false, asset_id: "b" } }, [0, 4], caps), []);
  assert.equal(normaliseCta({ opacity: 5 }).opacity, 1);
});
