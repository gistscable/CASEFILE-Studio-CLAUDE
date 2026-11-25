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
  assert.deepEqual(ctaEvents({ scenes, cta: { enabled: true, asset_id: "b" } }, [0, 4], caps).map(([a, b]) => [a, b]), [[5.5, 10]]);
  assert.deepEqual(ctaEvents({ scenes, cta: { enabled: false, asset_id: "b" } }, [0, 4], caps), []);
  assert.equal(normaliseCta({ opacity: 5 }).opacity, 1);
});

test("v0.4.50 preview stills sit in their part of the card; old soft stills are made again", async () => {
  const { ctaStillBox, ctaStillsCurrent, CTA_PREVIEW_VERSION } = await import("../../web/src/cta.js");
  const card = { left: 100, top: 50, width: 600, height: 337.5 };
  const b = ctaStillBox(card, { box: [0.25, 0.4, 0.75, 0.6] });
  assert.deepEqual([b.left, b.top, b.width, b.height].map((v) => +v.toFixed(3)), [250, 185, 300, 67.5]);
  assert.deepEqual(ctaStillBox(card, { count: 45, fps: 15 }), card); // old stills: the whole card
  assert.equal(CTA_PREVIEW_VERSION, 2);
  assert.equal(ctaStillsCurrent({ version: 2 }), true);
  assert.equal(ctaStillsCurrent({ count: 45, fps: 15 }), false);
  assert.equal(ctaStillsCurrent(undefined), false);
});
