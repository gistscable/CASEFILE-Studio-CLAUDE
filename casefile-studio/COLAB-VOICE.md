# Your cloned voice on free Google Colab (v0.4.23)

Episode setup → **1 · The voice** → **My cloned voice on free Google Colab**.

1. **Choose my voice clip**: 10 to 20 seconds of only you speaking (MP3, M4A or WAV). Casefile
   keeps a cleaned copy (mono, 24 kHz, at most 20 s); play it back to check it.
2. **Read this**: the locked script, the Episode setup script, or narration you paste. Headings,
   tables, `[VISUAL]` lines, re-cut notes and tags are left out automatically.
   **Pace** (Slower / A little slower / Normal) and **Feeling** (Calm / Normal / More feeling).
3. **Download the voice pack**: one zip with everything Colab needs.
4. On **Google Colab**: open the Casefile notebook (first time: *download it* from the same card,
   then in Colab **File → Upload notebook**; after that it is in your Google Drive).
   **Runtime → Change runtime type → T4 GPU**. Press ▶ on **Step 1** and wait for the restart,
   then ▶ on **Step 2** and choose the voice pack. The first part plays early so you can stop if it
   sounds wrong. The MP3 downloads by itself. If it stops halfway, press ▶ on Step 2 again with the
   same pack: it carries on.
5. **Add the MP3 from Colab**: it becomes the narration and **Make the timing** starts by itself.
   Then check **Places to check**.

## Why Casefile does not run Colab for you

Google gives apps no way to start a free Colab session or press its Run buttons, and the free tier
forbids using a session as a server driven from another app's interface (sessions doing that are
stopped without warning). So the heavy work runs on Google's GPU, and you press ▶ twice.

The voice model is Chatterbox by Resemble AI (MIT licence). Its audio carries an inaudible
watermark that marks it as AI-generated. Clone only your own voice or one you have permission to use.
