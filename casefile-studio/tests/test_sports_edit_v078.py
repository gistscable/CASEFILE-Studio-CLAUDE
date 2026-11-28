"""v0.4.78 Sports engine pieces still used by the Edit page (v0.4.79): footage analysis, the planner (which now
only fills the scenes the guide left empty), the shared test helpers and the sports sounds."""
from __future__ import annotations

import json
import subprocess
import time

import numpy as np

import sportsedit
from cinegfx.sports import planner as P
from cinegfx.sports import semantics as S
from cinegfx.sports import shots as SH
from cinegfx.timing import ffbin

SCRIPT = ("Lionel Messi.\n\n"
          "The sixth of April, twenty ten. Camp Nou.\n\n"
          "One. Twenty-one minutes, from the edge of the box. Two. Thirty-seven, calmly past the keeper. "
          "Three. Forty-two, a chip.\n\n"
          "Four goals. One night.")


def heard_for(script, gap=0.36):
    import autotiming
    out, t = [], 0.2
    for para in script.split("\n\n"):           # a narrator pauses between paragraphs
        for w in autotiming.script_words(para):
            out.append({"word": w, "start": round(t, 3), "end": round(t + gap - 0.04, 3)})
            t += gap + (0.35 if w.endswith((".", "!", "?")) else 0)
        t += 0.9
    return out


def words():
    return S.timeline([{"text": SCRIPT, "at": 0.8, "heard": heard_for(SCRIPT)}])


def make_video(path, size="320x180"):
    """Three shots: a green pitch (with movement), a dark shot, a busy texture."""
    subprocess.run([ffbin(), "-v", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c=0x2f8a3a:s={size}:d=4:r=25",
                    "-f", "lavfi", "-i", f"color=c=0x141414:s={size}:d=3:r=25",
                    "-f", "lavfi", "-i", f"testsrc2=s={size}:d=3:r=25",
                    "-filter_complex", "[0:v]drawgrid=w=32:h=30:t=2:c=white@0.7,noise=alls=12:allf=t[a];[a][1:v][2:v]concat=n=3:v=1[v]",
                    "-map", "[v]", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(path)],
                   check=True)


def make_tone(path, seconds):
    subprocess.run([ffbin(), "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=44100:duration={seconds}",
                    str(path)], check=True)


# ---------------------------------------------------------------- footage analysis
def test_classify_reads_the_picture_not_the_name():
    base = {"luma": 0.4, "sat": 0.4, "edges": 0.06, "person": None}
    assert SH.classify({**base, "green": 0.8, "motion": 0.02})[0] == "wide"
    assert SH.classify({**base, "green": 0.7, "motion": 0.09})[0] == "action"
    assert SH.classify({**base, "green": 0.0, "motion": 0.05, "luma": 0.1})[0] == "dark"
    assert SH.classify({**base, "green": 0.05, "motion": 0.05, "edges": 0.09})[0] == "crowd"
    assert SH.classify({**base, "green": 0.02, "motion": 0.05, "edges": 0.04})[0] == "close"
    assert SH.classify({**base, "green": 0.1, "motion": 0.05, "person": 0.3})[0] == "close"
    k, why = SH.classify({**base, "green": 0.8, "motion": 0.02})
    assert "pitch" in why and "%" in why


def test_detect_finds_hard_cuts_but_not_movement():
    rng = np.random.default_rng(1)
    frames = []
    for colour, n in (((40, 140, 60), 40), ((20, 20, 20), 30), ((200, 180, 160), 30)):
        for k in range(n):
            f = np.full((SH.SH, SH.SW, 3), colour, np.uint8)
            x = (k * 2) % SH.SW                       # a moving bar inside the shot is not a cut
            f[:, x:x + 6] = 255
            frames.append(np.clip(f + rng.integers(0, 6, f.shape), 0, 255).astype(np.uint8))
    spans, meas, motion = SH.detect(iter(frames))
    assert [a for a, _ in spans] == [0, 40, 70]


def test_analyse_a_file_and_cache_it(tmp_path):
    v = tmp_path / "clip.mp4"
    make_video(v)
    assert SH.cached(str(v), tmp_path / "c") is None
    info = SH.analyse(str(v), tmp_path / "c")
    kinds = [s["kind"] for s in info["shots"]]
    assert len(info["shots"]) == 3, info["shots"]
    assert kinds[0] in ("wide", "action") and kinds[1] == "dark"
    assert abs(info["shots"][1]["t0"] - 4.0) < 0.2 and abs(info["shots"][2]["t0"] - 7.0) < 0.2
    assert SH.cached(str(v), tmp_path / "c") == info


