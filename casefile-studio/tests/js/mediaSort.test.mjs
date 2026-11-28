import { test } from "node:test";
import assert from "node:assert/strict";
import { sortMedia } from "../../web/src/mediaSort.js";

const list = [
  { id: "a", name: "Clip 10.mp4", duration: 4 },
  { id: "b", name: "clip 2.mp4", duration: 12 },
  { id: "c", name: "Archive.jpg" },
  { id: "d", name: "River.jpg" },
];
const ids = (l) => l.map((a) => a.id).join("");

test("oldest keeps import order, newest reverses it", () => {
  assert.equal(ids(sortMedia(list, "oldest")), "abcd");
  assert.equal(ids(sortMedia(list, "newest")), "dcba");
  assert.equal(ids(list), "abcd", "the original list is not changed");
});

test("name sorts naturally, ignoring case", () => {
  assert.equal(ids(sortMedia(list, "name")), "cbad");
});

test("longest first; files without a length keep import order at the end", () => {
  assert.equal(ids(sortMedia(list, "longest")), "bacd");
});

test("order in the edit follows the scenes, then unused files", () => {
  const scenes = [{ asset_id: "d" }, { asset_id: null }, { asset_id: "b" }, { asset_id: "d" }];
  assert.equal(ids(sortMedia(list, "timeline", scenes)), "dbac");
});
