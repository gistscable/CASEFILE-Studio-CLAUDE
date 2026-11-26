"""v0.4.54: transitions export on FFmpeg 6, 7 and newer.

FFmpeg 7.0 marks the frame rate unknown (1/0) after setpts, and xfade refuses
that: "The inputs needs to be a constant frame rate; current rate of 1/0 is
invalid". Every export with a transition failed. The scene step now states the
rate again (fps=) after numbering its frames, and leaves the previous scene's
frame alone: an fps= there made FFmpeg 6's xfade end the blend a frame early
and shift the rest of the scene one frame late.

Also: a video crop looped to fill the scene, shown "over a blur of itself",
came out one frame short (every later scene then ran 1/24 s early).

The renders use the ffmpeg on PATH. To check other builds too, set
CASEFILE_EXTRA_FFMPEG to folders holding ffmpeg/ffprobe, separated by ":".
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

import renderer
import storage

FPS = renderer.FPS


def builds():
    extra = [p for p in os.environ.get("CASEFILE_EXTRA_FFMPEG", "").split(os.pathsep) if p]
    return [None] + extra


def version(folder=None):
    exe = str(Path(folder) / "ffmpeg") if folder else "ffmpeg"
    return subprocess.run([exe, "-version"], capture_output=True, text=True).stdout.split()[2]


@pytest.fixture
def media(tmp_path):
    folder = storage.ROOT / "qa" / ("xrate-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    clip = folder / "clip.mp4"  # 30 fps, a moving picture and a frame counter
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=640x360:r=30:d=6", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip)], check=True)
    photo = folder / "photo.jpg"
    Image.effect_mandelbrot((1600, 900), (-2, -1.2, 1, 1.2), 40).convert("RGB").save(photo, quality=90)
    assets = [
        {"id": "clip", "kind": "video", "path": str(clip), "name": "clip.mp4", "duration": 6.0, "width": 640, "height": 360},
        {"id": "photo", "kind": "image", "path": str(photo), "name": "photo.jpg", "width": 1600, "height": 900},
    ]
    yield assets
    shutil.rmtree(folder, ignore_errors=True)


def scene(seconds, **kw):
    return {"id": f"s{seconds}{sorted(kw.items())}", "title": "", "narration": "", "duration": seconds, "show_title": False, **kw}


# Every kind of picture a transition can blend into.
KINDS = {
    "video": {"asset_id": "clip"},
    "looped video crop": {"asset_id": "clip", "trim_start": 1.0, "source_crop_end": 2.0},
    "photo, no motion": {"asset_id": "photo", "motion": "none"},
    "photo, slow zoom": {"asset_id": "photo", "motion": "slow-zoom"},
    "photo, keyframes": {"asset_id": "photo", "keyframes": [{"t": 0, "zoom": 1.0, "x": 0.5, "y": 0.5}, {"t": 1.0, "zoom": 1.3, "x": 0.4, "y": 0.5}]},
    "VISUAL NEEDED card": {},
}


def project(assets, scenes, **kw):
    base = {"id": "xrate", "title": "X", "look": "noir", "effects": {"vignette": 0.3, "grain": 0.2, "letterbox": True},
            "captions": False, "music_volume": 0, "assets": assets, "scenes": scenes}
    base.update(kw)
    return base


def render(monkeypatch, tmp_path, p, build=None, check=None):
    """Export `p`; `check(steps)` runs on the scene commands while the work folder still exists."""
    if build:
        monkeypatch.setenv("PATH", str(build) + os.pathsep + os.environ["PATH"])
    if check:
        original = renderer.run_scenes

        def run_and_check(steps, *a, **k):
            result = original(steps, *a, **k)
            check(steps)
            return result

        monkeypatch.setattr(renderer, "run_scenes", run_and_check)
    out = tmp_path / "out.mp4"
    renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    return out


def frame_count(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames,r_frame_rate",
                          "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout.strip()
    rate, count = out.split(",")
    return rate, int(count)


def blend_commands(steps):
    return [c for chain in steps for c in chain if "xfade=" in " ".join(c)]


def picture_timestamps(command):
    """Run a scene's command, but write the blended picture's raw frames (before
    any encoder could paper over a missing one) and return their timestamps."""
    run = command[: command.index("-map")]  # ffmpeg, the inputs and -filter_complex <graph>
    g = run.index("-filter_complex") + 1
    run[g] = run[g].split(";[pic1]")[0] + ";[pic1]null[raw]"  # stop right after the blend
    frames = command[command.index("-frames:v") + 1]  # a still picture loops forever: stop at the scene's length
    run += ["-map", "[raw]", "-frames:v", frames, "-f", "framemd5", "-"]
    out = subprocess.run(run, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-600:]
    return [int(line.split(",")[2]) for line in out.stdout.splitlines() if line and not line.startswith("#")]


def test_every_blend_states_the_frame_rate_and_keeps_the_previous_frame_untouched(monkeypatch, tmp_path, media):
    scenes = [scene(1.5, asset_id="clip")]
    for kind in KINDS.values():
        scenes.append(scene(1.5, transition="dissolve", transition_duration=0.5, **kind))
    seen = []

    def check(steps):
        for command in blend_commands(steps):
            graph = command[command.index("-filter_complex") + 1]
            chains = {m.group(2): m.group(1) for m in re.finditer(r"(?:^|;)([^;]*)\[(pic0|prev)\](?=;|$)", graph)}
            pic, prev = chains["pic0"], chains["prev"]
            # after the last setpts (which clears the rate on FFmpeg 7), fps= states it again
            assert re.search(rf"setpts=[^,]*,fps={FPS},settb=AVTB$", pic), pic
            # the previous scene's frame: already numbered at FPS by -loop 1 -framerate; no setpts, no fps=
            assert "setpts" not in prev and "fps=" not in prev, prev
            assert prev.endswith("settb=AVTB")  # the same time base as [pic0]: xfade requires it
            seen.append(graph)

    out = render(monkeypatch, tmp_path, project(media, scenes), check=check)
    assert len(seen) == len(KINDS)
    assert frame_count(out) == (f"{FPS}/1", len(scenes) * round(1.5 * FPS))


@pytest.mark.parametrize("build", builds(), ids=lambda b: version(b))
@pytest.mark.parametrize("kind", list(KINDS))
def test_each_picture_blends_in_with_every_timestamp(monkeypatch, tmp_path, media, kind, build):
    """The blend's raw output has a frame at every 1/24 s: none dropped, none late."""
    scenes = [scene(2.0, asset_id="clip"), scene(2.0, transition="dissolve", transition_duration=0.5, **KINDS[kind])]
    timestamps = []

    def check(steps):
        for command in blend_commands(steps):
            timestamps.append(picture_timestamps(command))

    out = render(monkeypatch, tmp_path, project(media, scenes), build=build, check=check)
    assert timestamps and timestamps[0] == list(range(len(timestamps[0])))
    assert len(timestamps[0]) >= 2 * FPS
    assert frame_count(out) == (f"{FPS}/1", 4 * FPS)


