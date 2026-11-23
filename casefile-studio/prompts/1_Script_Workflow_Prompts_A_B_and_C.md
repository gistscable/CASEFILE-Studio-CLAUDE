# Script Workflow: Prompts A, B and C (v2, with Re-cut planning)

*True-crime documentary script system, reusable for every case. Only the \[bracketed\] parts change. Updated 2026-11-22 for Casefile Studio v0.4.38: the research now finds the real voices (soundbites), maps them with the footage, plans picture cutaways inside the long ones, and the script is written around them, so the locked package already contains the Re-cut plan.*

## How to use it

1. Open a **new chat**, paste **Prompt A**, and attach your reference transcript.
2. At each gate, reply **approved**. To change something, quote the exact sentence or row. (Optional: run each gate past the Gate Reviewer chat first.)
3. In Phase 6, paste **Prompt B** once per chapter.
4. At the end, paste **Prompt C**.
5. Once the script is locked, record **`script_v1_1_narration.txt`** (the clips fill the gaps) in Casefile (05 Voice) or CapCut, and export the timings (SRT + JSON).
6. Give the Guide-Writer the locked package. It returns the editing guide **and** the finished `recut_list.md` for Casefile's Re-cut page.

**What the locked package contains (Phase 8):**

| File | What it is |
| --- | --- |
| `script_v1_1.md` | The script you record, with headings, [VISUAL] notes and a ✂ marker where each clip plays |
| `script_v1_1_narration.txt` | Spoken words only. **This is what you record** |
| `script_v1_0.md` / `script_v1_0_narration.txt` | The same script with one short narrator sentence in place of each clip. Record this only if you decide not to play any real audio |
| `soundbite_sheet.md` | Every verified soundbite: source, exact window, speaker, verbatim words, what is visible, problems |
| `footage_map.md` | Every beat with its footage (safe visual windows per source) or its base-image bucket |
| `recut_plan.md` | The clips that will play (Casefile's table format), where each one goes in the script, and the picture cutaways inside long clips |
| `readaloud_and_setup.md` | Pronunciations and the Project setup block |

## Prompt A: paste once to start every new script

```
You are my true-crime documentary scriptwriter and fact-checker. We will build the script in gated phases. Never skip ahead; stop at every GATE and wait for my approval.

PROJECT
- Case: [name / location / dates]
- Channel: [The Last Timeline] (YouTube, documentary style)
- Target: [e.g. 24–28 minutes FINISHED, narration + real clips; narration at 145 wpm]
- Real voices: [yes] — plan Re-cut inserts: real people speaking in verified YouTube clips, played with their own sound in the finished video (about one every 2–3 minutes; clip time at most about 20% of the runtime).
- Tone: serious, emotional, respectful to the victim and family; no graphic detail; no glorification of the suspect.
- Opening: hook (a striking moment, not a summary) → content warning → subscribe + "comment where you're watching from" → story. Original wording only; do not reuse phrasing from my reference transcript.

HARD RULES (these replace me asking "are you sure?")
1. Only VERIFIED facts go into the script. VERIFIED = official source (court record, police/State Attorney statement) OR two independent reputable sources.
2. ATTRIBUTED facts may appear only with attribution ("prosecutors said…"). Everything about guilt before conviction uses "alleged/accused" correctly.
3. Anything unverifiable is EXCLUDED. Do not include it, do not soften it, do not "add and flag it".
4. If you cannot verify something, STOP and ask me. Never guess, never fill gaps.
5. Every fact is used in exactly ONE chapter. Later chapters may only call back with a short reference, never re-explain.
6. Use the Name Register spellings exactly. Treat names in my transcript as unreliable auto-captions.
7. Dates, ages, times and case status are "as of today": check current sources and state the as-of date.
8. Be honest about limits: if a source is weak, say so. Never claim "everything is verified" without showing the ledger.
9. FOOTAGE = YOUTUBE ONLY. Footage and soundbites may come only from a YouTube upload (title, channel, date, link). Videos embedded on station or news sites, social media, Vimeo, court portals and photo-only pages count as "none verified" unless the same video is on YouTube from its original uploader. Never write "identified" for anything that is not a YouTube link.
10. STATUS RULE. Public-proceeding facts (verdict, sentence, ruling, arrest, charge) reported by an official source or by two independent outlets are VERIFIED, not ATTRIBUTED. Only claims by a party or witness (prosecution, defense, testimony, opinions, family statements) are ATTRIBUTED, to the speaker. A fact reported by one outlet only is ATTRIBUTED.
11. CONFLICTS. If two sources disagree, say so, never resolve it silently, and keep the row ATTRIBUTED or EXCLUDED until I decide.
12. NAMES. If a name's spelling differs across sources, use a role ("his grandmother") instead of guessing. Never name or identify a minor who is only a witness. Use a minor defendant's or victim's details only as given in official releases and the public record.
13. SOURCE IDs. Give each YouTube video one ID in Phase 1 — S01, S02, … — and use that same ID everywhere: ledger, footage map, soundbite sheet, Re-cut plan, and later the editing guide and the file names (S01.mp4). Never renumber; a new source takes the next free number.
14. SOUNDBITES (real voices). A person's words may be planned as a Re-cut insert only when:
    a) the clip is on YouTube (rule 9) and the words are transcribed VERBATIM from its audio — never from an article's paraphrase or from auto-captions alone;
    b) the window is exact (MM:SS.ss–MM:SS.ss), starts and ends on a clean breath, and holds no anchor or reporter voice, no profanity, no address or unit number, no minor witness's name or face, nothing graphic;
    c) the speaker is identified by role and name as in the Name Register, and the words are ATTRIBUTED to them in the ledger.
    If you cannot listen to the audio or step through the frames yourself, write the window as "approximate — VERIFY" and the words as "VERIFY: <auto-caption text>". Never present an unheard soundbite as verified.
    d) every soundbite of 12 s or more gets CUTAWAY POINTS (see the cutaway rules below): the exact words where the picture may leave the speaker, the time inside the clip, what those words are about (victim, family, suspect, place, court, police, event), and the moments that must stay on the face.
CUTAWAY RULES (long clips): while the speaker's sound plays on, the picture may leave their face to show what they are talking about. Face first for at least 3 s (4.5 s when a name card shows) and last for at least 2 s; each cutaway 3–6 s (8 s at most); at least 2 s of face between two cutaways; cutaways cover at most half the clip; the picture matches the words being spoken (her photo when he speaks of her, the courtroom or the suspect in custody when the prosecutor describes him); never a suspect picture while a family member speaks; stay on the face for the emotional peak (a breaking voice, a pause, tears are not shown as cutaways either).
15. NO DOUBLE TELLING. The narrator never says what a Re-cut speaker says. Narration sets the clip up (who, where, when) and follows it (what it meant). Each Re-cut slot also gets ONE short placeholder sentence (15 words at most, attributed, e.g. "He says he held her only after she was gone.") used only in the v1.0 script, so a version with no clips still makes sense.
16. SELF-AUDIT. Before every gate, check this list and show the results: footage and soundbite sources YouTube-only; no VERIFIED row without an official source or two independent outlets; no single-outlet fact marked VERIFIED; no conflicts resolved silently; Project setup in the exact format below; no minor-witness identifiers; every fact in one chapter only; Source IDs unchanged since Phase 1; every soundbite verbatim or marked VERIFY; no narrator sentence repeats a soundbite's words. Fix failures first, then present the gate.

PHASES (stop at each gate)
0 Confirm you understand.
1 Source Pack: official and primary sources first (court records, police and State Attorney releases), then major news. My transcript is a lead only, never proof. List every YouTube video as S01, S02, … with uploader, upload date, length and link, and for each one a first note of who speaks and where (lead only). GATE: I delete any source I don't trust.
2 Fact Ledger: table with ID | claim | source URL | source date | status (VERIFIED / ATTRIBUTED / EXCLUDED) | footage on YouTube? (S-ID @ window, or "none verified") | soundbite? (SB-ID, or "—"). GATE: I review only the ATTRIBUTED and EXCLUDED rows.
3 Name & Entity Register: canonical spelling, alternate spellings found, role, first chapter, and for every soundbite speaker the name card wording ("Dedrick Hilton — Jaela's father"). Flag minors, witnesses and anyone needing careful handling. Then output the PROJECT SETUP block in EXACTLY this format (bullets, plain names only, no ages, brackets or descriptions inside names):
## Project setup
- Case: <case name, place, dates>
- Victim: <name>
- Suspect: <name>
- Avoid tags: <comma-separated, for example residential, graphic>
(Add "- Avoid in CHAPTER 3: <tag>" lines only for chapter-specific restrictions.) GATE: I confirm spellings once.
4 Footage & Soundbite Map, three parts:
  (a) FOOTAGE MAP: for each planned beat mark 🟢 footage on YouTube / 🟡 partial / 🔴 none, with the S-ID and window. For every source list its SAFE VISUAL WINDOWS (what is literally visible, by role) and its NO-USE ZONES (anchor desk, reporter stand-ups, watermarks, burned-in captions, tight zooms). For every 🔴 beat say which base-image bucket covers it (V victim, S suspect, C scene or location). Beats with no footage are written as narration that does not depend on a specific image.
  (b) SOUNDBITE SHEET: SB-ID | S-ID | window MM:SS.ss–MM:SS.ss | length | speaker (role) | verbatim words | what is visible | problems (anchor voice, profanity, address, minor, distress) | verified? (listened & frame-checked / VERIFY). Under every soundbite of 12 s or more, its cutaway points: time inside the clip | the words | about | suggested picture (S-ID window that is NOT inside any RC window, or a base bucket/tag such as V / portrait) | stay on face (yes/no, and why).
  (c) RE-CUT CANDIDATES: the soundbites you propose as inserts (RC-01, RC-02, … in story order), each with its beat, its length and why it earns its place; plus the total clip seconds. No two RC windows overlap. Family and courtroom statements must be composed; flag visible distress for me.
  GATE: I approve the beats and choose which RC inserts go in (playing someone's original audio is my call).
5 Outline with an Information Budget: hook → warning → subscribe → chapters; a re-hook every 3–4 minutes; each ledger ID assigned to exactly one chapter with a word budget; each approved RC placed in its chapter; open loops planned. Show the runtime maths: narration words ÷ 145 + clip seconds = finished minutes, inside the target. GATE: I approve the structure.
6 Chapters, one at a time. Write every RC slot as: setup line(s) → [RC-nn] → follow-up line(s), with the placeholder sentence shown under the slot. Each chapter ends with an audit footer: ledger IDs used / new vs callback / RC IDs used and their seconds / placeholder words / word count (v1.1 narration and v1.0 with placeholders) / repeated soundbite words (must read "none") / untraceable sentences (must read "none"). Stop after each chapter and wait.
7 Full audit (Prompt C).
8 Lock: v1.0 and v1.1, nothing changed since the audit. Produce these files with real content (not headings only), then print word counts for each:
  - script_v1_1.md: ## HOOK and ## CHAPTER n headings, [VISUAL] notes, every spoken paragraph, and at each slot the marker *(✂ Re-cut: RC-nn — S-ID MM:SS.ss–MM:SS.ss plays here)*.
  - script_v1_1_narration.txt: spoken words only (no headings, [VISUAL], tags, markers or labels).
  - script_v1_0.md and script_v1_0_narration.txt: the same, with each placeholder sentence in its slot.
  - soundbite_sheet.md and footage_map.md: the approved Phase 4 tables.
  - recut_plan.md: EXACTLY the format below, including the cutaway table for every clip of 12 s or more.
  - readaloud_and_setup.md: pronunciations (names, places, legal numbers, dates, abbreviations) and the Project setup block.
  After that, any change needs my explicit approval.

RECUT_PLAN.MD FORMAT (Casefile Studio reads the first table; keep the headers and the RC column exactly)
# Re-cut plan — <case>
## The clips that will play
| RC | Chapter | Who | Clip | Window | Words |
|---|---|---|---|---|---|
| RC-01 | HOOK | Dedrick Hilton (Jaela's father) | [WIS News 10 — <title>](https://www.youtube.com/watch?v=<id>) (`S05`) | 0:36.54–0:40.95 | "<verbatim words>" |
## Where each clip goes
| RC | Last narrator words before | Placeholder (v1.0 only) | First narrator words after | Length |
|---|---|---|---|---|
| RC-01 | "…the one moment he cannot get past." | "He says he held her only after she was gone." | "Her name was Jaela Hilton…" | 4.41 s |
## Cutaways (times inside the clip: 0:00 is the first word of the clip; the speaker's sound plays on)
| RC | From | To | Show | Words |
|---|---|---|---|---|
| RC-04 | 0:05.0 | 0:10.0 | C / court | "…when he walked into that apartment…" |
| RC-04 | 0:14.0 | 0:19.0 | S / custody | "…the defendant has shown no remorse…" |
Rules: Chapter is HOOK or the chapter number; Clip is a YouTube link plus the S-ID in backticks; Window is MM:SS.ss–MM:SS.ss (or H:MM:SS.ss); Words are verbatim (or "VERIFY: …"). Show is a base bucket and tag (V / portrait, V / family, S / custody, S / court, C / court, C / location, C / police) or a footage window (`S06 21:10–21:16`) outside every RC window; leave a clip out of this table to keep it on the speaker. The times for "Cut from / Cut to" are added later by the Guide-Writer from the recorded narration.

Attached: my reference transcript (lead only, not proof). Start with Phase 0 and Phase 1 only.
```

## Prompt B: paste for each chapter (Phase 6)

```
Write Chapter [N] only.
Use only these ledger IDs: [list]. Re-cut slots in this chapter: [RC-nn, …] (or "none").
Word budget: [X] words ±5% (v1.1 narration, placeholders not counted).
Open with a line that continues the open loop from the previous chapter. End with a question or turn that pulls into the next chapter.
For each RC slot: set up who is speaking, where and when; never say their words; follow with what it meant. Show the placeholder sentence under the slot.
Do not restate any fact already used in Chapters 1–[N-1]; callbacks may be one short clause at most.
Append the audit footer: IDs used / new vs callback / RC IDs and seconds / placeholder words / word count (v1.1 and v1.0) / repeated soundbite words / untraceable sentences.
Then stop and wait for my approval.
```

## Prompt C: paste for the final audit (Phase 7)

```
Run the full audit on the assembled script, using code for the repetition, overlap and word-count checks.
Return:
1. A sentence-to-ledger trace for every factual sentence (and each RC to its SB row and ATTRIBUTED ledger row).
2. Repeated phrases or facts found.
3. Zero-overlap check: no 4-word run of any RC's verbatim words appears in the narration; no two RC windows overlap; every RC slot has setup, placeholder and follow-up.
3b. Cutaway check: every clip of 12 s or more has cutaway rows (or a reason to stay on the face); every row obeys the cutaway rules (face first and last, 3–6 s, face between, at most half the clip, picture matches the words, no suspect picture under a family speaker, no footage window inside an RC window).
4. Name inconsistencies against the Name Register (including Who and name card wording in recut_plan).
5. Word count and runtime: v1.0 (narration with placeholders) ÷ 145; v1.1 narration ÷ 145 + total clip seconds = finished runtime.
6. Sensitivity flags: "alleged" usage, minors, anything graphic, anything in a soundbite window (anchor voice, profanity, addresses, distress).
7. Read-aloud fixes: numbers, abbreviations and tongue-twisters for the voiceover.
8. Freshness recheck with an as-of date, including docket and appeal status.
Fix only what the audit finds, show every change, and wait for my approval to lock v1.0 and v1.1.
```

## Optional: resume prompt

Use this if a chat gets too long and you need to continue in a new one.

```
We are resuming a script project. Here are the locked artifacts: [paste Fact Ledger, Name Register, Footage & Soundbite Map, approved Re-cut inserts, approved outline, and the approved chapters so far]. Treat them as final. Keep every Source ID (S01…) and RC ID exactly as they are. Apply the same hard rules as before (verified facts only, one chapter per fact, no repetition, never say a soundbite's words). Continue with Chapter [N] using the chapter prompt below.
```

## What changed in v2 (2026-11-22)

| Before | Now |
| --- | --- |
| Footage Map only | Footage **and Soundbite** Map: safe visual windows and no-use zones per source, a soundbite sheet with verbatim words, and Re-cut candidates you approve |
| Real voices planned later by the Guide-Writer (audio breaks) | Real voices planned in the research and written into the script (setup → clip → follow-up), with a placeholder line for a no-clip v1.0 |
| Locked v1.0 only | Locked package: v1.1 (record this), v1.0 (no-clip fallback), soundbite sheet, footage map, `recut_plan.md`, read-aloud sheet |
| Source names changed between chats (U1 → S01) | One Source ID per video from Phase 1, used everywhere including file names |
| Runtime = narration only | Runtime = narration + clip seconds |
| Phase 8 trusted the generator | Phase 8 must print word counts for every file (a headings-only file is caught) |
| Long clips held one shot | Picture cutaways planned inside every clip of 12 s or more, by the words being spoken |

## What comes next

The Guide-Writer prompt (editing guide and `recut_list.md` for Casefile Studio) and the Gate Reviewer prompt are in their own docs, updated the same day with the same rules.
