import * as OLD from './old_music.js';
import * as NEW from './new_music.js';
const ctx = new AudioContext();
const host = { ensure: () => ctx };
let rec = null, merger = null, narrEl = null;
async function setup() {
  if (rec) return;
  await ctx.audioWorklet.addModule('rec-worklet.js');
  rec = new AudioWorkletNode(ctx, 'rec', { numberOfInputs: 1, channelCount: 2, channelCountMode: 'explicit' });
  merger = ctx.createChannelMerger(2);
  merger.connect(rec);
  const mute = ctx.createGain(); mute.gain.value = 0; rec.connect(mute).connect(ctx.destination);
  narrEl = new Audio('narr.wav'); narrEl.preload = 'auto';
  const ns = ctx.createMediaElementSource(narrEl); ns.connect(merger, 0, 0); ns.connect(ctx.destination);
}
const ready = (els) => new Promise((r) => { let k = 0; const f = () => (els.every((e) => e.readyState >= 4) || ++k > 200 ? r() : setTimeout(f, 50)); f(); });
window.runCase = async function (which, settings, seconds, seekAt, seekTo, jank) {
  const M = which === 'new' ? NEW : OLD;
  await ctx.resume(); await setup();
  const lay = M.musicLayout(settings, 8.0, 42, []);
  const mp = new M.MusicPreview(host);
  mp.setSource('track.wav'); mp.setLayout(lay); mp.setVolume(1);
  mp._graph(); mp.nodes.duck.connect(merger, 0, 1);
  narrEl.currentTime = 0; await ready([narrEl, ...mp.els]);
  rec.port.postMessage(0); await new Promise((r) => { rec.port.onmessage = () => r(); }); // flush earlier onsets
  const t0 = ctx.currentTime;
  await narrEl.play();
  const seekLog = [];
  let seeked = false, t = 0, last = performance.now();
  await new Promise((resolve) => {
    const frame = (now) => {
      const dt = Math.min(0.15, (now - last) / 1000); last = now;
      // the editor's clock: while the narration speaks it is the master clock (nextTime)
      if (!narrEl.paused && !narrEl.seeking && narrEl.readyState >= 2) t = narrEl.currentTime; else t += dt;
      if (!seeked && seekAt && t >= seekAt) { narrEl.currentTime = seekTo; t = seekTo; seeked = true; seekLog.push(ctx.currentTime); }
      mp.tick(t, true, false);
      if (jank && Math.random() < 1 / 45) { const e = performance.now() + jank; while (performance.now() < e); } // a heavy re-render: the main thread blocked
      if (t < seconds) requestAnimationFrame(frame); else { mp.stop(); narrEl.pause(); resolve(); }
    };
    requestAnimationFrame(frame);
  });
  await new Promise((r) => setTimeout(r, 300));
  const on = await new Promise((r) => { rec.port.onmessage = (e) => r(e.data); rec.port.postMessage(0); });
  mp.nodes.duck.disconnect();
  const narr = on[0].filter((x) => x >= t0), mus = on[1].filter((x) => x >= t0);
  return { narr, mus, seek: seekLog[0] || null, passes: NEW.musicPasses(lay), lay };
};