@pytest.mark.parametrize("build", builds(), ids=lambda b: version(b))
@pytest.mark.parametrize("transition", ["dip-black", "slide-left", "wipe-left", "zoom", "circle", "pixelize", "fade"])
def test_every_transition_exports(monkeypatch, tmp_path, media, transition, build):
    scenes = [scene(1.5, asset_id="clip"), scene(1.5, asset_id="photo", motion="slow-zoom", transition=transition, transition_duration=0.5),
              scene(1.5, asset_id="clip", trim_start=0.5, transition=transition, transition_duration=0.5)]
    out = render(monkeypatch, tmp_path, project(media, scenes), build=build)
    assert frame_count(out) == (f"{FPS}/1", 3 * round(1.5 * FPS))


@pytest.mark.parametrize("build", builds(), ids=lambda b: version(b))
@pytest.mark.parametrize("fit", ["cover", "blur"])
def test_a_looped_crop_fills_its_scene_to_the_last_frame(monkeypatch, tmp_path, media, fit, build):
    # A 1 s crop looped over a 3 s scene ends exactly at the scene's end; shown
    # over a blur of itself it used to lose its final frame.
    scenes = [scene(3.0, asset_id="clip", trim_start=1.0, source_crop_end=2.0, fit=fit),
              scene(1.0, asset_id="clip", fit=fit)]
    out = render(monkeypatch, tmp_path, project(media, scenes, effects={}), build=build)
    assert frame_count(out) == (f"{FPS}/1", 4 * FPS)
