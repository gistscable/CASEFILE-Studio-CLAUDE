"""v0.4.23: the Re-cut page fetches its own clips, and the cloned voice can be
made on free Google Colab through a voice pack (Colab and the model are
stand-ins here; the notebook's Step 2 code itself is executed)."""
import io
import json
import subprocess
import sys
import types
import zipfile

import numpy as np
import pytest

import app as server
import autotiming
import colabvoice
import recut
import voicegen
from test_episode import SCRIPT
from test_fetcher import fake_ytdlp, calls  # noqa: F401  (fixture)
from test_recut_delete import LIST, make, upload, wait


# ------------------------------------------------------------ Re-cut fetch


def test_fetch_items_groups_by_source_and_uses_guide_links():
    ins = recut.parse(LIST)
    items = recut.fetch_items(ins, have=set(), links={})
    assert [(i["id"], i["save_as"], i["video_id"], i["status"], i["need"]) for i in items] == [
        ("S01", "S01.mp4", "AAAAAAAAAAA", "todo", 13.0), ("S02", "S02.mp4", "BBBBBBBBBBB", "todo", 15.0)]
    assert [i["status"] for i in recut.fetch_items(ins, have={"S01"}, links={})] == ["have", "todo"]
    simple = recut.parse("| At | Source | From | To |\n|---|---|---|---|\n| 0:04.5 | S07 | 1:10 | 1:14 |\n| 0:09 | S07 | 2:00 | 2:05 |\n")
    assert recut.fetch_items(simple, set(), {})[0]["status"] == "manual"  # no link anywhere: upload by hand
    got = recut.fetch_items(simple, set(), {"S07": "CCCCCCCCCCC"})
    assert len(got) == 1 and got[0]["status"] == "todo" and got[0]["need"] == 135.0  # one download covers both clips


def test_recut_page_fetches_missing_clips(isolated, fake_ytdlp, tmp_path):
    c, _ = isolated
    p = c.post("/api/projects", json={"title": "Recut fetch", "mode": "narration"}).json()
    url = "/api/projects/" + p["id"]
    upload(c, url, make(tmp_path / "base.mp4", 10, "0.5*sin(2*PI*440*t)"), "my-rendered-video.mp4")
    v = c.post(url + "/recut/list", json={"text": LIST}).json()
    assert [(f["id"], f["status"]) for f in v["fetch"]] == [("S01", "todo"), ("S02", "todo")]
    assert all(i["file"] is None for i in v["inserts"]) and not v["fetch_acknowledged"]
    r = c.post(url + "/recut/fetch", json={})
    assert r.status_code == 422 and "notice" in r.text  # the download notice must be accepted once
    r = c.post(url + "/recut/fetch", json={"confirm_responsibility": True})
    assert r.status_code == 200, r.text
    job = wait(r.json()["job_id"])
    assert job["status"] == "done" and job["result"]["fetched"] == 2, job
    args = calls(fake_ytdlp)
    assert len(args) == 2 and any("--download-sections" in a for a in args)  # only up to the clip, not the whole video
    v = c.get(url + "/recut").json()
    assert [(i["source_id"], i["file"], i["file_has_audio"]) for i in v["inserts"]] == [("S01", "S01.mp4", True), ("S02", "S02.mp4", True)]
    assert all(f["status"] == "have" for f in v["fetch"]) and v["fetch_acknowledged"]
    assert c.post(url + "/recut/fetch", json={}).status_code == 422  # nothing left to fetch
    # The fetched clips render.
    video = {"kind": "asset", "id": v["videos"][0]["id"]}
    r = c.post(url + "/recut/render", json={"video": video, "inserts": [{"at": 3, "until": 3, "source_id": "S02", "start": 2, "end": 4, "audio_ok": True}]})
    assert wait(r.json()["job_id"])["status"] == "done"


# ------------------------------------------------------------ narration text


