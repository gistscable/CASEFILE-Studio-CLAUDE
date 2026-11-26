"""v0.4.57 Everything to listen to, in one place:

  index.html        the 7 demos (before | after, side by side, with what to listen for and the
                    measurements) and the library: every sound, the previous version next to the new
  demo-reel.mp4     all 7 demos in one file: a title card, BEFORE, then AFTER, for each
  library/v1, v2    each sound as a short MP3 (v1 only for the sounds that changed)

    cd casefile-studio && PATH=$PWD/.venv/bin:$PATH .venv/bin/python qa/sound-design/make_page.py [old-sfxlib-commit]

The previous library is read from git (default: the v0.4.56 release, c53cf69), so the comparison
is with what shipped, not with a copy.
"""
from __future__ import annotations

import html
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent.parent
sys.path.insert(0, str(APP))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import sfxlib  # noqa: E402

FONT = APP / "web" / "assets" / "fonts"
LIB = HERE / "library"
WORK = HERE / "work"

DEMOS = [
    ("1-bullet-reveals", "Bullet reveals", "A whoosh as the graphic enters, a soft sweep on the divider, a click on the exact frame each line appears."),
    ("2-typing", "Typing", "A typewriter key on every typed character (6 different keys and a space bar, at slightly different strengths), never one loop."),
    ("3-diagram", "Diagram", "A directional whoosh in, then a tick on each timeline marker as it is drawn."),
    ("4-transitions", "Transitions", "Each transition gets the sound its movement suggests: a right-to-left whoosh on the slide, a tonal sweep on the circle, a swell on the chapter change; the dissolve stays silent."),
    ("5-narrative-development", "Narrative development", "One restrained low thump on the word that carries the finding (\u201cmatched\u201d), nothing elsewhere."),
    ("6-cta", "Subscribe animation", "Whoosh in, the click on SUBSCRIBE, the bell when it rings, a quieter whoosh out \u2014 on the animation's own keyframes."),
    ("7-interview-suppression", "Interview: nothing added", "Original source audio is never touched: no sound goes in or near the soundbite. Before and after are identical."),
]


def run(cmd):
    return subprocess.run(cmd, capture_output=True, check=True)


def old_library(commit):
    src = run(["git", "-C", str(APP), "show", f"{commit}:casefile-studio/sfxlib.py"]).stdout
    tmp = Path(tempfile.mkdtemp()) / "sfxlib_old.py"
    tmp.write_bytes(src)
    spec = importlib.util.spec_from_file_location("sfxlib_old", tmp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mp3(x, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1).T * 32767).astype("<i2").tobytes()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", "-", "-af", "apad=pad_dur=0.25",
                    "-c:a", "libmp3lame", "-b:a", "128k", str(path)], input=pcm, check=True)


def card(path, title, line2, line3=""):
    im = Image.new("RGB", (1280, 720), (16, 18, 22))
    d = ImageDraw.Draw(im)
    big = ImageFont.truetype(str(FONT / "Inter-Bold.otf"), 56)
    mid = ImageFont.truetype(str(FONT / "Inter-Bold.otf"), 34)
    small = ImageFont.truetype(str(FONT / "DejaVuSans.ttf"), 24)
    d.text((90, 250), title, font=big, fill=(236, 232, 224))
    d.text((90, 340), line2, font=mid, fill=(217, 183, 122))
    y = 410
    words, row = line3.split(), ""
    for w in words:
        if d.textlength(row + " " + w, font=small) > 1080:
            d.text((90, y), row.strip(), font=small, fill=(170, 170, 170))
            y += 34
            row = ""
        row += " " + w
    if row.strip():
        d.text((90, y), row.strip(), font=small, fill=(170, 170, 170))
    im.save(path)


def reel():
    WORK.mkdir(parents=True, exist_ok=True)
    inputs, filters, k = [], [], 0
    for i, (name, title, listen) in enumerate(DEMOS, 1):
        for side in ("before", "after"):
            png = WORK / f"card-{name}-{side}.png"
            card(png, f"Demo {i} \u2014 {title}", "BEFORE: sound design off" if side == "before" else "AFTER: sound design on",
                 "" if side == "before" else listen)
            inputs += ["-loop", "1", "-framerate", "24", "-t", "2.2", "-i", str(png), "-f", "lavfi", "-t", "2.2", "-i",
                       "anullsrc=r=48000:cl=stereo"]
            filters.append(f"[{k}:v]format=yuv420p,setsar=1[v{k}];[{k + 1}:a]anull[a{k}]")
            k += 2
            inputs += ["-i", str(HERE / f"demo-{name}-{side}.mp4")]
            filters.append(f"[{k}:v]fps=24,scale=1280:720,setsar=1,format=yuv420p[v{k}];[{k}:a]aresample=48000,aformat=channel_layouts=stereo[a{k}]")
            k += 1
    labels = [i for i in range(k) if f"[v{i}]" in ";".join(filters)]
    graph = ";".join(filters) + ";" + "".join(f"[v{i}][a{i}]" for i in labels) + f"concat=n={len(labels)}:v=1:a=1[v][a]"
    out = HERE / "demo-reel.mp4"
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "28", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)])
    return out


