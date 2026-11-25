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


# --------------------------------------------------------------------------
# v0.4.43: a clip file whose timestamps are broken (they stop advancing, as in
# a stream ffmpeg copied out of order) made "stop after N seconds" never
# trigger. The clip's sound ran to the end of the file (re-cut sound 36:54
# instead of 22:05) and the join stalled. Such clips are cut by frame and
# sample number now, and every piece is checked before the join.
# --------------------------------------------------------------------------

def stuck_timestamps(tmp_path, seconds=120, tone=2500):
    good = tmp_path / "good-source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={seconds}", "-f", "lavfi", "-i",
                    f"sine=f={tone}:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(good)], check=True)
    bad = tmp_path / "S06.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(good), "-c", "copy", "-bsf:a", "setts=ts=mod(PTS\\,8/TB)",
                    "-bsf:v", "setts=ts=mod(PTS\\,8/TB)", str(bad)], check=True)
    return bad


def test_broken_timestamps_are_spotted(tmp_path):
    assert recut._probe(stuck_timestamps(tmp_path))["timing_broken"]
    assert not recut._probe(video(tmp_path / "fine.mp4", 6, 6))["timing_broken"]


def test_a_clip_with_broken_timestamps_recuts_at_the_right_length(tmp_path):
    from test_recut_delete import pitch_at
    base = video(tmp_path / "base.mp4", 20, 20, tone=440)
    good = video(tmp_path / "S05.mp4", 30, 30, "testsrc2", 1200)
    bad = stuck_timestamps(tmp_path)
    inserts = [{"at": 4.0, "until": 4.0, "start": 1.0, "end": 5.0, "path": good},
               {"at": 8.0, "until": 8.0, "start": 38.13, "end": 52.99, "path": bad},
               {"at": 14.0, "until": 14.0, "start": 3.0, "end": 9.0, "path": good}]
    out, checks = tmp_path / "out.mp4", []
    recut.render(base, inserts, out, checks=checks)
    lens = lengths(out)
    expected = 20 + 4 + 14.875 + 6  # each clip snapped to whole frames
    assert abs(lens["video"] - lens["audio"]) < 0.1
    assert abs(lens["video"] - expected) < 0.15
    assert inserts[1]["timing"] == "frame-count" and inserts[0]["timing"] == "timestamps"
    assert all(c["ok"] for c in checks)
    # The damaged clip plays its own sound, and the video resumes on time after it.
    assert abs(pitch_at(out, 4 + 8 + 7) - 2500) < 40
    assert abs(pitch_at(out, 4 + 8 + 14.875 + 2) - 440) < 40


def test_piece_lengths_reads_frames_and_samples(tmp_path):
    clip = video(tmp_path / "c.mp4", 3, 3)
    pic, snd = tmp_path / "p.mp4", tmp_path / "s.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-map", "0:v", "-r", "24", "-frames:v", "48", "-c:v", "libx264", str(pic),
                    "-map", "0:a", "-af", "aresample=48000,atrim=end_sample=96000", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(snd)], check=True)
    assert recut._piece_lengths(pic, snd) == (48, 96000)
