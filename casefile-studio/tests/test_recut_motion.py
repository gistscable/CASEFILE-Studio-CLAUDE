"""Inserted clips must move and must play on Apple devices.

v0.4.41: with the logo watermark on, clip pieces were encoded as H.264 4:4:4,
which Safari/DuckDuckGo (Apple's decoder) cannot play: the clip's picture froze
while its sound played on, although the file itself was fine."""
import subprocess

import numpy as np

import recut
from test_recut_delete import make, pitch_at


def moving(path, start, seconds):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(seconds), "-i", str(path), "-vf", "scale=64:36,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 36 * 64).astype(int)
    d = [abs(f[i] - f[i - 1]).mean() for i in range(1, len(f))]
    return sum(x > 0.5 for x in d), len(d)


def test_a_still_photo_in_the_clip_stays_still_and_the_rest_moves(tmp_path):
    base = make(tmp_path / "base.mp4", 6, "0.5*sin(2*PI*400*t)")
    clip = tmp_path / "photo.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x806040:s=320x180:r=30:d=4", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=6", "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*2500*t)':s=48000:d=10",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset",
                    "ultrafast", "-c:a", "aac", "-shortest", str(clip)], check=True)
    out, checks = tmp_path / "out.mp4", []
    recut.render(base, [{"at": 2.0, "until": 2.1, "start": 0.0, "end": 9.0, "path": clip}], out, checks=checks)
    assert moving(out, 2.2, 3.5)[0] == 0  # the photo
    moved, total = moving(out, 6.4, 4.0)
    assert moved >= total * 0.95
    assert checks[0]["ok"]


def test_output_is_one_clean_stream(tmp_path):
    """Picture and sound joined once, like the main export: same length, rising frame times."""
    base = make(tmp_path / "base.mp4", 6, "0.5*sin(2*PI*400*t)")
    clip = make(tmp_path / "clip.mp4", 12, "0.5*sin(2*PI*2500*t)", size="640x360")
    out = tmp_path / "out.mp4"
    recut.render(base, [{"at": 2.0, "until": 2.1, "start": 1.0, "end": 9.0, "path": clip}, {"at": 4.0, "until": 4.0, "start": 2.0, "end": 5.0, "path": clip}], out)
    s = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split()
    lens = {x.split(",")[0]: float(x.split(",")[1]) for x in s}
    assert abs(lens["video"] - lens["audio"]) < 0.1 and abs(lens["video"] - (6 - 0.1 + 8 + 3)) < 0.2
    dts = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=dts_time", "-of", "csv=p=0", str(out)],
                         capture_output=True, text=True).stdout.split()
    vals = [float(x) for x in dts if x.strip()]
    assert all(b > a for a, b in zip(vals, vals[1:]))


def test_clips_with_logo_and_name_card_are_plain_420(tmp_path):
    from PIL import Image, ImageDraw
    base = make(tmp_path / "base.mp4", 6, "0.5*sin(2*PI*400*t)")
    clip = make(tmp_path / "clip.mp4", 12, "0.5*sin(2*PI*2500*t)", size="640x360")

    def logo(w, h, path):
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((w - 60, 5, w - 5, 60), fill=(214, 164, 96, 255))
        im.save(path)

    import shutil
    kept = tmp_path / "kept"
    real = shutil.rmtree
    shutil.rmtree = lambda p, ignore_errors=False: (shutil.copytree(p, kept), real(p, ignore_errors=True))
    try:
        recut.render(base, [{"at": 2.0, "until": 2.1, "start": 1.0, "end": 7.0, "path": clip,
                             "lower_third": {"name": "Pat Doe", "role": "her father"}}], tmp_path / "out.mp4", logo=logo)
    finally:
        shutil.rmtree = real
    pieces = sorted(kept.glob("[0-9][0-9][0-9].mp4"))
    assert len(pieces) == 3
    for p in pieces:
        got = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=profile,pix_fmt,color_primaries",
                              "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
        assert got == "High,yuv420p,bt709", (p.name, got)
    moved, total = moving(tmp_path / "out.mp4", 2.2, 5.5)
    assert moved >= total * 0.95
