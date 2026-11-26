// v0.4.60 Browser QA of the Sound FX lane and of playback sync, in a real Chromium against a running app.
//
//   node browser_timeline_qa.mjs <base url> <project id> <out.json>
//
// Needs puppeteer-core and a Chromium (CHROME=/path, default /tmp/chromium); run it from a folder where
// puppeteer-core is installed. The project: qa_app_project.py (40 s narration, 4 scenes, music on scene 2 /
// chapter 2 with crossfades, sound design on).
//
// 1. Manual Sound FX straight from the timeline, all WHILE PLAYING: double-click the Sound FX lane (the
//    moment is pinned), pick a sound in the library ("+ at"), select it on the lane, drag it 2 s later,
//    audition it, change its volume, delete it with the Delete key. After each step: still playing, the
//    narration never paused or re-seeked by it, only `sound` saved (no scene / storyboard change), the
//    scene clips on the timeline unchanged, and the sound really heard at its (moved) time.
// 2. Sync of narration, music and effects through repeated seeks, playhead drags, pause / play and timeline
//    edits during playback: each engine's timeline position is read side by side (narration = its media
//    element, music = its element mapped through the music layout, effects = the audio-clock anchor) and
//    compared with the steady-state offsets measured first; the effects onset is also checked by ear
//    (recorded from the effects bus) against the narration's position.
import puppeteer from "puppeteer-core";
import fs from "fs";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const PID = process.argv[3];
const OUT = process.argv[4] || "browser-timeline-qa.json";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const report = { base: BASE, project: PID, timeline_sfx: {}, sync: {} };

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || "/tmp/chromium",
  headless: true,
  args: ["--no-sandbox", "--autoplay-policy=no-user-gesture-required", "--disable-gpu", "--window-size=1600,1000"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000 });
const pageErrors = [];
page.on("pageerror", (e) => { pageErrors.push(e.message); console.log("page error:", e.message); });
const T0 = Date.now();
if (process.env.QA_DEBUG) {
  page.on("requestfinished", (r) => { if (/sound\/plan/.test(r.url()) || r.method() === "PATCH") console.log(`  [${Date.now() - T0} ms] ${r.method()} ${r.url().split("/api/")[1]}`); });
  page.on("console", (m) => console.log("  console:", m.text()));
}
await page.evaluateOnNewDocument(() => {
  window.__casefileQA = {};
  const log = (window.__qaLog = { patches: [], pauses: [], seeks: [] });
  const of = window.fetch;
  window.fetch = (u, o = {}) => {
    if ((o.method || "GET") === "PATCH") log.patches.push({ t: performance.now(), url: String(u), body: String(o.body || "") });
    return of(u, o);
  };
  document.addEventListener("pause", (e) => { if (e.target?.dataset?.qaVoice) log.pauses.push(performance.now()); }, true);
  document.addEventListener("seeking", (e) => { if (e.target?.dataset?.qaVoice) log.seeks.push(performance.now()); }, true);
});

async function clickText(selector, re) {
  const ok = await page.evaluate((sel, src) => {
    const r = new RegExp(src);
    const el = [...document.querySelectorAll(sel)].find((x) => r.test(x.textContent.trim()));
    if (el) el.click();
    return !!el;
  }, selector, re.source);
  if (!ok) throw new Error(`nothing to click: ${selector} ${re}`);
}
const shot = (name) => page.screenshot({ path: OUT.replace(/\.json$/, `-${name}.png`) });

await page.goto(`${BASE}/?project=${PID}`, { waitUntil: "networkidle2" });
await sleep(800);
const editorShown = () => page.evaluate(() => (document.querySelector(".timeline-content")?.getBoundingClientRect().width || 0) > 0);
if (!(await editorShown())) {
  await page.evaluate(() => {
    const el = [...document.querySelectorAll("button, a, [role=button], div, h3, b, strong")].filter((x) => x.textContent.trim() === "QA sound").pop();
    (el?.closest("button, a, [role=button]") || el)?.click();
  });
  await sleep(1500);
}
await clickText("button, a", /^0\d\s*Edit/).catch(() => {});
await page.waitForFunction(() => (document.querySelector(".timeline-content")?.getBoundingClientRect().width || 0) > 0, { timeout: 15000 });
await page.waitForSelector(".sfx-lane", { timeout: 15000 });
await clickText(".inspector-tabs button", /^Sound$/);
await sleep(600);
const DUR = 40;