def test_spoken_text_leaves_out_editor_directions():
    md = """# SCRIPT v1.1

Retained narration: **3,189** words + 13 clips.

## HOOK

### Beat HOOK — cold hook (RC-01)

**[VISUAL]** Real: U5 interview frame. Base: **V** portrait.

**(setup — retained in v1.1)** Just over two weeks after his daughter died, a father spoke.

*(07 ✂ Re-cut: CLIP RC-01 — U5 00:36.54–00:40.95 plays here — placeholder "not spoken")*

And if you recognized the voice - that was her father. [callback F25a — short]

**[RE-HOOK / OPEN LOOP]** Next: the morning of March 20th, 2026.

Her name (as her family spells it) was Jaela.
"""
    assert voicegen.spoken_text(md).split("\n\n") == [
        "Just over two weeks after his daughter died, a father spoke.",
        "And if you recognized the voice - that was her father.",
        "Next: the morning of March 20th, 2026.",
        "Her name (as her family spells it) was Jaela.",
    ]


# ------------------------------------------------------------ Colab


def wav_bytes(seconds, rate=44100):
    return subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=f=220:d={seconds}:r={rate}", "-ac", "2", "-f", "wav", "-"],
                          capture_output=True, check=True).stdout


def run_notebook_step2(tmp_path, monkeypatch, pack_bytes, pack_name="voice-pack.zip"):
    """Execute the notebook's Step 2 with stand-ins for google.colab and Chatterbox."""
    downloads, shown, said = [], [], []
    colab = types.ModuleType("google.colab")
    colab.files = types.SimpleNamespace(upload=lambda: {pack_name: pack_bytes}, download=downloads.append)
    google = types.ModuleType("google")
    google.colab = colab
    display = types.ModuleType("IPython.display")
    display.Audio = lambda path: ("audio", path)
    display.display = shown.append
    ipython = types.ModuleType("IPython")
    ipython.display = display

    class FakeTensor:
        def __init__(self, a):
            self.a = a

        def squeeze(self, _):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.a

    class Model:
        sr = 24000

        def generate(self, text, audio_prompt_path, exaggeration, cfg_weight):
            said.append((text, audio_prompt_path, exaggeration, cfg_weight))
            n = int(self.sr * (0.3 + 0.01 * len(text.split())))
            silence = np.zeros(int(self.sr * 0.2), dtype=np.float32)
            voice = 0.3 * np.sin(2 * np.pi * 200 * np.arange(n) / self.sr).astype(np.float32)
            return FakeTensor(np.concatenate([silence, voice, silence])[None, :])

    tts = types.ModuleType("chatterbox.tts")
    tts.ChatterboxTTS = types.SimpleNamespace(from_pretrained=lambda device: Model())
    chatterbox = types.ModuleType("chatterbox")
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: True)
    torch.manual_seed = lambda s: None
    def sf_write(path, data, rate):  # stand-in for soundfile.write: a real 16-bit WAV
        import wave
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(np.asarray(data), -1, 1) * 32767).astype("<i2").tobytes())
    soundfile = types.ModuleType("soundfile")
    soundfile.write = sf_write
    for name, mod in {"google": google, "google.colab": colab, "IPython": ipython, "IPython.display": display,
                      "chatterbox": chatterbox, "chatterbox.tts": tts, "torch": torch, "soundfile": soundfile}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.chdir(tmp_path)
    step2 = "".join(colabvoice.notebook()["cells"][2]["source"])
    assert "!" not in [line.strip()[:1] for line in step2.splitlines()]  # plain Python, nothing Colab-only
    assert step2.index("import chatterbox") < step2.index("files.upload()")  # checks Step 1 ran before asking for the pack
    exec(compile(step2, "step2", "exec"), {"__name__": "__main__"})
    return downloads, shown, said


def test_step2_says_run_step1_when_chatterbox_is_missing(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "chatterbox", None)  # import fails, as on a fresh Colab machine
    monkeypatch.chdir(tmp_path)
    step2 = "".join(colabvoice.notebook()["cells"][2]["source"])
    with pytest.raises(SystemExit, match="Run Step 1 first"):
        exec(compile(step2, "step2", "exec"), {"__name__": "__main__"})


