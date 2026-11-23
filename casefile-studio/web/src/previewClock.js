// Preview playback clock (v0.4.19).
//
// The editor preview used to run its own wall clock (requestAnimationFrame) and
// re-seek the narration <audio> whenever the two drifted more than 0.3 s apart.
// Every time the page stalled (a heavy re-render, a busy tab, buffering), the
// clocks drifted, the narration was yanked to a new position, and the producer
// heard skips, repeats and gaps that are not in the recording.
//
// Now the narration is the master clock while it is speaking: the timeline
// position is read FROM the audio element, so the browser plays the recording
// continuously and the picture follows it. The wall clock is only used where
// nothing is speaking (no narration, an audio break, or silence after a scene's
// speech). These helpers are pure so they can be unit-tested without a browser.

/** Narration time (seconds into the recording) at timeline time `t` inside
 *  `scene` (which starts at `offset`), or null when the narration is silent
 *  there: an audio break, or past the end of the scene's speech. */
export function speechAt(scene, offset, t) {
  if (!scene || scene.insert_audio) return null;
  const local = t - offset;
  const length = scene.audio_duration ?? scene.duration ?? 0;
  if (!(local >= 0) || local >= length) return null;
  return (scene.audio_start || 0) + local;
}

/** Index of the scene playing at timeline time `t`. */
export function sceneIndexAt(scenes, offsets, t) {
  for (let i = 0; i < scenes.length; i++)
    if (t < offsets[i] + scenes[i].duration) return i;
  return Math.max(0, scenes.length - 1);
}

/** Map the narration element's position `src` back to timeline time, starting
 *  from the scene at `index`. Looks a few scenes ahead so a scene change while
 *  the audio keeps playing is followed without a seek. Returns null when `src`
 *  is not inside the speech of any nearby scene (the caller then keeps its own
 *  clock and the normal sync re-aligns the audio). If an audio break comes
 *  next, returns the break's start so the narration pauses exactly there. */
export function timelineFromSpeech(scenes, offsets, index, src, lookahead = 8) {
  if (!Number.isFinite(src)) return null;
  const last = Math.min(scenes.length - 1, index + lookahead);
  for (let k = Math.max(0, index); k <= last; k++) {
    const s = scenes[k];
    if (s.insert_audio) {
      if (k > index) return offsets[k];
      continue;
    }
    const start = s.audio_start || 0;
    const length = s.audio_duration ?? s.duration ?? 0;
    if (src >= start - 0.02 && src < start + length)
      return offsets[k] + Math.max(0, src - start);
    if (k === index && src >= start + length) {
      // Speech for this scene is over. If the next scene's speech does not
      // continue straight on, hold at the end of this scene's speech and let
      // the wall clock run the silent tail.
      const n = scenes[k + 1];
      if (!n || n.insert_audio || Math.abs((n.audio_start || 0) - (start + length)) > 0.05)
        return offsets[k] + length;
    }
  }
  return null;
}

/** One clock step. `audio` is a snapshot { paused, seeking, ready, currentTime }
 *  of the narration element, or null when there is none. Returns the next
 *  timeline time. Follows the narration when it is playing and close to the
 *  current position (within `follow` seconds); otherwise advances by `dt`. */
export function nextTime(scenes, offsets, t, dt, audio, follow = 1.0) {
  if (audio && !audio.paused && !audio.seeking && audio.ready) {
    const index = sceneIndexAt(scenes, offsets, t);
    const hit = timelineFromSpeech(scenes, offsets, index, audio.currentTime);
    if (hit != null && Math.abs(hit - t) <= follow) return Math.max(t, hit);
  }
  return t + dt;
}