// recorder: RMS per 128-sample block of the effects bus (0) and the audition bus (1)
await page.evaluate(async () => {
  const sfx = window.__casefileQA.sfx;
  const ctx = sfx.ensure();
  await ctx.resume();
  const code = `class R extends AudioWorkletProcessor{constructor(){super();this.buf=[];this.port.onmessage=()=>{this.port.postMessage(this.buf);this.buf=[]}}
    process(ins){const row=[currentTime];for(const inp of ins){let s=0,n=0;for(const ch of inp){for(let i=0;i<ch.length;i++)s+=ch[i]*ch[i];n+=ch.length}row.push(n?Math.sqrt(s/n):0)}this.buf.push(row);return true}}
    registerProcessor('qa-rec',R)`;
  await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([code], { type: "text/javascript" })));
  const rec = new AudioWorkletNode(ctx, "qa-rec", { numberOfInputs: 2, numberOfOutputs: 1 });
  const z = ctx.createGain();
  z.gain.value = 0;
  rec.connect(z).connect(ctx.destination);
  sfx.out.connect(rec, 0, 0);
  sfx.audOut.connect(rec, 0, 1);
  window.__qa = { ctx, rec, pull: () => new Promise((r) => { rec.port.onmessage = (e) => r(e.data); rec.port.postMessage(0); }) };
});
const pull = () => page.evaluate(() => window.__qa.pull());

// the narration element (voice.wav) is watched for pauses / seeks it was not asked for
const markVoice = () => page.evaluate(() => {
  const v = [...document.querySelectorAll("audio, video")].find((e) => /voice\.wav/.test(e.currentSrc || e.src));
  if (v) v.dataset.qaVoice = "1";
  return !!v;
});
const isPlaying = () => page.evaluate(() => !!document.querySelector('[aria-label="Pause preview"]'));
const play = () => page.evaluate(() => document.querySelector('[aria-label="Play preview"]')?.click());
const pause = () => page.evaluate(() => document.querySelector('[aria-label="Pause preview"]')?.click());
const xOf = (t) => page.evaluate((t, D) => { const r = document.querySelector(".timeline-content").getBoundingClientRect(); return r.left + (t / D) * r.width; }, t, DUR);
const seek = async (t) => {
  await page.evaluate((t, D) => {
    const c = document.querySelector(".timeline-content"), ruler = c.querySelector(".ruler");
    const r = c.getBoundingClientRect(), rr = ruler.getBoundingClientRect();
    const x = r.left + (t / D) * r.width, y = rr.top + rr.height / 2;
    ruler.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 }));
    window.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: x, clientY: y }));
  }, t, DUR);
};
const clips = () => page.evaluate(() => [...document.querySelectorAll(".timeline-content .clip, .timeline-content [class*='scene-clip']")]
  .map((c) => `${c.style.left}|${c.style.width}`).join(","));
