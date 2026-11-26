"""v0.4.56 Sound design demonstrations: every demo is rendered twice by the real exporter, with
sound design off ("before") and on ("after"), at 720p. Because the narration is identical in both,
after minus before is exactly what the sound design added: the script measures from that difference
where each sound actually landed (sync), how loud it is against the speech, and the peaks.

    cd casefile-studio && PATH=$PWD/.venv/bin:$PATH .venv/bin/python qa/sound-design/make_demos.py [names]

Voices: AI-generated for this demo (qa/sound-design/voice). Pictures: neutral placeholder plates —
no case imagery is made up. The guide-plan check (episode.issues) is skipped for these synthetic
projects only; the audio path is the exporter's own.
"""
from __future__ import annotations

import json
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent.parent
sys.path.insert(0, str(APP))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import episode  # noqa: E402
import motion  # noqa: E402
import renderer  # noqa: E402
import sound  # noqa: E402

episode.issues = lambda project: []  # synthetic guide projects (see above)
OUT = HERE
WORK = HERE / "work"
VOICE = HERE / "voice"
FONT = APP / "web" / "assets" / "fonts"
LEAD = 1.5  # seconds of quiet before the narration in each demo


def run(cmd):
    return subprocess.run(cmd, capture_output=True, check=True)


def padded(name, lead=LEAD, tail=1.2):
    out = WORK / f"{name}.wav"
    if not out.exists():
        run(["ffmpeg", "-v", "error", "-y", "-i", str(VOICE / f"{name}.mp3"), "-af", f"adelay={int(lead * 1000)}:all=1,apad=pad_dur={tail}",
             "-ar", "48000", "-ac", "2", str(out)])
    return out


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).stdout)


def plate(name, label, tone=(28, 34, 40)):
    """A neutral placeholder picture (no case imagery is made up)."""
    out = WORK / f"{name}.png"
    if not out.exists():
        im = Image.new("RGB", (1280, 720), tone)
        d = ImageDraw.Draw(im)
        for y in range(720):
            k = y / 720
            d.line([(0, y), (1280, y)], fill=tuple(int(c * (1.15 - 0.4 * k)) for c in tone))
        f = ImageFont.truetype(str(next(FONT.glob("Oswald*"))), 30)
        d.text((60, 640), label.upper(), font=f, fill=(150, 150, 150))
        d.text((60, 600), "DEMO PLATE", font=ImageFont.truetype(str(next(FONT.glob("Oswald*"))), 18), fill=(110, 110, 110))
        im.save(out)
    return out


def asset(aid, path, kind):
    a = {"id": aid, "kind": kind, "path": str(path), "name": Path(path).name}
    if kind in ("audio", "video"):
        a["duration"] = duration(path)
        a["has_audio"] = True
    if kind in ("image", "video"):
        a["width"], a["height"] = 1280, 720
    return a


