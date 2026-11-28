import test from "node:test";
import assert from "node:assert/strict";
import { audioRoleOf, audioLists, roleBlock, canBeSfx } from "../../web/src/audioRoles.js";

const A = (id, extra = {}) => ({ id, kind: "audio", has_audio: true, duration: 120, ...extra });
const project = {
  narration_id: "nar",
  music_id: "mus",
  assets: [
    A("nar"),
    A("mus"),
    A("nar2", { audio_role: "narration" }),
    A("mus2", { audio_role: "music" }),
    A("hit", { sfx: true, duration: 2 }),
    A("whoosh", { audio_role: "sfx", duration: 1 }),
    A("loose", { duration: 4 }),
    { id: "clip", kind: "video", has_audio: true, duration: 30 },
    { id: "clip2", kind: "video", has_audio: true, duration: 30, audio_role: "music" },
    { id: "pic", kind: "image", has_audio: false },
  ],
};

test("narration, music and sound effects are separate lists", () => {
  const l = audioLists(project);
  assert.deepEqual(l.narration.map((a) => a.id), ["nar", "nar2"]);
  assert.deepEqual(l.music.map((a) => a.id), ["mus", "mus2", "clip2"]);
  assert.deepEqual(l.sfx.map((a) => a.id), ["hit", "whoosh"]);
  assert.deepEqual(l.unsorted.map((a) => a.id), ["loose"]); // footage with sound is not listed unsorted
});

test("the role that uses a file wins over how it was sorted", () => {
  assert.equal(audioRoleOf(A("nar", { audio_role: "music" }), project), "narration");
  assert.equal(audioRoleOf({ id: "pic", kind: "image" }, project), null);
});

test("a file in use cannot move; a long file is no sound effect", () => {
  assert.match(roleBlock(project.assets[0], "music", project), /your narration/);
  assert.match(roleBlock(project.assets[1], "sfx", project), /your music/);
  assert.equal(roleBlock(project.assets[2], "music", project), "");
  assert.match(roleBlock(project.assets[2], "sfx", project), /30 seconds/);
  assert.equal(roleBlock(project.assets[6], "sfx", project), "");
  assert.equal(canBeSfx({ kind: "video", duration: 2 }), false);
});