def page(rows, report, audit):
    def ms(v):
        return "\u2014" if v is None else f"{v:g} ms"

    demo_html = []
    for i, (name, title, listen) in enumerate(DEMOS, 1):
        r = report.get(name, {})
        sync = r.get("exact_placement_error_ms", {})
        est = r.get("transient_sync_error_ms", {})
        keys = r.get("typing_sync_error_ms", {})
        la, lb = r.get("loudness_after", {}), r.get("loudness_before", {})
        facts = [f"sounds placed: {len(r.get('sounds', []))}" + (f" ({sum(s['keys'] for s in r.get('sounds', []))} typed keys)" if any(s['keys'] for s in r.get('sounds', [])) else ""),
                 f"exact placement in the mix: {ms(sync.get('max'))} max over {sync.get('n', 0)}",
                 f"onset read through AAC: {ms(est.get('max'))} max" if est.get("n") else "",
                 f"typed keys read through AAC: median {ms(keys.get('median'))}, p95 {ms(keys.get('p95'))}" if keys.get("n") else "",
                 f"loudest effect vs the speech: {r.get('loudest_effect_vs_speech_db')} dB" if r.get("loudest_effect_vs_speech_db", -100) > -100 else "no effect added",
                 f"peak {r.get('after_peak_dbfs')} dBFS, {r.get('after_samples_over_full_scale')} samples at full scale",
                 f"loudness {lb.get('integrated_lufs')} \u2192 {la.get('integrated_lufs')} LUFS"]
        silent = "".join(f"<li>{s['t']:.2f} s \u2014 {html.escape(s['label'])}: {html.escape(s['why'])}</li>" for s in r.get("silenced", []))
        placed = "".join(f"<li>{s['t']:.2f} s \u2014 <code>{s['sound']}</code> {html.escape(s['label'])}</li>" for s in r.get("sounds", []))
        demo_html.append(f"""
<section class="demo" id="demo-{i}">
  <h3>Demo {i} \u2014 {html.escape(title)}</h3>
  <p class="listen">{html.escape(listen)}</p>
  <div class="pair">
    <figure><figcaption>Before (sound design off)</figcaption><video controls preload="metadata" src="demo-{name}-before.mp4"></video></figure>
    <figure><figcaption>After (sound design on)</figcaption><video controls preload="metadata" src="demo-{name}-after.mp4"></video></figure>
  </div>
  <ul class="facts">{''.join(f'<li>{html.escape(f)}</li>' for f in facts if f)}</ul>
  <details><summary>Every sound placed{' and every moment left silent' if silent else ''}</summary><ul>{placed}{silent}</ul></details>
</section>""")

    lib_html = []
    for cat in sfxlib.CATEGORIES:
        trs = []
        for sid, info in rows.items():
            if info["category"] != cat:
                continue
            a = audit["v2"][sid]
            b = audit["v1"].get(sid, {})
            change = info["changed"]
            D = "\u2014"
            bcut = b.get("cut_db") if b.get("cut_db") is not None else D
            acut = a["cut_db"] if a["cut_db"] is not None else D
            v1 = f'<audio controls preload="none" src="library/v1/{sid}.mp3"></audio>' if change else '<span class="same">unchanged</span>'
            trs.append(f"""<tr><td><code>{sid}</code><br><small>{html.escape(info['label'])}</small></td>
<td>{v1}</td><td><audio controls preload="none" src="library/v2/{sid}.mp3"></audio></td>
<td><small>{info['note']}</small></td>
<td><small>peaks {b.get('peaks', D)}&rarr;{a['peaks']}<br>flatness {b.get('flat_db', D)}&rarr;{a['flat_db']} dB<br>
tail cut {bcut}&rarr;{acut} dB<br>RMS {b.get('rms_db', D)}&rarr;{a['rms_db']} dB</small></td></tr>""")
        lib_html.append(f"<h3>{html.escape(cat)}</h3><table><tr><th>Sound</th><th>v0.4.56</th><th>v0.4.57</th><th>What changed</th><th>Measured</th></tr>{''.join(trs)}</table>")

    changed = sum(1 for r in rows.values() if r["changed"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Casefile sound design \u2014 v0.4.58 demos and library</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font:15px/1.5 Inter,system-ui,sans-serif;background:#111317;color:#e9e5dc;margin:0;padding:28px 36px;max-width:1500px}}
h1{{font-size:26px;margin:0 0 4px}} h2{{margin-top:44px;border-bottom:1px solid #333;padding-bottom:6px}} h3{{margin:26px 0 6px;color:#d9b77a}}
a{{color:#d9b77a}} code{{color:#cfc6b4}} small{{color:#9a968e}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} figure{{margin:0}} figcaption{{font-size:13px;color:#9a968e;margin-bottom:4px}}
video{{width:100%;background:#000;border-radius:6px}} .listen{{color:#cfc6b4;margin:0 0 10px}}
.facts{{display:flex;flex-wrap:wrap;gap:6px 18px;padding:0;list-style:none;font-size:13px;color:#b8b2a6;margin:10px 0}}
details{{font-size:13px;color:#b8b2a6}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid #26292f;padding:6px 8px;text-align:left;vertical-align:middle}} audio{{height:30px;width:230px}}
.same{{color:#6f6b64}} .note{{background:#1a1d22;border-left:3px solid #d9b77a;padding:10px 14px;margin:14px 0}}
</style></head><body>
<h1>Casefile sound design \u2014 v0.4.58</h1>
<p>Rendered by the real exporter at 720p. Narration voices are AI-generated for these demos; the pictures are neutral plates (no case imagery is made up).
Use headphones for the low sounds. <a href="demo-reel.mp4">All 7 demos in one video (before, then after)</a>.
<b><a href="music.html">Background music demos (v0.4.58): loop, chapter, long track, all layers</a></b>.</p>
<div class="note">Not a final approval: this page is for your review. The measurements say where each sound landed and how loud it is;
only listening says whether it sounds right.</div>
<h2>The seven demos</h2>
{''.join(demo_html)}
<h2>The library: {len(rows)} sounds, {changed} improved, {len(rows) - changed} unchanged</h2>
<p>Every sound is made on this computer (NumPy synthesis, no downloads). Same ids, categories and sync points as before; each improved
sound keeps its loudness in the mix within 1.5 dB of v0.4.56 (the two lighter keystrokes are lighter on purpose).
<b>peaks</b> = spectral peaks within 30 dB (richness; a bare sine has 1\u20132), <b>flatness</b> near the loudest moment (very low = a pure test tone),
<b>tail cut</b> = a click where a layer stopped abruptly instead of dying away (v0.4.56: up to 111 dB on the thumps and impacts).</p>
{''.join(lib_html)}
</body></html>"""


NOTES = {
    "click": "switch modes, rattle, distinct press/release", "click-muted": "switch modes, rattle", "cta-click": "switch modes, rattle",
    "typewriter": "finger contact, mechanism rattle, carriage step; 6 distinct keys", "keyboard": "plate modes, rattle; 6 distinct keys",
    "whoosh": "broad moving air instead of a whistling band", "reverse-whoosh": "broad moving air instead of a whistling band",
    "thump": "tail dies away (was cut), skin and beater, warm harmonics", "bass-impact": "tail dies away (was cut), texture, warm harmonics",
    "transition-impact": "whole crack tail (was cut at 0.25 s), low-mid boom", "pulse": "felt thud with pitch drop instead of a sine; lub-dub",
    "notification": "FM glass attack, shimmer, mallet tap", "bell": "beating partial pairs, striker tap", "scan": "soft grains instead of a hard square gate",
    "tonal-sweep": "breathy tone with vibrato instead of pure glides", "swell": "detuned saw pad with an opening filter instead of sines",
    "document": "the landing thump's tail dies away", "shutter": "two different shutters (were the same)",
}


def main(commit="c53cf69"):
    old = old_library(commit)
    sys.path.insert(0, str(HERE))
    import library_audit

    rows = {}
    for c in sfxlib.CATALOG:
        sid = c[0]
        x, _ = sfxlib.synth(sid)
        y, _ = old.synth(sid)
        same = x.shape == y.shape and np.array_equal(x, y)
        rows[sid] = {"category": c[1], "label": c[2], "changed": not same, "note": "" if same else NOTES.get(c[1], "")}
        mp3(x, LIB / "v2" / f"{sid}.mp3")
        if not same:
            mp3(y, LIB / "v1" / f"{sid}.mp3")
    audit = {"v1": {}, "v2": {}}
    for c in sfxlib.CATALOG:
        x, sync = sfxlib.synth(c[0])
        audit["v2"][c[0]] = library_audit.metrics(x)
        y, _ = old.synth(c[0])
        audit["v1"][c[0]] = library_audit.metrics(y)
        if c[1] not in library_audit.TAILED:
            audit["v1"][c[0]]["cut_db"] = audit["v2"][c[0]]["cut_db"] = None
    (HERE / "library-audit.json").write_text(json.dumps(audit, indent=1))
    report = json.loads((HERE / "demo-report.json").read_text())
    (HERE / "index.html").write_text(page(rows, report, audit))
    out = reel()
    print("index.html, library-audit.json,", out.name, "and", sum(1 for _ in LIB.rglob("*.mp3")), "MP3s")


if __name__ == "__main__":
    main(*sys.argv[1:])
