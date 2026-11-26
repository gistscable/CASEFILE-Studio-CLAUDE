import puppeteer from 'puppeteer-core';
import http from 'http'; import fs from 'fs'; import path from 'path';
const root = '/tmp/qa/timing';
const srv = http.createServer((q, r) => {
  const u = decodeURIComponent(q.url.split('?')[0]); const f = path.join(root, u === '/' ? 'index.html' : u);
  if (!fs.existsSync(f)) { r.writeHead(404); return r.end(); }
  const data = fs.readFileSync(f); const type = f.endsWith('.wav') ? 'audio/wav' : f.endsWith('.js') ? 'text/javascript' : 'text/html';
  const range = q.headers.range;
  if (range) { const [a, b] = range.replace('bytes=', '').split('-'); const s = +a, e = b ? +b : data.length - 1;
    r.writeHead(206, { 'Content-Type': type, 'Content-Range': `bytes ${s}-${e}/${data.length}`, 'Accept-Ranges': 'bytes', 'Content-Length': e - s + 1 }); return r.end(data.subarray(s, e + 1)); }
  r.writeHead(200, { 'Content-Type': type, 'Content-Length': data.length, 'Accept-Ranges': 'bytes' }); r.end(data);
}).listen(8765);
const b = await puppeteer.launch({ executablePath: '/tmp/chromium', headless: true, args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required', '--disable-gpu'] });
const p = await b.newPage();
p.on('console', (m) => console.log('page:', m.text()));
await p.goto('http://127.0.0.1:8765/');
// the narration clicks are at narration (= timeline) positions 0.1 + k s: fit audio time = a + t
function analyse(r) {
  const segs = r.seek ? [[r.narr.filter((x) => x < r.seek), 0.1], [r.narr.filter((x) => x > r.seek), null]] : [[r.narr, 0.1]];
  // per segment: offset a = onset - timeline position (median), positions from nearest k
  const fits = [];
  for (const [ons, first] of segs) {
    if (!ons.length) continue;
    const base = first ?? null; let offs = [];
    if (base !== null) offs = ons.map((x, k) => x - (0.1 + k));
    else { // after the seek: positions are 0.1 + k for k >= ceil(seekTo-0.1); fit using the first onset's fraction
      const a0 = ons[0]; offs = ons.map((x, k) => x - k); const m = offs.sort((x, y) => x - y)[offs.length >> 1];
      fits.push({ from: ons[0] - 0.05, to: ons[ons.length - 1] + 1, a: null, m, ons }); continue; }
    offs.sort((x, y) => x - y); fits.push({ from: ons[0] - 1, to: ons[ons.length - 1] + 1, a: offs[offs.length >> 1] });
  }
  return fits;
}
const out = {};
const cases = process.env.JANK ? [['part from the top, main thread blocked 150 ms about every 0.75 s', { crossfade: 1.0 }, 0, 0, 150], ['part from 2 s, main thread blocked 150 ms about every 0.75 s', { crossfade: 1.0, start: 2.0 }, 0, 0, 150]] : [['part from the top (start 0), crossfade 1 s', { crossfade: 1.0 }], ['part from 2 s, crossfade 1 s', { crossfade: 1.0, start: 2.0 }], ['part from the top, seek 18.3 -> 9.6 s', { crossfade: 1.0 }, 18.3, 9.6]];
const runs = +process.argv[2] || 1;
for (const [name, settings, seekAt, seekTo, jank] of cases) {
  for (const which of ['old', 'new']) {
    const errs = [], starts = [];
    for (let n = 0; n < runs; n++) {
      const r = await p.evaluate((w, s, a, b, j) => window.runCase(w, s, 39, a, b, j), which, settings, seekAt || 0, seekTo || 0, jank || 0);
      const fits = analyse(r);
      const before = fits[0];
      // before any seek: audio time of timeline t = before.a + t
      const expected = [];
      for (const ps of r.passes) for (let s = 0.25; s < 8; s += 0.5) {
        const tl = ps.at + (s - ps.src);
        if (s < ps.src - 1e-6 || tl >= ps.at + ps.len) continue;
        expected.push({ tl, first: Math.abs(s - ps.src - 0.25) < 1e-6 || s - ps.src < 0.5 });
      }
      for (const m of r.mus) {
        if (r.seek && m > r.seek - 0.05 && m < r.seek + 0.6) continue; // the seek itself
        let a;
        if (!r.seek || m < r.seek) a = before.a;
        else { // after the seek: the timeline is t = seekTo + (audio - narration restart); narration click at 0.1+k
          const ons = fits[1].ons; const k0 = Math.ceil(seekTo - 0.1 - 1e-6); a = ons[0] - (0.1 + k0);
        }
        const tl = m - a;
        let best = null;
        for (const e of expected) if (!best || Math.abs(e.tl - tl) < Math.abs(best.tl - tl)) best = e;
        if (!best || Math.abs(best.tl - tl) > 0.24) { errs.push(NaN); continue; }
        const err = (tl - best.tl) * 1000; // + = music late vs the export, - = early
        errs.push(err); if (best.first) starts.push(+err.toFixed(1));
      }
    }
    const ok = errs.filter((x) => !isNaN(x)), abs = ok.map(Math.abs).sort((x, y) => x - y);
    const q = (f) => +abs[Math.min(abs.length - 1, Math.floor(f * abs.length))].toFixed(1);
    const mean = ok.reduce((x, y) => x + y, 0) / ok.length;
    const res = { clicks: ok.length, unmatched: errs.length - ok.length, mean_ms: +mean.toFixed(1), abs_median_ms: q(0.5), abs_p95_ms: q(0.95), abs_max_ms: q(1), first_click_of_each_pass_ms: starts };
    out[`${name} — ${which === 'old' ? 'v0.4.58' : 'v0.4.59'}`] = res;
    console.log(name, which, JSON.stringify(res));
  }
}
fs.writeFileSync(process.argv[3] || '/tmp/qa/timing/result2.json', JSON.stringify(out, null, 1));
await b.close(); srv.close();
