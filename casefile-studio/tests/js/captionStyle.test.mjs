import test from "node:test";
import assert from "node:assert/strict";
import { normaliseStyle, applyPreset, captionAt, captionCss, chunks } from "../../web/src/captionStyle.js";

test("presets and limits", () => {
  const s = normaliseStyle({ preset: "pop", size: 9, color: "red" });
  assert.equal(s.size, 0.1);
  assert.equal(s.color, "#FFFFFF");
  assert.equal(s.font, "inter-black");
  assert.equal(normaliseStyle(null).preset, "documentary");
});

test("a preset keeps where you put the captions unless it has its own place", () => {
  assert.equal(applyPreset({ position: 0.4 }, "clean").position, 0.4);
  assert.equal(applyPreset({ position: 0.4 }, "highlight").position, 0.14);
});

test("the highlighted word follows the time", () => {
  const scene = { duration: 4, captions: [{ start: 0, end: 4, text: "one two three four" }] };
  const style = { preset: "highlight" };
  assert.deepEqual(captionAt(scene, 0.1, style).words, ["ONE", "TWO", "THREE", "FOUR"]);
  assert.equal(captionAt(scene, 0.1, style).active, 0);
  assert.equal(captionAt(scene, 3.9, style).active, 3);
  assert.equal(captionAt(scene, 5, style), null);
});

test("CSS sizes come from the frame height and the font's ratio", () => {
  const css = captionCss({ preset: "highlight" }, 1280, 720);
  assert.equal(css.wrap.fontSize, "37.44px");
  assert.equal(css.wrap.bottom, "100.80px");
  assert.equal(css.wrap.lineHeight, (1 / 0.5675).toFixed(4));
  assert.ok(css.text.WebkitTextStroke.startsWith("8.64px"));
  assert.equal(chunks([{ start: 0, end: 1, text: "a b c" }], 2).length, 2);
});
