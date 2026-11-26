"""v0.4.19: the narration is rendered back-to-back exactly as it sounds.

A narration file whose timestamps jump (some MP3, phone and CapCut exports do)
used to lose audio at the end of a guided render, and the final coverage check
then rejected the export. The renderer now rebuilds narration timestamps from
the sample count, so every sample plays once, in order, with no gap.
"""
import io
import subprocess

import numpy as np
from PIL import Image

import app as server
import renderer
import storage
from test_episode import api_project

RATE = 48000
SECONDS = 6.04


def sweep(t):
    # A rising tone: every moment has a unique pitch, so a skip, repeat or gap
    # shows up as a pitch mismatch.
    return 200 + 1400 * t / SECONDS


def gapped_narration(folder):
    clean = folder / "clean.m4a"
    gapped = folder / "narration-with-timestamp-jump.m4a"
    expr = f"0.5*sin(2*PI*(200*t+700*t*t/{SECONDS}))"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"aevalsrc='{expr}':s={RATE}:d={SECONDS}", "-c:a", "aac", "-b:a", "160k", str(clean)],
        check=True, capture_output=True,
    )
    # Same samples, but the timestamps jump 0.3 s forward at 3 s.
    jump, at = int(0.3 * RATE), 3 * RATE
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(clean), "-c", "copy", "-bsf:a",
         f"setts=pts='if(gte(PTS,{at}),PTS+{jump},PTS)':dts='if(gte(DTS,{at}),DTS+{jump},DTS)'",
         str(gapped)],
        check=True, capture_output=True,
    )
    return gapped


def decoded(path, rate=16000):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
         "-ar", str(rate), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32), rate


def test_guided_render_keeps_narration_continuous_despite_timestamp_jumps(isolated):
    c, root = isolated
    p, url = api_project(c)
    picture = io.BytesIO()
    Image.new("RGB", (640, 360), "#283c47").save(picture, format="JPEG")
    still = io.BytesIO()
    Image.new("RGB", (640, 360), "#40342a").save(still, format="JPEG")
    files = [
        ("files", ("S01-synthetic.jpg", picture.getvalue(), "image/jpeg")),
        ("files", ("S03-synthetic.jpg", still.getvalue(), "image/jpeg")),
    ]
    assert c.post(url + "/upload", data={"episode_role": "sources"}, files=files).status_code == 200
    narration = gapped_narration(root)
    r = c.post(
        url + "/upload",
        data={"episode_role": "narration"},
        files={"files": (narration.name, narration.read_bytes(), "audio/mp4")},
    )
    assert r.status_code == 200, r.text
    v = r.json()["assets"][-1]
    assert c.patch(url + "/episode/options", json={"narration_id": v["id"]}).status_code == 200
    assert c.post(url + "/episode/autolink", json={}).status_code == 200
    for sid in ("S01", "S03"):
        assert c.patch(
            url + "/episode/source/" + sid,
            json={"license": "Synthetic QA media created locally, not case evidence.",
                  "rights_confirmed": True},
        ).status_code == 200
    for cue in ("C01", "C02"):
        assert c.patch(url + f"/episode/cue/{cue}", json={"reviewed": True}).status_code == 200
    r = c.post(url + "/episode/build", json={"allow_placeholders": True})
    assert r.status_code == 200, r.text
    p = r.json()["project"]
    total = sum(round(float(s["duration"]) * 24) / 24 for s in p["scenes"])

    record = server.write_export(
        p, {"resolution": "480p", "draft": True, "captions": False},
        lambda *_: None, lambda: False,
    )
    out = storage.DATA / "exports" / record["id"] / "documentary.mp4"
    x, rate = decoded(out)
    assert len(x) / rate >= total - 0.05
    win = int(0.04 * rate)
    checked = mismatches = quiet = 0
    for k in range(0, int((min(total, SECONDS) - 0.1) * rate) - win, win):
        seg = x[k : k + win]
        t = (k + win / 2) / rate
        if np.sqrt(np.mean(seg**2)) < 0.05:
            quiet += 1
            continue
        spec = np.abs(np.fft.rfft(seg * np.hanning(win), n=win * 8))
        f = np.argmax(spec) * rate / (win * 8)
        checked += 1
        if abs(f - sweep(t)) > 10:
            mismatches += 1
    assert checked > 100
    assert quiet == 0, "a silent gap was rendered into the narration"
    assert mismatches == 0, "the narration skipped or repeated"


def test_guided_audio_filter_uses_sample_count_timestamps():
    import inspect

    # v0.4.57 the voice bus is built by renderer.voice_graph (shared with the preview's ducking)
    src = inspect.getsource(renderer.render) + inspect.getsource(renderer.voice_graph)
    assert "asetpts=N/SR/TB" in src
    assert "[{voice_index}:a]asetpts=PTS-STARTPTS" not in src
