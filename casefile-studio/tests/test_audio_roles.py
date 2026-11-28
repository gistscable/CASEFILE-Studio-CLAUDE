"""v0.4.68 Narration, music and sound effects are separate kinds of audio.

The Edit page's Audio tab imports into one kind (`audio_role`), a file can be moved to
another kind, and one file is never both the narration and the music."""
import subprocess


def _wav(path, seconds, freq=220):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", str(path)], check=True)
    return path


def _up(client, pid, path, **data):
    return client.post(f"/api/projects/{pid}/upload", files={"files": (path.name, path.read_bytes(), "audio/wav")}, data=data)


def _project(client):
    p = client.post("/api/projects", json={"title": "Audio", "topic": "t"}).json()
    client.patch(f"/api/projects/{p['id']}", json={"scenes": [{"id": "s0", "title": "", "narration": "The house.", "duration": 5.0}]})
    return p["id"]


def test_each_kind_of_audio_is_imported_on_its_own(isolated, tmp_path):
    client, _ = isolated
    pid = _project(client)
    voice = _up(client, pid, _wav(tmp_path / "voice.wav", 6), audio_role="narration")
    assert voice.status_code == 200, voice.text
    p = voice.json()
    a = p["assets"][-1]
    # sorted only: the timeline, the episode and the narration choice are untouched
    assert a["audio_role"] == "narration" and not p.get("narration_id") and not p.get("episode")
    assert p["scenes"][0]["narration"] == "The house."
    music = _up(client, pid, _wav(tmp_path / "theme.wav", 40, 440), audio_role="music").json()["assets"][-1]
    assert music["audio_role"] == "music"
    hit = _up(client, pid, _wav(tmp_path / "hit.wav", 1, 880), audio_role="sfx").json()["assets"][-1]
    assert hit["audio_role"] == "sfx" and hit["sfx"] is True
    r = _up(client, pid, _wav(tmp_path / "long.wav", 31), audio_role="sfx")
    assert r.status_code == 422 and "30 seconds" in r.text
    loose = _up(client, pid, _wav(tmp_path / "loose.wav", 3)).json()["assets"][-1]
    assert "audio_role" not in loose


def test_narration_and_music_stay_different_files(isolated, tmp_path):
    client, _ = isolated
    pid = _project(client)
    a = _up(client, pid, _wav(tmp_path / "a.wav", 6)).json()["assets"][-1]
    b = _up(client, pid, _wav(tmp_path / "b.wav", 6, 330)).json()["assets"][-1]
    p = client.patch(f"/api/projects/{pid}", json={"narration_id": a["id"]}).json()
    assert next(x for x in p["assets"] if x["id"] == a["id"])["audio_role"] == "narration"  # chosen = sorted
    r = client.patch(f"/api/projects/{pid}", json={"music_id": a["id"]})
    assert r.status_code == 422 and "different files" in r.text
    # swapping in one change is fine
    p = client.patch(f"/api/projects/{pid}", json={"narration_id": b["id"], "music_id": a["id"]}).json()
    assert p["narration_id"] == b["id"] and p["music_id"] == a["id"]
    roles = {x["id"]: x.get("audio_role") for x in p["assets"]}
    assert roles == {a["id"]: "music", b["id"]: "narration"}


def test_moving_a_file_to_another_kind(isolated, tmp_path):
    client, _ = isolated
    pid = _project(client)
    a = _up(client, pid, _wav(tmp_path / "a.wav", 2), audio_role="music").json()["assets"][-1]
    url = f"/api/projects/{pid}/assets/{a['id']}"
    p = client.patch(url, json={"audio_role": "sfx"}).json()
    x = next(x for x in p["assets"] if x["id"] == a["id"])
    assert x["audio_role"] == "sfx" and x["sfx"] is True
    p = client.patch(url, json={"audio_role": None}).json()
    x = next(x for x in p["assets"] if x["id"] == a["id"])
    assert "audio_role" not in x and "sfx" not in x
    client.patch(f"/api/projects/{pid}", json={"narration_id": a["id"]})
    r = client.patch(url, json={"audio_role": "music"})
    assert r.status_code == 422 and "your narration" in r.text  # the file in use stays put
    assert client.patch(url, json={"audio_role": "drums"}).status_code == 422
    long = _up(client, pid, _wav(tmp_path / "long.wav", 40)).json()["assets"][-1]
    r = client.patch(f"/api/projects/{pid}/assets/{long['id']}", json={"audio_role": "sfx"})
    assert r.status_code == 422 and "30 seconds" in r.text
