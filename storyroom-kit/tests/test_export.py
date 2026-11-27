"""Rendering: a transparent video, the sound cues, a preview MP4 and the placement lists, at the plan's times."""
import csv
import json
import subprocess

import numpy as np
from PIL import Image

from storyroom_kit import export as X
from storyroom_kit import graphics as G
from storyroom_kit import plan as PL

from conftest import KIT

SHERIFF = (KIT / "examples" / "sheriff" / "script.md").read_text()


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,pix_fmt,width,height", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"]


def test_render_one_graphic_small(tmp_path, ffmpeg):
    plan = PL.make(SHERIFF)
    turning = next(n for n, g in enumerate(plan["graphics"], 1) if g["category"] == "turning")
    rep = X.render_plan(plan, tmp_path, only=[turning], size=(640, 360), alpha="prores", log=lambda *_: None)
    g = rep["graphics"][0]
    assert g["category"] == "turning" and g["frames"] == G.frames_of(plan["graphics"][turning - 1])
    v = _probe(tmp_path / g["files"]["video"])[0]
    assert v["codec_name"] == "prores" and v["pix_fmt"].startswith("yuva") and (v["width"], v["height"]) == (640, 360)
    kinds = {s["codec_name"] for s in _probe(tmp_path / g["files"]["preview"])}
    assert kinds == {"h264", "aac"}
    assert (tmp_path / g["files"]["sound"]).stat().st_size > 10_000 and g["cues"]
    rows = list(csv.DictReader(open(tmp_path / "placements.csv")))
    assert rows[0]["category"] == "turning" and float(rows[0]["start_s"]) == g["start"]
    edl = (tmp_path / "timeline.edl").read_text()
    assert "FROM CLIP NAME: " + g["files"]["video"] in edl and X.tc(g["start"], 24) in edl


def test_png_sequence_has_the_fade_in_its_transparency(tmp_path, ffmpeg):
    plan = PL.make(SHERIFF, categories=["contradiction"])
    rep = X.render_plan(plan, tmp_path, size=(480, 270), alpha="png", mp4=False, wav=False, log=lambda *_: None)
    seq = tmp_path / "01-contradiction"
    first, mid = Image.open(seq / "00000.png"), Image.open(seq / f"{rep['graphics'][0]['frames'] // 2:05d}.png")
    assert first.mode == "RGBA" and first.getchannel("A").getextrema()[1] < 40
    assert mid.getchannel("A").getextrema() == (255, 255)


def test_over_footage_is_see_through(tmp_path):
    plan = PL.make(SHERIFF, categories=["timeline"], look={"background": "footage", "dim": 0.5})
    it = plan["graphics"][0]
    g = G.build(it)
    a = np.asarray(G.frame(g, it, G.frames_of(it) // 2, 1920, 1080).getchannel("A"))
    assert a.min() == round(255 * 0.5) or a.min() < 255   # the darkening shows the video through
    assert a.max() == 255                                   # the type itself is solid


def test_stills(tmp_path):
    plan = PL.make(SHERIFF, categories=["legal"])
    files = X.stills(plan, tmp_path, at=[1.0, 5.0], size=(640, 360))
    assert len(files) == 2 and Image.open(files[0]).size == (640, 360)


def test_other_frame_rates(tmp_path, ffmpeg):
    plan = PL.make(SHERIFF, categories=["turning"], fps=30)
    it = plan["graphics"][0]
    assert plan["fps"] == 30 and abs(it["start"] * 30 - round(it["start"] * 30)) < 1e-6
    assert G.frames_of(it) == int(round((it["dur"] + 0.6) * 30))
    rep = X.render_plan(plan, tmp_path, size=(480, 270), alpha="qtrle", mp4=False, wav=False, log=lambda *_: None)
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=nb_read_frames,r_frame_rate", "-of", "json",
                          str(tmp_path / rep["graphics"][0]["files"]["video"])], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    assert s["r_frame_rate"] == "30/1" and int(s["nb_read_frames"]) == G.frames_of(it)
    PL.make(SHERIFF)  # back to the default rate for the other tests
