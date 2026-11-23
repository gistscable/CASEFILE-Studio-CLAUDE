"""Make the narration in your cloned voice on free Google Colab (v0.4.23).

Casefile cannot drive Colab: Google offers no way for an app to start a free
Colab session, and turning a free session into a voice server for another app
breaks Colab's free-tier rules. So the work is split cleanly:

* Casefile prepares a *voice pack*: the narration (narration only, already
  split into parts), your voice sample cleaned to 24 kHz mono, and the
  settings. One zip.
* The Casefile notebook on Colab has two cells. Cell 1 installs and restarts.
  Cell 2 asks for the pack, makes every part on Google's free T4 GPU, joins
  them and downloads one MP3.
* Back in Casefile, "Add the MP3 from Colab" makes it the narration and
  starts Make the timing.

The voice model is Chatterbox (Resemble AI, MIT licence). Its files carry an
inaudible watermark that marks them as AI-generated.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

import voicegen

PART_LIMIT = 260  # characters per part: Chatterbox drifts on longer text
SAMPLE_MAX = 20.0
SAMPLE_MIN = 8.0
NOTEBOOK_NAME = "Casefile_Voice_Colab.ipynb"
WPM = 175  # what the cloned voice measured on a real 3,214-word script (about 195); a little under


class ColabError(RuntimeError):
    pass


def _probe_seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def prepare_sample(src, dst):
    """Your voice clip as the model wants it: mono, 24 kHz, level, at most 20 s."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-t", str(SAMPLE_MAX), "-ac", "1", "-ar", "24000",
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "pcm_s16le", str(dst)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode or not dst.exists():
        raise ColabError("That file could not be read as audio. Use an MP3, M4A or WAV of your voice.")
    seconds = _probe_seconds(dst)
    if seconds < 3:
        dst.unlink(missing_ok=True)
        raise ColabError("That clip is too short to copy a voice from. Record 10 to 20 seconds.")
    return seconds


def settings(emotion=0.5, pace=0.5, seed=7):
    def num(v, lo, hi, default):
        try:
            return round(min(hi, max(lo, float(v))), 2)
        except (TypeError, ValueError):
            return default
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = 7
    return {"emotion": num(emotion, 0.25, 0.9, 0.5), "pace": num(pace, 0.2, 0.8, 0.5), "seed": seed}


def safe_name(title):
    stem = re.sub(r"[^A-Za-z0-9]+", "-", title or "").strip("-")[:60]
    return (stem or "casefile") + "-narration.mp3"


def plan(text):
    """Parts, words and a rough length for the narration text."""
    narration = voicegen.spoken_text(text) if re.search(r"^\s*(#|\||\*\*\[)", text or "", re.M) else (text or "").strip()
    parts = voicegen.pieces(narration, PART_LIMIT)
    words = len(narration.split())
    return {"narration": narration, "parts": [{"text": t, "pause": p} for t, p in parts], "words": words,
            "minutes": round(words / WPM, 1)}


def make_pack(text, sample_path, options, title):
    """The zip the notebook asks for."""
    p = plan(text)
    if not p["parts"]:
        raise ColabError("There is no narration to read. Add the script, or paste the narration.")
    sample = Path(sample_path) if sample_path else None
    if not sample or not sample.is_file():
        raise ColabError("Add your voice sample first (10 to 20 seconds of you speaking).")
    meta = {"casefile_voice_pack": 1, "title": title or "", "output": safe_name(title), **settings((options or {}).get("emotion", 0.5), (options or {}).get("pace", 0.5), (options or {}).get("seed", 7)),
            "words": p["words"], "minutes": p["minutes"], "parts": len(p["parts"])}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("settings.json", json.dumps(meta, indent=1))
        z.writestr("parts.json", json.dumps(p["parts"], ensure_ascii=False, indent=0))
        z.writestr("narration.txt", p["narration"] + "\n")
        z.write(sample, "voice.wav")
    return buf.getvalue(), meta


# --------------------------------------------------------------------------
# The notebook
# --------------------------------------------------------------------------

STEP1 = r'''
# Step 1 · Install (2 to 4 minutes). Run once per Colab session.
# Do not import torch before this: the install replaces it.
!nvidia-smi --query-gpu=name --format=csv,noheader || echo "NO GPU. Runtime > Change runtime type > T4 GPU > Save, then run this cell again."
!pip install -q chatterbox-tts
# Colab's torchvision and torchao are built for a newer torch than chatterbox uses; they break loading. Not needed here.
!pip uninstall -y -q torchvision torchao
print("\nInstalled. (Red 'pip's dependency resolver' lines above are normal; ignore them.)")
print("The session now restarts by itself (Colab may say it crashed: that is expected).")
print("Then run Step 2.")
import os
os.kill(os.getpid(), 9)
'''

