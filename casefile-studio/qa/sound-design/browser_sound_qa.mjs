// v0.4.59 Browser QA of the editor's sound controls in a real Chromium, against a running app.
//
//   node browser_sound_qa.mjs <base url> <project id> <out.json>
//
// Needs puppeteer-core and a Chromium (CHROME=/path, default /tmp/chromium); run it from a folder
// where puppeteer-core is installed. The project should have narration, a music track placed on
// chosen scenes and sound design switched on (qa: /tmp/qa/app, see make the project with qa_app_project.py).
//
// What it measures (all in the page, nothing mocked):
//  1. every library sound is auditioned: it is really heard (its output, recorded from the audition
//     bus with an AudioWorklet, rises above silence), how long from the click until it is heard,
//     and that listening never changes the project (no PATCH);
//  2. a manual sound added at the playhead ("+ at"): saved, drawn on the Sound FX lane, heard in
//     playback (the effects bus at its time) — the "manual sfx" path;
//  3. during playback, every level slider (narration, music, effects, the sound's own volume):
//     the time from the slider moving to the gain change, the level actually heard before / after
//     (recorded from the effects and music buses), no request while dragging, one save on release,
//     and the playback never stopping or re-seeking.
import puppeteer from "puppeteer-core";
import fs from "fs";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const PID = process.argv[3];
const OUT = process.argv[4] || "browser-sound-qa.json";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const report = { base: BASE, project: PID, audition: {}, manual: {}, sliders: {}, playback: {} };

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || "/tmp/chromium",
  headless: true,
  args: ["--no-sandbox", "--autoplay-policy=no-user-gesture-required", "--disable-gpu", "--window-size=1600,1000"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000 });
page.on("pageerror", (e) => console.log("page error:", e.message));
await page.evaluateOnNewDocument(() => {
  window.__casefileQA = {};
  const log = (window.__qaLog = { patches: [], params: [], vols: [], seeks: 0 });
  const of = window.fetch;
  window.fetch = (u, o = {}) => {
    if ((o.method || "GET") === "PATCH") log.patches.push({ t: performance.now(), url: String(u), body: String(o.body || "") });
    return of(u, o);
  };
  const st = AudioParam.prototype.setTargetAtTime;
  AudioParam.prototype.setTargetAtTime = function (v, at, tc) { log.params.push({ t: performance.now(), v }); return st.call(this, v, at, tc); };
  const d = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "volume");
  Object.defineProperty(HTMLMediaElement.prototype, "volume", {
    configurable: true,
    get() { return d.get.call(this); },
    set(v) { log.vols.push({ t: performance.now(), v, src: this.src }); d.set.call(this, v); },
  });
  document.addEventListener("seeking", (e) => { if (e.target?.dataset?.qaWatch) log.seeks++; }, true);
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
// the home screen: open the project (the editor behind it has no size until then)
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
await clickText(".inspector-tabs button", /^Sound$/);
await sleep(500);

// the recorder: RMS per 128-sample block of the effects bus (0), the audition bus (1), the music bus (2)
await page.evaluate(async () => {
  const sfx = window.__casefileQA.sfx;
  const ctx = sfx.ensure();
  await ctx.resume();
  const code = `class R extends AudioWorkletProcessor{constructor(){super();this.buf=[];this.port.onmessage=()=>{this.port.postMessage(this.buf);this.buf=[]}}
    process(ins){const row=[currentTime];for(const inp of ins){let s=0,n=0;for(const ch of inp){for(let i=0;i<ch.length;i++)s+=ch[i]*ch[i];n+=ch.length}row.push(n?Math.sqrt(s/n):0)}this.buf.push(row);return true}}
    registerProcessor('qa-rec',R)`;
  await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([code], { type: "text/javascript" })));
  const rec = new AudioWorkletNode(ctx, "qa-rec", { numberOfInputs: 3, numberOfOutputs: 1 });
  const z = ctx.createGain();
  z.gain.value = 0;
  rec.connect(z).connect(ctx.destination);
  sfx.out.connect(rec, 0, 0);
  sfx.audOut.connect(rec, 0, 1);
  window.__qa = {
    ctx, rec,
    music() { const n = window.__casefileQA.music.nodes; if (n && !n.__qa) { n.duck.connect(rec, 0, 2); n.__qa = 1; } return !!n; },
    pull: () => new Promise((r) => { rec.port.onmessage = (e) => r(e.data); rec.port.postMessage(0); }),
  };
});
const pull = () => page.evaluate(() => window.__qa.pull());
const ctxNow = () => page.evaluate(() => window.__qa.ctx.currentTime);
const db = (x) => +(20 * Math.log10(x + 1e-9)).toFixed(1);
const rmsOf = (rows, ch, t0, t1) => {
  const r = rows.filter((x) => x[0] >= t0 && x[0] < t1);
  return r.length ? Math.sqrt(r.reduce((a, x) => a + x[1 + ch] ** 2, 0) / r.length) : 0;
};