# ---------------------------------------------------------------- planner
def lib():
    shots = [{"t0": 0.0, "t1": 6.0, "kind": "wide", "why": "pitch 80%", "person": None},
             {"t0": 6.0, "t1": 12.0, "kind": "close", "why": "large shapes", "person": None},
             {"t0": 12.0, "t1": 18.0, "kind": "action", "why": "fast", "person": None},
             {"t0": 18.0, "t1": 24.0, "kind": "crowd", "why": "texture", "person": None},
             {"t0": 24.0, "t1": 30.0, "kind": "action", "why": "fast", "person": None},
             {"t0": 30.0, "t1": 36.0, "kind": "close", "why": "large shapes", "person": None}]
    return [{"id": "v1", "name": "match.mp4", "kind": "video", "shots": shots},
            {"id": "p1", "name": "camp_nou_2010.jpg", "kind": "image", "shots": []},
            {"id": "p2", "name": "holiday_beach.jpg", "kind": "image", "shots": []}]


def test_plan_cuts_on_words_and_explains_every_choice():
    ws = words()
    els = S.analyse(ws)
    fams = [e.family for e in els]
    assert "name" in fams and "numbered" in fams
    pl = P.plan(ws, els, lib(), "emotional", lead=0.8)
    starts = {round(w.s, 3) for w in ws} | {0.0}
    for c in pl["cuts"][1:]:
        assert c["t"] in starts or any(abs(c["t"] - e.t_in) < 1e-3 for e in els), c
        assert c["why"] and c["need"] and c["asset_id"]
    for a, b in zip(pl["cuts"], pl["cuts"][1:]):
        assert a["end"] == b["t"]
    # each spoken number of the numbered list starts a new shot
    num = next(e for e in els if e.family == "numbered")
    cut_times = [c["t"] for c in pl["cuts"]]
    for it in num.data["items"]:
        assert any(abs(t - it["t"]) < 1e-3 for t in cut_times)
    # the photo only where its name is spoken; the unrelated photo never
    photos = [c for c in pl["cuts"] if c["photo"]]
    assert photos and all(c["asset_id"] == "p1" for c in photos)
    assert "camp" in photos[0]["why"]
    # the name graphic's shot asks for a close-up (type behind the player when segmentation is available)
    name = next(e for e in els if e.family == "name")
    under = next(c for c in pl["cuts"] if c["t"] <= name.t_in < c["end"])
    assert under["matte"] and under["kind"] == "close"


def test_every_style_and_auto():
    ws = words()
    els = S.analyse(ws)
    seen = set()
    for k in P.STYLE_KEYS:
        pl = P.plan(ws, els, lib(), k, lead=0.8)
        assert pl["style"] in P.STYLES and pl["style"] != "auto"
        assert pl["music"] and pl["music"][0][0] == 0.0
        seen.add((pl["style"], len(pl["cuts"])))
    fast = P.plan(ws, els, lib(), "high_energy", lead=0.8)
    slow = P.plan(ws, els, lib(), "historical", lead=0.8)
    assert len(fast["cuts"]) > len(slow["cuts"])
    assert {c["grade"] for c in P.plan(ws, els, lib(), "analytical", lead=0.8)["cuts"] if not c["photo"]} <= \
        {"natural", "mono_cool", "low_key", "punch"}


