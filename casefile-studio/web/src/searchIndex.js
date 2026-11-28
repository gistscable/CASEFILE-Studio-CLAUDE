// v0.4.68 Search everything in the editor: tools, settings, pages, actions, scenes, words in the
// narration and media files. Each result says where it lives and what opening it does (`go`).
// Pure data so it can be tested; main.jsx runs `go`.

// [label, where it lives, go, extra words people use for it]
const TOOLS = [
  ["Scenes", "Media", { left: ["media", "scenes"] }, "timeline clips shots order reorder storyboard"],
  ["All media", "Media", { left: ["media", "all"] }, "files library uploads imported"],
  ["Videos", "Media", { left: ["media", "video"] }, "clips footage mp4 mov"],
  ["Photos", "Media", { left: ["media", "image"] }, "images pictures stills jpg png"],
  ["Audio files", "Media", { left: ["media", "audio"] }, "mp3 wav sounds"],
  ["Music", "Audio", { left: ["audio", "music"] }, "song soundtrack background score bgm track"],
  ["Sound effects", "Audio", { left: ["audio", "sfx"] }, "sfx whoosh hit impact riser sound design foley"],
  ["Narration (voice-over)", "Audio", { left: ["audio", "voice"] }, "voice voice-over voiceover vo narrator record speech"],
  ["Text templates", "Text", { left: ["text", "templates"] }, "template message notification subscribe bell lower third breaking news quote place date chapter title card"],
  ["Scene titles", "Text", { left: ["text", "titles"] }, "title heading chapter text"],
  ["Name cards", "Text", { left: ["text", "names"] }, "lower third lowerthird name tag caption person who"],
  ["Stickers", "Stickers", { left: ["stickers"] }, "emoji arrow shape subscribe like bell overlay"],
  ["Point & mark (follow, blur, spotlight)", "Stickers", { left: ["stickers", "mark"] }, "track tracking follow face blur censor hide pixelate spotlight highlight darken box circle pointer callout label point mark"],
  ["Video effects", "Effects", { left: ["effects", "video"] }, "vignette grain letterbox film blur glow"],
  ["Logo", "Effects", { left: ["effects", "logo"] }, "watermark brand channel corner bug"],
  ["Subscribe animation", "Effects", { left: ["effects", "subscribe"] }, "cta call to action like bell subscribe button"],
  ["Transitions", "Transitions", { left: ["transitions"] }, "fade dissolve wipe slide cut between scenes"],
  ["Captions", "Captions", { left: ["captions"] }, "subtitles subs words text on screen font karaoke srt"],
  ["Filters", "Filters", { left: ["filters"] }, "look colour color grade lut tone black and white"],
  ["Graphics", "Graphics", { left: ["graphics"] }, "motion graphics map timeline diagram animation text animation infographic"],
  ["Scene settings", "Video › Basic", { insp: ["video", "basic"] }, "duration length title remove delete scene"],
  ["Picture: crop, fill and movement", "Video › Picture", { insp: ["video", "picture"] }, "crop zoom pan ken burns fit fill keyframes position scale"],
  ["Story and sources", "Video › Story", { insp: ["video", "story"] }, "source reference citation facts notes"],
  ["Tracks of a scene", "Video › Tracks", { insp: ["video", "tracks"] }, "split remove track picture narration music"],
  ["Voice settings", "Audio › Voice", { insp: ["audio", "voice"] }, "narration level volume loudness transcribe align"],
  ["Music settings", "Audio › Music", { insp: ["audio", "music"] }, "volume level loop fade ducking part of the track start"],
];

const PAGES = [
  ["Episode setup", "setup", "import script guide narration music episode start"],
  ["Case desk", "desk", "case facts people timeline candidates"],
  ["Research", "research", "sources facts web links citations"],
  ["Script", "script", "write text story narration draft"],
  ["Edit", "edit", "editor timeline"],
  ["Review & export", "review", "export render mp4 checks preflight review download"],
  ["Re-cut", "recut", "shorts vertical clips cut down"],
];

