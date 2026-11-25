"""The re-cut follows the picture of the chosen video.

v0.4.42: a finished video whose sound runs on past its picture (its container
length is the sound's) made the re-cut plan its last stretch to the sound's
length. The sound was padded to it while the picture ran out of frames, and
the re-cut failed with "picture (11:26) and sound (79:24) came out different
lengths". The picture sets the length now.
"""
import subprocess

import recut


def lengths(path):
    s = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True).stdout.split()
    return {x.split(",")[0]: float(x.split(",")[1]) for x in s}


def video(path, picture, sound, pattern="testsrc", tone=440):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{pattern}=s=320x180:r=30:d={picture}",
                    "-f", "lavfi", "-i", f"sine=f={tone}:d={sound}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)
    return path


def test_probe_reads_the_picture_length_not_the_container(tmp_path):
    base = video(tmp_path / "base.mp4", 6, 20)
    info = recut._probe(base)
    assert abs(info["picture"] - 6) < 0.05 and abs(info["sound"] - 20) < 0.1
    assert abs(info["duration"] - 6) < 0.05 and abs(info["container_duration"] - 20) < 0.1
    assert "0:06 of picture but 0:20 of sound" in recut.mismatch_note(info)


def test_sound_longer_than_picture_still_recuts_with_matching_lengths(tmp_path):
    base = video(tmp_path / "base.mp4", 6, 20)
    clip = video(tmp_path / "clip.mp4", 10, 10, "testsrc2", 2500)
    out, checks = tmp_path / "out.mp4", []
    recut.render(base, [{"at": 2.0, "until": 2.5, "start": 1.0, "end": 4.0, "path": clip}], out, checks=checks)
    lens = lengths(out)
    assert abs(lens["video"] - lens["audio"]) < 0.1
    assert abs(lens["video"] - (6 - 0.5 + 3)) < 0.2  # the picture's length, not the sound's
    assert checks and checks[0]["ok"]


def test_an_insert_past_the_picture_is_explained(tmp_path):
    base = video(tmp_path / "base.mp4", 6, 20)
    clip = video(tmp_path / "clip.mp4", 10, 10, "testsrc2", 2500)
    problems, _ = recut.check(base, [{"at": 12.0, "until": 12.0, "start": 1.0, "end": 4.0, "path": clip}])
    assert "of picture but" in problems[0]
    assert any("outside the video" in p for p in problems)


def test_matching_video_gives_no_note(tmp_path):
    base = video(tmp_path / "base.mp4", 6, 6)
    assert recut.mismatch_note(recut._probe(base)) == ""