// ------------------------------------------------------------------ 1. audition every library sound
await clickText("button", /^Browse the library$/);
await page.waitForSelector(".sfx-lib-row button.icon-btn", { timeout: 10000 });
const labels = await page.$$eval(".sfx-lib-list .sfx-lib-row button.icon-btn", (bs) => bs.map((b) => b.getAttribute("aria-label").replace(/^Play /, "")));
const patches0 = await page.evaluate(() => window.__qaLog.patches.length);
const heard = [], silent = [], lat = [];
for (const name of labels) {
  await pull();
  const t0 = await ctxNow();
  await page.evaluate((n) => [...document.querySelectorAll(".sfx-lib-list .sfx-lib-row button.icon-btn")].find((b) => b.getAttribute("aria-label") === `Play ${n}`)?.click(), name);
  let first = null;
  for (let k = 0; k < 30 && first === null; k++) {
    await sleep(60);
    for (const row of await pull()) if (row[0] >= t0 && row[2] > 1e-4) { first = row[0]; break; }
  }
  if (first === null) silent.push(name); else { heard.push(name); lat.push((first - t0) * 1000); }
  await page.evaluate(() => window.__casefileQA.sfx.stopAudition());
}
lat.sort((a, b) => a - b);
// a second round: the sounds are now in the browser's memory (as when you listen to one again)
const warm = [];
for (const name of labels.slice(0, 20)) {
  await pull();
  const t0 = await ctxNow();
  await page.evaluate((n) => [...document.querySelectorAll(".sfx-lib-list .sfx-lib-row button.icon-btn")].find((b) => b.getAttribute("aria-label") === `Play ${n}`)?.click(), name);
  let first = null;
  for (let k = 0; k < 30 && first === null; k++) {
    await sleep(30);
    for (const row of await pull()) if (row[0] >= t0 && row[2] > 1e-4) { first = row[0]; break; }
  }
  if (first !== null) warm.push((first - t0) * 1000);
  await page.evaluate(() => window.__casefileQA.sfx.stopAudition());
}
warm.sort((a, b) => a - b);
report.audition = {
  again_click_to_sound_ms: warm.length ? { sounds: warm.length, median: +warm[warm.length >> 1].toFixed(1), max: +warm.at(-1).toFixed(1) } : null,
  sounds: labels.length, heard: heard.length, silent,
  first_time_click_to_sound_ms: { median: +lat[lat.length >> 1].toFixed(1), p95: +lat[Math.floor(lat.length * 0.95)].toFixed(1), max: +lat.at(-1).toFixed(1) },
  project_changed_while_listening: (await page.evaluate(() => window.__qaLog.patches.length)) - patches0,
};
console.log("audition", JSON.stringify(report.audition));

// ------------------------------------------------------------------ 2. a manual sound at 12 s
const seek = async (t) => {
  await page.evaluate((t) => {
    const c = document.querySelector(".timeline-content"), ruler = c.querySelector(".ruler");
    const r = c.getBoundingClientRect(), rr = ruler.getBoundingClientRect();
    const x = r.left + (t / window.__qaDur) * r.width, y = rr.top + rr.height / 2;
    ruler.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 }));
    window.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: x, clientY: y }));
  }, t);
  await sleep(250);
};
await page.evaluate(() => { window.__qaDur = 40; });
await page.type('input[aria-label="Search sounds"]', "swell");
await sleep(300);
await seek(12);
const addLabel = await page.$eval(".sfx-lib-list .sfx-lib-row .text-link", (b) => b.textContent.trim());
const before = await page.evaluate(() => window.__qaLog.patches.length);
await page.evaluate(() => document.querySelector(".sfx-lib-list .sfx-lib-row .text-link").click());
let saved = null;
for (let k = 0; k < 40 && !saved; k++) {
  await sleep(150);
  saved = await page.evaluate((n) => window.__qaLog.patches.slice(n).find((p) => p.body.includes('"source":"manual"')), before);
}
let mark = null;
for (let k = 0; k < 40 && !mark; k++) {
  await sleep(200);
  mark = await page.evaluate(() => {
    const m = document.querySelector(".sfx-lane .sfx-mark.manual");
    return m ? { left: m.style.left, title: m.title } : null;
  });
}
const item = saved ? JSON.parse(saved.body).sound.items.find((x) => x.source === "manual") : null;
report.manual = { button: addLabel, saved: !!saved, anchor: item?.anchor, sound: item?.sound, on_the_sfx_lane: mark };
console.log("manual", JSON.stringify(report.manual));
await shot("manual");

