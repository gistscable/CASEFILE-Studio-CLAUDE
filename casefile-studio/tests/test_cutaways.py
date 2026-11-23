"""Picture cutaways on long Re-cut clips (v0.4.38)."""
import subprocess

import numpy as np
from PIL import Image

import cutaways
import recut
from test_recut_delete import make, pitch_at


def test_parse_list_with_cutaway_table():
    text = """| RC | Chapter | Cut from | Cut to |
|---|---|---|---|
| RC-01 | 1 | 00:05.00 | 00:05.20 |
| RC-02 | 1 | 00:09.00 | 00:09.10 |

| RC | Chapter | Who | Clip | Window | Words |
|---|---|---|---|---|---|
| RC-01 | 1 | Her father | [A](https://www.youtube.com/watch?v=AAAAAAAAAAA) (`S01`) | 0:10.00–0:30.00 | "a" |
| RC-02 | 1 | The judge | [B](https://www.youtube.com/watch?v=BBBBBBBBBBB) (`S02`) | 1:00.00–1:20.00 | "b" |

## Cutaways
| RC | From | To | Show |
|---|---|---|---|
| RC-01 | 0:04.0 | 0:09.0 | V / portrait |
| RC-01 | 0:12.0 | 0:16.0 | BASE-C--location--01.jpg |
| RC-02 | 0:05.0 | 0:10.0 | S03 2:10–2:16 |
| RC-02 | 0:11.0 | 0:13.0 | face |
"""
    got = recut.parse(text)
    assert [g["rc"] for g in got] == ["RC-01", "RC-02"]
    a, b = got[0]["cutaways"], got[1]["cutaways"]
    assert [(c["from"], c["to"], c["show"]["kind"]) for c in a] == [(4.0, 9.0, "base"), (12.0, 16.0, "file")]
    assert a[0]["show"]["bucket"] == "V" and a[0]["show"]["tags"] == ["portrait"]
    assert b == [{"from": 5.0, "to": 10.0, "show": {"kind": "footage", "source_id": "S03", "start": 130.0, "end": 136.0}, "label": "S03 2:10.0–2:16.0"}]


def test_rules():
    # short clips get none; long ones keep the face first and last and at most half
    assert cutaways.auto_plan(10, "Her father") == []
    plan = cutaways.auto_plan(40, "Dedrick Hilton (her father)", card=True)
    assert plan[0]["from"] == 4.5 and plan[-1]["to"] <= 38 and all(c["show"]["bucket"] == "V" for c in plan)
    assert sum(c["to"] - c["from"] for c in plan) <= 20.0 + 1e-6
    assert cutaways.auto_plan(30, "Assistant Solicitor")[0]["show"] == {"kind": "base", "bucket": "C", "tags": ["court"], "exclude": []}
    assert cutaways.auto_plan(30, "Assistant Solicitor", "Khalil Gillard fired", suspect="Khalil Gillard")[0]["show"]["bucket"] == "S"
    assert cutaways.auto_plan(30, "Her grandfather", "Khalil Gillard took her", suspect="Khalil Gillard")[0]["show"]["bucket"] == "V"
    # clean: clamps the head, drops a suspect picture under a family speaker, caps the share
    s = {"kind": "base", "bucket": "S", "tags": [], "exclude": []}
    v = {"kind": "base", "bucket": "V", "tags": [], "exclude": []}
    got, warn = cutaways.clean([{"from": 0.5, "to": 6, "show": v}, {"from": 8, "to": 12, "show": s}], 20, "her mother")
    assert [(c["from"], c["to"]) for c in got] == [(2.5, 6)] and "suspect" in warn[0]
    got, warn = cutaways.clean([{"from": 3, "to": 20, "show": v}], 20, "")
    assert got[0]["to"] == 11.0 and "shortened" in warn[0]


def frame(path, t, w, h):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).astype(int)


