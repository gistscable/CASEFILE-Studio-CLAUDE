# Case Desk (v0.4.20)

A new **Case desk** tab. It holds the script workflow (gates 1 to 8) inside the app and
finds real footage on YouTube. It uses **no AI model and no paid service**: your own
chats still research, write and review. The Case Desk removes the carrying and the
format send-backs around them.

## Two chats, and which text goes where

You keep two chats open: a **WRITER** chat (researches and writes) and a **REVIEWER** chat
(checks the writer's work). Every copy button names the chat its text goes into.

Each gate is five numbered steps:

1. **Ask for it** (WRITER chat). Copy the prompt. Gate 1 gives Prompt A with your case,
   channel and target filled in; chapters give Prompt B with the chapter number, its ledger
   IDs and word budget from your outline; gate 7 gives Prompt C.
2. **Bring the writer's answer here.** Paste it or load its .md file, press **Check it**.
3. **Get it reviewed** (REVIEWER chat). Copy the packet, paste it there, then paste the
   reviewer's whole reply back and press **Read the reply**. The app reads its VERDICT and
   shows the YOUR CALL decisions. The first time, use **Start a REVIEWER chat** to copy the
   reviewer's own prompt.
4. **Decide.** **Approve this gate** is switched off while the automatic checks show a
   problem that must be fixed, or while the reviewer's verdict is APPROVE WITH CHANGES or
   SEND BACK (or has no clear verdict). The reasons are listed. A corrected version needs a
   fresh review: the old reply does not carry over. "Approve anyway…" exists for the case
   where you checked a flagged point yourself; it asks why and records your reason.
5. **Tell the writer** (WRITER chat). The button gives either "approved, continue" or the
   numbered corrections, built from the checks and the reviewer's paste-ready reply.

The footage search at the bottom runs in the app, not in a chat. Its approved uploads are
added to the gate 2 and gate 4 prompts for the WRITER chat automatically.

## What is checked in code

| Gate | Checks |
|---|---|
| 1 Source Pack | links present; official/primary section; every source dated; confidence notes; listing pages instead of articles; transcript treated as a lead; exclusions listed |
| 2 Fact Ledger | every row has ID, link, date and a valid status; duplicate IDs; footage column is a YouTube link or "none verified" (rule 9); VERIFIED on a single outlet with no official source (rule 10) |
| 3 Name Register | register table found; Project setup block in the exact format the editor reads (plain bullets, plain names, no ages or brackets); minors and witnesses mentioned |
| 4 Footage Map | every beat marked green/yellow/red; every gap has a V, S or C bucket; YouTube-only links; every usable ledger ID mapped once; seconds needing base pictures and the smallest pool per bucket |
| 5 Outline | every ledger ID in exactly one chapter; no EXCLUDED rows; word budget and runtime against your target; hook, warning, subscribe; re-hooks |
| 6 Chapters | word count against budget (+5% limit; under budget is accepted, never padded); audit footer present; IDs belong to that chapter; "Untraceable sentences: none"; spellings the register rules out; guilt words; six-word runs repeated from earlier chapters |
| 7 Full audit | word count and runtime; approved chapters that changed; repeated eight-word runs; register spellings; read-aloud list; an as-of date |
| 8 Lock | all of gate 7, plus the narration is word for word the audited script |

After the lock, **Download the script for the editor** gives the narration under
`## HOOK` and `## CHAPTER n`, ready for Episode setup.

Checked against the real Javits Frimpong files: the pool it computed from the footage map
(V 14, C 12) is the pool that project ended up approving.

**What it cannot do:** tell whether a claim is true, read an article, judge wording or
sensitivity, or clear rights. Those stay with you and your reviewer chat.

## Find real footage on YouTube

Free search through yt-dlp (already in the image), no API key. Type search phrases or
press **Suggest searches** (built from the victim and suspect names in Project setup).
Results are **candidates only**. Open each one, then **Approve** (it gets a Source ID
and its upload date is read) or **Reject**, and say what it shows. Nothing is downloaded
here. **Copy approved sources** gives the list for your script chat; the gate 2 and gate 4
prompts include it automatically. Downloading still happens later, from the guide, with
Fetch from guide.

## Where it is kept

`data/casedesk/<project id>.json` in the same Docker volume as your projects.
Code: `casedesk.py`, `discovery.py`, `web/src/CaseDesk.jsx`, prompts in `prompts/`
(your own Prompt A, B, C and reviewer prompt; edit those files to change the wording).
Tests: `tests/test_casedesk.py`.
