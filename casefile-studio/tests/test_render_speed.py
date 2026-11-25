"""v0.4.48: faster export without changing a single frame.

* scenes are encoded several at a time (scenes joined by a transition stay in order);
* a still picture with no motion is decoded and scaled once, not once per frame;
* a looped video crop seeks on the input instead of decoding from 0:00;
* progress says so when the render runs as translated Intel code or on 1-2 CPUs.
"""
import re
import shutil
import subprocess
import time

import pytest
from PIL import Image

import renderer
import storage

FPS = renderer.FPS


def frames_md5(video):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:v", "-f", "framemd5", "-"],
                         capture_output=True, text=True, check=True).stdout
    return [line.split(",")[-1].strip() for line in out.splitlines() if line and not line.startswith("#")]


@pytest.fixture
def media(tmp_path):
    folder = storage.ROOT / "qa" / ("speed-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    big = folder / "photo.jpg"
    Image.effect_mandelbrot((2400, 1600), (-2, -1.2, 1, 1.2), 60).convert("RGB").save(big, quality=90)
    clip = folder / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip)], check=True)
    assets = [
        {"id": "photo", "kind": "image", "path": str(big), "name": "photo.jpg"},
        {"id": "clip", "kind": "video", "path": str(clip), "name": "clip.mp4", "duration": 8.0},
    ]
    yield assets
    shutil.rmtree(folder, ignore_errors=True)


def scenes():
    return [
        {"id": "a", "title": "A", "asset_id": "photo", "motion": "slow-zoom", "duration": 1.5},
        {"id": "b", "title": "B", "asset_id": "photo", "motion": "none", "duration": 1.25,
         "transition": "wipe-left", "transition_duration": 0.5},
        {"id": "c", "title": "C", "asset_id": "clip", "motion": "none", "duration": 1.5, "trim_start": 2.0,
         "transition": "dissolve", "transition_duration": 0.5},
        {"id": "d", "title": "D", "asset_id": "clip", "motion": "none", "duration": 2.0, "trim_start": 5.0,
         "source_crop_end": 5.5, "transition": "dissolve", "transition_duration": 0.4},
        {"id": "e", "title": "E", "asset_id": "photo", "motion": "pan-left", "duration": 1.0},
    ]


def render(assets, tmp_path, name, monkeypatch, jobs):
    monkeypatch.setenv("CASEFILE_RENDER_JOBS", str(jobs))
    commands = []
    real = renderer.run

    def spy(cmd, cancelled):
        commands.append(list(cmd))
        real(cmd, cancelled)

    monkeypatch.setattr(renderer, "run", spy)
    project = {"id": "speed", "title": "Speed", "look": "noir", "assets": assets, "scenes": scenes(), "music_volume": 0}
    out = tmp_path / name
    renderer.render(project, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    return out, commands


def worst_psnr(a, b):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b), "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    value = re.search(r"PSNR .* min:(\S+)", err).group(1)
    return float("inf") if value == "inf" else float(value)


def test_several_scenes_at_a_time_give_the_same_frames(media, tmp_path, monkeypatch):
    one, _ = render(media, tmp_path, "one.mp4", monkeypatch, 1)
    many, _ = render(media, tmp_path, "many.mp4", monkeypatch, 3)
    expected = sum(round(s["duration"] * FPS) for s in scenes())
    assert len(frames_md5(one)) == len(frames_md5(many)) == expected
    # The same pictures. (Not compared bit for bit: x264's own threading can
    # differ in the last bits between any two runs, parallel or not.)
    assert worst_psnr(one, many) > 50


def test_still_without_motion_is_decoded_once(media, tmp_path, monkeypatch):
    _, commands = render(media, tmp_path, "still.mp4", monkeypatch, 1)
    photo = media[0]["path"]
    scene_cmds = [c for c in commands if "-filter_complex" in c and c[c.index("-filter_complex") + 1].startswith("[0:v]")]
    still = scene_cmds[1]
    i = still.index(photo)
    assert "-loop" not in still[:i]  # not re-read for every frame
    graph = still[still.index("-filter_complex") + 1]
    assert "loop=loop=-1:size=1" in graph and "zoompan" not in graph
    # the moving scenes still use zoompan
    assert "zoompan" in scene_cmds[0][scene_cmds[0].index("-filter_complex") + 1]


def test_looped_crop_seeks_on_the_input(media, tmp_path, monkeypatch):
    _, commands = render(media, tmp_path, "crop.mp4", monkeypatch, 1)
    clip = media[1]["path"]
    crop = next(c for c in commands if any(str(x).endswith("/crop3.mp4") for x in c))
    assert crop.index("-ss") < crop.index(clip)
    assert crop[crop.index("-ss") + 1] == "5.0"


def test_a_failing_scene_stops_the_others_quickly():
    steps = [[["sleep", "20"]], [["false"]], [["sleep", "20"]]]
    t = time.monotonic()
    with pytest.raises(RuntimeError, match="Render failed"):
        renderer.run_scenes(steps, [0, 1, 2], 3, lambda *a: None, lambda: False)
    assert time.monotonic() - t < 8


def test_cancel_stops_parallel_scenes():
    steps = [[["sleep", "20"]], [["sleep", "20"]]]
    t = time.monotonic()
    with pytest.raises(RuntimeError, match="Cancelled"):
        renderer.run_scenes(steps, [0, 1], 2, lambda *a: None, lambda: time.monotonic() - t > 1)
    assert time.monotonic() - t < 8


def test_workers(monkeypatch):
    monkeypatch.delenv("CASEFILE_RENDER_JOBS", raising=False)
    monkeypatch.setattr(renderer, "available_cpus", lambda: 10)
    assert 1 <= renderer.render_workers(100) <= 5
    assert renderer.render_workers(1) == 1
    monkeypatch.setattr(renderer, "available_cpus", lambda: 2)
    assert renderer.render_workers(100) == 1
    monkeypatch.setenv("CASEFILE_RENDER_JOBS", "3")
    assert renderer.render_workers(100) == 3
    assert renderer.render_workers(2) == 2


def test_machine_note():
    apple_kernel = "processor\t: 0\nBogoMIPS\t: 48.00\nCPU implementer\t: 0x61\n"
    intel = "processor\t: 0\nvendor_id\t: GenuineIntel\nflags\t\t: fpu sse avx2\n"
    assert renderer.machine("x86_64", apple_kernel)["emulated"] is True
    assert renderer.machine("x86_64", intel)["emulated"] is False
    assert renderer.machine("aarch64", apple_kernel)["emulated"] is False
    note = renderer.machine_note({"arch": "x86_64", "cpus": 8, "emulated": True})
    assert "--platform linux/arm64" in note
    assert "2 CPUs" in renderer.machine_note({"arch": "aarch64", "cpus": 2, "emulated": False})
    assert renderer.machine_note({"arch": "aarch64", "cpus": 8, "emulated": False}) == ""