def test_voice_pack_notebook_and_mp3_back(isolated, monkeypatch, tmp_path):
    c, _ = isolated
    p = c.post("/api/projects", json={"title": "Colab QA: Javits", "mode": "narration"}).json()
    url = "/api/projects/" + p["id"]
    for role, text in [("script", SCRIPT)]:
        assert c.post(url + "/episode/import", json={"role": role, "text": text, "filename": role + ".md"}).status_code == 200
    v = c.get(url + "/voice").json()
    assert v["colab"]["sample"] is None and v["colab"]["settings"] == {"emotion": 0.5, "pace": 0.5, "seed": 7}
    r = c.post(url + "/voice/colab/pack", json={"source": "script"})
    assert r.status_code == 422 and "voice sample" in r.text
    assert c.post(url + "/voice/colab/sample", files={"files": ("me.wav", wav_bytes(1.0), "audio/wav")}).status_code == 422  # too short
    v = c.post(url + "/voice/colab/sample", files={"files": ("my voice.m4a", wav_bytes(25), "audio/wav")}).json()
    assert v["colab"]["sample"]["seconds"] == 20.0 and v["colab"]["sample"]["name"] == "my voice.m4a"  # trimmed to 20 s
    v = c.patch(url + "/voice", json={"pace": 0.3, "emotion": 2}).json()
    assert v["colab"]["settings"] == {"emotion": 0.9, "pace": 0.3, "seed": 7}
    v = c.post(url + "/voice/colab/pack", json={"source": "script"}).json()
    assert v["colab"]["pack"]["words"] == len(voicegen.spoken_text(SCRIPT).split())
    got = c.get(v["colab"]["pack"]["url"])
    assert got.status_code == 200 and "Colab-QA-Javits-voice-pack.zip" in got.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(got.content))
    assert sorted(z.namelist()) == ["narration.txt", "parts.json", "settings.json", "voice.wav"]
    meta = json.loads(z.read("settings.json"))
    assert meta["pace"] == 0.3 and meta["output"] == "Colab-QA-Javits-narration.mp3"
    parts = json.loads(z.read("parts.json"))
    assert all(len(x["text"]) <= colabvoice.PART_LIMIT + 200 for x in parts) and "#" not in z.read("narration.txt").decode()
    pasted = c.post(url + "/voice/colab/pack", json={"source": "text", "text": "One line only."}).json()
    assert pasted["colab"]["pack"]["words"] == 3

    nb = c.get("/api/voice/colab-notebook")
    assert nb.status_code == 200 and colabvoice.NOTEBOOK_NAME in nb.headers["content-disposition"]
    cells = json.loads(nb.text)["cells"]
    assert [x["cell_type"] for x in cells] == ["markdown", "code", "code"] and "os.kill" in "".join(cells[1]["source"])

    # Colab, Step 2: one upload, every part made, one MP3 downloaded.
    downloads, shown, said = run_notebook_step2(tmp_path, monkeypatch, got.content, "Colab-QA-Javits-voice-pack.zip")
    assert downloads == ["Colab-QA-Javits-narration.mp3"] and len(said) == len(parts)
    assert said[0][1] == "pack/voice.wav" and said[0][3] == 0.3 and said[0][0] == parts[0]["text"]
    mp3 = tmp_path / downloads[0]
    length = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                                  capture_output=True, text=True).stdout)
    assert length > len(parts) * 0.3
    # Running Step 2 again with the same pack carries on: nothing is made twice.
    downloads2, _, said2 = run_notebook_step2(tmp_path, monkeypatch, got.content)
    assert said2 == [] and downloads2 == downloads

    # Back in Casefile: the MP3 becomes the narration and the timing starts by itself.
    heard = voicegen.spoken_text(SCRIPT).split()
    monkeypatch.setattr(autotiming, "available", lambda: True)
    monkeypatch.setattr(autotiming, "transcribe", lambda *a, **k: [{"word": w, "start": i * 0.1, "end": i * 0.1 + 0.1} for i, w in enumerate(heard)])
    assert c.post(url + "/voice/colab/result", files={"files": ("notes.txt", b"x", "text/plain")}).status_code == 422
    r = c.post(url + "/voice/colab/result", files={"files": (mp3.name, mp3.read_bytes(), "audio/mpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timing_started"] and body["narration"]["generated"] and body["narration"]["name"] == "narration-cloned-voice.mp3"
    assert wait(body["job_id"])["status"] == "done"
    assert c.get(url + "/voice").json()["made_timing"]["applied"]

    # Deleting the project removes the sample and the pack too.
    folder = server.DATA / "media" / p["id"] / "voice"
    assert (folder / "sample.wav").is_file() and (folder / "pack.zip").is_file()
    assert c.request("DELETE", url, json={"confirm_title": "Colab QA: Javits"}).status_code == 200
    assert not folder.exists()