def test_overrides_graphics_moves_and_shots():
    ws = words()
    els = S.analyse(ws)
    pl = P.plan(ws, els, lib(), "emotional", lead=0.8)
    g = pl["graphics"][0]
    c2 = pl["cuts"][2]
    c3 = pl["cuts"][3]
    ov = {"graphics": {g["key"]: False}, "moves": {c2["key"]: c2["t"] + 0.3}, "shots": {c3["key"]: {"asset_id": "v1", "in": 25.0}}}
    p2 = P.plan(ws, els, lib(), "emotional", lead=0.8, overrides=ov)
    g2 = next(x for x in p2["graphics"] if x["key"] == g["key"])
    assert not g2["on"] and g2["note"] == "switched off by hand"
    m = next(x for x in p2["cuts"] if x["key"] == c2["key"])
    assert m["moved"] and abs(m["t"] - (c2["t"] + 0.3)) < 1e-6
    s = next(x for x in p2["cuts"] if x["key"] == c3["key"])
    assert s["in"] == 25.0 and s["hand"] and s["why"] == "chosen by hand"
    assert p2["stale"] == []
    # a cut can't be moved past its neighbours
    p3 = P.plan(ws, els, lib(), "emotional", lead=0.8, overrides={"moves": {c2["key"]: 999}})
    k = [x["key"] for x in p3["cuts"]].index(c2["key"])
    assert p3["cuts"][k]["t"] < p3["cuts"][k + 1]["t"] if k + 1 < len(p3["cuts"]) else p3["cuts"][k]["t"] < p3["duration"]
    # a choice for a cut that no longer exists is reported, not applied
    p4 = P.plan(ws, els, lib(), "emotional", lead=0.8, overrides={"shots": {"999.99": {"asset_id": "v1", "in": 1}}})
    assert p4["stale"] == ["999.99"]


def test_no_footage_means_no_invented_pictures():
    ws = words()
    pl = P.plan(ws, S.analyse(ws), [], "auto", lead=0.8)
    assert all(c["asset_id"] is None and c["why"] == "no footage in the project" for c in pl["cuts"])


def test_thin_keeps_the_stronger_of_overlapping_graphics():
    a = S.Element("label", 1.0, 5.0, {"lines": []})
    b = S.Element("impact", 4.0, 7.0, {"value": "4"})
    assert P.thin([a, b], 0.3) == [b]


# ---------------------------------------------------------------- settings (v0.4.79: the Edit page builds the video;
# the settings, the Edit-page flow and the export are tested in test_sports_gfx_v079.py)
def test_segmentation_status_explains_how_to_enable():
    st = sportsedit.segmentation()
    assert set(st) >= {"available", "reason", "how", "license"}
    assert any("onnxruntime" in h for h in st["how"]) and any("models/" in h for h in st["how"])
    if not st["available"]:
        assert st["reason"]


# ---------------------------------------------------------------- the app
def wait_job(server, job_id, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        j = server.JOBS[job_id]
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def make_project(client, root, niche="football"):
    pid = client.post("/api/projects", json={"title": "Four goals", "mode": "script", "target_minutes": 20, "niche": niche}).json()["id"]
    media = root / "in"
    media.mkdir(exist_ok=True)
    make_tone(media / "narration.wav", 14)
    make_video(media / "match_highlights.mp4")
    from PIL import Image
    Image.new("RGB", (480, 270), (90, 70, 60)).save(media / "camp_nou_2010.jpg")
    for name, mime, extra in (("narration.wav", "audio/wav", {"audio_role": "narration"}), ("match_highlights.mp4", "video/mp4", {}),
                              ("camp_nou_2010.jpg", "image/jpeg", {})):
        with open(media / name, "rb") as f:
            assert client.post(f"/api/projects/{pid}/upload", files=[("files", (name, f, mime))], data=extra).status_code == 200
    p = client.get(f"/api/projects/{pid}").json()
    nid = next(a["id"] for a in p["assets"] if a["kind"] == "audio")
    assert client.patch(f"/api/projects/{pid}", json={"narration_id": nid}).status_code == 200
    return pid


def import_text(client, pid):
    assert client.post(f"/api/projects/{pid}/episode/import", json={"role": "script", "text": SCRIPT, "filename": "s.md"}).status_code == 200
    js = json.dumps({"source": "test", "words": heard_for(SCRIPT)})
    r = client.post(f"/api/projects/{pid}/episode/import", json={"role": "timings", "text": js, "filename": "word_timings.json"})
    assert r.status_code == 200, r.text


def test_glitch_sound_never_overruns_and_is_the_same_every_run():
    from cinegfx.sports import score
    for k in range(300):                       # v0.4.77 could write a burst past the end (seed-dependent)
        assert score._glitch(np.random.default_rng(k)).shape[0] == 2
    import zlib
    a = score._glitch(np.random.default_rng(zlib.crc32(b"sp-glitch")))
    b, _ = score.sound("sp-glitch")
    assert np.allclose(a / (np.max(np.abs(a)) + 1e-9), b / (np.max(np.abs(b)) + 1e-9), atol=1e-5)
