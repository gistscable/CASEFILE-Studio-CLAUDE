# Re-cut and Delete project (v0.4.22)

## Re-cut (new tab, after Review & export)

Puts the real voices into a finished video. At each insert the video stops, the original
clip plays with its own picture and sound, and the video carries on **after** the narrator's
version of the same words. That stretch of the video (picture, narration and burned-in
captions together) is skipped, so each line is heard once, from the real speaker. You do not
cut the voiceover, re-export from CapCut or change the editing guide.

1. **The video to re-cut.** Videos rendered in this project are listed, newest first. Or
   upload any finished MP4.
2. **Where the real clips go.** Press **Load my re-cut list** and choose the re-cut list
   file (the Markdown with a table of cut points and a table of "the clips that will play").
   Each insert appears with who speaks, the words, **where the video stops**, **where it
   continues from** (the list's "Cut from" and "Cut to"), the clip and its from/to. You can
   also add inserts by hand. Set "stops at" and "continue from" to the same time if you want
   to add a clip without skipping anything.
   - Clip times in a list are usually approximate. Use **Listen on YouTube**, then set
     "from" and "to" to the exact words.
   - Optional inserts come unticked.
   - The clip file must be in the project (get it with Fetch from guide, or upload it
     named like `S16.mp4`).
   - Tick **I may play this clip's original audio** on each insert you use. That is your
     decision, clip by clip; nothing ticks it for you.
3. **Make the re-cut.** The result plays on the page and has a **Download the re-cut**
   button. A re-cut can be re-cut again.

The clip's sound is levelled to match the narration and faded in and out briefly. The clip's
picture is fitted to the video's size. The new length is the old one, minus what is skipped,
plus the clips. The inserted clips carry no captions. Play the result at each insert: the
list's times are where the narrated quote starts and ends, and if a word is clipped, move
"stops at" or "continue from" by a few tenths of a second and make it again.

## Delete project

Open the project list (the arrow beside the title). Each project has a bin button. It
shows how much space the project uses and asks you to type the project's title. Deleting
removes the project, its footage, renders, re-cuts and Case desk documents from the data
volume, so the space really comes back. It cannot be undone; download any video you still
need first. Files that another project still uses are kept. The fictional sample cannot be
deleted.

Code: `recut.py`, `/recut` endpoints and `DELETE /api/projects/{id}` in `app.py`,
`web/src/Recut.jsx`. Tests: `tests/test_recut_delete.py`.

## Fetch the clips from the Re-cut page (v0.4.23)

When the loaded list names clips that are not in the project, a box under the list says which ones
and offers **Fetch these clips**. Accept the download notice once, press it, and Casefile downloads
each video only as far as the last clip needs, saves it as `S01.mp4` and so on, and ticks the
inserts that were waiting for it. Clips with no YouTube link in the list or the guide are named so
you can upload them by hand.

## The re-cut follows the picture (v0.4.42)

A finished video's file length is its longest track. When the sound ran on past the picture
(a CapCut export with a long voice track, or a stray late audio packet), the re-cut planned its
last stretch to the sound's length: the sound was padded out to it, the picture ran out of frames,
and the re-cut failed with "The re-cut's picture (11:26) and sound (79:24) came out different
lengths". Casefile now reads where the picture and the sound really end (from the file's packets)
and uses the picture's length. If the sound runs more than 2 seconds past the picture, the
finished message says so ("has 6:19 of picture but 74:17 of sound… the sound after 6:19 is left
out"), and an insert placed after the picture ends is refused with the same explanation. A piece
whose picture runs a few frames short holds its last frame (up to 2 s), so later shots never
shift. Clip files are measured the same way. Tests: `tests/test_recut_lengths.py`.

## Clips with broken timestamps (v0.4.43)

Some downloaded clips (cut sections from YouTube are the usual case) have timestamps that stop
advancing or jump backwards part-way through. The re-cut used to cut each clip by its timestamps,
so "stop after 14.86 seconds" never triggered: the clip's sound ran on to the end of its file
(a 22:05 re-cut came out with 36:54 of sound) and the picture join stalled after the clip
("The re-cut's picture (2:04) and sound (36:54) came out different lengths").

Now:
- Every clip file's packets are read first; broken timestamps are spotted, and such clips are cut
  by frame and sample number from the start of the file, never by their times.
- Every clip's and every video stretch's sound is cut by sample count, so it is exactly as long as
  its picture whatever the file's timestamps say.
- Each piece is checked (frames and samples) before the join. A clip that still comes out wrong is
  retried the other way; if that fails too, the message names the clip, its file and its times, and
  says to fetch or upload that file again, instead of "send this message to support".
- The picture check reads broken clips by frame number as well.

Tests: `tests/test_recut_lengths.py`.
