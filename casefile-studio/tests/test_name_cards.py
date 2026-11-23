"""Name cards (v0.4.30): a clear gap above footage labels, and optional
automatic name cards from the re-cut list's Who column."""
import shutil
import subprocess

import numpy as np
from PIL import Image

import effects
import recut
import renderer
import storage
from test_recut_delete import LIST, make, upload, wait


def test_who_is_split_into_name_and_role():
    assert effects.split_who("Dedrick Hilton (father)") == {"name": "Dedrick Hilton", "role": "Father"}
    assert effects.split_who("  The chief ") == {"name": "The chief", "role": ""}


def test_first_scene_per_person_and_typed_cards_win():
    scenes = [
        {"guide_source_id": "S01"}, {"guide_source_id": "S01"},
        {"guide_source_id": "S02", "lower_third": {"name": "Typed", "role": ""}},
        {"guide_source_id": "S02"}, {"guide_source_id": "S03"}, {},
    ]
    p = {"scenes": scenes, "name_cards": {"auto": True, "people": {
        "S01": {"name": "Dedrick Hilton", "role": "Father"}, "S02": {"name": "Ignored", "role": ""}, "S03": {"name": "Off", "on": False}}}}
    cards = effects.effective_lower_thirds(p)
    assert cards == {0: {"name": "Dedrick Hilton", "role": "Father"}, 2: {"name": "Typed", "role": ""}}
    p["name_cards"]["auto"] = False
    assert effects.effective_lower_thirds(p) == {2: {"name": "Typed", "role": ""}}  # optional: off means only typed cards
    assert effects.normalise_name_cards({"auto": "yes", "people": {"bad id": {"name": "x"}, "S9": {"name": ""}}}) == {"auto": False, "people": {}}


def test_card_sits_above_the_footage_label_with_a_gap(tmp_path):
    assert effects.lower_third_bottom(1280, 720) == 0.24
    assert effects.lower_third_bottom(1280, 720, lift=True) == 0.27
    assert effects.lower_third_bottom(720, 1280, lift=True) == 0.49
    folder = storage.ROOT / "qa" / ("nc-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        Image.new("RGB", (640, 360), "#24303a").save(folder / "bg.png")
        scene = {"id": "a", "title": "", "narration": "", "duration": 3, "asset_id": "bg", "motion": "none", "show_title": False,
                 "source_label": "Archive image, not footage of the narrated event", "lower_third": {"name": "Dedrick Hilton", "role": "Father"}}
        p = {"id": "n", "title": "N", "look": "natural", "captions": False, "music_volume": 0, "scenes": [scene],
             "assets": [{"id": "bg", "kind": "image", "path": str(folder / "bg.png"), "name": "bg.png"}]}
        out = tmp_path / "o.mp4"
        renderer.render(p, {"resolution": "720p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.5", "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    img = np.frombuffer(raw, dtype=np.uint8).reshape(720, 1280, 3).astype(int)
    left = img[:, 40:700]
    rows = np.where((left.min(axis=2) > 200).sum(axis=1) > 0)[0]  # rows with white or light text
    card = rows[rows < 0.76 * 720 - 5]
    label = rows[rows >= 0.76 * 720 - 5]
    assert len(card) and len(label)
    assert label.min() - card.max() >= 0.025 * 720  # a clear gap between the card and the label


def test_suggestions_and_recut_cards(isolated, tmp_path):
    c, _ = isolated
    p = c.post("/api/projects", json={"title": "Cards QA", "mode": "narration"}).json()
    url = "/api/projects/" + p["id"]
    upload(c, url, make(tmp_path / "base.mp4", 6, "0.3*sin(2*PI*300*t)"), "my-video.mp4")
    upload(c, url, make(tmp_path / "b.mp4", 6, "0.5*sin(2*PI*900*t)"), "S02.mp4")
    v = c.post(url + "/recut/list", json={"text": LIST}).json()
    s = c.get(url + "/name-cards").json()
    assert s["suggested"]["S02"]["name"] == "The mother" and s["suggested"]["S01"]["from"] == "re-cut list"
    assert s["current"] == {"auto": False, "people": {}}  # nothing is applied until you switch it on
    r = c.patch(url, json={"name_cards": {"auto": True, "people": {"S02": {"name": "Maria Lopez", "role": "Mother"}}}})
    assert r.json()["name_cards"]["people"]["S02"]["on"] is True
    video = {"kind": "asset", "id": v["videos"][0]["id"]}
    ins = [{"at": 2.0, "until": 2.0, "source_id": "S02", "start": 1, "end": 4, "audio_ok": True, "lower_third": {"name": "Maria Lopez", "role": "Mother"}}]
    job = wait(c.post(url + "/recut/render", json={"video": video, "inserts": ins}).json()["job_id"])
    assert job["status"] == "done", job
    out = c.get(c.get(url + "/recut").json()["recuts"][0]["url"]).content
    path = tmp_path / "r.mp4"
    path.write_bytes(out)
    def grab(video, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.uint8).reshape(180, 320, 3).astype(int)

    got = grab(path, 3.5)  # 1.5 s into the inserted clip
    plain = grab(tmp_path / "b.mp4", 2.5)  # the same moment of the clip without a card
    diff = np.abs(got - plain).mean(axis=2)
    assert diff[110:140, 15:110].mean() > 25  # the name card, lower left (bottom 24%, 6% in)
    assert diff[20:80, 160:300].mean() < 12  # the rest of the clip is untouched
    assert not list((storage.DATA / "media" / p["id"] / "recut").glob("*.ass"))  # temporary card files are cleaned up
