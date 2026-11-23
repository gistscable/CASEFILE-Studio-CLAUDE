"""Re-cut (original clips replace the narrated lines, with their own sound) and
Delete project (files leave the data folder too). v0.4.22."""
import subprocess
import time

import numpy as np
import pytest

import app as server
import recut

LIST = """# Re-cut list

| Order | Chapter | Cut from | Cut to | Length | Captions |
|---|---|---|---|---|---|
| 1 | 2 | About 00:06.00 (frame 00:00:06:00), in the pause | 00:07.50 | 1.5 s | delete |
| 2 (optional) | 1 | 00:02.50 (frame 00:00:02:15) | 00:03.00 | 0.5 s | delete |

## The clips that will play

| Chapter | Who | Clip | Window | Words |
|---|---|---|---|---|
| 1 (optional) | The chief | [News 9](https://www.youtube.com/watch?v=AAAAAAAAAAA&t=1s) (`S01`) | about 0:01 to 0:03 | "First words." |
| 2 | The mother | [News 9](https://www.youtube.com/watch?v=BBBBBBBBBBB&t=2s) (`S02`) | somewhere between about 0:02 and 0:05; find the edges by ear | "Second words." |
"""


def make(path, seconds, expr, size="320x180"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=24:d={seconds}", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=48000:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def pitch_at(path, t, rate=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-t", "0.2", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)), n=len(x) * 4))
    return np.argmax(spec) * rate / (len(x) * 4)


def test_parse_reads_cut_points_and_clip_windows():
    ins = recut.parse(LIST)
    assert [(i["at"], i["until"], i["source_id"], i["start"], i["end"], i["optional"]) for i in ins] == [(2.5, 3.0, "S01", 1, 3, True), (6.0, 7.5, "S02", 2, 5, False)]
    assert ins[1]["video_id"] == "BBBBBBBBBBB" and ins[1]["who"] == "The mother" and ins[1]["words"] == "Second words." and ins[1]["approximate"]
    simple = "| At | Source | From | To |\n|---|---|---|---|\n| 0:04.5 | S07 | 1:10 | 1:14 |\n"
    assert [(i["at"], i["until"], i["source_id"], i["start"], i["end"]) for i in recut.parse(simple)] == [(4.5, 4.5, "S07", 70, 74)]
    resume = "| At | Resume at | Source | From | To |\n|---|---|---|---|---|\n| 0:04.5 | 0:09 | S07 | 1:10 | 1:14 |\n"
    assert recut.parse(resume)[0]["until"] == 9.0
    assert recut.parse("no tables here") == []


def test_render_plays_the_clip_instead_of_the_narrated_line(tmp_path):
    # Base: a rising tone, so every moment has its own pitch. Clips: fixed tones.
    base = make(tmp_path / "base.mp4", 10, "0.5*sin(2*PI*(300*t+50*t*t))")  # pitch = 300 + 100 t
    clip_a = make(tmp_path / "a.mp4", 6, "0.5*sin(2*PI*2500*t)", size="640x360")
    clip_b = make(tmp_path / "b.mp4", 6, "0.5*sin(2*PI*3500*t)")
    out = tmp_path / "out.mp4"
    # Insert 1 skips the narrated line from 2.5 to 4.0; insert 2 skips nothing.
    inserts = [{"at": 6.0, "until": 6.0, "start": 2, "end": 5, "path": clip_b}, {"at": 2.5, "until": 4.0, "start": 1, "end": 3, "path": clip_a}]
    duration = recut.render(base, inserts, out)
    assert abs(duration - 13.5) < 0.15  # 10 s - 1.5 s skipped + 2 s + 3 s
    assert abs(pitch_at(out, 1.0) - 410) < 25                 # the video before the first insert
    assert abs(pitch_at(out, 3.3) - 2500) < 40                # the first clip's own sound
    assert abs(pitch_at(out, 4.7) - (300 + 100 * 4.3)) < 30   # carries on from 4.0, not 2.5: the line is not repeated
    for t in (4.55, 5.0, 5.5, 6.0, 6.4):                      # nothing from the skipped 2.5-4.0 stretch is heard
        assert pitch_at(out, t) > 300 + 100 * 3.95
    assert abs(pitch_at(out, 8.0) - 3500) < 40                # the second clip (starts at 6.5)
    assert abs(pitch_at(out, 9.8) - (300 + 100 * 6.4)) < 30   # carries on from 6.0: nothing skipped there
    info = recut._probe(out)
    assert (info["width"], info["height"]) == (320, 180)  # clips are fitted to the video's size
    with pytest.raises(recut.RecutError, match="inside the part"):
        recut.render(base, [{"at": 2, "until": 5, "start": 0, "end": 1, "path": clip_a}, {"at": 4, "until": 4, "start": 0, "end": 1, "path": clip_b}], out)
    with pytest.raises(recut.RecutError, match="continue at or after"):
        recut.render(base, [{"at": 5, "until": 3, "start": 0, "end": 1, "path": clip_a}], out)
    with pytest.raises(recut.RecutError, match="outside the video"):
        recut.render(base, [{"at": 99, "start": 0, "end": 1, "path": clip_a}], out)
    silent = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=3", "-c:v", "libx264", "-preset", "ultrafast", str(silent)], check=True)
    with pytest.raises(recut.RecutError, match="no sound"):
        recut.render(base, [{"at": 1, "start": 0, "end": 1, "path": silent}], out)


