# Voice and timing (v0.4.21)

In **Episode setup**, under the upload cards, there is now a **Narration voice and timing**
panel. Each half has two choices, and you can mix them freely.

## 1 · The voice

- **Use my own recording**: upload it with "Choose recording", as before.
- **Generate it in my cloned voice**: VoiceStudio on your computer reads the narration.
  Pick what to read (the locked script from the Case desk, the script in Episode setup,
  or narration you paste) and which voice, then **Generate the narration**. The audio is
  set as the project's narration, and **Download the audio** gives you the MP3 (for
  CapCut, or to keep).

### Setting up VoiceStudio once (it is a separate free app)

1. Install and start it on your Mac. With Docker:
   `docker run -d --name omnivoice -p 127.0.0.1:3900:3900 -e OMNIVOICE_API_KEY="choose-a-key" -e OMNIVOICE_DATA_DIR=/app/omnivoice_data -v omnivoice-data:/app/omnivoice_data ghcr.io/debpalash/voicestudio:stable`
2. Open http://127.0.0.1:3900, click **New voice**, upload 5 to 15 seconds of your clean
   speech and type exactly what you said in it.
3. In Casefile Studio open **Voice server settings**, paste the same key, **Save and test**,
   then choose your voice. The default address `http://host.docker.internal:3900` is how
   Casefile's container reaches an app on your Mac.

Know before you rely on it:
- **Speed.** One published test measured 7.6 seconds of cloned speech taking about 4 minutes
  on a desktop CPU. Docker on a Mac has no GPU, so a six-minute narration could take hours.
  The native Mac app may be faster; test with one paragraph first ("Narration I paste here").
- **Licence.** The app code is AGPL-3.0, but the default OmniVoice voice model is reported
  as CC-BY-NC (non-commercial), and renders carry an audio watermark by default. If the
  channel earns money, check the licence of the engine you use, or keep recording yourself.
- Any server that speaks the OpenAI speech API (`POST /v1/audio/speech`) works; change the
  address and engine name in the settings.

## 2 · The timing

- **Use the SRT and JSON from CapCut**: upload them with "Choose SRT / word-timing JSON",
  as before.
- **Make the timing from the audio**: Whisper (in the Docker image, free, runs on your
  computer) listens for *when* each word is said. The *spelling* of every word, name and
  figure comes from your script, matched word by word, so "Javitz" or "nine thirty" in what
  it heard becomes "Javits" and "9:30" as your script writes them. The result is loaded into
  the project and you can download three files: **Captions (SRT)**, **Word timing (JSON)**
  and **Places to check** (every spot where the audio and the script differ, with its time).
  If less than 60% of the script is heard, nothing is loaded and it says so: wrong audio or
  wrong script.

The first run downloads the speech model (about 150 MB for "Faster") into the data volume,
so it needs the internet once. If Whisper could not be installed when the image was built,
the panel says so and the CapCut route still works.

Read **Places to check** before rendering: most entries are spelling (fine), but an entry
where the audio says something the script does not is a misread line in the recording.

Code: `voicegen.py`, `autotiming.py`, `/voice` endpoints in `app.py`, `web/src/VoiceTiming.jsx`.
Tests: `tests/test_voice_timing.py` (speech server and Whisper are stand-ins there).

## Troubleshooting Whisper (v0.4.33)

Episode setup shows the exact reason when Whisper cannot load, and a timing run that fails shows
its error. Common causes:
- **Not installed:** the Docker build prints `Whisper ready: …` when it works. If it printed the
  WARNING instead, rebuild with `docker build --no-cache -t casefile-studio .` and read the lines
  above the warning.
- **First run needs the internet:** the speech model (about 150 MB for "Faster") downloads once
  into Casefile's data volume.
- **"Only N% of the script was heard":** the recording and the script do not match (wrong file, or
  a script that still has re-cut lines the voice did not read).
