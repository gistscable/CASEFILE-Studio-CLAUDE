"""v0.4.33: in guide-built projects, the producer's transitions, replaced
pictures, movement and name cards survive the automatic rebuild."""
import episode
from test_episode import api_project, tone_bytes


def test_transition_and_replacement_survive_the_rebuild(isolated):
    c, _ = isolated
    p, url = api_project(c)
    # A picture to swap in.
    from PIL import Image
    import io
    b = io.BytesIO()
    Image.new("RGB", (640, 360), "#335577").save(b, format="PNG")
    p = c.post(url + "/upload", files={"files": ("my-replacement.png", b.getvalue(), "image/png")}).json()
    new_asset = [a for a in p["assets"] if a["name"].startswith("my-replacement")][-1]["id"]
    r = c.post(url + "/episode/build", json={"allow_placeholders": True, "inspection": True})
    assert r.status_code == 200, r.text
    p = c.get(url).json()
    assert len(p["scenes"]) >= 2
    scenes = p["scenes"]
    key0, key1 = episode.scene_key(scenes[0]), episode.scene_key(scenes[1])
    scenes[1] = {**scenes[1], "transition": "wipe-left", "transition_duration": 0.7, "lower_third": {"name": "A", "role": "B"}}
    scenes[0] = {**scenes[0], "asset_id": new_asset, "trim_start": 0, "replaced": True, "source_label": ""}
    r = c.patch(url, json={"scenes": scenes})
    assert r.status_code == 200, r.text
    after = r.json()["scenes"]  # rebuilt from the guide
    by_key = {episode.scene_key(s): s for s in after}
    assert by_key[key1]["transition"] == "wipe-left" and by_key[key1]["transition_duration"] == 0.7
    assert by_key[key1]["lower_third"] == {"name": "A", "role": "B"}
    assert by_key[key0]["asset_id"] == new_asset and by_key[key0]["replaced"] is True
    # A later, unrelated change keeps them too, and the plan stays current.
    after[-1] = {**after[-1], "motion": "pan-left"}
    again = c.patch(url, json={"scenes": after}).json()
    by_key = {episode.scene_key(s): s for s in again["scenes"]}
    assert by_key[key1]["transition"] == "wipe-left" and by_key[key0]["asset_id"] == new_asset
    analysis = c.get(url + "/episode").json()
    assert analysis["plan_current"] is True  # the overrides are part of the plan, not a change after it
    # Untouched scenes do not collect overrides.
    proj = c.get(url).json()
    assert len(proj["episode"]["overrides"]) <= 3


def test_restore_brings_back_the_guides_picture(isolated):
    c, _ = isolated
    p, url = api_project(c)
    from PIL import Image
    import io
    b = io.BytesIO()
    Image.new("RGB", (64, 36), "#335577").save(b, format="PNG")
    p = c.post(url + "/upload", files={"files": ("swap.png", b.getvalue(), "image/png")}).json()
    swap = p["assets"][-1]["id"]
    c.post(url + "/episode/build", json={"allow_placeholders": True, "inspection": True})
    p = c.get(url).json()
    original = p["scenes"][0].get("asset_id")
    scenes = p["scenes"]
    scenes[0] = {**scenes[0], "asset_id": swap, "replaced": True, "source_label": ""}
    p = c.patch(url, json={"scenes": scenes}).json()
    assert p["scenes"][0]["asset_id"] == swap
    p = c.post(url + "/episode/restore-scene", json={"scene_id": p["scenes"][0]["id"]}).json()
    assert p["scenes"][0].get("asset_id") == original and not p["scenes"][0].get("replaced")




def test_delete_leaves_nothing_behind(isolated):
    import json
    import app as server
    c, root = isolated
    data = root / "data"
    p = c.post("/api/projects", json={"title": "Gone QA", "mode": "narration"}).json()
    pid = p["id"]
    # Things a project leaves around: a saved job record, a recovery backup, a browser session snapshot.
    (data / "jobs" / "aaaabbbbccccdddd.json").write_text(json.dumps({"id": "aaaabbbbccccdddd", "project_id": pid}))
    (data / "jobs" / "eeeeffff00001111.json").write_text(json.dumps({"id": "eeeeffff00001111", "project_id": "someone-else"}))
    (data / "recovery-backups").mkdir(exist_ok=True)
    (data / "recovery-backups" / f"{pid}-x.json").write_text("{}")
    (data / "browser-sessions").mkdir(exist_ok=True)
    (data / "browser-sessions" / "s.json").write_text(json.dumps({"snapshot": {"id": pid}}))
    r = c.request("DELETE", "/api/projects/" + pid, json={"confirm_title": "Gone QA"})
    assert r.status_code == 200, r.text
    leftovers = [str(f.relative_to(data)) for f in data.rglob("*") if f.is_file() and pid in (f.name + f.read_text(errors="ignore"))]
    assert leftovers == []
    assert (data / "jobs" / "eeeeffff00001111.json").exists()  # other projects untouched
