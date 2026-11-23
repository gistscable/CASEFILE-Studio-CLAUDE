import test from "node:test";
import assert from "node:assert/strict";
import { transitionId, transitionLength, motionTransform, transitionStyle, lowerThirdAt, normaliseEffects, letterboxBar } from "../../web/src/effects.js";

test("transition names and lengths follow the export's rules", () => {
  assert.equal(transitionId("cross-dissolve"), "dissolve");
  assert.equal(transitionId("cut"), "none");
  assert.equal(transitionId("spin"), "none");
  assert.equal(transitionLength({ transition: "slide-left" }, 4), 0.5);
  assert.equal(transitionLength({ transition: "slide-left", transition_duration: 9 }, 3), 1.5);
  assert.equal(transitionLength({ transition: "none", transition_duration: 2 }, 9), 0);
});

test("photo movement matches zoompan at the start, middle and end", () => {
  assert.equal(motionTransform("slow-zoom", 0), "scale(1)");
  assert.equal(motionTransform("slow-zoom", 1), "scale(1.075)");
  assert.equal(motionTransform("pan-left", 0.5), "translateX(0.000%) scale(1.08)");
  assert.equal(motionTransform("pan-up", 0), "translateY(-4.000%) scale(1.08)");
  assert.equal(motionTransform("none", 0.5), undefined);
});

test("transition styles run from hidden to fully in", () => {
  assert.deepEqual(transitionStyle("dissolve", 0), { opacity: 0 });
  assert.deepEqual(transitionStyle("slide-left", 1), { transform: "translateX(0%)" });
  assert.equal(transitionStyle("dip-black", 0.25).opacity, 0);
});

test("the name card shows from 0.3 s to 5 s", () => {
  const lt = { name: "A", role: "" };
  assert.equal(lowerThirdAt(lt, 0.1, 10), null);
  assert.ok(lowerThirdAt(lt, 2, 10).opacity === 1);
  assert.equal(lowerThirdAt(lt, 5.2, 10), null);
  assert.equal(lowerThirdAt({ name: "", role: "" }, 2, 10), null);
});

test("effects are clamped and the bars match 2.35:1", () => {
  assert.deepEqual(normaliseEffects({ grain: 3, vignette: -2, letterbox: 1 }), { grain: 1, vignette: 0, letterbox: false });
  assert.equal(Math.round(letterboxBar(1280, 720)), 88);
});

import { textUnit, captionBottom, captionCss } from "../../web/src/captionStyle.js";
import { lowerThirdCss, aspectOf, fitOf } from "../../web/src/effects.js";

test("9:16 sizes text from the width and keeps captions above the app buttons", () => {
  assert.equal(textUnit(1920, 1080), 1080);
  assert.equal(textUnit(1080, 1920), 1080 * 1.4);
  assert.equal(captionBottom(0.075, 1080, 1920), 0.2);
  assert.equal(captionBottom(0.3, 1080, 1920), 0.3);
  assert.equal(captionCss({}, 1080, 1920).wrap.bottom, "384.00px");
  assert.equal(lowerThirdCss(1080, 1920).wrap.bottom, "48%");
  assert.equal(aspectOf({ aspect: "9:16" }), "9:16");
  assert.equal(aspectOf({ aspect: "4:3" }), "16:9");
  assert.equal(fitOf({}), "blur");
});

import { splitWho, effectiveLowerThirds, lowerThirdBottom } from "../../web/src/effects.js";

test("name cards: split, first scene per person, typed wins, gap above labels", () => {
  assert.deepEqual(splitWho("Dedrick Hilton (father)"), { name: "Dedrick Hilton", role: "Father" });
  const scenes = [{ guide_source_id: "S01" }, { guide_source_id: "S01" }, { guide_source_id: "S02", lower_third: { name: "Typed", role: "" } }];
  const people = { S01: { name: "A", role: "B" }, S02: { name: "C", role: "" } };
  assert.deepEqual(Object.keys(effectiveLowerThirds({ scenes, name_cards: { auto: true, people } })), ["0", "2"]);
  assert.deepEqual(Object.keys(effectiveLowerThirds({ scenes, name_cards: { auto: false, people } })), ["2"]);
  assert.equal(lowerThirdBottom(1280, 720, true), 0.27);
  assert.equal(lowerThirdBottom(720, 1280, true), 0.49);
});