// ------------------------------------------------------------------ 3. sliders during playback
// select the manual sound first (clicking a mark pauses playback), so its own volume slider shows
await page.evaluate(() => {
  const m = document.querySelector(".sfx-lane .sfx-mark.manual");
  const r = m.getBoundingClientRect();
  for (const type of ["pointerdown", "pointerup"]) (type === "pointerdown" ? m : window).dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: r.left + 1, clientY: r.top + 2, button: 0 }));
});
await sleep(400);
await seek(11.0);
await page.evaluate(() => document.querySelectorAll("audio").forEach((a) => { a.dataset.qaWatch = "1"; }));
const seeks0 = await page.evaluate(() => window.__qaLog.seeks);
await pull();

// drag a slider with the real mouse: press, move in steps (every 40 ms), release
async function drag(aria, frac, nth = 0) {
  const box = await page.evaluate((a, n) => {
    const els = [...document.querySelectorAll(`input[type=range][aria-label="${a}"]`)];
    const el = els[n];
    if (!el) return null;
    el.scrollIntoView({ block: "center" });
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top + r.height / 2, w: r.width, v: +el.value, min: +el.min, max: +el.max };
  }, aria, nth);
  if (!box) throw new Error(`no slider ${aria}`);
  await sleep(50);
  const at = (box.v - box.min) / (box.max - box.min);
  if (Math.abs(at - frac) < 0.2) frac = at > 0.5 ? 0.1 : 0.9; // always a real change
  const from = box.x + at * box.w;
  const to = box.x + frac * box.w;
  const n0 = await page.evaluate(() => [window.__qaLog.patches.length, window.__qaLog.params.length, window.__qaLog.vols.length, window.__qaLog.seeks]);
  const tStart = await page.evaluate(() => [performance.now(), window.__qa.ctx.currentTime]);
  await page.mouse.move(from, box.y);
  await page.mouse.down();
  const moves = [];
  for (let k = 1; k <= 8; k++) {
    const t = await page.evaluate(() => performance.now());
    await page.mouse.move(from + ((to - from) * k) / 8, box.y);
    moves.push(t);
    await sleep(40);
  }
  const during = await page.evaluate((n) => window.__qaLog.patches.length - n, n0[0]);
  const seeksDuring = await page.evaluate((n) => window.__qaLog.seeks - n, n0[3]);
  await page.mouse.up();
  const tEnd = await page.evaluate(() => [performance.now(), window.__qa.ctx.currentTime]);
  await sleep(1200);
  const L = await page.evaluate(() => window.__qaLog);
  const after = L.patches.slice(n0[0]);
  const params = L.params.slice(n0[1]).filter((p) => p.t >= moves[0]);
  const vols = L.vols.slice(n0[2]).filter((p) => p.t >= moves[0]);
  const reacts = [...params, ...vols].map((p) => p.t).sort((a, b) => a - b);
  // the reaction to each mouse step: the first gain change after it
  const lags = moves.map((m) => { const r = reacts.find((x) => x >= m); return r ? r - m : null; }).filter((x) => x !== null);
  lags.sort((a, b) => a - b);
  const value = await page.evaluate((a, n) => +document.querySelectorAll(`input[type=range][aria-label="${a}"]`)[n].value, aria, nth);
  return {
    from: box.v, to: value,
    gain_changes: reacts.length,
    move_to_gain_ms: lags.length ? { median: +lags[lags.length >> 1].toFixed(1), max: +lags.at(-1).toFixed(1) } : null,
    requests_while_dragging: during,
    media_seeks_while_dragging: seeksDuring,
    saves_after_release: after.length,
    saved_body: after[0]?.body?.slice(0, 160),
    audio_window: [tStart[1], tEnd[1]],
  };
}