def test_render_shows_cutaways_and_keeps_the_sound(tmp_path):
    base = make(tmp_path / "base.mp4", 4, "0.5*sin(2*PI*400*t)")
    clip = make(tmp_path / "clip.mp4", 16, "0.5*sin(2*PI*2500*t)")
    other = tmp_path / "other.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x00ff00:s=320x180:r=24:d=10", "-f", "lavfi", "-i",
                    "aevalsrc='0.5*sin(2*PI*700*t)':s=48000:d=10", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(other)], check=True)
    pic = tmp_path / "pic.png"
    Image.new("RGB", (640, 360), (255, 0, 255)).save(pic)
    out = tmp_path / "out.mp4"
    cuts = [{"from": 3.0, "to": 6.0, "kind": "image", "path": str(pic), "start": 0},
            {"from": 9.0, "to": 12.0, "kind": "video", "path": str(other), "start": 2.0}]
    recut.render(base, [{"at": 2.0, "until": 2.0, "start": 0, "end": 15, "path": clip, "cutaways": cuts,
                         "lower_third": {"name": "Pat Doe", "role": "her father"}}], out)
    info = recut._probe(out)
    w, h = info["width"], info["height"]
    # clip starts at 2.0 s in the re-cut
    r, g, b = frame(out, 2 + 4.5, w, h)[h // 2, w // 2]
    assert r > 200 and b > 200 and g < 80  # the photo
    r, g, b = frame(out, 2 + 10.5, w, h)[h // 2, w // 2]
    assert g > 180 and r < 80 and b < 80  # the other clip's picture
    centre = frame(out, 2 + 7.5, w, h)[h // 2, w // 2]
    assert not (centre[0] > 200 and centre[2] > 200 and centre[1] < 80) and not (centre[1] > 180 and centre[0] < 80)  # back on the speaker
    for t in (2 + 4.5, 2 + 10.5):
        assert abs(pitch_at(out, t) - 2500) < 40  # the speaker's sound plays on, never the cutaway's


def test_resolve_rotates_and_reports_gaps():
    pool = [{"id": "a", "name": "BASE-V--portrait--01.jpg", "kind": "image", "bucket": "V", "tags": ["portrait"], "duration": 0, "window": None},
            {"id": "b", "name": "BASE-V--family--01.jpg", "kind": "image", "bucket": "V", "tags": ["family"], "duration": 0, "window": None}]
    v = {"kind": "base", "bucket": "V", "tags": [], "exclude": []}
    cuts = [{"from": 3, "to": 6, "show": v}, {"from": 9, "to": 12, "show": v}, {"from": 14, "to": 16, "show": {"kind": "base", "bucket": "C", "tags": [], "exclude": []}}]
    used = {}
    got, warn = cutaways.resolve(cuts, pool, {}, used, lambda a: "/x/" + a["name"])
    assert [c["asset_id"] for c in got] == ["a", "b"] and "no base image" in warn[0]
    got, _ = cutaways.resolve([{"from": 3, "to": 6, "show": {"kind": "base", "bucket": "V", "tags": ["family"], "exclude": []}}], pool, {}, used, lambda a: a["name"])
    assert got[0]["asset_id"] == "b"


def test_api_plans_cutaways(isolated, tmp_path):
    """The Re-cut page asks the server which pictures each insert cuts away to."""
    from PIL import Image as Img
    c, _ = isolated
    p = c.post("/api/projects", json={"title": "Cut"}).json()
    files = []
    for name, col in [("BASE-V--portrait--01.jpg", (200, 60, 160)), ("BASE-S--custody--01.jpg", (90, 90, 90)), ("BASE-C--court--01.jpg", (40, 90, 200))]:
        Img.new("RGB", (320, 180), col).save(tmp_path / name)
        files.append(("files", (name, open(tmp_path / name, "rb"), "image/jpeg")))
    assert c.post(f"/api/projects/{p['id']}/upload", files=files).status_code == 200
    body = {"auto": True, "inserts": [
        {"start": 0, "end": 20, "who": "Her mother", "words": "", "card": False},
        {"start": 0, "end": 8, "who": "Her mother", "words": ""},
        {"start": 0, "end": 20, "who": "The judge", "words": "", "off": [1]},
    ]}
    r = c.post(f"/api/projects/{p['id']}/recut/cutaways", json=body).json()
    one, two, three = r["plans"]
    assert one["auto"] and one["speaker"] == "family" and {x["name"] for x in one["cutaways"]} == {"BASE-V--portrait--01.jpg"}
    assert two["cutaways"] == []  # short clip: stays on the speaker
    assert [x["name"] for x in three["cutaways"]] == ["BASE-C--court--01.jpg"] and three["off"] == [1]
    assert all("path" not in x for x in one["cutaways"]) and len(r["pictures"]) == 3
    body["auto"] = False
    assert all(not x["cutaways"] for x in c.post(f"/api/projects/{p['id']}/recut/cutaways", json=body).json()["plans"])


def test_prompt_formats_parse():
    """The cutaway table in the prompts is what recut.parse reads."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "prompts"
    script = (root / "1_Script_Workflow_Prompts_A_B_and_C.md").read_text(encoding="utf-8")
    assert "| RC | From | To | Show | Words |" in script
    assert "| RC | From | To | Show | Words |" in (root / "2_Guide-Writer_Prompt_for_Casefile_Studio.md").read_text(encoding="utf-8")
    text = """| RC | Chapter | Cut from | Cut to | Length | Captions |
|---|---|---|---|---|---|
| RC-04 | 3 | 07:10.00 | 07:10.20 | 30 s | delete |
## The clips that will play
| RC | Chapter | Who | Clip | Window | Words |
|---|---|---|---|---|---|
| RC-04 | 3 | Assistant Solicitor | [Court](https://www.youtube.com/watch?v=PDM1tXzPl-w) (`S06`) | 6:57.18–7:27.18 | "x" |
## Cutaways
| RC | From | To | Show | Words |
|---|---|---|---|---|
| RC-04 | 0:05.0 | 0:10.0 | C / court | "…when he walked into that apartment…" |
| RC-04 | 0:14.0 | 0:19.0 | `S06 21:10–21:16` | "…no remorse…" |
"""
    (ins,) = recut.parse(text)
    assert [(c["from"], c["show"]["kind"]) for c in ins["cutaways"]] == [(5.0, "base"), (14.0, "footage")]
    assert ins["cutaways"][1]["show"]["source_id"] == "S06" and ins["cutaways"][1]["show"]["start"] == 1270.0


def test_picture_check_passes_real_clips_and_catches_a_wrong_picture(tmp_path):
    """v0.4.39: after the re-cut, each clip's picture is compared with its source."""
    base = make(tmp_path / "base.mp4", 6, "0.5*sin(2*PI*400*t)")
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=s=640x360:r=30", "-t", "20", "-f", "lavfi", "-i",
                    "aevalsrc='0.5*sin(2*PI*2500*t)':s=44100:d=20", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(clip)], check=True)
    out, checks = tmp_path / "out.mp4", []
    recut.render(base, [{"at": 2.0, "until": 2.1, "start": 5.0, "end": 13.0, "path": clip}], out, checks=checks, proof_dir=tmp_path)
    assert len(checks) == 1 and checks[0]["ok"] and checks[0]["diff"] < 10 and checks[0]["at"] == 2.0
    assert (tmp_path / checks[0]["proof"]).exists()
    info = recut._probe(out)
    other = tmp_path / "other.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=640x360:r=24:d=20", "-c:v", "libx264", "-preset", "ultrafast", str(other)], check=True)
    wrong = recut.picture_check(out, base, [({"at": 2.0, "start": 5.0, "path": other}, 2.0, 8.0)], info["width"], info["height"])
    assert not wrong[0]["ok"]  # the finished video at that spot is not the narration video
