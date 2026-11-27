"""v0.4.63 Look options of the cinematic graphics, as a page to view (qa/cinegfx-demos/looks/index.html).

Every picture is drawn by the app's own look code: `motion.normalise` resolves the look into the item's style
(cinematic.style_of), `cinematic.build` / `cinematic.frame` draw it, exactly as the editor and the export do.
The clips use the approved Javits narration, its word timings and the graphics' designed sound.
"Your footage" is stood in by the approved NYPD briefing photo (slow push-in), "a project photo" by the courthouse.

  PATH=$PWD/.venv/bin:$PATH .venv/bin/python qa/cinegfx-demos/make_looks.py            # stills + page
  ... make_looks.py --clips                                                               # also the MP4s
  .venv/bin/python qa/cinegfx-demos/serve.py   -> http://0.0.0.0:8001/looks/
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(HERE)]

from PIL import Image  # noqa: E402

import cinematic  # noqa: E402
import motion  # noqa: E402
from cinegfx import core, look as L, sfx, story as S, timing as TM  # noqa: E402
import make_demos as MD  # noqa: E402
from test_cinematic import javits_project  # noqa: E402

OUT = HERE / "looks"
P = str(HERE / "photos") + "/"
TC = core.load_collections()["truecrime"]
CATS = ["findings", "timeline", "contradiction", "legal", "digital", "turning"]
NAMES = {"findings": "Investigative findings", "timeline": "Timeline", "contradiction": "Contradiction", "legal": "Legal outcome",
         "digital": "Digital evidence", "turning": "Turning point"}
MAP = {"Joseph Kenny": "kenny.jpg", "Ben Crump": "crump.jpg", "Javits Frimpong": "javits.jpg", "vigil": "memorial-candles.jpg"}
FOOTAGE = P + "kenny.jpg"
PHOTO = "courthouse.jpg"
_ITEMS = {}


def items():
    if not _ITEMS:
        _ITEMS.update({x["category"]: x for x in cinematic.suggest(javits_project(), [])})
    return _ITEMS


def cover(im, w, h, z=1.0):
    s = max(w / im.width, h / im.height) * z
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def footage(w, h, t=0.0, dur=10.0):
    """The stand-in for your footage: the briefing photo with a slow push-in (it moves, like video)."""
    return cover(Image.open(FOOTAGE).convert("RGB"), w, h, 1.0 + 0.05 * min(1.0, t / max(dur, 0.1))).convert("RGBA")


def slot_files(slots, backdrop=None):
    out = {}
    for sl in slots:
        v = sl["value"]
        f = MAP.get(v) or ("courthouse.jpg" if "ourt" in v else "freeman-tracks.jpg" if "Freeman" in v else None)
        if f:
            out[sl["key"]] = {"file": P + f, "credit": _credit(f), "month": ""}
    if backdrop:
        out[cinematic.BACKDROP] = {"file": P + backdrop, "credit": "", "month": ""}
    return out


def _credit(f):
    src = json.loads((HERE / "photos" / "sources.json").read_text())
    e = src.get(Path(f).stem) or {}
    return e.get("credit", "")


def styled(cat, look=None, ilook=None):
    it = dict(items()[cat])
    if ilook:
        it["look"] = ilook
    return motion.normalise({"enabled": True, "items": [it], "look": look or {}})["items"][0]


def still(cat, look=None, ilook=None, backdrop=None, colors=None, size=(960, 540)):
    it = styled(cat, look, ilook)
    if colors:  # the colour as you picked it, without the readability check (to compare)
        it["style"] = dict(it["style"], colors=dict(it["style"]["colors"], **colors))
    g = cinematic.build(it, slot_files(cinematic.slots(it), backdrop))
    fr = cinematic.frame(g, it, cinematic.frames_of(it) - 24, *size)
    return Image.alpha_composite(footage(*size), fr).convert("RGB"), it["style"]


def save(im, name):
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    im.save(OUT / "img" / name, quality=88)
    return f"img/{name}"


# ---------------------------------------------------------------- clips: the real narration, its timing and the designed sound

def narrated(key):
    story = S.parse_script((HERE / "javits-script.md").read_text())
    texts = json.loads((HERE / "narration" / "texts.json").read_text())
    a, b = MD.window_for(story, texts[key])
    score, cat, payload, why = MD.classify(story, TC, a, b)[0]
    tl = TM.timeline_for(str(HERE / "narration" / f"{key}.mp3"), texts[key])
    return core.Beat("truecrime", cat, a, b, score, payload, why), tl


def clip(name, key, look=None, ilook=None, backdrop=None, fps=24, size=(1280, 720), out=None):
    beat, tl = narrated(key)
    cat = TC.categories[beat.category]
    st = cinematic.style_of({"collection": "truecrime", "category": beat.category, "look": cinematic.normalise_look(ilook or {}), "start": 0.0},
                            cinematic.normalise_look(look or {}, project=True))
    g = cat.graphic(beat, L.theme_for(cat, st["colors"], st.get("type")), tl, core.Assets(items={
        k: {"file": v["file"], "credit": v["credit"], "month": "", "subject": s["value"],
            "people": [s["value"]] if s["kind"] == "person" else [], "places": [s["value"]] if s["kind"] == "place" else [],
            "tags": [s["value"]] if s["kind"] == "tag" else []}
        for s in cat.photo_slots(beat.payload) for k, v in slot_files([s]).items()}))
    # what the app does in cinematic.build for the background (and v0.4.64 the layout's size and place)
    g.place = L.placement(st["type"]["place"]) if (st.get("type") or {}).get("place") else None
    g.backdrop = None
    if st["background"] == "footage":
        g.backdrop = ("footage", st.get("dim") or L.default_dim(cat))
    elif st["background"] in ("photo", "still") and backdrop:
        g.backdrop = ("picture", cinematic._picture(P + backdrop, st.get("dim") or L.default_dim(cat)))
    total = g.duration
    n = int(total * fps)
    out = out or OUT
    wav = out / f"{name}.wav"
    sfx.mix(g.cues, str(HERE / "narration" / f"{key}.mp3"), total, str(wav))
    mp4 = out / f"{name}.mp4"
    w, h = size
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                          "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac",
                          "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    for k in range(n):
        t = k / fps
        canvas = cinematic._canvas(g, t, total)
        a = cinematic._envelope(t, total)
        if a < 0.999:
            canvas.putalpha(canvas.getchannel("A").point(lambda v: int(round(v * a))))
        canvas = canvas.resize((w, h), Image.LANCZOS)
        p.stdin.write(Image.alpha_composite(footage(w, h, t, total), canvas).convert("RGB").tobytes())
    p.stdin.close()
    p.wait()
    wav.unlink(missing_ok=True)
    print("clip:", mp4.name, round(total, 1), "s", st["palette"], st["background"], st["notes"], flush=True)
    return {"src": mp4.name, "notes": st["notes"]}


CLIPS = [
    ("clip-timeline-footage", "2-timeline", {"background": "footage"}, None, None,
     "Timeline over your footage, darkened (see-through: the video moves underneath)"),
    ("clip-legal-footage", "4-legal", {"background": "footage"}, None, None,
     "Legal outcome over your footage: the paper docket switches to its dark version"),
    ("clip-digital-amber", "5-digital", None, {"palette": "B"}, None, "Digital evidence, colour set B (amber terminal), its own background"),
    ("clip-turning-photo", "6-turning", {"background": "photo"}, {"accent": "#E8B04B"}, PHOTO,
     "Turning point over a project photo, your own gold accent (adjusted to stay readable)"),
    ("clip-findings-light", "1-findings", None, {"palette": "L"}, None, "Investigative findings, light version"),
]


# ---------------------------------------------------------------- the page

def build(with_clips):
    OUT.mkdir(exist_ok=True)
    d = {}
    # 1 scope
    proj = {"palettes": {k: "B" for k in CATS}}
    d["scope"] = []
    for c in ["findings", "timeline", "legal", "digital", "turning"]:
        im, st = still(c, proj, {"palette": "C"} if c == "legal" else None)
        d["scope"].append({"src": save(im, f"scope-{c}.jpg"), "cap": f"{NAMES[c]} · set {st['palette']}", "changed": c == "legal"})
    # 2 sets
    d["sets"] = {}
    for c in CATS:
        d["sets"][c] = []
        for key, lab, col in L.palettes(TC.categories[c]):
            im, st = still(c, None, {"palette": key})
            d["sets"][c].append({"src": save(im, f"set-{c}-{key}.jpg"), "key": key, "label": lab,
                                 "sw": [col["bg"], col["ink"], col["accent"], col["accent2"]],
                                 "text": round(L.contrast(col["ink"], col["bg"]), 1), "accent": round(L.contrast(col["accent"], col["bg"]), 1)})
    # 2b own colours
    d["own"] = []
    for c, acc in (("digital", "#1F3A68"), ("legal", "#E8B04B"), ("turning", "#E8B04B")):
        raw = {"accent": acc, "accent2": acc} if c in ("legal", "turning") else {"accent": acc}
        im, st0 = still(c, None, None, colors=raw)
        im2, st = still(c, None, {"accent": acc})
        ref = "#FFFFFF" if c == "turning" else st["colors"]["bg"]
        d["own"].append({"cat": c, "picked": acc, "ratio": round(L.contrast(acc, ref), 1), "used": st["colors"]["accent"],
                         "a": save(im, f"own-{c}-picked.jpg"), "b": save(im2, f"own-{c}-drawn.jpg"), "note": st["notes"][0] if st["notes"] else ""})
    # 3 backgrounds
    d["bg"] = []
    for c, look, ilook, bd, cap in (
            ("timeline", None, None, None, "Its own background"),
            ("timeline", {"background": "footage"}, None, None, "Your footage, darkened (see-through)"),
            ("timeline", {"background": "still"}, None, "kenny.jpg", "A still from your footage"),
            ("timeline", {"background": "photo"}, None, PHOTO, "A photo from the project"),
            ("digital", {"background": "footage", "dim": 0.75}, None, None, "Digital over footage, darkened 75%"),
            ("findings", {"background": "footage", "dim": 0.45}, None, None, "Findings over footage, darkened 45%"),
            ("legal", {"background": "footage"}, None, None, "Legal over footage (uses its dark docket)"),
            ("turning", {"background": "photo"}, None, PHOTO, "Turning point over a project photo"),
            ("contradiction", {"background": "footage"}, None, None, "Contradiction: keeps its own background")):
        im, st = still(c, look, ilook, bd)
        d["bg"].append({"src": save(im, f"bg-{c}-{(look or {}).get('background', 'own')}-{len(d['bg'])}.jpg"), "cap": cap, "note": " ".join(st["notes"])})
    # handoff with a see-through graphic: the earlier one fades out under the next (app items, frames around the cut)
    order = sorted(items().values(), key=lambda x: x["start"])
    a, b = next((a, b) for a, b in zip(order, order[1:]) if b["start"] < a["end"] and b["category"] != "contradiction")
    m = motion.normalise({"enabled": True, "items": [dict(a, status="approved"), dict(b, status="approved", look={"background": "footage"})]})
    A, B = m["items"]
    ga, gb = cinematic.build(A, slot_files(cinematic.slots(A))), cinematic.build(B, slot_files(cinematic.slots(B)))
    d["handoff"] = []
    for i, (t, cap) in enumerate(((B["start"] - 0.4, "Before: the earlier graphic"), (B["start"] + 0.08, "Crossfade (0.2 s)"),
                                  (B["start"] + 0.5, "After: the next one, over the footage"))):
        base = footage(960, 540)
        for it, g in ((A, ga), (B, gb)):
            k = int(round((t - it["start"]) * 24))
            if 0 <= k < cinematic.frames_of(it):
                base = Image.alpha_composite(base, cinematic.frame(g, it, k, 960, 540))
        d["handoff"].append({"src": save(base.convert("RGB"), f"handoff-{i}.jpg"), "cap": cap})
    d["handoff_names"] = [NAMES[A["category"]], NAMES[B["category"]]]
    # 4 vary
    d["vary"] = []
    for pid, name in (("1a5bbba59d244274", "Jevario Buie"), ("4791316c6fae4722", "Project 2"), ("1b06752858c94e67", "Project 3")):
        row = []
        for c in ["findings", "timeline", "legal", "digital", "turning"]:
            im, st = still(c, {"vary": True, "seed": pid})
            row.append({"src": save(im, f"vary-{pid[:6]}-{c}.jpg"), "cap": f"{NAMES[c]} · set {st['palette']}"})
        d["vary"].append({"name": name, "row": row})
    print("stills done", flush=True)
    clips_file = OUT / "clips.json"
    if with_clips:
        cl = []
        for name, key, look, ilook, bd, cap in CLIPS:
            r = clip(name, key, look, ilook, bd)
            cl.append({"src": r["src"], "cap": cap, "notes": r["notes"]})
        clips_file.write_text(json.dumps(cl))
    d["clips"] = json.loads(clips_file.read_text()) if clips_file.exists() else []
    (OUT / "index.html").write_text(page(d))
    print("->", OUT / "index.html")


def page(d):
    def fig(src, cap, cls="", sub=""):
        return f'<figure class="{cls}"><img src="{src}" loading="lazy"><figcaption>{cap}{f"<small>{sub}</small>" if sub else ""}</figcaption></figure>'

    def sw(cols):
        return "".join(f'<i style="background:{c}"></i>' for c in cols)
    clips = "".join(f'<figure><video src="{c["src"]}" controls preload="metadata" playsinline></video><figcaption>{c["cap"]}'
                    f'{"<small>" + " ".join(c["notes"]) + "</small>" if c["notes"] else ""}</figcaption></figure>' for c in d["clips"])
    scope = "".join(fig(x["src"], x["cap"] + (" · <b>changed on this graphic</b>" if x["changed"] else " · project look"), "on" if x["changed"] else "")
                    for x in d["scope"])
    sets = "".join(f'<h3>{NAMES[c]}</h3><div class="grid g4">' + "".join(
        fig(s["src"], f'<b>{s["key"]}</b> · {s["label"]} <span class="sw">{sw(s["sw"])}</span>',
            sub=f'text {s["text"]}:1 · accent {s["accent"]}:1' + (" · the approved design" if i == 0 else ""))
        for i, s in enumerate(d["sets"][c])) + "</div>" for c in CATS)
    own = "".join(f'<h3>{NAMES[x["cat"]]}</h3><div class="grid g2">'
                  + fig(x["a"], f'You picked <span class="sw">{sw([x["picked"]])}</span> {x["picked"]}', "bad", f'{x["ratio"]}:1 — too faint (needs 3:1)')
                  + fig(x["b"], f'The app draws <span class="sw">{sw([x["used"]])}</span> {x["used"]}', "ok", x["note"]) + "</div>" for x in d["own"])
    bg = '<div class="grid g3">' + "".join(fig(x["src"], x["cap"], sub=x["note"]) for x in d["bg"]) + "</div>"
    ho = '<div class="grid g3">' + "".join(fig(x["src"], x["cap"]) for x in d["handoff"]) + "</div>"
    vary = "".join(f'<h3>{p["name"]}</h3><div class="grid g5">' + "".join(fig(x["src"], x["cap"]) for x in p["row"]) + "</div>" for p in d["vary"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cinematic graphics — look options (v0.4.63)</title><style>
body{{background:#0e0f12;color:#e9e6df;font:15px/1.5 -apple-system,Segoe UI,Inter,sans-serif;margin:0;padding:28px 40px 90px;max-width:1600px}}
h1{{font-size:28px;margin:0 0 6px}} h2{{font-size:21px;margin:48px 0 6px;border-top:1px solid #2a2c31;padding-top:26px}}
h3{{font-size:14px;margin:22px 0 8px;color:#c9c4b8;text-transform:uppercase;letter-spacing:.06em}}
p.q{{color:#b8b3a8;max-width:1050px;margin:4px 0 12px}} .note{{background:#17181c;border-left:3px solid #f2b33d;padding:10px 14px;color:#c9c4b8;max-width:1050px}}
.grid{{display:grid;gap:14px}} .g2{{grid-template-columns:repeat(2,1fr)}} .g3{{grid-template-columns:repeat(3,1fr)}} .g4{{grid-template-columns:repeat(4,1fr)}}
.g5{{grid-template-columns:repeat(5,1fr)}} @media(max-width:900px){{.g3,.g4,.g5{{grid-template-columns:repeat(2,1fr)}}}}
figure{{margin:0;background:#16171b;border:1px solid #24262b;border-radius:8px;overflow:hidden}} figure.on{{outline:3px solid #f2b33d}}
figure.bad figcaption{{color:#ff8b7b}} figure.ok figcaption{{color:#8fe0a8}}
img,video{{width:100%;display:block;background:#000}} figcaption{{padding:8px 10px;font-size:13px}} small{{display:block;color:#8f8b82;margin-top:3px}}
.sw i{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:2px;vertical-align:-1px;border:1px solid #0008}}
</style></head><body>
<h1>Cinematic graphics — look options</h1>
<p class="note">Built in v0.4.63 (PR #22, not merged). Every picture and clip is drawn by the app's own look code — the same frames the editor previews
and the export writes. Words and photos are the approved Javits material. Stand-ins: <b>“your footage”</b> is the NYPD briefing photo (slowly pushing in
in the clips), <b>“a project photo”</b> is the courthouse. In the app: Motion › <i>Look of all cinematic graphics</i> (the whole project), or select a
graphic › <i>LOOK</i> (that graphic only).</p>
<h2>Moving examples — narration, word timing and the designed sound</h2><div class="grid g3">{clips}</div>
<h2>1 · Whole project + one graphic changed</h2>
<p class="q">The project look sets colour set B for everything; the legal graphic was changed on its own to set C (outlined). “Use the project look” on a graphic puts it back.</p>
<div class="grid g5">{scope}</div>
<h2>2a · Ready-made colour sets</h2><p class="q">Three tested sets per category (A is the approved design), plus a light version (or the dark docket for the paper one) where the design has one.
Every set passes text ≥ 4.5:1 and accent ≥ 3:1 against its background.</p>{sets}
<h2>2b · Your own colours, checked for readability</h2><p class="q">Pick any accent or text colour. One too faint to read is drawn in the nearest readable shade of the same colour, and the graphic tells you.</p>{own}
<h2>3 · Backgrounds</h2><p class="q">Its own background, your footage darkened (see-through), a still from your footage, or a photo from the project, with a Darken setting (40–85%).
The paper docket switches to its dark version over a picture; contradiction keeps its own background (its columns fill the screen).</p>{bg}
<h3>Back to back with a see-through graphic ({d["handoff_names"][0]} → {d["handoff_names"][1]} over the footage)</h3>
<p class="q">An opaque graphic covers the one before it; a see-through one would show it underneath, so the earlier one fades out during the next one's 0.2 s fade-in.</p>{ho}
<h2>4 · Automatic variation (a switch on the project)</h2><p class="q">The same graphics as three projects get them: each project its own mix of the tested sets, always the same for that project.
Sets you choose by hand win.</p>{vary}
</body></html>"""


if __name__ == "__main__":
    build("--clips" in sys.argv[1:])