const results = {};
const timeNow = () => page.evaluate(() => { const a = window.__casefileQA.sfx.anchor; return a ? a.t + (window.__qa.ctx.currentTime - a.at) : 0; });
const isPlaying = () => page.evaluate(() => !!document.querySelector('[aria-label="Pause preview"]'));
// each slider is moved while the thing it controls is heard: playback from just before the manual
// sound (12 s), or inside the music's scenes; the playback is never paused by the slider itself
async function startAt(at) {
  if (await isPlaying()) await page.evaluate(() => document.querySelector('[aria-label="Pause preview"]').click());
  await seek(11.6);
  await page.evaluate(() => document.querySelector('[aria-label="Play preview"]').click());
  for (let k = 0; k < 80; k++) { await page.evaluate(() => window.__qa.music()); if ((await timeNow()) >= at) break; await sleep(25); }
}
// the same moment of playback with the slider left alone: what the level does by itself there
// (the music's fades and ducking, the swell's shape), so the slider's own effect can be told apart
async function control(bus, at, len) {
  await pull();
  await startAt(at);
  const a0 = await ctxNow();
  await sleep(len * 1000);
  const b0 = await ctxNow();
  await sleep(400);
  const rows = await pull();
  return db(rmsOf(rows, bus, b0 + 0.05, b0 + 0.3)) - db(rmsOf(rows, bus, a0 - 0.25, a0));
}
async function during(name, tab, aria, frac, at = 12.25) {
  await clickText(".inspector-tabs button", new RegExp(`^${tab}$`));
  await sleep(250);
  const bus0 = { Volume: 0, "Effects volume": 0, "Music level": 2 }[aria];
  const ctl = bus0 !== undefined ? await control(bus0, at, 0.42) : null;
  await pull();
  await startAt(at);
  const media = () => page.evaluate(() => [...document.querySelectorAll("audio, video")].concat(window.__casefileQA.music.els || [])
    .filter((e) => e.src).map((e) => [e.src.split("/").pop(), e.paused, +e.currentTime.toFixed(2)]));
  const m0 = await media();
  const state = () => page.evaluate(() => { const x = window.__casefileQA.sfx; return { list: (x.list || []).map((i) => [i[1], +i[2].toFixed(5)]), override: [...x.override], master: x.master, out: x.out?.gain.value }; });
  const s0 = await state();
  const r = await drag(aria, frac);
  const rows = await pull();
  const bus = { Volume: 0, "Effects volume": 0, "Music level": 2 }[aria];
  if (bus !== undefined) {
    const [a0, b0] = r.audio_window;
    const before = db(rmsOf(rows, bus, a0 - 0.25, a0)), after = db(rmsOf(rows, bus, b0 + 0.05, b0 + 0.3));
    const set = { Volume: r.to - r.from, "Effects volume": db(r.to) - db(r.from), "Music level": db(r.to) - db(r.from) }[aria];
    r.heard_db = { before, after, change: +(after - before).toFixed(1), same_moment_untouched: +ctl.toFixed(1),
                   slider_effect: +(after - before - ctl).toFixed(1), slider_set: +set.toFixed(1), drag_s: +(b0 - a0).toFixed(2) };
  }
  delete r.audio_window;
  r.effects_state_before_after = [s0, await state()];
  // once saved, the preview plays the saved levels (the plan read back from the server), nothing stale
  await sleep(1200);
  r.preview_matches_saved_plan = await page.evaluate(async (pid) => {
    const plan = await (await fetch(`/api/projects/${pid}/sound/plan`)).json();
    const x = window.__casefileQA.sfx;
    const want = plan.items.map((i) => [i.sound, +Math.pow(10, i.level / 20).toFixed(5)]);
    const have = (x.list || []).map((i) => [i[1], +i[2].toFixed(5)]);
    const saved = (await (await fetch(`/api/projects/${pid}`)).json()).sound?.master ?? 0.8;
    // the effects volume heard = the plan's levels (made with the plan's master) x the live ratio
    const master_ok = Math.abs(x.master * plan.settings.master - saved) < 1e-6;
    return { ok: JSON.stringify(want) === JSON.stringify(have) && x.override.size === 0 && master_ok, master_ok, want, have };
  }, PID);
  r.still_playing = await isPlaying();
  r.media_before_after = [m0, await media()]; // [file, paused, position]: still running, moved on
  results[name] = r;
}
await during("this sound's volume (Sound tab)", "Sound", "Volume", 0.15);
await during("effects volume (Sound tab)", "Sound", "Effects volume", 0.15);
await during("narration level (Sound tab)", "Sound", "Narration level", 0.2);
await during("music level (Audio tab)", "Audio", "Music level", 0.1);
await during("narration level (Audio tab)", "Audio", "Narration level", 0.6);
const playing = Object.values(results).every((r) => r.still_playing);
const seeks = (await page.evaluate(() => window.__qaLog.seeks)) - seeks0;
await page.evaluate(() => document.querySelector('[aria-label="Pause preview"]')?.click());
report.sliders = results;
report.playback = { still_playing_after_every_slider: playing, media_seeks_while_dragging_total: Object.values(results).reduce((a, r) => a + r.media_seeks_while_dragging, 0) };
console.log(JSON.stringify(report, null, 1));
await shot("sliders");
fs.writeFileSync(OUT, JSON.stringify(report, null, 1));
await browser.close();
