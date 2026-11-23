"""Voice and timing (v0.4.21): cloned-voice narration through a local speech
server (mocked) and Whisper timing with the script's spelling (Whisper mocked).
Uploading your own audio and CapCut files stays possible and is tested elsewhere."""
import io
import json
import subprocess
import time
import wave

import httpx
import pytest

import app as server
import autotiming
import casedesk
import voicegen
from test_episode import SCRIPT, GUIDE


def tone(seconds=1.0, rate=24000):
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=f=330:d={seconds}:r={rate}", "-ac", "1", "-f", "wav", "-"],
                         capture_output=True, check=True).stdout
    return out


def fake_server(seen, fail=False):
    def handler(request):
        seen.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "device": "cpu", "version": "0.5.6"})
        if request.url.path == "/profiles":
            return httpx.Response(200, json=[{"id": "myvoice01", "name": "My voice"}])
        if request.url.path == "/v1/audio/speech":
            if fail:
                return httpx.Response(500, text="engine crashed")
            return httpx.Response(200, content=tone(0.8))
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def wait(job_id, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        j = server.JOBS[job_id]
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_spoken_text_and_pieces():
    md = "# Title\n**Recording date:** today\n\n## Hook\n\nFirst line. Second line.\n\n## Chapter 1\n\nA paragraph.\n\n### Audit footer\n- **IDs used:** L1.\n"
    text = voicegen.spoken_text(md)
    assert text == "First line. Second line.\n\nA paragraph."
    parts = voicegen.pieces(text)
    assert [p[0] for p in parts] == ["First line. Second line.", "A paragraph."]
    long = " ".join(f"Sentence number {i} goes here." for i in range(40))
    assert all(len(p[0]) <= voicegen.MAX_CHARS for p in voicegen.pieces(long)) and len(voicegen.pieces(long)) > 2


def test_alignment_keeps_script_spelling_and_whisper_times():
    script = "By his father’s account, Javits arrived on October 28, 2025. It happened at around 9:30 that morning."
    heard_text = "by his fathers account Javitz arrived on October 28th 2025 it happened um at around nine thirty that morning"
    heard = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(heard_text.split())]
    words, report = autotiming.align(script, heard)
    assert " ".join(w["word"] for w in words) == script  # every script word, spelt as the script spells it
    assert words[0]["start"] == 0 and all(b["start"] >= a["start"] for a, b in zip(words, words[1:]))
    pairs = {(d["script"], d["heard"]) for d in report["differences"]}
    assert ("Javits", "Javitz") in pairs and ("9:30", "nine thirty") in pairs and ("(not in the script)", "um") in pairs
    srt = autotiming.to_srt(words)
    assert "Javits" in srt and "Javitz" not in srt and "00:00:00,000 -->" in srt
    data = json.loads(autotiming.to_json(words))
    assert [w["word"] for w in data["words"]][:3] == ["By", "his", "father’s"]
    # The editor's own importer accepts both files.
    assert server.episode.parse_timings(autotiming.to_json(words), "w.json")["words"][0]["word"] == "By"
    assert server.episode.parse_timings(srt, "c.srt")["captions"]
    with pytest.raises(ValueError):
        autotiming.align(script, [])


def project(c):
    p = c.post("/api/projects", json={"title": "Voice QA", "mode": "narration"}).json()
    url = "/api/projects/" + p["id"]
    for role, text in (("script", SCRIPT), ("guide", GUIDE)):
        assert c.post(url + "/episode/import", json={"role": role, "text": text, "filename": role + ".md"}).status_code == 200
    return url, p["id"]


def test_generate_narration_then_whisper_timing_end_to_end(isolated, monkeypatch):
    c, _ = isolated
    url, pid = project(c)
    seen = []
    client = fake_server(seen)
    real = voicegen.SpeechServer
    monkeypatch.setattr(voicegen, "SpeechServer", lambda *a, **k: real(*a, client=client, **k))
    v = c.get(url + "/voice").json()
    assert v["server"]["ready"] and "CPU" in v["server"]["detail"] and v["voices"] == [{"id": "myvoice01", "name": "My voice"}]
    assert "script" in v["sources"] and v["narration"] is None
    assert c.post(url + "/voice/generate", json={"source": "script"}).status_code == 422  # no voice chosen yet
    v = c.patch(url + "/voice", json={"voice": "myvoice01", "key": "secret-key"}).json()
    assert v["settings"]["key_saved"] and "secret-key" not in json.dumps(v)
    r = c.post(url + "/voice/generate", json={"source": "script"})
    assert r.status_code == 200, r.text
    job = wait(r.json()["job_id"])
    assert job["status"] == "done", job
    speech = [q for q in seen if q.url.path == "/v1/audio/speech"]
    assert speech and json.loads(speech[0].content)["voice"] == "myvoice01" and speech[0].headers["authorization"] == "Bearer secret-key"
    spoken = " ".join(json.loads(q.content)["input"] for q in speech)
    assert "First synthetic sentence" in spoken and "#" not in spoken
    v = c.get(url + "/voice").json()
    assert v["narration"]["generated"] and v["narration"]["name"] == "narration-cloned-voice.mp3" and v["narration"]["duration"] > 1
    assert c.get(v["narration"]["url"]).status_code == 200  # downloadable
    p = c.get(url).json()
    assert p["narration_id"] == job["result"]["asset_id"]

    # Timing: Whisper (stand-in) mishears a word; the script's spelling wins.
    narration_text = voicegen.spoken_text(SCRIPT)
    heard_words = narration_text.replace("synthetic", "sinthetic", 1).split()
    step = v["narration"]["duration"] / len(heard_words)
    monkeypatch.setattr(autotiming, "available", lambda: True)
    monkeypatch.setattr(autotiming, "transcribe", lambda *a, **k: [{"word": w, "start": i * step, "end": (i + 1) * step} for i, w in enumerate(heard_words)])
    r = c.post(url + "/voice/timing", json={"model": "base.en"})
    assert r.status_code == 200, r.text
    job = wait(r.json()["job_id"])
    assert job["status"] == "done", job
    made = c.get(url + "/voice").json()["made_timing"]
    assert made["applied"] and made["differences"] == 1 and made["match"] > 0.9
    srt = c.get(made["files"]["captions.srt"]).text
    assert "sinthetic" not in srt and "synthetic" in srt
    assert "sinthetic" in c.get(made["files"]["differences.txt"]).text
    assert json.loads(c.get(made["files"]["word_timings.json"]).text)["words"]
    assert c.get(url).json()["episode"]["timings"]["words"]


def test_clear_messages_when_things_are_missing(isolated, monkeypatch):
    c, _ = isolated
    url, pid = project(c)
    real = voicegen.SpeechServer

    def down(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(voicegen, "SpeechServer", lambda *a, **k: real(*a, client=httpx.Client(transport=httpx.MockTransport(down)), **k))
    v = c.get(url + "/voice").json()
    assert not v["server"]["ready"] and "Start VoiceStudio" in v["server"]["detail"]
    c.patch(url + "/voice", json={"voice": "x"})
    assert "Start VoiceStudio" in c.post(url + "/voice/generate", json={"source": "script"}).text
    assert "Add the narration audio first" in c.post(url + "/voice/timing", json={}).text
    assert c.patch(url + "/voice", json={"base": "ftp://x"}).status_code == 422
    assert "no narration text" in c.post(url + "/voice/generate", json={"source": "text", "text": "  "}).text
