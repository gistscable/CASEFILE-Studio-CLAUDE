// v0.4.68 Narration, music and sound effects are separate kinds of audio.
// A file's kind: the role that uses it now, else how it was sorted (imported into the
// Audio tab's Narration, Music or Sound effects, or moved there later), else not sorted.

export const AUDIO_ROLES = [
  ["narration", "Narration"],
  ["music", "Music"],
  ["sfx", "Sound effect"],
];

export const hasSound = (a) => !!a && (a.kind === "audio" || a.has_audio === true);

export function audioRoleOf(a, project) {
  if (!hasSound(a)) return null;
  if (a.id === project?.narration_id) return "narration";
  if (a.id === project?.music_id) return "music";
  if (["narration", "music", "sfx"].includes(a.audio_role)) return a.audio_role;
  if (a.sfx === true) return "sfx";
  return null;
}

// A sound effect is a short audio file (the export's sound design takes up to 30 s).
export const canBeSfx = (a) => a?.kind === "audio" && Number(a.duration || 0) <= 30;

// The Audio tab's lists. Videos with sound are footage: they are listed only once sorted.
export function audioLists(project) {
  const out = { narration: [], music: [], sfx: [], unsorted: [] };
  for (const a of project?.assets || []) {
    if (!hasSound(a)) continue;
    const role = audioRoleOf(a, project);
    if (role) out[role].push(a);
    else if (a.kind === "audio") out.unsorted.push(a);
  }
  return out;
}

// Why a file cannot be moved to `role` (empty: it can).
export function roleBlock(a, role, project) {
  const now = audioRoleOf(a, project);
  if (now === role) return "";
  if (a.id === project?.narration_id) return "This is your narration now. Stop using it as narration first.";
  if (a.id === project?.music_id) return "This is your music now. Stop using it as music first.";
  if (role === "sfx" && !canBeSfx(a)) return "A sound effect is an audio file of up to 30 seconds.";
  return "";
}
