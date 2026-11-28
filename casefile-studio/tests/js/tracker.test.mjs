// v0.4.72 following something on screen, and the sticker extras
import test from "node:test";
import assert from "node:assert/strict";
import { makeTracker, simplifyPath, match, patchSize, TRACK } from "../../web/src/tracker.js";
import { normaliseStickers, stickerAspect, stickerFrameUrl, cleanText, blurPx, regionOf } from "../../web/src/stickers.js";

// a textured grey frame with a bright, detailed blob centred at (cx, cy)
function frame(w, h, cx, cy, seed = 1) {
  const data = new Float32Array(w * h);
  let s = seed;
  for (let i = 0; i < data.length; i++) {
    s = (s * 16807) % 2147483647;
    data[i] = 60 + (s % 40);
  }
  for (let y = -8; y <= 8; y++)
    for (let x = -8; x <= 8; x++) {
      const px = Math.round(cx + x);
      const py = Math.round(cy + y);
      if (px >= 0 && py >= 0 && px < w && py < h) data[py * w + px] = 200 + ((x * 7 + y * 13) % 5) * 10 + (x > 0 ? 30 : 0);
    }
  return { data, w, h };
}

test("the tracker follows a moving thing", () => {
  const w = 240;
  const h = 135;
  const tr = makeTracker();
  assert.ok(tr.start(frame(w, h, 60, 60), 60 / w, 60 / h, 0.1));
  let r;
  for (let i = 1; i <= 20; i++) {
    r = tr.next(frame(w, h, 60 + i * 4, 60 + i * 1.5, 1));
    assert.equal(r.lost, false, `step ${i}`);
  }
  assert.ok(Math.abs(r.x * w - 140) <= 1.5 && Math.abs(r.y * h - 90) <= 1.5, JSON.stringify(r));
});

test("a still picture does not drift; a cut is lost", () => {
  const w = 240;
  const h = 135;
  const tr = makeTracker();
  tr.start(frame(w, h, 100, 70), 100 / w, 70 / h, 0.1);
  for (let i = 0; i < 10; i++) {
    const r = tr.next(frame(w, h, 100, 70));
    assert.ok(Math.abs(r.x * w - 100) < 0.01 && Math.abs(r.y * h - 70) < 0.01);
  }
  const flat = { data: new Float32Array(w * h).fill(90), w, h };
  assert.equal(tr.next(flat).lost, true);
});

test("match and patch size", () => {
  const f = frame(120, 80, 50, 40);
  const p = new Float32Array(16 * 16);
  for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) p[y * 16 + x] = f.data[(32 + y) * 120 + 42 + x];
  const m = match(f.data, 120, 80, p, 16, 45, 35, 10);
  assert.deepEqual([m.x, m.y], [50, 40]);
  assert.ok(m.score > 0.999);
  assert.equal(patchSize(0.01), TRACK.patch[0]);
  assert.equal(patchSize(1), TRACK.patch[1]);
});

test("simplifyPath keeps the shape, drops the straight bits, caps the count", () => {
  const line = Array.from({ length: 50 }, (_, i) => ({ t: i / 12, x: 0.1 + i * 0.01, y: 0.5 }));
  assert.equal(simplifyPath(line).length, 2);
  const corner = [...line.slice(0, 25), ...Array.from({ length: 25 }, (_, i) => ({ t: (25 + i) / 12, x: 0.34, y: 0.5 + i * 0.01 }))];
  assert.ok(simplifyPath(corner).length >= 3);
  const zig = Array.from({ length: 400 }, (_, i) => ({ t: i / 12, x: 0.5 + (i % 2 ? 0.1 : -0.1), y: 0.5 }));
  const z = simplifyPath(zig);
  assert.equal(z.length, TRACK.max);
  assert.equal(z[0], zig[0]);
  assert.equal(z[z.length - 1], zig[zig.length - 1]);
});

test("stickers: words, shape, strength", () => {
  const [a, b, c] = normaliseStickers([
    { kind: "callout", text: " Suspect\n car ", ratio: 2 },
    { kind: "spotlight", strength: 0.6, ratio: 1 },
    { kind: "blur", strength: 1 },
  ]);
  assert.equal(a.text, "Suspect car");
  assert.equal(stickerAspect(a), 2);
  assert.equal(stickerFrameUrl("callout", 0, a), "/api/stickers/callout/0.png?text=Suspect%20car&ratio=2");
  assert.ok(!("strength" in b) && !("ratio" in b));
  assert.equal(regionOf(b), "spot");
  assert.equal(c.strength, 1);
  assert.ok(Math.abs(blurPx(c, 1000) - 0.82 * 35) < 1e-9);
  assert.equal(cleanText("😀".repeat(30)), "😀".repeat(28));
  const many = normaliseStickers([{ kind: "pointer", length: 30, keyframes: Array.from({ length: 300 }, (_, i) => ({ t: i / 10, x: 0.5 })) }]);
  assert.equal(many[0].keyframes.length, 120);
});

test("text templates: paragraphs, intro once, label", async () => {
  const { frameIndex, cleanLines, linesOf, stickerLabel, CATALOG } = await import("../../web/src/stickers.js");
  const [a, b] = normaliseStickers([
    { kind: "tt-lower", lines: ["JANE DOE", "Lead detective"] },
    { kind: "tt-lower", lines: [" Sam\nRivers ", ""] },
  ]);
  assert.ok(!("lines" in a));
  assert.deepEqual(b.lines, ["Sam Rivers", ""]);
  assert.deepEqual(linesOf(a), CATALOG["tt-lower"].lines);
  assert.equal(stickerLabel(b), "Lower third · Sam Rivers");
  assert.deepEqual(cleanLines(["x".repeat(80)], ["A", "B"]), ["x".repeat(60), "B"]);
  const n = Math.round(CATALOG["tt-lower"].cycle * 24);
  assert.equal(frameIndex("tt-lower", 0), 0);
  assert.equal(frameIndex("tt-lower", 30), n - 1); // holds
  assert.equal(frameIndex("bell", 0.5), 12); // loops still loop
  assert.equal(stickerFrameUrl("tt-lower", 30, b), `/api/stickers/tt-lower/${n - 1}.png?l=Sam%20Rivers&l=`);
});