def sentences_of(name, texts):
    """Caption times for each sentence from the recording's own pauses (silencedetect)."""
    log = subprocess.run(["ffmpeg", "-nostdin", "-i", str(VOICE / f"{name}.mp3"), "-af", "silencedetect=noise=-35dB:d=0.25", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    import re

    ends = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    starts = [0.05] + [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    total = duration(VOICE / f"{name}.mp3")
    return starts, ends + [total], total


def project(pid, title, scenes, assets, narration, motion_items=(), cta=None, sound_on=False, guide=True, preset="cinematic"):
    p = {"id": pid, "title": title, "look": "natural", "captions": False, "music_volume": 0, "aspect": "16:9",
         "assets": assets, "scenes": scenes, "narration_id": narration, "exports": [],
         "motion": {"enabled": bool(motion_items), "items": list(motion_items)},
         "sound": {"enabled": sound_on, "preset": preset}}
    if guide:
        p["episode"] = {"guide": True, "plan": {"mode": "final"}}
    if cta:
        p["cta"] = cta
    return p


def render(p, name):
    out = OUT / f"{name}.mp4"
    t0 = time.monotonic()
    r = renderer.render(p, {"resolution": "720p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    return out, r, time.monotonic() - t0


def pcm(path, channels=1):
    """Decoded audio. Mono is the left channel (the renders are dual-mono): FFmpeg's own downmix of
    some AAC files reports peaks above the real stereo signal."""
    raw = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ar", "48000", "-"]).stdout
    x = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    return x if channels == 2 else np.ascontiguousarray(x[:, 0])


def measure(before, after, placed, stem=None):
    a, b = pcm(after), pcm(before)
    n = min(len(a), len(b))
    diff = a[:n] - b[:n]
    sr = 48000
    env = np.sqrt(np.convolve(diff ** 2, np.ones(int(0.002 * sr)) / int(0.002 * sr), mode="same"))
    rise = np.diff(env, prepend=env[0])

    def onset(t, w=0.025):
        """Where the sound actually starts near `t`: the steepest rise of its 2 ms envelope."""
        lo, hi = max(0, int((t - w) * sr)), int((t + w) * sr)
        seg = rise[lo:hi]
        return None if not seg.size or env[lo:hi].max() < 1e-5 else (np.argmax(seg) + lo) / sr

    speech = np.sqrt(np.convolve(b[:n] ** 2, np.ones(int(0.4 * sr)) / int(0.4 * sr), mode="same"))
    fx_s = np.sqrt(np.convolve(diff ** 2, np.ones(int(0.4 * sr)) / int(0.4 * sr), mode="same"))
    talking = speech > 10 ** (-35 / 20)
    ratio = 20 * np.log10((fx_s[talking].max() + 1e-9) / (np.median(speech[talking]) + 1e-9)) if talking.any() else None
    errs = []
    starts = sorted([(p["start"], p["start"] + p["seconds"]) for p in placed if not p["keys"]] +
                    [(k[0] - 0.01, k[0] + 0.15) for p in placed if p["keys"] for k in p["keys"]])
    for p in placed:
        if p["keys"]:
            continue
        others = [s for s in starts if s != (p["start"], p["start"] + p["seconds"])]
        if any(s0 < p["t"] + 0.15 and s1 > p["t"] - 0.15 for s0, s1 in others):
            continue  # another sound rings across this one: no clean onset to measure
        info = sound.sfxlib.BY_ID.get(p["sound"])
        if not info or info[1] in sound.sfxlib.SYNC_AT_END | sound.sfxlib.SYNC_AT_PEAK | {"swell", "scan", "paper", "document", "pulse", "bell"}:
            continue  # slow shapes: no single transient to find
        o = onset(p["t"])
        if o is not None:
            errs.append(float(abs(o - p["t"]) * 1000))
    # whole-track alignment: the effects heard in the export against the stem that was mixed
    lag_ms = None
    if stem is not None:
        ref = np.pad(pcm(stem), (0, n))[:n]
        L = int(0.05 * sr)
        best = max(range(-L, L + 1, 4), key=lambda k: float(np.dot(diff[max(0, k):n + min(0, k)], ref[max(0, -k):n - max(0, k)])))
        best = max(range(best - 4, best + 5), key=lambda k: float(np.dot(diff[max(0, k):n + min(0, k)], ref[max(0, -k):n - max(0, k)])))
        lag_ms = round(best / sr * 1000, 3)
    # v0.4.57 exact placement: every sound (and every typed key) found in the stem by
    # cross-correlating its own waveform (the onset estimates above are read through AAC, whose
    # pre-echo smears quiet onsets; the stem is what the export mixes, at 0.0 ms lag)
    place = []
    if stem is not None:
        st = pcm(stem)
        for p in placed:
            for t, sid in ([(k[0], k[1]) for k in p["keys"]] if p["keys"] else [(p["t"], p["sound"])]):
                info = sound.sfxlib.BY_ID.get(sid)
                if not info:
                    continue
                w, sync = sound.sfxlib.synth(sid)
                w = w[0][: int(0.25 * sr)]
                start = int(round((t - sync) * sr))
                L = int(0.02 * sr)
                seg = st[max(0, start - L): start + L + len(w)]
                if start - L < 0 or len(seg) < 2 * L + len(w):
                    continue
                c = np.correlate(seg, w, mode="valid")
                place.append(abs(int(np.argmax(c)) - L) / sr * 1000)
    keys = [k for p in placed if p["keys"] for k in p["keys"]]
    kerr = []
    for t, _, _ in keys:
        o = onset(t, 0.02)
        if o is not None:
            kerr.append(float(abs(o - t) * 1000))
    return {
        "after_peak_dbfs": round(float(20 * np.log10(np.abs(pcm(after, 2)).max() + 1e-9)), 2),  # stereo, as delivered
        "after_samples_over_full_scale": int((np.abs(pcm(after, 2)) >= 1.0).sum()),
        "effects_peak_dbfs": round(float(20 * np.log10(np.abs(diff).max() + 1e-9)), 2),
        "loudest_effect_vs_speech_db": round(float(ratio), 1) if ratio is not None else None,
        "transient_sync_error_ms": {"n": len(errs), "max": round(max(errs), 1) if errs else None, "mean": round(float(np.mean(errs)), 1) if errs else None},
        "typing_sync_error_ms": {"n": len(kerr), "max": round(max(kerr), 1) if kerr else None,
                                 "median": round(float(np.median(kerr)), 1) if kerr else None,
                                 "p95": round(float(np.percentile(kerr, 95)), 1) if kerr else None},
        "export_vs_stem_lag_ms": lag_ms,
        "exact_placement_error_ms": {"n": len(place), "max": round(max(place), 3) if place else None},
    }


def loudness(path):
    log = subprocess.run(["ffmpeg", "-nostdin", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    import re

    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)
    return {"integrated_lufs": float(i[-1]) if i else None, "true_peak_dbfs": float(tp[-1]) if tp else None}


# ---------------------------------------------------------------------- the demos

def caption_scene(sid, text_sents, starts, ends, dur, aid, offset=0.0, **kw):
    caps = [{"start": round(s + LEAD - offset, 3), "end": round(e + LEAD - offset, 3), "text": t}
            for t, s, e in zip(text_sents, starts, ends) if s + LEAD - offset < dur]
    s = {"id": sid, "title": kw.pop("title", sid), "narration": " ".join(c["text"] for c in caps), "duration": dur, "asset_id": aid,
         "motion": "none", "show_title": False, "captions": caps, "audio_start": offset, "audio_duration": dur}
    s.update(kw)
    return s


def demo_bullets(on):
    texts = ["Phone records placed him two miles from the house.", "Surveillance video showed his car on Nebraska Avenue.",
             "And a receipt put him at the gas station eleven minutes later."]
    st, en, total = sentences_of("n1-findings", texts)
    en = [en[0], en[1], total]
    st = [st[0], st[1], st[2]]
    v = padded("n1-findings")
    dur = round(duration(v), 2)
    img = plate("d1", "Investigation · records")
    sc = [caption_scene("s1", texts, st, en, dur, "img", chapter="CHAPTER 3 — THE EVIDENCE")]
    g = motion.normalise_item({"id": "mgd1", "status": "approved", "template": "findings", "start": 0.3, "end": dur - 0.3,
                               "heading": "KEY FINDINGS", "title": "What the records showed",
                               "lines": [{"text": "Phone records: two miles from the house", "at": LEAD + st[0]},
                                         {"text": "Surveillance video: his car on Nebraska Avenue", "at": LEAD + st[1]},
                                         {"text": "Receipt: the gas station, eleven minutes later", "at": LEAD + st[2]}]})
    return project("5d0000000000d001", "Demo 1 — findings", sc, [asset("img", img, "image"), asset("nar", v, "audio")], "nar", [g], sound_on=on)


def demo_typing(on):
    texts = ["At nine forty that night, the first call reached the dispatch center.", "The caller gave one address, and hung up."]
    st, en, total = sentences_of("n2-typing", texts)
    st, en = [st[0], st[2]], [en[1], total]
    v = padded("n2-typing")
    dur = round(duration(v), 2)
    img = plate("d2", "Dispatch")
    sc = [caption_scene("s1", texts, st, en, dur, "img", chapter="CHAPTER 2 — THE NIGHT")]
    g = motion.normalise_item({"id": "mgd2", "status": "approved", "template": "findings", "layout": "list", "start": 0.3, "end": dur - 0.2,
                               "heading": "DISPATCH LOG", "title": "9:40 P.M.", "enter": "type",
                               "lines": [{"text": "First call reaches the dispatch center", "at": LEAD + st[0]},
                                         {"text": "Caller gives one address, hangs up", "at": LEAD + st[1]}]})
    return project("5d0000000000d002", "Demo 2 — typing", sc, [asset("img", img, "image"), asset("nar", v, "audio")], "nar", [g], sound_on=on)


def demo_diagram(on):
    texts = ["On March third, a neighbor saw her for the last time.", "On March ninth, investigators searched the house.",
             "And on March fourteenth, detectives made the arrest."]
    st, en, total = sentences_of("n3-timeline", texts)
    st = [st[0], st[2], st[4]]
    en = [en[1], en[3], total]
    v = padded("n3-timeline")
    dur = round(duration(v), 2)
    img = plate("d3", "Chronology")
    sc = [caption_scene("s1", texts, st, en, dur, "img", chapter="CHAPTER 2 — TIMELINE")]
    g = motion.normalise_item({"id": "mgd3", "status": "approved", "template": "timeline", "layout": "horizontal", "start": 0.3, "end": dur - 0.2,
                               "heading": "TIMELINE", "title": "Eleven days in March",
                               "lines": [{"label": "MARCH 3", "text": "Last confirmed sighting", "at": LEAD + st[0]},
                                         {"label": "MARCH 9", "text": "House searched", "at": LEAD + st[1]},
                                         {"label": "MARCH 14", "text": "Arrest made", "at": LEAD + st[2]}]})
    return project("5d0000000000d003", "Demo 3 — diagram", sc, [asset("img", img, "image"), asset("nar", v, "audio")], "nar", [g], sound_on=on)


def demo_transitions(on):
    texts = ["Investigators went back to the house the following week.", "This time, they brought a search warrant.",
             "What they found in the garage would change the direction of the entire case."]
    st, en, total = sentences_of("n4-transitions", texts)
    v = padded("n4-transitions", tail=2.0)
    dur = round(duration(v), 2)
    plates = [plate(f"d4{k}", lab, tone) for k, (lab, tone) in enumerate([("The house", (30, 36, 44)), ("Warrant", (40, 34, 30)),
                                                                          ("Garage", (26, 40, 34)), ("Chapter 4", (14, 14, 16)), ("Hard cut", (36, 30, 40))])]
    cuts = [0, 2.6, 4.9, 7.0, 9.6, dur]
    tr = [None, ("slide-left", 0.6), ("circle", 0.8), ("dip-black", 1.0), None]
    chap = ["CHAPTER 3 — THE SEARCH"] * 3 + ["CHAPTER 4 — THE EVIDENCE"] * 2
    sc = []
    for k in range(5):
        a, b = cuts[k], cuts[k + 1]
        caps = [{"start": max(0, s + LEAD - a), "end": min(b - a, e + LEAD - a), "text": t}
                for t, s, e in zip(texts, [st[0], st[1], st[3]], [en[0], en[2], total]) if s + LEAD < b and e + LEAD > a]
        s = {"id": f"s{k}", "title": f"Scene {k + 1}", "chapter": chap[k], "narration": " ".join(c["text"] for c in caps) or "",
             "duration": round(b - a, 3), "asset_id": f"p{k}", "motion": "none", "show_title": False, "captions": caps,
             "audio_start": a, "audio_duration": round(b - a, 3)}
        if tr[k]:
            s["transition"], s["transition_duration"] = tr[k]
        sc.append(s)
    assets = [asset(f"p{k}", plates[k], "image") for k in range(5)] + [asset("nar", v, "audio")]
    return project("5d0000000000d004", "Demo 4 — transitions", sc, assets, "nar", sound_on=on)


def demo_development(on):
    texts = ["For six weeks, the case stalled.", "Then the lab results came back.", "The DNA on the receipt matched him."]
    st, en, total = sentences_of("n5-development", texts)
    en = [en[0], en[1], total]
    v = padded("n5-development", tail=2.5)
    dur = round(duration(v), 2)
    img = plate("d5", "Laboratory")
    sc = [caption_scene("s1", texts, st, en, dur, "img", chapter="CHAPTER 5 — THE BREAKTHROUGH")]
    return project("5d0000000000d005", "Demo 5 — development", sc, [asset("img", img, "image"), asset("nar", v, "audio")], "nar", sound_on=on)


def banner():
    out = WORK / "banner.png"
    if not out.exists():
        im = Image.new("RGB", (1280, 720), (0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((300, 230, 980, 490), 28, fill=(24, 24, 28))
        f = ImageFont.truetype(str(next(FONT.glob("Oswald*"))), 40)
        d.text((360, 270), "CASEFILE — TRUE CRIME", font=f, fill=(235, 235, 235))
        d.rounded_rectangle((520, 380, 760, 450), 10, fill=(204, 0, 0))
        d.text((555, 386), "SUBSCRIBE", font=f, fill=(255, 255, 255))
        im.save(out)
    return out


def demo_cta(on):
    texts = ["If you want to follow this case all the way to the verdict, subscribe and turn on notifications."]
    st, en, total = sentences_of("n6-cta", texts)
    v = padded("n6-cta", lead=0.6, tail=3.5)
    dur = round(duration(v), 2)
    img = plate("d6", "Outro")
    sc = [{"id": "s1", "title": "Subscribe", "chapter": "SUBSCRIBE", "narration": texts[0], "duration": dur, "asset_id": "img",
           "motion": "none", "show_title": False, "captions": [{"start": 0.6, "end": 0.6 + total, "text": texts[0]}],
           "audio_start": 0, "audio_duration": dur}]
    assets = [asset("img", img, "image"), asset("ban", banner(), "image"), asset("nar", v, "audio")]
    import cta

    c = cta.normalise({"enabled": True, "asset_id": "ban", "opacity": 0.85, "seconds": 5.0}, {"img", "ban"}, set())
    c["button"] = cta.detect_button(banner())
    return project("5d0000000000d006", "Demo 6 — CTA", sc, assets, "nar", cta=c, sound_on=on)


def demo_interview(on):
    """Narration, then a family interview (an audio break with its own sound), then narration.
    The transitions into and out of the interview would get a whoosh anywhere else."""
    a = padded("n7a-before-interview", lead=0.8, tail=0.6)
    b = padded("n7b-after-interview", lead=0.4, tail=1.5)
    joined = WORK / "n7-narration.wav"
    if not joined.exists():
        run(["ffmpeg", "-v", "error", "-y", "-i", str(a), "-i", str(b), "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1", str(joined)])
    da, db = round(duration(a), 3), round(duration(b), 3)
    clip = WORK / "interview.mp4"
    if not clip.exists():
        run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "24", "-i", str(plate("d7i", "Interview — sister", (44, 36, 30))),
             "-i", str(VOICE / "i7-interview.mp3"), "-af", "adelay=300:all=1,apad=pad_dur=0.6", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "48000", str(clip)])
    di = round(duration(clip) - 0.1, 3)
    pa, pb = plate("d7a", "Narration"), plate("d7b", "Narration — the house", (30, 36, 44))
    cap_a = [{"start": 0.8, "end": da - 0.6, "text": "Her sister agreed to speak with us about the last time they talked."}]
    cap_b = [{"start": 0.4, "end": db - 1.5, "text": "Three days later, police records show, investigators returned to the house with a warrant."}]
    sc = [
        {"id": "s1", "title": "Intro", "chapter": "CHAPTER 4 — THE FAMILY", "narration": cap_a[0]["text"], "duration": da, "asset_id": "pa",
         "motion": "none", "show_title": False, "captions": cap_a, "audio_start": 0, "audio_duration": da},
        {"id": "s2", "title": "Interview", "chapter": "CHAPTER 4 — THE FAMILY", "narration": "", "duration": di, "asset_id": "clip", "motion": "none",
         "show_title": False, "insert_audio": True, "audio_break": True, "trim_start": 0, "transition": "slide-left", "transition_duration": 0.6},
        {"id": "s3", "title": "Back to the case", "chapter": "CHAPTER 5 — THE SEARCH", "narration": cap_b[0]["text"], "duration": db, "asset_id": "pb",
         "motion": "none", "show_title": False, "captions": cap_b, "audio_start": da, "audio_duration": db,
         "transition": "slide-left", "transition_duration": 0.6},
    ]
    assets = [asset("pa", pa, "image"), asset("pb", pb, "image"), asset("clip", clip, "video"), asset("nar", joined, "audio")]
    return project("5d0000000000d007", "Demo 7 — interview", sc, assets, "nar", sound_on=on)


DEMOS = [("1-bullet-reveals", demo_bullets), ("2-typing", demo_typing), ("3-diagram", demo_diagram), ("4-transitions", demo_transitions),
         ("5-narrative-development", demo_development), ("6-cta", demo_cta), ("7-interview-suppression", demo_interview)]


def main(names):
    WORK.mkdir(parents=True, exist_ok=True)
    renderer.DATA = WORK / "data"
    report = {}
    for name, make in DEMOS:
        if names and not any(n in name for n in names):
            continue
        before, rb, tb = render(make(False), f"demo-{name}-before")
        p = make(True)
        t0 = time.monotonic()
        plan, info = sound.plan(p)
        t_plan = time.monotonic() - t0
        after, ra, ta = render(p, f"demo-{name}-after")
        placed, gone = sound.resolve(p, renderer.DATA)
        total = sum(round(float(s["duration"]) * 24) / 24 for s in p["scenes"])
        stem = sound.stem(p, renderer.DATA, total, WORK)[0] if placed else None
        m = measure(before, after, placed, stem)
        report[name] = {
            "sounds": [{"t": r["t"], "sound": r["sound"], "label": r["label"], "keys": len(r["keys"] or [])} for r in placed],
            "silenced": info["silenced"], "warnings": ra["warnings"], "render_s": {"before": round(tb, 2), "after": round(ta, 2)},
            "plan_s": round(t_plan, 3), **m, "loudness_after": loudness(after), "loudness_before": loudness(before),
        }
        print(name, json.dumps({k: report[name][k] for k in ("render_s", "transient_sync_error_ms", "typing_sync_error_ms", "exact_placement_error_ms", "export_vs_stem_lag_ms",
                                                            "loudest_effect_vs_speech_db", "after_peak_dbfs")}))
        for r in placed:
            print(f"   {r['t']:6.2f}s {r['sound']:16s} {r['label']}" + (f" ({len(r['keys'])} keys)" if r["keys"] else ""))
        for s in info["silenced"]:
            print(f"   {s['t']:6.2f}s SILENT  {s['label']} — {s['why']}")
    report["max_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    (OUT / "demo-report.json").write_text(json.dumps(report, indent=1))
    shutil.rmtree(WORK / "data", ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