const voiceState = () => page.evaluate(() => {
  const v = document.querySelector("[data-qa-voice]");
  return v ? { paused: v.paused, t: +v.currentTime.toFixed(3) } : null;
});
const laneMarks = () => page.evaluate(() => [...document.querySelectorAll(".sfx-lane .sfx-mark.manual")].map((m) => ({ left: m.style.left, on: m.classList.contains("on") })));
const since = (n) => page.evaluate((n) => ({ patches: window.__qaLog.patches.slice(n.p), pauses: window.__qaLog.pauses.length - n.pa, seeks: window.__qaLog.seeks.length - n.s }), n);
const mark0 = () => page.evaluate(() => ({ p: window.__qaLog.patches.length, pa: window.__qaLog.pauses.length, s: window.__qaLog.seeks.length }));
async function waitPatch(n, re, ms = 6000) {
  for (let k = 0; k < ms / 100; k++) {
    const p = await page.evaluate((n, src) => window.__qaLog.patches.slice(n).find((x) => new RegExp(src).test(x.body)), n, re.source);
    if (p) return p;
    await sleep(100);
  }
  return null;
}
/** One step of the timeline QA: run `act` while playing, then check playback and saves. */
async function step(name, act) {
  const n = await mark0();
  const clips0 = await clips();
  const v0 = await voiceState();
  const out = (await act(n)) || {};
  await sleep(500);
  const s = await since(n);
  const v1 = await voiceState();
  out.still_playing = await isPlaying();
  out.narration_paused_or_reseeked = s.pauses + s.seeks;
  out.narration_moved_on = v0 && v1 ? +(v1.t - v0.t).toFixed(2) : null;
  out.saves = s.patches.length;
  out.saved_only_sound = s.patches.every((p) => { try { return Object.keys(JSON.parse(p.body)).every((k) => k === "sound"); } catch { return false; } });
  out.scene_clips_unchanged = clips0 === (await clips());
  report.timeline_sfx[name] = out;
  console.log(name, JSON.stringify(out));
  return out;
}
const startPlaying = async (at) => {
  if (await isPlaying()) await pause();
  await sleep(150);
  await seek(at);
  await sleep(200);
  await play();
  for (let k = 0; k < 40 && !(await markVoice()); k++) await sleep(50);
  await sleep(400);
};