STEP2 = r'''
# Step 2 · Make the narration. Choose the voice pack from Casefile when the box appears.
try:
    import chatterbox  # installed by Step 1; Colab forgets it when the session resets
except ImportError:
    print("Step 1 has not run in this Colab session.")
    print("Colab wipes installs when it disconnects or sits idle. Press the play button on Step 1,")
    print("wait for the restart (2 to 4 minutes), then run this step again.")
    raise SystemExit("Run Step 1 first.")
import io, json, os, shutil, subprocess, time, zipfile, hashlib
from IPython.display import Audio, display
from google.colab import files

print("Choose the voice pack (.zip) you downloaded from Casefile Studio.")
up = files.upload()
pack_name = next(n for n in up if n.lower().endswith(".zip"))
data = up[pack_name]
key = hashlib.sha1(data).hexdigest()[:12]
shutil.rmtree("pack", ignore_errors=True)
with zipfile.ZipFile(io.BytesIO(data)) as z:
    z.extractall("pack")
S = json.load(open("pack/settings.json"))
PARTS = json.load(open("pack/parts.json"))
VOICE = "pack/voice.wav"
print(f"{S['title'] or 'Narration'}: {S['words']} words in {len(PARTS)} parts, about {S['minutes']} minutes of speech.")
print(f"Emotion {S['emotion']} · pace {S['pace']} · your voice sample:")
display(Audio(VOICE))

import torch, soundfile as sf
from chatterbox.tts import ChatterboxTTS
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
if DEVICE == "cpu":
    print("WARNING: no GPU. Runtime > Change runtime type > T4 GPU. On CPU this takes hours.")
if "model" not in globals():
    print("Loading the voice model (about a minute the first time)...")
    model = ChatterboxTTS.from_pretrained(device=DEVICE)

def say(text):
    torch.manual_seed(int(S["seed"]))
    return model.generate(text, audio_prompt_path=VOICE, exaggeration=float(S["emotion"]), cfg_weight=float(S["pace"]))

def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

work = f"parts-{key}"  # the same pack again carries on where it stopped
os.makedirs(work, exist_ok=True)
start, names, made = time.time(), [], 0
for i, part in enumerate(PARTS):
    raw, clean = f"{work}/raw{i:04d}.wav", f"{work}/p{i:04d}.wav"
    if not os.path.exists(clean):
        sf.write(raw, say(part["text"]).squeeze(0).cpu().numpy(), model.sr)
        ffmpeg("-i", raw, "-af",
               "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.03,areverse,"
               "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.03,areverse,"
               f"aresample=48000,apad=pad_dur={float(part['pause'])}", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", clean)
        os.remove(raw)
        made += 1
        if made == 1:
            print("First part, so you can hear it early (if it sounds wrong, press Stop and change the settings in Casefile):")
            display(Audio(clean))
    names.append(clean)
    left = (time.time() - start) / max(made, 1) * (len(PARTS) - i - 1) if made else 0
    print(f"\rPart {i + 1} of {len(PARTS)} · about {left / 60:.0f} min left   ", end="")
with open(f"{work}/list.txt", "w") as f:
    f.write("\n".join(f"file '{os.path.basename(n)}'" for n in names))
OUT = S.get("output") or "narration-cloned-voice.mp3"
ffmpeg("-f", "concat", "-safe", "0", "-i", f"{work}/list.txt", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
       "-ar", "48000", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k", OUT)
print(f"\nDone in {(time.time() - start) / 60:.1f} minutes: {OUT}")
display(Audio(OUT))
files.download(OUT)
print("Now in Casefile Studio: Episode setup > The voice > Add the MP3 from Colab.")
'''


def _md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)}


def _code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n").splitlines(True)}


def notebook():
    cells = [
        _md("""
# Casefile Studio · your cloned voice on free Google Colab

**Once per session:** menu **Runtime → Change runtime type → T4 GPU → Save**.

1. Run **Step 1** with ▶. It installs, then restarts the session by itself (Colab may say it crashed; that is expected).
2. Run **Step 2** with ▶ and choose the **voice pack** you downloaded from Casefile. That is all: it makes every part, joins them and downloads the MP3.
3. In Casefile Studio, use **Add the MP3 from Colab**. The timing is made for you.

Keep this tab open while it runs. If it stops halfway, run Step 2 again with the same pack: it carries on from where it stopped. If Colab disconnects completely, start again from Step 1.

The voice model is Chatterbox by Resemble AI (MIT licence). Every file it makes carries an inaudible watermark that marks it as AI-generated. Only clone your own voice, or a voice you have permission to use.
"""),
        _code(STEP1),
        _code(STEP2),
    ]
    return {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"display_name": "Python 3", "name": "python3"}, "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 0}
