"""v0.4.64 Type and layout of the cinematic graphics, as a page to view (qa/cinegfx-demos/type/index.html).

Every picture and clip is drawn by the app's own code (motion.normalise -> cinematic.style_of -> cinematic.build /
frame), like make_looks.py. The layout check (tests/cinegfx_layout.py) is run on every still and its result printed
under it. `type/img/timeline-before-v0463.jpg` is the v0.4.63 drawing, kept for the comparison (not remade).

  PATH=$PWD/.venv/bin:$PATH .venv/bin/python qa/cinegfx-demos/make_type.py           # stills + page
  ... make_type.py --clips                                                             # also the narrated MP4s
  .venv/bin/python qa/cinegfx-demos/serve.py   -> http://0.0.0.0:8001/type/
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import make_looks as M  # noqa: E402  (sets up sys.path for the app)
import cinematic  # noqa: E402
from cinegfx import look as L  # noqa: E402
from cinegfx_layout import check  # noqa: E402

OUT = HERE / "type"
NAMES = M.NAMES
TC = M.TC


def shot(cat, look=None, ilook=None, backdrop=None, name=None):
    im, st = M.still(cat, look, ilook, backdrop)
    it = M.styled(cat, look, ilook)
    problems = check(cinematic.build(it, M.slot_files(cinematic.slots(it), backdrop)))
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    im.save(OUT / "img" / name, quality=88)
    return {"src": f"img/{name}", "notes": st["notes"], "ok": not problems, "problems": [f"{p[0]}: {p[1]}" + (f" / {p[2]}" if p[2] else "") for p in problems]}


CLIPS = [
    ("clip-legal-footage-75", "4-legal", {"background": "footage"}, None, None,
     "Legal outcome over your footage: now darkened 75% by default (was 62%), so its small red labels read"),
    ("clip-turning-mirror-serif", "6-turning", None, {"mirror": True, "font": "serif"}, None,
     "Turning point mirrored (photo on the left), Editorial serif"),
    ("clip-findings-sans-115", "1-findings", None, {"font": "sans", "size": 1.15, "mirror": True}, None,
     "Investigative findings: Bold sans, text 115%, mirrored (photo on the right)"),
    ("clip-digital-placed", "5-digital", {"background": "footage"}, {"place": {"scale": 0.85, "x": 0, "y": 0}}, None,
     "Digital evidence at 85% size, centred, over your footage (the darkening still fills the frame)"),
    ("clip-timeline-bottom", "2-timeline", {"background": "footage"}, {"place": {"scale": 0.85, "x": 0, "y": 1}, "font": "condensed"}, None,
     "Timeline at 85%, at the bottom, Condensed, over your footage"),
]


def build(with_clips):
    OUT.mkdir(exist_ok=True)
    d = {}
    # 1 the crowded timeline
    d["timeline"] = shot("timeline", name="timeline-after.jpg")
    # 2 legal over footage: the old default and the new
    d["legal"] = [shot("legal", {"background": "footage", "dim": 0.62}, name="legal-footage-62.jpg"),
                  shot("legal", {"background": "footage"}, name="legal-footage-75.jpg")]
    d["legal_ratio"] = [round(L.contrast("#D0503F", L.picture_ref(x)), 1) for x in (0.62, 0.75)]
    # 3 fonts
    d["fonts"] = {}
    for c in M.CATS:
        d["fonts"][c] = [dict(shot(c, None, {"font": k}, name=f"font-{c}-{k}.jpg"), label=lab) for k, lab in L.fonts_of(TC.categories[c])]
    # 4 text size
    d["size"] = {c: [dict(shot(c, None, {"size": s}, name=f"size-{c}-{int(round(s * 100))}.jpg"), label=f"{int(round(s * 100))}%") for s in (0.85, 1.0, 1.15)]
                 for c in ("findings", "timeline", "contradiction", "legal")}
    # 5 mirrored
    d["mirror"] = {c: [shot(c, name=f"mirror-{c}-design.jpg"), shot(c, None, {"mirror": True}, name=f"mirror-{c}-mirrored.jpg")]
                   for c in ("findings", "legal", "turning")}
    d["mirror_label"] = {c: TC.categories[c].looks["mirror"] for c in d["mirror"]}
    # 6 size and position
    d["place"] = [
        dict(shot("timeline", {"background": "footage"}, {"place": {"scale": 0.85, "x": 0, "y": 1}}, name="place-timeline.jpg"),
             cap="Timeline · 85% · bottom · over your footage"),
        dict(shot("findings", {"background": "footage"}, {"place": {"scale": 0.8, "x": -1, "y": 1}}, name="place-findings.jpg"),
             cap="Findings · 80% · bottom left · over your footage"),
        dict(shot("digital", None, {"place": {"scale": 0.85, "x": 0, "y": 0}}, name="place-digital.jpg"), cap="Digital evidence · 85% · centre · its own background"),
        dict(shot("legal", None, {"place": {"scale": 0.9, "x": 0, "y": 0}}, name="place-legal.jpg"), cap="Legal outcome · 90% · centre"),
        dict(shot("turning", None, {"place": {"scale": 0.85, "x": 1, "y": 0}}, name="place-turning.jpg"), cap="Turning point · 85% · right"),
        dict(shot("contradiction", None, {"place": {"scale": 0.8, "x": 0, "y": 0}}, name="place-contradiction.jpg"),
             cap="Contradiction · asked for 80%: keeps its size (fills the screen)"),
    ]
    print("stills done", flush=True)
    clips_file = OUT / "clips.json"
    if with_clips:
        cl = []
        for name, key, look, ilook, bd, cap in CLIPS:
            r = M.clip(name, key, look, ilook, bd, out=OUT)
            cl.append({"src": r["src"], "cap": cap, "notes": r["notes"]})
        clips_file.write_text(json.dumps(cl))
    d["clips"] = json.loads(clips_file.read_text()) if clips_file.exists() else []
    (OUT / "index.html").write_text(page(d))
    n = sum(1 for _ in (OUT / "img").glob("*.jpg"))
    bad = [x for x in _all(d) if not x["ok"]]
    print(f"-> {OUT / 'index.html'}: {n} stills, layout check failed on {len(bad)}", [x["src"] for x in bad])


def _all(d):
    yield d["timeline"]
    yield from d["legal"]
    for v in d["fonts"].values():
        yield from v
    for v in d["size"].values():
        yield from v
    for v in d["mirror"].values():
        yield from v
    yield from d["place"]


def page(d):
    e = html.escape

    def fig(x, cap, cls=""):
        chk = '<span class="ok">layout check ✓</span>' if x.get("ok", True) else f'<span class="bad">layout check: {e("; ".join(x["problems"][:2]))}</span>'
        notes = "".join(f"<small class='n'>{e(n)}</small>" for n in x.get("notes") or [])
        return f'<figure class="{cls}"><img src="{x["src"]}" loading="lazy"><figcaption>{cap}<small>{chk}</small>{notes}</figcaption></figure>'

    clips = "".join(f'<figure><video src="{c["src"]}" controls preload="metadata" playsinline></video><figcaption>{e(c["cap"])}'
                    + "".join(f"<small class='n'>{e(n)}</small>" for n in c["notes"]) + "</figcaption></figure>" for c in d["clips"])
    fonts = "".join(f'<h3>{NAMES[c]}</h3><div class="grid g4">' + "".join(fig(x, e(x["label"]) + (" · the design" if i == 0 else ""))
                                                                       for i, x in enumerate(v)) + "</div>" for c, v in d["fonts"].items())
    size = "".join(f'<h3>{NAMES[c]}</h3><div class="grid g3">' + "".join(fig(x, x["label"]) for x in v) + "</div>" for c, v in d["size"].items())
    mirror = "".join(f'<h3>{NAMES[c]}</h3><div class="grid g2">' + fig(v[0], "As designed") + fig(v[1], "Mirrored: " + e(d["mirror_label"][c].lower())) + "</div>"
                     for c, v in d["mirror"].items())
    place = '<div class="grid g3">' + "".join(fig(x, e(x["cap"])) for x in d["place"]) + "</div>"
    r62, r75 = d["legal_ratio"]
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cinematic graphics — type and layout (v0.4.64)</title><style>
body{{background:#0e0f12;color:#e9e6df;font:15px/1.5 -apple-system,Segoe UI,Inter,sans-serif;margin:0;padding:28px 40px 90px;max-width:1600px}}
h1{{font-size:28px;margin:0 0 6px}} h2{{font-size:21px;margin:48px 0 6px;border-top:1px solid #2a2c31;padding-top:26px}}
h3{{font-size:14px;margin:22px 0 8px;color:#c9c4b8;text-transform:uppercase;letter-spacing:.06em}}
p.q{{color:#b8b3a8;max-width:1050px;margin:4px 0 12px}} .note{{background:#17181c;border-left:3px solid #f2b33d;padding:10px 14px;color:#c9c4b8;max-width:1050px}}
.grid{{display:grid;gap:14px}} .g2{{grid-template-columns:repeat(2,1fr)}} .g3{{grid-template-columns:repeat(3,1fr)}} .g4{{grid-template-columns:repeat(4,1fr)}}
@media(max-width:900px){{.g3,.g4{{grid-template-columns:repeat(2,1fr)}}}}
figure{{margin:0;background:#16171b;border:1px solid #24262b;border-radius:8px;overflow:hidden}}
img,video{{width:100%;display:block;background:#000}} figcaption{{padding:8px 10px;font-size:13px}} small{{display:block;color:#8f8b82;margin-top:3px}}
.ok{{color:#8fe0a8}} .bad{{color:#ff8b7b}} small.n{{color:#e8c37a}} a{{color:#f2b33d}}
</style></head><body>
<h1>Cinematic graphics — type and layout</h1>
<p class="note">Built in v0.4.64 (new branch, PR not merged). Every picture and clip is drawn by the app's own code — the frames the editor previews and
the export writes. Under each still: the automatic layout check (no text running into other text, cut by its box or off the frame).
Stand-ins as before: “your footage” is the NYPD briefing photo, words and photos are the approved Javits material.
In the app: Motion › <i>Look of all cinematic graphics</i> › Type and layout (the whole project), or select a graphic › LOOK › Type and layout.
<br>The colours and backgrounds page: <a href="../looks/">look options (v0.4.63)</a>.</p>
<h2>Moving examples — narration, word timing and the designed sound</h2><div class="grid g3">{clips}</div>
<h2>1 · The crowded timeline (fixed)</h2>
<p class="q">Five events are closer together than a 330 px card, so the labels ran into each other (“retained” into “Community”). Now the cards,
their labels and the dates narrow to the spacing. Timelines with up to four events are drawn exactly as before (the approved Javits stills are pixel-identical).</p>
<div class="grid g2">{fig({"src": "img/timeline-before-v0463.jpg", "ok": False, "problems": ["overlap: The family retained / Community walk"]}, "Before (v0.4.63)")}{fig(d["timeline"], "After (v0.4.64)")}</div>
<h2>2 · Legal outcome over footage is darker by default</h2>
<p class="q">Its small red labels (DEFENDANT, CHARGES, BEFORE) measured {r62}:1 over a mid-grey picture at the general 62% — under the 3:1 minimum. At 75% they measure {r75}:1.
A darkening you set yourself (project or graphic) still wins.</p>
<div class="grid g2">{fig(d["legal"][0], "62% (the old default)")}{fig(d["legal"][1], "75% (the new default for legal)")}</div>
<h2>3 · Font</h2><p class="q">Five styles from the fonts bundled with the app (nothing downloaded): Condensed, Bold sans, Editorial serif, Geometric, Typewriter.
Each category offers the ones its layout passed the layout check with (all text sizes, mirrored too); its own design is always first.
Big headlines and dates fit their space in any font.</p>{fonts}
<h2>4 · Text size (85–115%)</h2><p class="q">Headings, labels and body text; the rows and lines below make room. The big dates and headlines are composed for each design and fitted.</p>{size}
<h2>5 · Layout mirrored (the “alignment” the designs allow)</h2><p class="q">Photo and text swap sides, for the three layouts built as a photo beside text.
The timeline (time runs left to right), the evidence route and the two-sided contradiction keep their layout.</p>{mirror}
<h2>6 · Layout size and position</h2><p class="q">80–100%, placed anywhere in the frame (the 3×3 grid in the editor, then nudge); at full size a small nudge.
The background — its own, your darkened footage or a picture — still fills the frame. Contradiction fills the screen and keeps its size.</p>{place}
</body></html>"""


if __name__ == "__main__":
    build("--clips" in sys.argv[1:])