// ------------------------------------------------------------------ 1. manual Sound FX from the timeline
await startPlaying(1.0);
let manualId = null;
await step("add: double-click the lane at 14 s, pick a sound", async (n) => {
  const box = await page.evaluate(() => { const r = document.querySelector(".sfx-lane").getBoundingClientRect(); return { y: r.top + r.height / 2 }; });
  const x = await xOf(14);
  await page.mouse.click(x, box.y, { clickCount: 2 });
  await sleep(400);
  const pin = await page.evaluate(() => document.querySelector(".sfx-lane .sfx-pin")?.style.left || null);
  await page.waitForSelector('input[aria-label="Search sounds"]', { timeout: 5000 });
  await page.evaluate(() => { const i = document.querySelector('input[aria-label="Search sounds"]'); i.value = ""; });
  await page.type('input[aria-label="Search sounds"]', "bell");
  await sleep(300);
  const label = await page.$eval(".sfx-lib-list .sfx-lib-row .text-link", (b) => b.textContent.trim());
  await page.evaluate(() => document.querySelector(".sfx-lib-list .sfx-lib-row .text-link").click());
  const p = await waitPatch(n.p, /"source":"manual"/);
  const item = p ? JSON.parse(p.body).sound.items.find((x) => x.source === "manual") : null;
  manualId = item?.id;
  let marks = [];
  for (let k = 0; k < 30 && !marks.length; k++) { await sleep(150); marks = await laneMarks(); }
  return { pinned_at: pin, button: label, anchor: item?.anchor, on_lane: marks[0] || null, pin_cleared: !(await page.$(".sfx-lane .sfx-pin")) };
});
await step("select: click the sound on the lane", async () => {
  const t0 = await voiceState();
  await page.evaluate(() => {
    const m = document.querySelector(".sfx-lane .sfx-mark.manual");
    const r = m.getBoundingClientRect();
    m.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, clientX: r.left + 1, clientY: r.top + 2, button: 0 }));
    window.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: r.left + 1, clientY: r.top + 2 }));
  });
  await sleep(300);
  const t1 = await voiceState();
  return { selected: (await laneMarks())[0]?.on || false, inspector_shows_it: await page.evaluate(() => !!document.querySelector('.st-actions button[aria-pressed]')),
           playhead_jumped: t0 && t1 ? Math.abs(t1.t - t0.t) > 1.0 : null };
});
await step("move: drag it 2 s later on the lane", async (n) => {
  const before = (await laneMarks())[0]?.left;
  const r = await page.evaluate(() => { const b = document.querySelector(".sfx-lane .sfx-mark.manual").getBoundingClientRect(); return { x: b.left + 1, y: b.top + b.height / 2 }; });
  const dx = (await xOf(2)) - (await xOf(0));
  await page.mouse.move(r.x, r.y);
  await page.mouse.down();
  for (let k = 1; k <= 6; k++) { await page.mouse.move(r.x + (dx * k) / 6, r.y); await sleep(40); }
  await page.mouse.up();
  const p = await waitPatch(n.p, /"offset":/);
  const item = p ? JSON.parse(p.body).sound.items.find((x) => x.id === manualId) : null;
  let after = before;
  for (let k = 0; k < 30 && after === before; k++) { await sleep(150); after = (await laneMarks())[0]?.left; }
  return { offset_saved: item?.offset ?? null, lane_left: [before, after] };
});
// the moved sound is heard at 16 s (14 + 2): playback from 15 s, the effects bus recorded
const heardAt = async (from, until) => {
  await startPlaying(from);
  await pull();
  const pts = [];
  const t0 = performance.now();
  while (performance.now() - t0 < (until - from) * 1000 + 300) {
    pts.push(await page.evaluate(() => { const v = document.querySelector("[data-qa-voice]"); return [window.__qa.ctx.currentTime, v ? v.currentTime : null]; }));
    await sleep(30);
  }
  const rows = await pull();
  const peak = Math.max(0, ...rows.map((r) => r[1]));
  const on = rows.find((r) => r[1] > Math.max(1e-4, peak * 0.1));
  if (!on) return { at: null, peak };
  // the narration's position at the moment the effect was first heard (interpolated)
  const i = pts.findIndex((p) => p[0] >= on[0]);
  if (i < 1) return null;
  const [a, b] = [pts[i - 1], pts[i]];
  return { at: +(a[1] + ((on[0] - a[0]) / (b[0] - a[0])) * (b[1] - a[1])).toFixed(3), peak: +peak.toFixed(4) };
};
report.timeline_sfx["heard: the moved sound, narration position at its onset"] = { expected: 16.0, ...(await heardAt(15.0, 17.0)) };
console.log("heard", JSON.stringify(report.timeline_sfx["heard: the moved sound, narration position at its onset"]));
await startPlaying(20.0);
await step("audition: the Sound button in the inspector", async () => {
  await clickText(".inspector-tabs button", /^Sound$/);
  await sleep(200);
  await pull();
  await page.evaluate(() => [...document.querySelectorAll(".st-actions button")].find((b) => /^Sound$/.test(b.textContent.trim()))?.click());
  let heard = false;
  for (let k = 0; k < 20 && !heard; k++) { await sleep(60); heard = (await pull()).some((r) => r[2] > 1e-4); }
  await page.evaluate(() => window.__casefileQA.sfx.stopAudition());
  return { audition_heard: heard };
});
await step("volume: the sound's own slider", async (n) => {
  const box = await page.evaluate(() => {
    const el = document.querySelector('input[type=range][aria-label="Volume"]');
    if (!el) return null;
    el.scrollIntoView({ block: "center" });
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top + r.height / 2, w: r.width, v: +el.value, min: +el.min, max: +el.max };
  });
  if (!box) return { slider: "missing" };
  await sleep(100);
  const from = box.x + ((box.v - box.min) / (box.max - box.min)) * box.w, to = box.x + 0.2 * box.w;
  await page.mouse.move(from, box.y);
  await page.mouse.down();
  for (let k = 1; k <= 6; k++) { await page.mouse.move(from + ((to - from) * k) / 6, box.y); await sleep(40); }
  await page.mouse.up();
  const p = await waitPatch(n.p, /"gain":/);
  const item = p ? JSON.parse(p.body).sound.items.find((x) => x.id === manualId) : null;
  return { from: box.v, saved_gain: item?.gain ?? null };
});
await step("delete: the Delete key on the selected sound", async (n) => {
  await page.evaluate(() => {
    const m = document.querySelector(".sfx-lane .sfx-mark.manual");
    const r = m.getBoundingClientRect();
    m.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, clientX: r.left + 1, clientY: r.top + 2, button: 0 }));
    window.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: r.left + 1, clientY: r.top + 2 }));
  });
  await sleep(200);
  await page.keyboard.press("Delete");
  const p = await waitPatch(n.p, /"sound":/);
  const gone = p ? !JSON.parse(p.body).sound.items.some((x) => x.id === manualId) : false;
  let marks = [1];
  for (let k = 0; k < 30 && marks.length; k++) { await sleep(150); marks = await laneMarks(); }
  return { removed_from_saved_project: gone, lane_marks_left: marks.length };
});
await shot("timeline-sfx");
await pause();