const ACTIONS = [
  ["Export video", "export", "render mp4 download make video publish"],
  ["Produce draft", "produce", "automatic guided production ai draft"],
  ["Undo", "undo", "back revert ctrl z"],
  ["Redo", "redo", "again ctrl shift z"],
  ["Split scene at playhead", "split", "cut razor divide"],
  ["Add a scene", "addScene", "new scene insert"],
  ["Import media", "importMedia", "upload add files photos videos"],
  ["Import a voice-over", "import:narration", "upload narration voice record"],
  ["Import music", "import:music", "upload song soundtrack"],
  ["Import a sound effect", "import:sfx", "upload sfx whoosh"],
  ["Ask the Director", "director", "ai assistant chat instruction plain english help me edit"],
  ["Full screen", "fullscreen", "fullscreen maximise maximize big preview theatre"],
  ["Video format (ratio)", "ratio", "aspect ratio 16:9 9:16 vertical tiktok shorts reels landscape portrait"],
  ["Media library", "mediaLibrary", "files rights license rename"],
  ["Your projects", "projects", "open switch project"],
  ["New project", "newProject", "create start"],
  ["Save backup", "backup", "download json save copy"],
  ["Home", "home", "start page dashboard"],
  ["How this workspace works", "help", "help guide tutorial how"],
  ["Settings and AI connection", "settings", "settings api key connect ai preferences"],
];

const norm = (s) => String(s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");

export function buildIndex({ scenes = [], assets = [], offsets = [], looks = [], transitions = [] } = {}) {
  const items = [];
  TOOLS.forEach(([label, where, go, words]) => items.push({ group: "Tools", label, where, go, words }));
  looks.forEach((l) => items.push({ group: "Tools", label: `${l.label} look`, where: "Filters", go: { left: ["filters"] }, words: `filter look ${l.id}` }));
  transitions
    .filter((t) => t.id !== "none")
    .forEach((t) => items.push({ group: "Tools", label: `${t.label} transition`, where: "Transitions", go: { left: ["transitions"] }, words: `transition ${t.id}` }));
  PAGES.forEach(([label, key, words]) => items.push({ group: "Pages", label, where: "Page", go: { page: key }, words }));
  ACTIONS.forEach(([label, action, words]) => items.push({ group: "Actions", label, where: "Action", go: { action }, words }));
  scenes.forEach((s, i) =>
    items.push({
      group: "Scenes",
      label: `${String(i + 1).padStart(2, "0")} ${s.title || "Scene"}`,
      where: s.chapter || "Scene",
      go: { scene: i, time: offsets[i] || 0 },
      words: `scene ${i + 1}`,
      text: s.narration || "",
    }),
  );
  assets.forEach((a) =>
    items.push({ group: "Media", label: a.name, where: a.kind === "audio" ? "Audio file" : a.kind === "video" ? "Video" : "Photo", go: { asset: a.id }, words: a.kind }),
  );
  return items;
}

// Score one item against the query words (0 = no match). Every word must be found.
function score(item, words) {
  const label = norm(item.label);
  const meta = norm(`${item.where} ${item.words || ""}`);
  const text = norm(item.text);
  let total = 0;
  for (const w of words) {
    let s = 0;
    if (label.startsWith(w)) s = 10;
    else if (new RegExp(`(^|[^a-z0-9])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(label)) s = 7;
    else if (label.includes(w)) s = 5;
    else if (new RegExp(`(^|[^a-z0-9])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(meta)) s = 4;
    else if (meta.includes(w)) s = 2;
    else if (w.length >= 3 && text.includes(w)) s = 1;
    if (!s) return 0;
    total += s;
  }
  return total;
}

// A short piece of the narration around the first match, so you see why a scene was found.
export function snippet(text, q, room = 70) {
  const t = String(text || "").replace(/\s+/g, " ").trim();
  const i = norm(t).indexOf(norm(q).trim().split(/\s+/)[0] || "\u0000");
  if (i < 0) return "";
  const a = Math.max(0, i - Math.floor(room / 3));
  return (a > 0 ? "…" : "") + t.slice(a, a + room).trim() + (a + room < t.length ? "…" : "");
}

export const GROUP_ORDER = ["Tools", "Actions", "Pages", "Scenes", "Media"];

export function search(items, query, limit = 40) {
  const words = norm(query).split(/[\s,]+/).filter(Boolean);
  if (!words.length) return [];
  return items
    .map((item, i) => ({ item, i, s: score(item, words) }))
    .filter((r) => r.s > 0)
    .sort((a, b) => b.s - a.s || GROUP_ORDER.indexOf(a.item.group) - GROUP_ORDER.indexOf(b.item.group) || a.i - b.i)
    .slice(0, limit)
    .map((r) => ({ ...r.item, snippet: r.item.text && !norm(r.item.label).includes(words[0]) ? snippet(r.item.text, query) : "" }));
}

// Shown before you type: the things people look for most.
export const POPULAR = ["Music", "Narration (voice-over)", "Sound effects", "Captions", "Transitions", "Filters", "Logo", "Picture: crop, fill and movement", "Export video", "Ask the Director"];
