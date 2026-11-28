import test from "node:test";
import assert from "node:assert/strict";
import { buildIndex, search, snippet, POPULAR } from "../../web/src/searchIndex.js";

const items = buildIndex({
  scenes: [
    { title: "A town after dark", chapter: "Setting the scene", narration: "The river ran black past the mill that night." },
    { title: "The road to Blackwater", narration: "Detectives found the car two days later." },
  ],
  offsets: [0, 3.5],
  assets: [{ id: "a1", name: "river-at-dusk.jpg", kind: "image" }, { id: "a2", name: "theme.mp3", kind: "audio" }],
  looks: [{ id: "archive", label: "Archive (faded colour)" }],
  transitions: [{ id: "none", label: "None" }, { id: "dissolve", label: "Dissolve" }],
});

test("words people use find the right tool", () => {
  assert.deepEqual(search(items, "watermark")[0].go, { left: ["effects", "logo"] });
  assert.deepEqual(search(items, "subtitles")[0].go, { left: ["captions"] });
  assert.deepEqual(search(items, "voice over")[0].go, { left: ["audio", "voice"] });
  assert.deepEqual(search(items, "sfx")[0].go, { left: ["audio", "sfx"] });
  assert.deepEqual(search(items, "crop")[0].go, { insp: ["video", "picture"] });
  assert.equal(search(items, "9:16")[0].go.action, "ratio");
  assert.equal(search(items, "fullscreen")[0].go.action, "fullscreen");
});

test("scenes, narration words and media files are found", () => {
  const r = search(items, "blackwater");
  assert.deepEqual(r[0].go, { scene: 1, time: 3.5 });
  const d = search(items, "detectives");
  assert.equal(d[0].group, "Scenes");
  assert.match(d[0].snippet, /Detectives found the car/);
  assert.deepEqual(search(items, "theme")[0].go, { asset: "a2" });
  assert.ok(search(items, "archive").some((x) => x.label === "Archive (faded colour) look"));
  assert.ok(search(items, "dissolve").some((x) => x.where === "Transitions"));
  assert.ok(!search(items, "none transition").length);
});

test("nothing for an empty or unknown query; every popular item exists", () => {
  assert.deepEqual(search(items, "   "), []);
  assert.deepEqual(search(items, "zzqx"), []);
  for (const p of POPULAR) assert.ok(items.some((i) => i.label === p), p);
  assert.equal(snippet("short", "nothing"), "");
});