// ------------------------------------------------------------------ 2. sync under seeks, drags, pause/play and edits
// a sound to be heard during the sync checks, at 30 s (added through the API: the app reloads it)
await page.evaluate(async (pid) => {
  const p = await (await fetch(`/api/projects/${pid}`)).json();
  const s = p.sound;
  s.items = [...(s.items || []).filter((x) => x.source !== "manual"), { id: "mqa30", anchor: "t:30.000", kind: "manual", sound: "bell-1", gain: 0, status: "approved", source: "manual", label: "qa", reason: "added by you" }];
  await fetch(`/api/projects/${pid}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sound: s }) });
}, PID);
await page.reload({ waitUntil: "networkidle2" });
await sleep(1000);
if (!(await editorShown())) { await clickText("button, a", /^0\d\s*Edit/).catch(() => {}); }
await page.waitForFunction(() => (document.querySelector(".timeline-content")?.getBoundingClientRect().width || 0) > 0, { timeout: 15000 });
await sleep(800);
await page.evaluate(async () => {
  const sfx = window.__casefileQA.sfx;
  const ctx = sfx.ensure();
  await ctx.resume();
  const code = `class R extends AudioWorkletProcessor{constructor(){super();this.buf=[];this.port.onmessage=()=>{this.port.postMessage(this.buf);this.buf=[]}}
    process(ins){const row=[currentTime];for(const inp of ins){let s=0,n=0;for(const ch of inp){for(let i=0;i<ch.length;i++)s+=ch[i]*ch[i];n+=ch.length}row.push(n?Math.sqrt(s/n):0)}this.buf.push(row);return true}}
    registerProcessor('qa-rec2',R)`;
  await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([code], { type: "text/javascript" })));
  const rec = new AudioWorkletNode(ctx, "qa-rec2", { numberOfInputs: 2, numberOfOutputs: 1 });
  const z = ctx.createGain(); z.gain.value = 0;
  rec.connect(z).connect(ctx.destination);
  sfx.out.connect(rec, 0, 0);
  sfx.audOut.connect(rec, 0, 1);
  window.__qa = { ctx, rec, pull: () => new Promise((r) => { rec.port.onmessage = (e) => r(e.data); rec.port.postMessage(0); }) };
});
// each engine's timeline position, read at one instant
const clocks = () => page.evaluate(() => {
  const v = document.querySelector("[data-qa-voice]") || [...document.querySelectorAll("audio, video")].find((e) => /voice\.wav/.test(e.currentSrc || e.src));
  const s = window.__casefileQA.sfx, m = window.__casefileQA.music;
  const now = s.ctx?.currentTime;
  const fx = s.anchor && now != null ? s.anchor.t + (now - s.anchor.at) : null;
  let mus = null;
  const ref = v ? v.currentTime : fx;
  (m.els || []).forEach((el, slot) => {
    if (!el || el.paused || mus !== null || ref == null) return;
    let best = null;
    for (const x of m.passes || []) {
      if (x.i % 2 !== slot) continue;
      const at = x.at + (el.currentTime - x.src);
      if (at < x.at - 0.05 || at > x.at + x.len + 0.05) continue;
      if (best === null || Math.abs(at - ref) < Math.abs(best - ref)) best = at;
    }
    mus = best;
  });
  return { narr: v && !v.paused ? v.currentTime : null, fx, mus };
});
async function sample(ms) {
  const out = [];
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { out.push(await clocks()); await sleep(40); }
  const med = (a) => { const b = a.filter((x) => x !== null && Number.isFinite(x)).sort((x, y) => x - y); return b.length ? b[b.length >> 1] : null; };
  return { fx: med(out.map((c) => (c.narr !== null && c.fx !== null ? c.fx - c.narr : null))),
           mus: med(out.map((c) => (c.narr !== null && c.mus !== null ? c.mus - c.narr : null))),
           narr: med(out.map((c) => c.narr)) };
}
await markVoice();
await startPlaying(9.0); // inside the music's scene 2 (10-20 s) soon
await sleep(2500);
const base = await sample(1500);
report.sync.steady_offsets_ms = { effects_minus_narration: base.fx !== null ? +(base.fx * 1000).toFixed(1) : null, music_minus_narration: base.mus !== null ? +(base.mus * 1000).toFixed(1) : null };
console.log("steady", JSON.stringify(report.sync.steady_offsets_ms));
const ops = [];
async function check(name, act, settleMs = 1200) {
  await act();
  await sleep(settleMs);
  const s = await sample(700);
  const row = { op: name, playing: await isPlaying(), at: s.narr !== null ? +s.narr.toFixed(2) : null,
                effects_drift_ms: s.fx !== null && base.fx !== null ? +((s.fx - base.fx) * 1000).toFixed(1) : null,
                music_drift_ms: s.mus !== null && base.mus !== null ? +((s.mus - base.mus) * 1000).toFixed(1) : null };
  ops.push(row);
  console.log(JSON.stringify(row));
}
const seekTargets = [12.3, 4.1, 17.8, 10.2, 25.5, 14.9, 2.2, 19.1, 11.0, 15.5, 31.2, 13.3];
// a click / drag on the ruler stops the playback (as in every version): scrub, then play
for (const t of seekTargets) await check(`seek to ${t} s, play`, async () => { await seek(t); await sleep(150); await play(); }, 2500);
for (const [a, b] of [[11, 16], [16, 12], [13, 18]]) {
  await check(`drag the playhead ${a} -> ${b} s, play`, async () => {
    await seek(a);
    await sleep(300);
    const y = await page.evaluate(() => { const r = document.querySelector(".timeline-content .ruler").getBoundingClientRect(); return r.top + r.height / 2; });
    const xa = await xOf(a), xb = await xOf(b);
    await page.mouse.move(xa, y);
    await page.mouse.down();
    for (let k = 1; k <= 10; k++) { await page.mouse.move(xa + ((xb - xa) * k) / 10, y); await sleep(50); }
    await page.mouse.up();
    await sleep(150);
    await play();
  }, 2500);
}
// jumps WHILE playing: select the sound on the lane (no pause since v0.4.60), then its "In context" (2 s before it)
await page.evaluate(() => {
  const m = document.querySelector(".sfx-lane .sfx-mark.manual");
  const r = m.getBoundingClientRect();
  m.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, clientX: r.left + 1, clientY: r.top + 2, button: 0 }));
  window.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: r.left + 1, clientY: r.top + 2 }));
});
await sleep(300);
for (let k = 0; k < 4; k++) {
  await check(`jump while playing ${k + 1} ("In context", to 28 s)`, async () => {
    await page.evaluate(() => [...document.querySelectorAll(".st-actions button")].find((b) => /In context/.test(b.textContent))?.click());
  }, 2500);
  await sleep(1500 + 700 * k);
}
for (let k = 0; k < 5; k++) {
  await check(`pause ${k + 1} / play again`, async () => { await seek(11 + 2 * k); await sleep(100); await play(); await sleep(1500); await pause(); await sleep(400 + 150 * k); await play(); }, 2500);
}
await check("seek while paused, then play", async () => { await pause(); await sleep(200); await seek(13.7); await sleep(300); await play(); }, 2500);
// timeline edits during playback: the effects volume, the music level, a sound moved
await check("edit: effects volume slider (playing)", async () => {
  await clickText(".inspector-tabs button", /^Sound$/);
  await sleep(200);
  await page.evaluate(() => { const el = document.querySelector('input[type=range][aria-label="Effects volume"]'); el?.scrollIntoView({ block: "center" }); });
  const b = await page.evaluate(() => { const r = document.querySelector('input[type=range][aria-label="Effects volume"]')?.getBoundingClientRect(); return r ? { x: r.left, y: r.top + r.height / 2, w: r.width } : null; });
  if (!b) return;
  await page.mouse.move(b.x + b.w * 0.6, b.y); await page.mouse.down();
  for (let k = 1; k <= 5; k++) { await page.mouse.move(b.x + b.w * (0.6 - 0.04 * k), b.y); await sleep(40); }
  await page.mouse.up();
});
await check("edit: music level slider (playing)", async () => {
  await clickText(".inspector-tabs button", /^Audio$/);
  await sleep(200);
  await page.evaluate(() => { const el = document.querySelector('input[type=range][aria-label="Music level"]'); el?.scrollIntoView({ block: "center" }); });
  const b = await page.evaluate(() => { const r = document.querySelector('input[type=range][aria-label="Music level"]')?.getBoundingClientRect(); return r ? { x: r.left, y: r.top + r.height / 2, w: r.width } : null; });
  if (!b) return;
  await page.mouse.move(b.x + b.w * 0.3, b.y); await page.mouse.down();
  for (let k = 1; k <= 5; k++) { await page.mouse.move(b.x + b.w * (0.3 + 0.05 * k), b.y); await sleep(40); }
  await page.mouse.up();
});
await check("edit: a sound dragged on the lane (playing)", async () => {
  const r = await page.evaluate(() => { const m = document.querySelector(".sfx-lane .sfx-mark.manual"); if (!m) return null; const b = m.getBoundingClientRect(); return { x: b.left + 1, y: b.top + b.height / 2 }; });
  if (!r) return;
  const dx = (await xOf(1)) - (await xOf(0));
  await page.mouse.move(r.x, r.y); await page.mouse.down();
  for (let k = 1; k <= 5; k++) { await page.mouse.move(r.x - (dx * k) / 5, r.y); await sleep(40); }
  await page.mouse.up();
}, 2000);
// by ear: the sound now at 29 s (30 - 1) heard on time against the narration
await pause();
const heard29 = await heardAt(27.5, 30.5);
const drifts = (k) => ops.map((o) => o[k]).filter((x) => x !== null);
const maxAbs = (a) => (a.length ? +Math.max(...a.map(Math.abs)).toFixed(1) : null);
report.sync.operations = ops;
report.sync.summary = {
  operations: ops.length,
  always_playing: ops.every((o) => o.playing),
  effects_max_drift_ms: maxAbs(drifts("effects_drift_ms")),
  music_max_drift_ms: maxAbs(drifts("music_drift_ms")),
  music_measured_in: drifts("music_drift_ms").length,
  // absolute offsets from the narration element (ms): what is heard, whatever the steady state
  music_minus_narration_ms: (() => { const a = drifts("music_drift_ms").map((d) => d + report.sync.steady_offsets_ms.music_minus_narration); return a.length ? [+Math.min(...a).toFixed(1), +Math.max(...a).toFixed(1)] : null; })(),
  effects_minus_narration_ms: (() => { const a = drifts("effects_drift_ms").map((d) => d + report.sync.steady_offsets_ms.effects_minus_narration); return a.length ? [+Math.min(...a).toFixed(1), +Math.max(...a).toFixed(1)] : null; })(),
  moved_sound_heard_at: { expected: 29.0, ...heard29 },
};
report.page_errors = pageErrors;
console.log(JSON.stringify(report.sync.summary));
fs.writeFileSync(OUT, JSON.stringify(report, null, 1));
await browser.close();