def wait(job_id, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        j = server.JOBS[job_id]
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def upload(c, url, path, name):
    r = c.post(url + "/upload", files={"files": (name, path.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text


def test_recut_page_flow_and_delete_project(isolated, tmp_path):
    c, _ = isolated
    keep = c.post("/api/projects", json={"title": "Keep me", "mode": "narration"}).json()
    p = c.post("/api/projects", json={"title": "Recut QA", "mode": "narration"}).json()
    url = "/api/projects/" + p["id"]
    upload(c, url, make(tmp_path / "base.mp4", 10, "0.5*sin(2*PI*(300*t+50*t*t))"), "my-rendered-video.mp4")
    upload(c, url, make(tmp_path / "a.mp4", 6, "0.5*sin(2*PI*2500*t)"), "S01.mp4")
    upload(c, url, make(tmp_path / "b.mp4", 6, "0.5*sin(2*PI*3500*t)"), "S02.mp4")
    upload(c, "/api/projects/" + keep["id"], make(tmp_path / "k.mp4", 2, "0.2*sin(2*PI*500*t)"), "other.mp4")

    v = c.post(url + "/recut/list", json={"text": LIST}).json()
    assert [(i["source_id"], i["file"], i["file_has_audio"]) for i in v["inserts"]] == [("S01", "S01.mp4", True), ("S02", "S02.mp4", True)]
    assert [x["label"] for x in v["videos"]] == ["Uploaded: my-rendered-video.mp4"]  # sources are not offered as the video to re-cut
    assert c.post(url + "/recut/list", json={"text": "nothing useful"}).status_code == 422
    video = {"kind": "asset", "id": v["videos"][0]["id"]}
    ins = [{"at": 6.0, "until": 7.5, "source_id": "S02", "start": 2, "end": 5}]
    r = c.post(url + "/recut/render", json={"video": video, "inserts": ins})
    assert r.status_code == 422 and "original audio" in r.text  # the producer must say yes, clip by clip
    assert "no file for S09" in c.post(url + "/recut/render", json={"video": video, "inserts": [{"at": 1, "source_id": "S09", "start": 0, "end": 1, "audio_ok": True}]}).text
    r = c.post(url + "/recut/render", json={"video": video, "inserts": [{**ins[0], "audio_ok": True}]})
    assert r.status_code == 200, r.text
    job = wait(r.json()["job_id"])
    assert job["status"] == "done", job
    v = c.get(url + "/recut").json()
    assert abs(v["recuts"][0]["duration"] - 11.5) < 0.15 and v["recuts"][0]["inserts"][0]["file"] == "S02.mp4"  # 10 - 1.5 + 3
    assert any(x["kind"] == "recut" for x in v["videos"])  # a re-cut can be re-cut again
    got = c.get(v["recuts"][0]["url"])
    assert got.status_code == 200 and "recut.mp4" in got.headers["content-disposition"]

    # Delete: needs the exact title; removes this project's files only.
    media = server.DATA / "media" / p["id"]
    desk = server.DATA / "casedesk" / (p["id"] + ".json")
    assert media.is_dir() and desk.is_file()
    assert c.get(url + "/storage").json()["total"] > 10000
    assert c.request("DELETE", url, json={"confirm_title": "wrong"}).status_code == 422
    r = c.request("DELETE", url, json={"confirm_title": "Recut QA"})
    assert r.status_code == 200 and r.json()["freed"] > 10000
    assert not media.exists() and not desk.exists() and not (server.DATA / "projects" / (p["id"] + ".json")).exists()
    assert c.get(url).status_code == 404
    assert p["id"] not in [x["id"] for x in r.json()["projects"]]
    assert (server.DATA / "media" / keep["id"]).is_dir() and c.get("/api/projects/" + keep["id"]).status_code == 200


def test_recut_puts_the_logo_on_inserted_clips(tmp_path):
    """v0.4.36: with a watermark, inserted clips carry the logo too, and keep their sound."""
    from PIL import Image, ImageDraw
    import numpy as np
    import subprocess
    base = make(tmp_path / "base.mp4", 6, "0.5*sin(2*PI*400*t)")
    clip = make(tmp_path / "a.mp4", 4, "0.5*sin(2*PI*2500*t)", size="640x360")
    out = tmp_path / "out.mp4"

    def logo(w, h, path):
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle((10, 10, 60, 60), fill=(255, 0, 255, 255))
        im.save(path)

    recut.render(base, [{"at": 2.0, "until": 2.0, "start": 0, "end": 2, "path": clip}], out, logo=logo)
    assert abs(pitch_at(out, 3.0) - 2500) < 40  # the clip's own sound is still there
    info = recut._probe(out)

    def px(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.uint8).reshape(info["height"], info["width"], 3).astype(int)[35, 35]

    r, g, b = px(3.0)
    assert r > 200 and b > 200 and g < 80  # logo on the clip
    assert not (px(1.0)[0] > 200 and px(1.0)[2] > 200 and px(1.0)[1] < 80)  # the base video is left as it was


def test_parse_keeps_two_inserts_in_one_chapter():
    """v0.4.37: RC IDs pair cuts with clips; without them the n-th cut of a chapter takes its n-th clip."""
    with_ids = """| RC | Chapter | Cut from | Cut to |
|---|---|---|---|
| RC-04 | 3 | 07:10.00 | 07:10.20 |
| RC-05 | 3 | 08:00.00 | 08:00.10 |

| RC | Chapter | Who | Clip | Window | Words |
|---|---|---|---|---|---|
| RC-05 | 3 | Defense | [U6](https://www.youtube.com/watch?v=PDM1tXzPl-w) (`S06`) | 11:10.17–11:36.59 | "b" |
| RC-04 | 3 | Prosecutor | [U6](https://www.youtube.com/watch?v=PDM1tXzPl-w) (`S06`) | 6:57.18–7:42.12 | "a" |
"""
    got = recut.parse(with_ids)
    assert [(x["at"], x["who"], x["start"]) for x in got] == [(430.0, "Prosecutor", 417.18), (480.0, "Defense", 670.17)]
    no_ids = with_ids.replace("| RC | Chapter", "| Order | Chapter").replace("RC-05 | 3 | Defense", "2 | 3 | Prosecutor2").replace("RC-04 | 3 | Prosecutor", "1 | 3 | Defense2")
    got = recut.parse(no_ids)
    assert len(got) == 2 and [x["who"] for x in got] == ["Prosecutor2", "Defense2"]  # in the order the clips are listed


def test_parse_reads_the_guide_writer_template():
    """The recut_list.md format in prompts/2_Guide-Writer_Prompt_for_Casefile_Studio.md."""
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "prompts" / "2_Guide-Writer_Prompt_for_Casefile_Studio.md").read_text(encoding="utf-8")
    assert "| RC | Chapter | Cut from | Cut to | Length | Captions |" in text and "| RC | Chapter | Who | Clip | Window | Words |" in text
    sample = """| RC | Chapter | Cut from | Cut to | Length | Captions |
|---|---|---|---|---|---|
| RC-01 | HOOK | 00:07.87 | 00:08.03 | 4.41 s | delete |
| RC-02 | 3 (optional) | 07:40.99 | 07:41.20 | 4.85 s | delete |
| RC-03 | 3 | 1:02:01.10 | 1:02:01.40 | 17.9 s | delete |
## The clips that will play
| RC | Chapter | Who | Clip | Window | Words |
|---|---|---|---|---|---|
| RC-01 | HOOK | The father | [WIS](https://www.youtube.com/watch?v=WrHpzJxbgEE) (`S05`) | 0:36.54–0:40.95 | "a" |
| RC-02 | 3 | The father | [WIS](https://www.youtube.com/watch?v=WrHpzJxbgEE) (`S05`) | 0:48.80–0:53.65 | "b" |
| RC-03 | 3 | The judge | [Court](https://www.youtube.com/watch?v=PDM1tXzPl-w) (`S06`) | 28:09.00–28:26.90 | "c" |
"""
    got = recut.parse(sample)
    assert [(round(x["at"], 2), x["source_id"], x["start"], x["optional"]) for x in got] == [
        (7.87, "S05", 36.54, False), (460.99, "S05", 48.8, True), (3721.1, "S06", 1689.0, False)]
