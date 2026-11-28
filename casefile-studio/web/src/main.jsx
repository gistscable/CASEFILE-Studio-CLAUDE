import React, { useState, useEffect, useRef, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { nextTime, speechAt } from "./previewClock.js";
import { normaliseLayout, timelineHeight, fitEdit, rulerTicks, captionBlocks, zoomScroll, LIMITS, LAYOUT_DEFAULTS } from "./editLayout.js";
import CaseDesk from "./CaseDesk.jsx";
import Recut from "./Recut.jsx";
import CaptionStyles from "./CaptionStyles.jsx";
import Effects from "./Effects.jsx";
import ReplacePicker from "./ReplacePicker.jsx";
import Home, { HomeIcon } from "./Home.jsx";
import CtaOverlay from "./CtaOverlay.jsx";
import PictureLayer from "./PictureLayer.jsx";
import StickerLayer from "./StickerLayer.jsx";
import { makeTracker, grabFrame, simplifyPath, TRACK } from "./tracker.js";
import StickerDialog, { StickerGallery } from "./StickerDialog.jsx";
import { sortMedia } from "./mediaSort.js";
import StickerPanel from "./StickerPanel.jsx";
import MotionPanel from "./MotionPanel.jsx";
import MotionLayer from "./MotionLayer.jsx";
import { graphicAt, graphicsAt, normaliseMotion } from "./motion.js";
import SoundPanel from "./SoundPanel.jsx";
import { SfxPreview, SFX, schedule as sfxSchedule, normaliseSound, editItem as editSfx, decodeDuck } from "./sound.js";
import { MusicPreview, musicLayout, normaliseMusic, timelineTotal, approxDuck, MUSIC_DUCK_RATIO } from "./music.js";
import MusicPanel from "./MusicPanel.jsx";
import LiveRange from "./LiveRange.jsx";
import CropDialog from "./CropDialog.jsx";
import { cropOf, fitOf as pictureFit, normaliseKeyframes, cameraAt, cameraTransform } from "./picture.js";
import SearchPalette from "./SearchPalette.jsx";
import { buildIndex } from "./searchIndex.js";
import { AUDIO_ROLES, audioLists, audioRoleOf, roleBlock } from "./audioRoles.js";
import { normaliseStickers, newSticker, normaliseStickerKeys, stickerAt, stickerLabel } from "./stickers.js";
import { ctaEvents as findCtaEvents, ctaSpots as findCtaSpots, ctaSpotAlpha, ctaReady, normaliseCta } from "./cta.js";
import { normaliseWatermark, watermarkBox } from "./watermark.js";
import { LOOKS, TRANSITIONS, normaliseNameCards, effectiveLowerThirds, aspectOf, fitOf, FORMATS, FITS, lookOf, motionTransform, normaliseEffects, transitionId, transitionLength, transitionStyle, transitionUnder, lowerThirdAt, lowerThirdCss, letterboxBar } from "./effects.js";
import { captionAt, captionCss, normaliseStyle, sceneCaptions, chunks as captionChunks, textUnit } from "./captionStyle.js";
import {
  Sticker,
  Clapperboard,
  Search,
  FileText,
  ShieldCheck,
  Sparkles,
  Upload,
  Download,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Plus,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  Maximize2,
  Minimize2,
  Undo2,
  Redo2,
  Layers,
  FolderOpen,
  Settings2,
  Music2,
  AudioLines,
  Zap,
  AudioWaveform,
  Film,
  Image as ImageIcon,
  X,
  ArrowUp,
  ArrowDown,
  Trash2,
  Check,
  CheckCircle2,
  Clock3,
  Link2,
  ExternalLink,
  LockKeyhole,
  CircleHelp,
  GripVertical,
  Info,
  AlertTriangle,
  LoaderCircle,
  Send,
  Mic,
  Monitor,
  ZoomIn,
  ZoomOut,
  Scissors,
  Scan,
  BookOpen,
  FileJson,
  MessageSquareText,
  PanelRight,
  Circle,
  RefreshCw,
  Type,
  Captions,
  Palette,
  Shapes,
  ArrowLeftRight,
  WandSparkles,
  Eye,
  EyeOff,
  Menu,
  Images,
  PanelLeft,
  ArrowUpDown,
  ArrowLeft,
} from "lucide-react";
import "./styles.css";
import EpisodeSetup from "./EpisodeSetup.jsx";
import { rememberSetup, cachedSetups, forgetSetup } from "./SessionBackup.js";
import {
  keepWorkingFiles,
  clearWorkingFiles,
  workingFiles,
  restoreWorkingSession,
  protectAvailableServerFiles,
} from "./MediaSession.js";
import {
  UploadProgress,
  validateUpload,
  sendUploadRequest,
  uploadLimits,
} from "./Uploads.jsx";
import { ProductionModal, PreflightModal } from "./ProductionTools.jsx";
import "./capcut.css"; // v0.4.67 the CapCut-style interface, after every other stylesheet

function downloadProjectSnapshot(project, onBlocked) {
  const { undo, history, ...snapshot } = project;
  if (window.top !== window && onBlocked) {
    rememberSetup(project).catch(() => {});
    onBlocked({ kind: "setup", url: window.location.href });
    return;
  }
  snapshot._casefile_export = {
    version: "0.4.56",
    preview_origin: window.location.origin,
    exported_at: new Date().toISOString(),
    media_bytes_included: false,
  };
  const blob = new Blob([JSON.stringify(snapshot, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "casefile-project.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

const uid = () =>
  [...crypto.getRandomValues(new Uint8Array(8))]
    .map((n) => n.toString(16).padStart(2, "0"))
    .join("");
const tc = (seconds = 0, frames = false) => {
  let s = Math.max(0, Number(seconds) || 0);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s) % 60).padStart(2, "0")}${frames ? ":" + String(Math.floor((s % 1) * 24)).padStart(2, "0") : ""}`;
};
const wc = (text) => (text?.match(/\b[\w’'-]+\b/g) || []).length;
const bytes = (n) =>
  n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
const sum = (scenes) =>
  (scenes || []).reduce((n, s) => n + Number(s.duration || 0), 0);
const referencePattern = /\[\s*(S\d+(?:(?:\s*[,;]\s*|\s+)S?\d+)*)\s*\]/gi;
const APP_VERSION = "0.4.73";
const TRANS_LABEL = Object.fromEntries(
  [["none", "None"], ["dissolve", "Dissolve"], ["dip-black", "Dip to black"], ["dip-white", "Flash white"], ["slide-left", "Slide"], ["slide-up", "Slide up"], ["wipe-left", "Wipe"], ["zoom", "Zoom in"], ["circle", "Circle open"], ["pixelize", "Pixelate"], ["fade", "Fade in and out"]],
);
const clean = (s) => (s || "").replace(referencePattern, "").trim();
const scriptFromScenes = (scenes) =>
  scenes
    .map((s) => {
      const refs = [
        ...new Set([
          ...(s.source_ids || []),
          ...[...(s.narration || "").matchAll(referencePattern)].flatMap(
            (match) => (match[1].match(/\d+/g) || []).map((n) => "S" + n),
          ),
        ]),
      ];
      return (
        clean(s.narration) +
        (refs.length ? " " + refs.map((id) => `[${id}]`).join(" ") : "")
      ).trim();
    })
    .join("\n\n");
const elapsed = (date) => {
  const n = Math.round((Date.now() - new Date(date)) / 60000);
  return n < 1
    ? "Just now"
    : n < 60
      ? `${n}m ago`
      : new Date(date).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        });
};

let browserSession;
try {
  browserSession = sessionStorage.getItem("casefile-session");
  if (!browserSession) {
    browserSession = uid() + uid();
    sessionStorage.setItem("casefile-session", browserSession);
  }
} catch {
  browserSession = uid() + uid();
}
const preference = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {}
  },
};
// v0.4.59 the project fields the sound plan (and its preview) is made from
const PLAN_FIELDS = ["sound", "scenes", "motion", "cta", "episode"];
async function api(path, method = "GET", body, onUploadProgress) {
  if (onUploadProgress)
    return sendUploadRequest(
      path,
      method,
      body,
      browserSession,
      onUploadProgress,
    );
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      "X-Casefile-Session": browserSession,
      ...(body && !(body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
    },
    body:
      body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  });
  const type = response.headers.get("content-type") || "";
  const data = type.includes("json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const e = new Error(data?.detail || data || "Something went wrong.");
    e.status = response.status;
    throw e;
  }
  // v0.4.59 a save that moved chosen-scene music to rebuilt / split scenes (or found them gone) says so
  if (data && typeof data === "object" && data.music_follow) window.dispatchEvent(new CustomEvent("casefile-music-follow", { detail: data.music_follow }));
  return data;
}
function Button({ icon: Icon, children, kind = "", className = "", ...props }) {
  return (
    <button className={`btn ${kind} ${className}`} {...props}>
      {Icon && <Icon size={15} />}
      <span>{children}</span>
    </button>
  );
}
const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
// v0.4.51 "Undo: Move sticker (⌘Z)"
// v0.4.67 "Auto saved: 20:15:03" (with the date when it was not today), as CapCut's top bar
// v0.4.67 the Edit page's panels sit 6 px apart inside a 6 px margin (capcut.css); the splitters
// sit in the gaps
const GRID_PAD = 6;
function savedClock(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "";
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  return d.toDateString() === new Date().toDateString() ? `: ${time}` : `: ${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}
function historyLabel(project, which) {
  const list = project?.history?.[which] || [];
  const keys = which === "undo" ? (IS_MAC ? "⌘Z" : "Ctrl+Z") : IS_MAC ? "⇧⌘Z" : "Ctrl+Shift+Z";
  if (!list.length) return `${which === "undo" ? "Nothing to undo" : "Nothing to redo"} (${keys})`;
  return `${which === "undo" ? "Undo" : "Redo"}: ${list[list.length - 1]} (${keys})`;
}
function isTyping(el) {
  if (!el) return false;
  if (el.isContentEditable || el.tagName === "TEXTAREA") return true;
  return el.tagName === "INPUT" && !["range", "checkbox", "radio", "button", "submit", "color", "file"].includes((el.type || "").toLowerCase());
}
function IconButton({ icon: Icon, label, className = "", ...props }) {
  return (
    <button
      className={`icon-btn ${className}`}
      title={label}
      aria-label={label}
      {...props}
    >
      <Icon size={16} />
    </button>
  );
}
function Badge({ children, tone = "" }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function Toggle({ checked, onChange, label }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`toggle ${checked ? "on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}
function Empty({ icon: Icon = Layers, title, children, action }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={24} />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
function Modal({
  title,
  eyebrow,
  children,
  onClose,
  wide = false,
  className = "",
}) {
  useEffect(() => {
    const key = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`modal ${wide ? "wide" : ""} ${className}`}
      >
        <header className="modal-header">
          <div>
            {eyebrow && <div className="eyebrow">{eyebrow}</div>}
            <h2>{title}</h2>
          </div>
          <IconButton icon={X} label="Close dialog" onClick={onClose} />
        </header>
        {children}
      </section>
    </div>
  );
}
function Wave({ values = [], color = "#91b0ab" }) {
  if (!values.length) return null;
  return (
    <svg
      className="wave"
      viewBox={`0 0 ${values.length * 3} 30`}
      preserveAspectRatio="none"
      aria-label="Audio waveform"
    >
      {values.map((v, i) => (
        <line
          key={i}
          x1={i * 3 + 1}
          x2={i * 3 + 1}
          y1={15 - Math.max(0.6, v * 13)}
          y2={15 + Math.max(0.6, v * 13)}
          stroke={color}
          strokeWidth="1.7"
        />
      ))}
    </svg>
  );
}

function App() {
  const [project, setProject] = useState(null),
    [projectList, setProjectList] = useState([]),
    [config, setConfig] = useState({ connected: false });
  const [tab, setTab] = useState("edit"),
    // v0.4.67 CapCut layout: the left panel's icon tabs (Media, Audio, Text …) with a
    // sub-section each, and the right panel shows what is selected (Video, Audio)
    [leftTab, setLeftTab] = useState("media"),
    [leftSub, setLeftSub] = useState({ media: "scenes", audio: "music", text: "titles", effects: "video" }),
    [mediaQuery, setMediaQuery] = useState(""),
    [inspectorTab, setInspectorTab] = useState("video"),
    [videoSub, setVideoSub] = useState("basic"),
    [audioSub, setAudioSub] = useState("voice"),
    [menuOpen, setMenuOpen] = useState(false);
  const [modal, setModal] = useState(null),
    [selectedId, setSelectedId] = useState(null),
    [time, setTime] = useState(0),
    [playing, setPlaying] = useState(false),
    [muted, setMuted] = useState(false);
  const [layout, setLayoutState] = useState(() => normaliseLayout(preference.get("casefile-edit-layout"))),
    [gridHeight, setGridHeight] = useState(600),
    // v0.4.71 the grid's width and how tall the timeline's tracks are, to fit the screen
    [gridWidth, setGridWidth] = useState(() => (typeof window === "undefined" ? 1440 : window.innerWidth)),
    [tlNeed, setTlNeed] = useState(0),
    [laneWidth, setLaneWidth] = useState(800);
  const setLayout = (patch) =>
    setLayoutState((cur) => {
      const next = normaliseLayout({ ...cur, ...(typeof patch === "function" ? patch(cur) : patch) });
      preference.set("casefile-edit-layout", JSON.stringify(next));
      return next;
    });
  // v0.4.67 open a left-panel tab (and its sub-section), showing the panel if it was hidden
  const openLeft = (key, sub) => {
    setLeftTab(key);
    if (sub) setLeftSub((cur) => ({ ...cur, [key]: sub }));
    if (!layout.showLeft) setLayout({ showLeft: true });
  };
  const motionEditing = leftTab === "graphics" && layout.showLeft; // the graphic you edit shows in the preview
  const gridRef = useRef(null);
  const [home, setHome] = useState(true); // v0.4.33: the app opens on the start page
  const [zoom, setZoom] = useState(1),
    [jobs, setJobs] = useState([]),
    [busy, setBusy] = useState(false),
    [uploading, setUploading] = useState(false),
    [uploadProgress, setUploadProgress] = useState(null),
    [savedBeforeClear, setSavedBeforeClear] = useState(false),
    [backupStatus, setBackupStatus] = useState("pending"),
    [recoveredSetup, setRecoveredSetup] = useState(null),
    [downloadGate, setDownloadGate] = useState(null),
    [signoffOpen, setSignoffOpen] = useState(false),
    [exportFinal, setExportFinal] = useState(false),
    [saving, setSaving] = useState("saved"),
    [toast, setToast] = useState(null),
  [command, setCommand] = useState("");
  const [stickerId, setStickerId] = useState(null),
    [stickerTrack, setStickerTrack] = useState(null), // v0.4.72 { id, progress } while following, { id, done, note } after
    [stickerPick, setStickerPick] = useState(null), // v0.4.72 the sticker waiting for you to click what it follows
    [motionId, setMotionId] = useState(null),
    [motionStatus, setMotionStatus] = useState(""),
    [soundId, setSoundId] = useState(null), // v0.4.56 the selected sound effect
    [sfxPin, setSfxPin] = useState(null), // v0.4.60 where a sound picked in the library goes (double-click on the Sound FX lane)
    [soundIds, setSoundIds] = useState([]), // v0.4.57 every sound the current edit applies to (a whole graphic)
    [soundPlan, setSoundPlan] = useState(null),
    [soundPlanError, setSoundPlanError] = useState(""),
    [planSaved, setPlanSaved] = useState(0), // v0.4.59 bumped when a save that changes the sound plan is stored
    [sfxMute, setSfxMute] = useState(false),
    [sfxSolo, setSfxSolo] = useState(false),
    [sfxDuck, setSfxDuck] = useState("none"), // v0.4.57: "none" | "working" | "ready" (the preview ducks like the export)
    [stickerDialog, setStickerDialog] = useState(false),
    [cropId, setCropId] = useState(null);
  const [selectedTrack, setSelectedTrack] = useState(null),
    [mediaId, setMediaId] = useState(null),
    [frameSize, setFrameSize] = useState({ width: 640, height: 360 }),
    [fullMode, setFullMode] = useState(""),
    [searchOpen, setSearchOpen] = useState(false), // v0.4.68
    [hoverLook, setHoverLook] = useState(null), // v0.4.69 the look you point at in Filters
    [mediaSort, setMediaSort] = useState("timeline"),
    [unusedOnly, setUnusedOnly] = useState(false),
    [focus, setFocus] = useState(null), // v0.4.70 what the right panel shows: a sticker, graphic, sound, caption or the subscribe clip (null: the scene)
    [captionSub, setCaptionSub] = useState("words"),
    [wide, setWide] = useState(() => typeof window === "undefined" || !window.matchMedia || window.matchMedia("(min-width: 1071px)").matches);
  useEffect(() => {
    // v0.4.70 the right panel sits beside the player only above 1070 px (below, it stacks)
    const mq = window.matchMedia?.("(min-width: 1071px)");
    if (!mq) return;
    const on = () => setWide(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  // v0.4.69 a look you were trying never sticks to the player when you leave Filters
  useEffect(() => setHoverLook(null), [leftTab, project?.id]);
  useEffect(() => setFocus(null), [selectedTrack, project?.id, tab]); // v0.4.70 a clip or scene you pick shows the scene again
  const historyRef = useRef(() => {}),
    historyBusy = useRef(false),
    gesture = useRef(false);
  const pending = useRef({}),
    saveTimer = useRef(null),
    savePromise = useRef(null),
    projectRef = useRef(null),
    toastTimer = useRef(null),
    watched = useRef(new Set()),
    initialPoll = useRef(true);
  const audioRef = useRef(null),
    videoRef = useRef(null),
    trackRef = useRef(null), // v0.4.72 the follow in progress ({ stop }), so the preview seeks exactly
    screenRef = useRef(null),
    fileRef = useRef(null),
    audioFileRef = useRef(null),
    audioRoleRef = useRef(null),
    timelineRef = useRef(null),
    playingRef = useRef(false),
    timeRef = useRef(0),
    dragId = useRef(null),
    messagesRef = useRef(null);
  projectRef.current = project;
  playingRef.current = playing;
  timeRef.current = time;
  const scenes = project?.scenes || [],
    assets = project?.assets || [],
    duration = sum(scenes),
    selected = scenes.find((s) => s.id === selectedId) || scenes[0];
  const offsets = useMemo(() => {
    let t = 0;
    return scenes.map((s) => {
      const n = t;
      t += s.duration;
      return n;
    });
  }, [scenes]);
  // v0.4.49: every place the subscribe animation can show; the ones that show.
  const ctaSpots = useMemo(
    () => (project ? findCtaSpots(project, offsets, (s) => sceneCaptions(s, clean)) : []),
    [project?.cta, project?.assets, scenes, offsets],
  );
  const ctaEvents = useMemo(() => ctaSpots.filter((r) => r.shown).map((r) => [r.start, r.end, r]), [ctaSpots]);
  const nameCards = useMemo(() => effectiveLowerThirds(project), [project?.name_cards, scenes]);
  // v0.4.56 Sound design: the plan from the server (re-read after an edit that can move a sound),
  // played in the preview with WebAudio on the preview clock.
  const soundOn = !!project?.sound?.enabled;
  // v0.4.67 the overlay track (graphics, stickers, the subscribe animation) shows when it has something
  const overlayGraphics = project ? normaliseMotion(project.motion).items : [];
  const overlayStickers = project ? normaliseStickers(project.stickers, project.assets) : [];
  const overlayOn = !!(overlayGraphics.length || overlayStickers.length || ctaEvents.length);
  // v0.4.71 what the Edit grid draws on this screen (the saved layout is kept as you left it)
  const fit = fitEdit(layout, { width: gridWidth, gridHeight, need: tlNeed, pad: GRID_PAD });
  const sfxPreview = useRef(null);
  if (!sfxPreview.current) sfxPreview.current = new SfxPreview();
  // v0.4.58 Levels while a slider moves (heard at once, saved when you let go): {narration, music, master}
  const live = useRef({});
  // the plan depends on every sound setting except the effects volume (applied live, see below)
  // a saved project comes back with new arrays: the plan and the ducking follow what the scenes say, not the array
  const scenesSig = useMemo(() => JSON.stringify(scenes), [scenes]);
  const soundKey = useMemo(() => {
    const { master, ...rest } = project?.sound || {};
    return JSON.stringify(rest);
  }, [project?.sound]);
  const musicPreview = useRef(null);
  if (!musicPreview.current) musicPreview.current = new MusicPreview(sfxPreview.current);
  useEffect(() => {
    if (!project?.id || !soundOn) return setSoundPlan(null);
    let live = true;
    const id = setTimeout(() => {
      // v0.4.59 the plan is read from the saved project: while an edit to it is still waiting to be
      // saved the server would answer with the plan before the edit (a sound's new volume, a move…)
      // and the preview kept it. The save that stores the edit asks again (planSaved).
      if (PLAN_FIELDS.some((k) => k in pending.current)) return;
      fetch(`/api/projects/${project.id}/sound/plan`, { credentials: "same-origin" })
        .then((r) => (r.ok ? r.json() : r.json().then((d) => Promise.reject(new Error(d.detail || "The sound plan could not be read.")))))
        .then((d) => { if (live) { setSoundPlan(d); setSoundPlanError(""); } })
        .catch((e) => live && setSoundPlanError(e.message || String(e)));
    }, 350);
    return () => { live = false; clearTimeout(id); };
  }, [project?.id, soundOn, scenesSig, project?.motion, soundKey, project?.cta, project?.episode?.timings, planSaved]);
  const sfxList = useMemo(() => (soundPlan ? sfxSchedule(soundPlan.items) : []), [soundPlan]);
  // v0.4.58 The effects volume is a gain on the preview's output (a ramp, in real time): the plan's
  // levels were made with the master it reports, so only the ratio is applied — no new plan.
  const sfxMaster = normaliseSound(project?.sound).master;
  useEffect(() => {
    sfxPreview.current.setMaster((live.current.master ?? sfxMaster) / (soundPlan?.settings?.master || 1));
  }, [sfxMaster, soundPlan]);
  useEffect(() => { sfxPreview.current.override.clear(); }, [soundPlan]); // the new plan has the saved levels
  useEffect(() => {
    if (sfxList.length && project?.id) sfxPreview.current.preload(project.id, sfxList);
  }, [sfxList]);
  useEffect(() => {
    sfxPreview.current.tick(project?.id, sfxList, time, playing && soundOn && !sfxMute && !muted);
  }, [time, playing, sfxList, soundOn, sfxMute, muted]);
  useEffect(() => () => { sfxPreview.current?.stop(); sfxPreview.current?.stopAudition(); musicPreview.current?.stop(); }, []);
  // QA only: an automated check that defines window.__casefileQA beforehand can read the players
  useEffect(() => { if (window.__casefileQA) Object.assign(window.__casefileQA, { sfx: sfxPreview.current, music: musicPreview.current }); }, []);
  // v0.4.57 The export's ducking, for the preview: the server runs the export's own compressor on
  // the export's own voice bus (made once in the background per narration/timeline/level, cached).
  const sfxDuckOn = soundOn && normaliseSound(project?.sound).duck;
  // v0.4.58 and the music's (the export's music compressor), made in the same background pass.
  // While a new curve is made (after a narration level change) the last one is used, moved by the
  // level change (approxDuck) — playback, seeking and the sliders never wait for it.
  const musicDuckOn = !!project?.music_id && normaliseMusic(project?.music).duck;
  const duckBase = useRef(null); // {fx, music, nv}: the last exact curves and the narration level they were made at
  const applyDuck = () => {
    const base = duckBase.current;
    if (!base) {
      sfxPreview.current.setDuck(null);
      musicPreview.current.setDuck(null);
      return;
    }
    const nv = live.current.narration ?? projectRef.current?.narration_volume ?? 1;
    const ratio = base.nv > 0 ? nv / base.nv : 1;
    sfxPreview.current.setDuck(sfxDuckOn ? approxDuck(base.fx, ratio, SFX.duck.ratio) : null);
    musicPreview.current.setDuck(musicDuckOn ? approxDuck(base.music, ratio, MUSIC_DUCK_RATIO) : null);
    setSfxDuck(Math.abs(ratio - 1) > 1e-3 ? "approx" : "ready");
  };
  useEffect(() => {
    if (!project?.id || !(sfxDuckOn || musicDuckOn) || !project?.narration_id) {
      duckBase.current = null;
      applyDuck();
      setSfxDuck("none");
      return;
    }
    let live_ = true, timer = null, tries = 0;
    const nvAsked = project?.narration_volume ?? 1;
    if (duckBase.current) applyDuck(); // the toggles changed: same curves
    const ask = () => {
      fetch(`/api/projects/${project.id}/sound/duck`, { credentials: "same-origin" })
        .then((r) => (r.ok ? r.json() : { status: "none" }))
        .then((d) => {
          if (!live_) return;
          if (d.status === "working" && tries++ < 300) { if (!duckBase.current) setSfxDuck("working"); timer = setTimeout(ask, 2000); return; }
          const fx = decodeDuck(d), mus = decodeDuck(d.music ? { ...d, gain: d.music } : null);
          duckBase.current = fx ? { fx, music: mus, nv: nvAsked } : null;
          applyDuck();
          if (!fx) setSfxDuck("none");
        })
        .catch(() => live_ && setSfxDuck("none"));
    };
    timer = setTimeout(ask, 600);
    return () => { live_ = false; clearTimeout(timer); };
  }, [project?.id, sfxDuckOn, musicDuckOn, project?.music_id, project?.narration_id, project?.narration_volume, scenesSig, project?.episode?.guide, project?.assets?.length]);
  /** v0.4.58 The narration level while its slider moves: the preview's gain now, the ducking moved with it. */
  const liveNarration = (v) => {
    live.current.narration = v;
    sfxPreview.current.narration(audioRef.current, v);
    applyDuck();
  };
  const commitNarration = (v) => {
    queueSave({ narration_volume: v });
    setTimeout(() => { if (live.current.narration === v) delete live.current.narration; }, 0);
  };
  const liveMusicVolume = (v) => {
    live.current.music = v;
    musicPreview.current.setVolume(Math.min(0.5, v));
  };
  const commitMusicVolume = (v) => {
    queueSave({ music_volume: v });
    setTimeout(() => { if (live.current.music === v) delete live.current.music; }, 0);
  };
  const liveMaster = (v) => {
    if (v === null) { delete live.current.master; return; } // saved: the project's value is used again
    live.current.master = v;
    sfxPreview.current.setMaster(v / (soundPlan?.settings?.master || 1));
  };
  // the chosen left-panel tab is always in view (nine icon tabs do not fit a narrow panel)
  useEffect(() => {
    document.querySelector(".cc-tabs button.active")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [leftTab]);
  const clockRef = useRef({ scenes: [], offsets: [] });
  clockRef.current = { scenes, offsets };
  const activeIndex = Math.max(
    0,
    scenes.findIndex((s, i) => time < offsets[i] + s.duration),
  );
  const activeScene = scenes[activeIndex] || selected;
  const visual = assets.find((a) => a.id === activeScene?.asset_id),
    voice = assets.find((a) => a.id === project?.narration_id),
    music = assets.find((a) => a.id === project?.music_id);
  // v0.4.58 Background music in the preview: the export's own layout (where, which part, loops and
  // their crossfades, fades), streamed and mixed with WebAudio; the volume is a real-time gain.
  const musicLay = useMemo(
    () => (music ? musicLayout(project?.music, +music.duration || 0, timelineTotal(scenes), scenes) : null),
    [project?.music, music?.id, music?.duration, scenes],
  );
  useEffect(() => { musicPreview.current.setSource(music?.url || null); }, [music?.url]);
  useEffect(() => { musicPreview.current.setLayout(musicLay); }, [musicLay]);
  useEffect(() => { musicPreview.current.setVolume(Math.min(0.5, live.current.music ?? project?.music_volume ?? 0)); }, [project?.music_volume]);
  useEffect(() => {
    musicPreview.current.tick(time, playing, muted || (sfxSolo && soundOn));
  }, [time, playing, muted, sfxSolo, soundOn, musicLay]);
  const activeJob = jobs.find((j) => ["running", "queued"].includes(j.status));
  const locked = busy || !!activeJob;
  const notify = (message, tone = "success") => {
    setToast({ message, tone });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 6500);
  };
  useEffect(() => {
    const f = (e) => {
      const { followed = [], lost = [] } = e.detail || {};
      if (lost.length) notify(`Background music: ${lost.length === 1 ? "a chosen scene was" : `${lost.length} chosen scenes were`} removed (${lost.slice(0, 3).join(", ")}${lost.length > 3 ? "…" : ""}) — its music no longer plays. See the Music panel.`, "warning");
      else if (followed.length) notify(`Background music follows the edited scenes (${followed.length} new scene${followed.length > 1 ? "s" : ""} kept on music).`);
    };
    window.addEventListener("casefile-music-follow", f);
    return () => window.removeEventListener("casefile-music-follow", f);
  }, []);
  const report = (e) => {
    if (e.status === 412) setModal("settings");
    notify(e.message || String(e), "error");
  };
  const acceptProject = (p) => {
    rememberSetup(p)
      .then(setBackupStatus)
      .catch(() => setBackupStatus("unavailable"));
    setProject(p);
    preference.set("casefile-project", p.id);
  };

  useEffect(() => {
    (async () => {
      try {
        const saved = await cachedSetups().catch(() => []);
        api("/api/browser-session", "POST", {
          origin: window.location.origin,
          version: "0.4.56",
          snapshot: saved[0]?.project || null,
        }).catch(() => {});
        const b = await api("/api/bootstrap");
        setProjectList(b.projects);
        setConfig(b.config);
        const last = preference.get("casefile-project");
        const requested = new URLSearchParams(window.location.search).get(
          "project",
        );
        if (requested) setHome(false); // a link straight to a project skips the start page
        const id =
          b.projects.find((p) => p.id === requested)?.id ||
          b.projects.find((p) => p.id === last && !p.is_demo)?.id ||
          b.projects.find((p) => p.has_episode)?.id ||
          b.projects.find((p) => p.is_demo)?.id ||
          b.projects[0]?.id;
        if (id) {
          let p = await api("/api/projects/" + id);
          const cached =
            saved.find((entry) => entry.id === last) ||
            saved.find((entry) => entry.id === id);
          if (cached) {
            const files = await workingFiles(cached.id).catch(() => []);
            if (
              cached.id !== p.id ||
              (cached.project.updated_at || "") > (p.updated_at || "") ||
              files.length
            ) {
              const recovered = await restoreWorkingSession(
                cached.project,
                api,
                (progress) => setUploadProgress(progress),
              ).catch((error) => {
                console.warn("Working-session recovery:", error.message);
                return null;
              });
              if (recovered && !recovered.missing) p = recovered.project;
              else if (
                cached.id !== p.id ||
                (cached.project.updated_at || "") > (p.updated_at || "")
              )
                setRecoveredSetup(cached);
            }
          }
          acceptProject(p);
          if (p.episode || p.mode === "narration") setTab("setup");
          setSelectedId(p.scenes[0]?.id);
        }
      } catch (e) {
        const saved = await cachedSetups().catch(() => []);
        if (saved[0]) setRecoveredSetup(saved[0]);
        report(e);
      }
    })();
    return () => {
      clearTimeout(saveTimer.current);
      clearTimeout(toastTimer.current);
    };
  }, []);
  useEffect(() => {
    if (!project?.id) return;
    if (
      recoveredSetup?.project?.id === project.id &&
      (recoveredSetup.project.assets?.length || 0) >
        (project.assets?.length || 0)
    )
      return;
    const timer = setTimeout(
      () =>
        rememberSetup(project)
          .then((status) => {
            setBackupStatus(status);
            if (status !== "newer-saved-copy")
              api("/api/browser-session", "POST", {
                origin: window.location.origin,
                version: "0.4.56",
                snapshot: project,
              }).catch(() => {});
          })
          .catch(() => setBackupStatus("unavailable")),
      350,
    );
    return () => clearTimeout(timer);
  }, [project, recoveredSetup]);

  useEffect(() => {
    if (project?.id) protectAvailableServerFiles(project).catch(() => {});
  }, [project?.id, project?.assets?.map((asset) => asset.id).join(",")]);

  useEffect(() => {
    if (!project?.id) return;
    initialPoll.current = true;
    watched.current = new Set();
    let stopped = false;
    const poll = async () => {
      try {
        const list = await api(`/api/projects/${project.id}/jobs`);
        if (stopped) return;
        setJobs(list);
        if (initialPoll.current) {
          list
            .filter((j) => ["running", "queued"].includes(j.status))
            .forEach((j) => watched.current.add(j.id));
          initialPoll.current = false;
        }
        for (const job of list) {
          if (
            watched.current.has(job.id) &&
            !["running", "queued"].includes(job.status)
          ) {
            watched.current.delete(job.id);
            if (job.status === "done") {
              const p = await api(`/api/projects/${project.id}`);
              if (!stopped) {
                setProject((cur) =>
                  cur?.id === p.id ? { ...p, ...pending.current } : cur,
                );
                if (job.kind === "render") {
                  // v0.4.55: say when something was left out of the video
                  const warned = (p.exports?.[0]?.warnings || []).length;
                  notify(
                    warned
                      ? `Your video export is ready, but ${warned === 1 ? "1 thing was" : `${warned} things were`} left out. See the warnings under the export in Review.`
                      : "Your video export is ready to download.",
                    warned ? "error" : undefined,
                  );
                }
                else if (job.kind === "production")
                  notify(
                    (job.result?.message || "Production stage saved.").slice(
                      0,
                      240,
                    ),
                    job.result?.outcome === "complete" ? "success" : "info",
                  );
                else
                  notify("Operation complete. Your project has been updated.");
              }
            } else if (job.status === "error") notify(job.message, "error");
            else notify(job.message, "info");
          }
        }
      } catch (e) {
        if (!stopped) console.warn("Job status unavailable");
      }
    };
    poll();
    const timer = setInterval(poll, 1600);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [project?.id]);
  // v0.4.68 Search opens with Ctrl+K / ⌘K on every page
  useEffect(() => {
    const k = (e) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  // v0.4.68 the player in fullscreen ("native") or filling the window ("window", when fullscreen is blocked)
  useEffect(() => {
    const sync = () => {
      const el = document.fullscreenElement || document.webkitFullscreenElement;
      setFullMode((m) => (el && el === screenRef.current ? "native" : m === "native" ? "" : m));
    };
    document.addEventListener("fullscreenchange", sync);
    document.addEventListener("webkitfullscreenchange", sync);
    return () => {
      document.removeEventListener("fullscreenchange", sync);
      document.removeEventListener("webkitfullscreenchange", sync);
    };
  }, []);
  useEffect(() => {
    if (fullMode !== "window") return;
    const esc = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setFullMode("");
      }
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [fullMode]);
  useEffect(() => {
    if (tab !== "edit" && fullMode === "window") setFullMode("");
  }, [tab]);
  useEffect(() => {
    if (!screenRef.current || tab !== "edit") return;
    const r = project?.aspect === "9:16" ? 9 / 16 : 16 / 9; // width / height
    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      const full = document.fullscreenElement === entries[0].target || document.webkitFullscreenElement === entries[0].target || entries[0].target.classList.contains("full-window");
      let w = full ? Math.min(width, height * r) : Math.min(width - 40, (height - 12) * r);
      setFrameSize({
        width: Math.max(r < 1 ? 90 : 180, w),
        height: Math.max(101, w / r),
      });
    });
    observer.observe(screenRef.current);
    return () => observer.disconnect();
  }, [tab, project?.id, project?.aspect]);
  useEffect(() => {
    if (tab !== "edit") return;
    const fit = () => {
      const g = gridRef.current;
      if (g) {
        setGridHeight(Math.max(420, window.innerHeight - g.getBoundingClientRect().top));
        setGridWidth(g.clientWidth || window.innerWidth);
      }
      const t = timelineRef.current;
      if (t) setLaneWidth(t.clientWidth || 800);
      // v0.4.71 the tracks' own height (tool row + ruler + each track + room for the scrollbar)
      const sec = g?.querySelector("section.timeline");
      const lanes = sec?.querySelector(".timeline-lanes");
      const heads = lanes?.querySelector(".track-labels");
      if (sec && lanes && heads) {
        const top = lanes.getBoundingClientRect().top - sec.getBoundingClientRect().top;
        const rows = [...heads.children].reduce((n, c) => n + c.getBoundingClientRect().height, 0);
        if (rows > 0) setTlNeed(Math.ceil(top + rows + 14));
      }
    };
    fit();
    const ro = new ResizeObserver(fit);
    if (timelineRef.current) ro.observe(timelineRef.current);
    if (gridRef.current) ro.observe(gridRef.current);
    window.addEventListener("resize", fit);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, [tab, project?.id, layout.compact, overlayOn, soundOn]);
  // Keep the playhead in view while playing (CapCut follows it the same way).
  useEffect(() => {
    const el = timelineRef.current;
    if (!el || !playing || !duration) return;
    const x = (time / duration) * el.scrollWidth;
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = Math.max(0, x - 60);
  }, [time, playing]);
  useEffect(() => {
    if (messagesRef.current)
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [project?.messages, layout.director]);
  useEffect(() => {
    const f = (e) => {
      // v0.4.51: ⌘Z / Ctrl+Z undo, ⇧⌘Z / Ctrl+Shift+Z / Ctrl+Y redo — except while typing,
      // where the text box keeps its own undo. After clicking a button or a slider it works.
      const k = e.key.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && !e.altKey && (k === "z" || (k === "y" && e.ctrlKey && !e.metaKey))) {
        if (isTyping(document.activeElement)) return;
        e.preventDefault();
        if (!e.repeat) historyRef.current(k === "y" || e.shiftKey ? "redo" : "undo");
        return;
      }
      if (
        ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(
          document.activeElement?.tagName,
        )
      )
        return;
      if (e.code === "Space" && tab === "edit") {
        e.preventDefault();
        setPlaying((v) => !v);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        flushSave().catch(report);
      }
    };
    window.addEventListener("keydown", f);
    return () => window.removeEventListener("keydown", f);
  }, [tab]);
  useEffect(() => {
    if (!playing) return;
    let id,
      last = performance.now();
    const tick = (now) => {
      const dt = Math.min(0.15, (now - last) / 1000);
      last = now;
      // v0.4.19: while the narration is speaking it is the master clock, so the
      // recording plays continuously and the picture follows it (no re-seeks).
      const a = audioRef.current;
      const snapshot = a
        ? {
            paused: a.paused,
            seeking: a.seeking,
            ready: a.readyState >= 2,
            currentTime: a.currentTime,
          }
        : null;
      setTime((t) => {
        const n = nextTime(
          clockRef.current.scenes,
          clockRef.current.offsets,
          t,
          dt,
          snapshot,
        );
        if (n >= duration) {
          setPlaying(false);
          return 0;
        }
        return n;
      });
      id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [playing, duration]);
  useEffect(() => {
    if (playing && activeScene) setSelectedId(activeScene.id);
  }, [activeScene?.id, playing]);
  useEffect(() => {
    const local = time - (offsets[activeIndex] || 0),
      source = (activeScene?.audio_start || 0) + local;
    const a = audioRef.current,
      v = videoRef.current;
    const isBreak = !!activeScene?.insert_audio;
    if (a) {
      a.muted = muted || (sfxSolo && soundOn);
      sfxPreview.current.narration(a, live.current.narration ?? project?.narration_volume ?? 1); // v0.4.57: the narration level
      // Audio breaks (Mode O) pause the narration; it resumes at the same word.
      const inSpeech =
        speechAt(activeScene, offsets[activeIndex] || 0, time) !== null &&
        source < (voice?.duration || Infinity);
      // Re-align only when genuinely out of place (a seek, a scene jump, or the
      // start of play). While playing, the clock follows the audio, so normal
      // playback never triggers this and the recording is never interrupted.
      if (
        inSpeech &&
        !a.seeking &&
        Math.abs(a.currentTime - source) > (playing ? 0.5 : 0.3) &&
        Number.isFinite(source)
      )
        a.currentTime = Math.min(source, voice?.duration || source);
      if (playing && inSpeech) a.play().catch(() => {});
      else a.pause();
    }
    if (v) {
      // Source audio is muted, except a producer-cleared audio break.
      v.muted = muted || !isBreak || (sfxSolo && soundOn);
      v.volume = 1;
      const trimStart = activeScene?.trim_start || 0;
      const sceneDur = activeScene?.duration || 0;
      // Use the cue's original selected crop end when stored on the scene
      // (gap scenes inherit it from their matched cue), so preview loops
      // within the exact crop, not the gap duration or full source file.
      const sourceCropEnd = activeScene?.source_crop_end;
      const cropOut = sourceCropEnd
        ? Math.min(sourceCropEnd, v.duration || Infinity)
        : Math.min(trimStart + sceneDur, v.duration || Infinity);
      const cropDur = cropOut - trimStart;
      if (cropDur > 0) {
        // Loop the selected crop within the scene: wrap playback position
        // within the crop boundaries (trim_start to crop_out), not the whole
        // source file duration. Trim the last repetition at the scene end.
        const expected = trimStart + (local % cropDur);
        // Tolerate more drift while playing so picture re-seeks stay rare;
        // during an audio break the clip's own sound must not be interrupted.
        const slack = trackRef.current ? 0.01 : playing ? (isBreak ? 0.6 : 0.45) : 0.3;
        if (
          Number.isFinite(expected) &&
          !v.seeking &&
          Math.abs(v.currentTime - expected) > slack
        )
          v.currentTime = expected;
      }
      if (playing) v.play().catch(() => {});
      else v.pause();
    }
  }, [
    time,
    playing,
    muted,
    activeScene?.id,
    voice?.id,
    tab,
    sfxSolo,
    soundOn,
  ]);

  function queueSave(fields) {
    if (activeJob && activeJob.kind !== "render") {
      notify(
        "Wait for the current AI operation to finish before editing this project.",
        "info",
      );
      return;
    }
    setProject((cur) => ({
      ...cur,
      ...fields,
      ...(fields.script !== undefined
        ? { script_dirty: !fields.scenes, script_approved_hash: null }
        : {}),
    }));
    pending.current = { ...pending.current, ...fields };
    setSaving("pending");
    clearTimeout(saveTimer.current);
    if (gesture.current) return; // still dragging: saved when the drag ends
    saveTimer.current = setTimeout(() => flushSave().catch(report), 650);
  }
  async function flushSave() {
    clearTimeout(saveTimer.current);
    if (savePromise.current) await savePromise.current;
    if (!Object.keys(pending.current).length) return projectRef.current;
    const fields = pending.current,
      id = projectRef.current.id;
    pending.current = {};
    setSaving("saving");
    const task = (async () => {
      try {
        const p = await api("/api/projects/" + id, "PATCH", fields);
        if (projectRef.current?.id === id)
          setProject({ ...p, ...pending.current });
        if (PLAN_FIELDS.some((k) => k in fields)) setPlanSaved((n) => n + 1);
        setSaving(Object.keys(pending.current).length ? "pending" : "saved");
        return p;
      } catch (e) {
        pending.current = { ...fields, ...pending.current };
        setSaving("error");
        throw e;
      }
    })();
    savePromise.current = task;
    try {
      return await task;
    } finally {
      savePromise.current = null;
    }
  }
  async function openProject(id, opts = {}) {
    try {
      if (!opts.stay) setHome(false);
      await flushSave();
      setPlaying(false);
      const p = await api("/api/projects/" + id);
      pending.current = {};
      acceptProject(p);
      setSelectedId(p.scenes[0]?.id);
      setTime(0);
      setJobs([]);
      setModal(null);
      setTab(
        p.episode || p.mode === "narration"
          ? "setup"
          : p.scenes.length
            ? "edit"
            : p.mode === "topic"
              ? "research"
              : p.mode === "script"
                ? "script"
                : "edit",
      );
    } catch (e) {
      report(e);
    }
  }
  async function deleteProject(p) {
    try {
      const size = await api(`/api/projects/${p.id}/storage`);
      const mb = Math.round(size.total / 1048576);
      const typed = window.prompt(
        `Delete "${p.title}"?\n\nThis removes the project and all its footage, renders, re-cuts and Case desk documents from this computer (about ${mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : mb + " MB"}). It cannot be undone. Download any video you still need first.\n\nType the project title to confirm:`,
      );
      if (typed === null) return false;
      const r = await api(`/api/projects/${p.id}`, "DELETE", {
        confirm_title: typed,
      });
      setProjectList(r.projects);
      const freed = Math.round(r.freed / 1048576);
      notify(`Deleted "${p.title}". ${freed >= 1024 ? (freed / 1024).toFixed(1) + " GB" : freed + " MB"} freed.`);
      if (p.id === project.id) {
        const next = r.projects[0];
        if (next) await openProject(next.id, { stay: home });
        else window.location.assign("/");
      }
      return true;
    } catch (e) {
      report(e);
      return false;
    }
  }
  async function refreshProjects() {
    try {
      const b = await api("/api/bootstrap");
      setProjectList(b.projects);
    } catch (e) {
      report(e);
    }
  }
  async function startOperation(path) {
    if (locked) return;
    setBusy(true);
    setPlaying(false);
    try {
      await flushSave();
      const result = await api(path, "POST", {});
      if (result.job_id) {
        watched.current.add(result.job_id);
        const list = await api(`/api/projects/${project.id}/jobs`);
        setJobs(list);
        notify("Operation started. You can follow its progress below.", "info");
      }
      return result;
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function doAssemble() {
    if (locked) return;
    setBusy(true);
    try {
      await flushSave();
      const p = await api(`/api/projects/${project.id}/assemble`, "POST", {});
      acceptProject(p);
      setSelectedId(p.scenes[0]?.id);
      setTime(0);
      setTab("edit");
      notify(
        `Built ${p.scenes.length} editable scenes. Check visuals and timing.`,
      );
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function uploadFiles(files, audioRole = null) {
    if (!files?.length) return;
    const before = new Set((project.assets || []).map((a) => a.id));
    setUploading(true);
    try {
      validateUpload(files);
      setUploadProgress({
        phase: "uploading",
        loaded: 0,
        total: 0,
        label: `${files.length} selected file(s)`,
      });
      await flushSave();
      const form = new FormData();
      [...files].forEach((f) => form.append("files", f));
      if (audioRole) form.append("audio_role", audioRole);
      const p = await api(
        `/api/projects/${project.id}/upload`,
        "POST",
        form,
        (progress) => setUploadProgress((old) => ({ ...old, ...progress })),
      );
      await keepWorkingFiles(
        project.id,
        [...files].filter((file) => !/\.(md|txt|json|srt)$/i.test(file.name)),
        "auto",
      ).catch(() =>
        notify(
          "Browser could not keep a local working-file recovery copy. Keep your originals.",
          "info",
        ),
      );
      acceptProject(p);
      if ([...files].some((f) => /\.(txt|md)$/i.test(f.name))) setTab("script");
      const added = p.assets.filter((a) => !before.has(a.id));
      const field = audioRole === "narration" ? "narration_id" : audioRole === "music" ? "music_id" : null;
      if (field && !p[field] && added[0]) {
        // v0.4.68 the first voice-over / music you import goes straight on its track
        queueSave({ [field]: added[0].id });
        notify(`${added[0].name} is your ${audioRole} now.`);
      } else if (audioRole) {
        notify(`${files.length} file${files.length > 1 ? "s" : ""} added to ${audioRole === "sfx" ? "your sound effects" : audioRole === "music" ? "your music" : "your narration"}.`);
      } else {
        const loose = added.filter((a) => a.kind === "audio").length;
        notify(`${files.length} file${files.length > 1 ? "s" : ""} imported.${loose ? " Sort the audio in the Audio tab: narration, music or sound effects." : ""}`);
      }
    } catch (e) {
      setUploadProgress((old) => (old ? { ...old, phase: "error" } : null));
      report(e);
      try {
        setProject(await api("/api/projects/" + project.id));
      } catch {}
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
      if (audioFileRef.current) audioFileRef.current.value = "";
    }
  }
  function importAudio(role) {
    // v0.4.68 import straight into one kind of audio
    audioRoleRef.current = role;
    audioFileRef.current?.click();
  }
  async function setAudioRole(a, role) {
    const why = roleBlock(a, role, project);
    if (why) return notify(why, "info");
    try {
      await flushSave();
      acceptProject(await api(`/api/projects/${project.id}/assets/${a.id}`, "PATCH", { audio_role: role }));
      notify(role ? `${a.name} moved to ${role === "sfx" ? "sound effects" : role}.` : `${a.name} is not sorted now.`);
    } catch (e) {
      report(e);
    }
  }
  function selectScene(scene, index) {
    setSelectedId(scene.id);
    setTime(offsets[index] || 0);
    setPlaying(false);
  }
  function selectVisualScene(scene, index) {
    selectScene(scene, index);
    setSelectedTrack({ kind: "visual", sceneId: scene.id });
    setInspectorTab("video"); // v0.4.67 the right panel follows what you click, as in CapCut
  }
  // v0.4.49 stickers
  // v0.4.70 CapCut's right panel: what you select (a sticker, graphic, sound, caption or the subscribe
  // clip) shows its settings on the right; the left tab keeps its library. Where the right panel is
  // hidden or stacked (≤ 1070 px), the left tab opens the settings as before.
  const dock = !!(layout.showRight && wide);
  function focusRight(kind, extra = {}) {
    if (!dock) {
      const left = { sticker: ["stickers", "placed"], graphic: ["graphics"], cta: ["effects", "subscribe"], sound: ["audio", "sfx"] }[kind];
      if (left) openLeft(...left);
      return;
    }
    setFocus({ kind, ...extra });
    if (layout.director) setLayout({ director: false });
  }
  function addSticker(kind, assetId) {
    const list = normaliseStickers(project.stickers, project.assets);
    const st = newSticker(kind, Math.min(time, Math.max(0, duration - 0.5)), assetId, list);
    queueSave({ stickers: [...list, st] });
    setStickerId(st.id);
    setStickerDialog(false);
    // v0.4.69 straight to its size, timing and keyframes: v0.4.70 on the right (the gallery stays open)
    if (dock) focusRight("sticker");
    else openLeft("stickers", "placed");
    setPlaying(false);
    notify("Sticker added at the playhead. Drag it in the preview to move it.");
  }
  async function uploadSticker(file) {
    try {
      const form = new FormData();
      form.append("files", file);
      const before = new Set((project.assets || []).map((a) => a.id));
      let p = await api(`/api/projects/${project.id}/upload`, "POST", form);
      const added = p.assets.find((a) => !before.has(a.id) && a.kind === "image");
      if (added) p = await api(`/api/projects/${project.id}/assets/${added.id}`, "PATCH", { sticker: true });
      setProject(p);
    } catch (e) {
      report(e);
    }
  }
  function moveSticker(id, x, y, local) {
    const list = normaliseStickers(projectRef.current.stickers, projectRef.current.assets);
    queueSave({
      stickers: list.map((s) => {
        if (s.id !== id) return s;
        if (!s.keyframes.length) return { ...s, x, y };
        const v = stickerAt(s, local);
        const near = s.keyframes.find((k) => Math.abs(k.t - local) < 0.05);
        const at = near ? near.t : Math.round(local * 1000) / 1000;
        return { ...s, keyframes: normaliseStickerKeys([...s.keyframes.filter((k) => k !== near), { ...(near || {}), size: v.size, opacity: v.raw, x, y, t: at }], s.length, s) };
      }),
    });
  }
  // v0.4.72 Esc: no longer waiting for a click on the thing to follow
  useEffect(() => {
    if (!stickerPick) return undefined;
    const esc = (e) => e.key === "Escape" && setStickerPick(null);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [stickerPick]);
  // v0.4.72 a resize handle in the preview: size (with keyframes, at this moment) and shape
  function resizeSticker(id, patch, local) {
    const list = normaliseStickers(projectRef.current.stickers, projectRef.current.assets);
    queueSave({
      stickers: list.map((s) => {
        if (s.id !== id) return s;
        const shape = patch.ratio ? { ratio: patch.ratio } : {};
        if (!s.keyframes.length) return { ...s, size: patch.size, ...shape };
        const v = stickerAt(s, local);
        const near = s.keyframes.find((k) => Math.abs(k.t - local) < 0.05);
        const at = near ? near.t : Math.round(local * 1000) / 1000;
        return { ...s, ...shape, keyframes: normaliseStickerKeys([...s.keyframes.filter((k) => k !== near), { ...(near || {}), x: v.x, y: v.y, opacity: v.raw, size: patch.size, t: at }], s.length, s) };
      }),
    });
  }
  // v0.4.72 Follow something: step the preview through the sticker's time from the playhead,
  // find the marked patch in each picture, and keep the path as keyframes.
  async function followSticker(id, point = null) {
    if (trackRef.current) return;
    const list = normaliseStickers(projectRef.current.stickers, projectRef.current.assets);
    const s = list.find((x) => x.id === id);
    const box = document.querySelector(".video-frame");
    if (!s || !box) return;
    const t0 = Math.max(0, Math.min(s.length - TRACK.step, time - s.start));
    const v0 = stickerAt(s, t0);
    const start = point ? { x: point.x, y: point.y } : { x: v0.x, y: v0.y };
    const run = { stop: false };
    trackRef.current = run;
    setPlaying(false);
    setStickerTrack({ id, progress: 0 });
    const frame = () => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
    const settle = async () => {
      await frame();
      const until = Date.now() + 2500;
      for (;;) {
        const v = videoRef.current;
        const imgs = [...box.querySelectorAll(".fx-media img.pic-media")];
        const ready = (!v || (!v.seeking && v.readyState >= 2)) && imgs.every((im) => im.complete);
        if (ready || Date.now() > until) break;
        await new Promise((ok) => setTimeout(ok, 30));
      }
      await frame();
    };
    const pts = [];
    let note = "";
    try {
      setTime(s.start + t0);
      await settle();
      const tr = makeTracker();
      const f0 = grabFrame(box);
      if (!f0 || !tr.start(f0, start.x, start.y, v0.size)) throw new Error("Casefile could not read this picture to follow it.");
      pts.push({ t: t0, ...start });
      const steps = Math.floor((s.length - t0) / TRACK.step);
      for (let i = 1; i <= steps && !run.stop; i++) {
        const t = Math.round((t0 + i * TRACK.step) * 1000) / 1000;
        setTime(s.start + t);
        await settle();
        const f = grabFrame(box);
        const r = f && tr.next(f);
        if (!r || r.lost) {
          note = `Lost it at ${(s.start + t).toFixed(1)} s (it left the picture or the shot changed): the sticker stays where it last was. Start another follow there if you need to.`;
          break;
        }
        pts.push({ t, x: r.x, y: r.y });
        setStickerTrack({ id, progress: i / steps });
      }
      if (run.stop) note = "Stopped: the path so far is kept.";
      // the path, as keyframes from the playhead on (earlier keyframes stay)
      const path = simplifyPath(pts).map((p) => {
        const v = stickerAt(s, p.t);
        return { t: p.t, x: p.x, y: p.y, size: v.size, opacity: v.raw, ease: "linear" };
      });
      const cur = normaliseStickers(projectRef.current.stickers, projectRef.current.assets);
      queueSave({
        stickers: cur.map((x) => (x.id !== id ? x : { ...x, keyframes: normaliseStickerKeys([...x.keyframes.filter((k) => k.t < t0 - 0.02), ...path], x.length, x) })),
      });
      const secs = pts.length > 1 ? pts[pts.length - 1].t - t0 : 0;
      note = `${note ? note + " " : ""}Followed for ${secs.toFixed(1)} s · ${path.length} keyframes.`;
    } catch (e) {
      note = e.message || String(e);
    } finally {
      trackRef.current = null;
      setStickerTrack({ id, done: true, note });
      setTime(s.start + t0);
      notify(note);
    }
  }
  function updateScene(fields) {
    if (!selected) return;
    const next = scenes.map((s) =>
      s.id === selected.id ? { ...s, ...fields } : s,
    );
    const changes = { scenes: next };
    if (fields.narration !== undefined) {
      changes.script = scriptFromScenes(next);
      if (voice) changes.narration_id = null;
      next.find((s) => s.id === selected.id).captions = [];
    }
    if (fields.source_ids !== undefined)
      changes.script = scriptFromScenes(next);
    queueSave(changes);
  }

  function currentOffset(index) {
    return offsets[index] || 0;
  }

  function trackLabel(kind) {
    return { visual: "Visuals V1", narration: "Narration A1", music: "Music A2" }[kind];
  }

  function trackIcon(kind) {
    return { visual: Film, narration: Mic, music: Music2 }[kind];
  }

  function trackFields(kind, scene) {
    switch (kind) {
      case "visual":
        return { asset: scene.asset_id, inPoint: scene.trim_start || 0, duration: scene.duration };
      case "narration":
        return { text: scene.narration || "", start: scene.audio_start || 0, duration: scene.audio_duration || scene.duration, volume: scene.narration_volume || 1 };
      default:
        return { id: scene.music_id || null, start: scene.music_start || 0, duration: scene.music_duration || scene.duration, volume: scene.music_volume || (project?.music_volume || 1) };
    }
  }

  function updateTrack(kind, fields) {
    if (!selected) return;
    const next = scenes.map((s) => {
      if (s.id !== selected.id) return s;
      const cur = trackFields(kind, s);
      const merged = { ...cur, ...fields };
      let out;
      if (kind === "visual") {
        out = { ...s, asset_id: merged.asset || null, trim_start: Math.max(0, merged.inPoint), duration: Math.max(0.5, merged.duration) };
      } else if (kind === "narration") {
        out = { ...s, narration: merged.text, audio_start: merged.start, audio_duration: Math.max(0.5, merged.duration), narration_volume: merged.volume };
      } else {
        out = { ...s, music_id: merged.id || null, music_start: merged.start, music_duration: Math.max(0.5, merged.duration), music_volume: merged.volume };
      }
      return out;
    });
    const changes = { scenes: next };
    if (kind !== "visual") changes.script = scriptFromScenes(next);
    queueSave(changes);
    notify(`${trackLabel(kind)} adjusted.`);
  }

  function deleteTrack(kind) {
    if (!selected) return;
    if (!window.confirm(`Remove ${trackLabel(kind)} from this scene?`)) return;
    const next = scenes.map((s) => {
      if (s.id !== selected.id) return s;
      if (kind === "visual") {
        const { asset_id, trim_start, ...rest } = s;
        return rest;
      }
      if (kind === "narration") {
        const { narration, audio_start, audio_duration, narration_volume, ...rest } = s;
        return rest;
      }
      const { music_id, music_start, music_duration, music_volume, ...rest } = s;
      return rest;
    });
    queueSave({ scenes: next, script: scriptFromScenes(next) });
    if (selectedTrack?.sceneId === selected.id) setSelectedTrack(null);
    notify(`${trackLabel(kind)} removed from scene.`);
  }

  function splitTrack(kind) {
    if (!selected || locked) return;
    const cut = Math.round((time - currentOffset(activeIndex)) * 1000) / 1000;
    if (cut < 0.5 || selected.duration - cut < 0.5) return;
    const s = selected;
    const words = (s.narration || "").split(/\s+/).filter(Boolean);
    const wordCut = Math.round((words.length * cut) / s.duration);
    const left = { ...s, duration: cut };
    const right = { ...s, id: uid(), duration: s.duration - cut, trim_start: (s.trim_start || 0) + cut, audio_start: (s.audio_start || 0) + cut, show_title: false };
    if (kind === "narration") {
      left.narration = words.slice(0, wordCut).join(" ");
      right.narration = words.slice(wordCut).join(" ");
      left.audio_duration = Math.min(s.audio_duration || s.duration, cut);
      right.audio_duration = Math.max(0.04, (s.audio_duration || s.duration) - cut);
      right.narration_volume = s.narration_volume;
    }
    if (kind === "music") {
      left.music_duration = Math.max(0.04, cut);
      right.music_start = (s.music_start || 0) + cut;
      right.music_duration = Math.max(0.04, (s.music_duration || s.duration) - cut);
      right.music_volume = s.music_volume;
    }
    if (kind === "visual") {
      right.captions = (s.captions || []).filter((c) => c.end > cut).map((c) => ({ ...c, start: Math.max(0, c.start - cut), end: c.end - cut }));
      left.captions = (s.captions || []).filter((c) => c.start < cut).map((c) => ({ ...c, end: Math.min(c.end, cut) }));
    }
    const next = [...scenes];
    next.splice(activeIndex, 1, left, right);
    queueSave({ scenes: next, script: scriptFromScenes(next) });
    setPlaying(false);
    setSelectedId(right.id);
    setSelectedTrack({ kind, sceneId: right.id });
    notify(`${trackLabel(kind)} split at playhead.`);
  }

  function addScene() {
    const s = {
      id: uid(),
      title: "New scene",
      chapter: "Case narrative",
      narration: "",
      source_ids: [],
      duration: 8,
      asset_id: null,
      motion: "slow-zoom",
      transition: "none",
      transition_duration: 0,
      show_title: true,
      trim_start: 0,
      audio_start: sum(scenes),
      audio_duration: 8,
      timing: "estimated",
      captions: [],
    };
    queueSave({ scenes: [...scenes, s] });
    setSelectedId(s.id);
    setTime(duration);
    setPlaying(false);
  }
  function moveScene(id, delta) {
    const list = [...scenes],
      i = list.findIndex((s) => s.id === id),
      j = i + delta;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    queueSave({ scenes: list });
    setPlaying(false);
    setTime(0);
  }
  function dropScene(target) {
    const list = [...scenes],
      i = list.findIndex((s) => s.id === dragId.current),
      j = list.findIndex((s) => s.id === target);
    if (i < 0 || i === j) return;
    const [s] = list.splice(i, 1);
    list.splice(j, 0, s);
    queueSave({ scenes: list });
    setPlaying(false);
    setTime(0);
  }
  function trimScene(event, scene, side) {
    event.preventDefault();
    event.stopPropagation();
    if (locked) return;
    setPlaying(false);
    const content = timelineRef.current?.querySelector(".timeline-content");
    if (!content || !duration) return;
    const pps = content.getBoundingClientRect().width / duration,
      startX = event.clientX,
      baseScenes = scenes;
    gesture.current = true; // v0.4.51: saved once, on release: one undo step
    const update = (e) => {
      let delta = Math.round(((e.clientX - startX) / pps) * 10) / 10,
        fields;
      if (side === "right")
        fields = {
          duration: Math.max(0.5, Math.min(600, scene.duration + delta)),
        };
      else {
        delta = Math.max(
          -Math.min(scene.audio_start || 0, scene.trim_start || 0),
          Math.min(scene.duration - 0.5, delta),
        );
        fields = {
          duration: Math.max(0.5, Math.min(600, scene.duration - delta)),
          trim_start: Math.max(0, (scene.trim_start || 0) + delta),
          audio_start: Math.max(0, (scene.audio_start || 0) + delta),
          audio_duration: Math.max(
            0.04,
            (scene.audio_duration || scene.duration) - delta,
          ),
          captions: (scene.captions || [])
            .filter((c) => c.end > delta)
            .map((c) => ({
              ...c,
              start: Math.max(0, c.start - delta),
              end: Math.max(0, c.end - delta),
            })),
        };
      }
      queueSave({
        scenes: baseScenes.map((s) =>
          s.id === scene.id ? { ...s, ...fields } : s,
        ),
      });
    };
    const finish = () => {
      window.removeEventListener("pointermove", update);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      window.removeEventListener("blur", finish);
      gesture.current = false;
      if (Object.keys(pending.current).length) {
        clearTimeout(saveTimer.current);
        saveTimer.current = setTimeout(() => flushSave().catch(report), 150);
      }
    };
    window.addEventListener("pointermove", update);
    window.addEventListener("pointerup", finish, { once: true });
    window.addEventListener("pointercancel", finish, { once: true });
    window.addEventListener("blur", finish, { once: true });
  }
  function splitAtPlayhead() {
    if (!activeScene || locked) return;
    const cut = Math.round((time - offsets[activeIndex]) * 1000) / 1000;
    if (cut < 0.5 || activeScene.duration - cut < 0.5) return;
    const s = activeScene,
      words = s.narration.split(/\s+/).filter(Boolean),
      wordCut = Math.round((words.length * cut) / s.duration);
    const left = {
      ...s,
      duration: cut,
      narration: words.slice(0, wordCut).join(" "),
      audio_duration: Math.min(s.audio_duration || s.duration, cut),
      captions: (s.captions || [])
        .filter((c) => c.start < cut)
        .map((c) => ({ ...c, end: Math.min(c.end, cut) })),
    };
    const right = {
      ...s,
      id: uid(),
      title: s.title + " · continued",
      duration: s.duration - cut,
      narration: words.slice(wordCut).join(" "),
      show_title: false,
      trim_start: (s.trim_start || 0) + cut,
      audio_start: (s.audio_start || 0) + cut,
      audio_duration: Math.max(0.04, (s.audio_duration || s.duration) - cut),
      captions: (s.captions || [])
        .filter((c) => c.end > cut)
        .map((c) => ({
          ...c,
          start: Math.max(0, c.start - cut),
          end: c.end - cut,
        })),
    };
    const next = [...scenes];
    next.splice(activeIndex, 1, left, right);
    queueSave({
      scenes: next,
      script: scriptFromScenes(next),
      narration_id: project.narration_id,
    });
    setPlaying(false);
    setSelectedId(right.id);
    notify("Scene split at the playhead. Review the cut and captions.");
  }
  // v0.4.51 Undo / redo any edit. Unsaved changes are saved first (so they are the step undone);
  // the playhead stays where it is.
  async function stepHistory(which) {
    if (!project || locked || historyBusy.current) return;
    historyBusy.current = true;
    try {
      const saved = await flushSave();
      const list = (saved || projectRef.current)?.history?.[which] || [];
      if (!list.length) {
        notify(which === "undo" ? "Nothing to undo." : "Nothing to redo.", "info");
        return;
      }
      const name = list[list.length - 1];
      const p = await api(`/api/projects/${project.id}/${which}`, "POST", {});
      acceptProject(p);
      notify(`${which === "undo" ? "Undone" : "Redone"}: ${name}`);
    } catch (e) {
      report(e);
    } finally {
      historyBusy.current = false;
    }
  }
  historyRef.current = stepHistory;
  async function direct(e, text) {
    e?.preventDefault();
    const instruction = (text || command).trim();
    if (!instruction || locked) return;
    setBusy(true);
    try {
      await flushSave();
      const r = await api(`/api/projects/${project.id}/command`, "POST", {
        instruction,
      });
      setCommand("");
      setLayout({ director: true });
      if (r.project) {
        acceptProject(r.project);
        notify("Edit applied. Undo is available.");
      } else {
        watched.current.add(r.job_id);
        setJobs(await api(`/api/projects/${project.id}/jobs`));
      }
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  function requireAI(next) {
    if (!config.connected) {
      setModal("settings");
      notify(
        "Connect an AI service to use this feature. Local editing is already available.",
        "info",
      );
      return false;
    }
    if (next) setModal(next);
    return true;
  }
  function transcribeAsset(asset) {
    if (!requireAI()) return;
    if (
      window.confirm(
        "Send this audio to the AI service for transcription? This replaces the current timeline and may incur usage charges. Undo will be available.",
      )
    ) {
      setModal(null);
      startOperation(`/api/projects/${project.id}/transcribe/${asset.id}`);
    }
  }
  async function setSource(source, fields) {
    try {
      await flushSave();
      const p = await api(
        `/api/projects/${project.id}/sources/${source.id}`,
        "PATCH",
        fields,
      );
      acceptProject(p);
    } catch (e) {
      report(e);
    }
  }
  function seekTimeline(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    setTime(
      Math.max(
        0,
        Math.min(duration, ((e.clientX - rect.left) / rect.width) * duration),
      ),
    );
    setPlaying(false);
  }
  // Drag on the ruler or the playhead to scrub, as in CapCut.
  function scrub(e) {
    const content = timelineRef.current?.querySelector(".timeline-content");
    if (!content || !duration) return;
    e.preventDefault();
    e.stopPropagation();
    setPlaying(false);
    const at = (x) => {
      const rect = content.getBoundingClientRect();
      if (!(rect.width > 0)) return; // v0.4.59 a hidden timeline: never a NaN playhead (a sound added "at NaN")
      setTime(Math.max(0, Math.min(duration, ((x - rect.left) / rect.width) * duration)));
    };
    at(e.clientX);
    const move = (ev) => at(ev.clientX);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
  function zoomTo(next, pointerX) {
    const el = timelineRef.current;
    const z = Math.max(1, Math.min(20, Math.round(next * 4) / 4));
    if (el) {
      // Buttons and the slider zoom around the playhead, as CapCut does.
      const head = duration ? (time / duration) * el.scrollWidth - el.scrollLeft : 0;
      const x = pointerX ?? Math.max(0, Math.min(el.clientWidth, head));
      const left = zoomScroll(el.scrollLeft, x, zoom, z);
      requestAnimationFrame(() => (el.scrollLeft = left));
    }
    setZoom(z);
  }
  // v0.4.71 The Edit grid's size on this screen. Wide (a Mac): three columns fitted by fitEdit.
  // Tablet (581-1070 px): two columns, the timeline as tall as its tracks (at most 45%).
  // Phone (580 px and under): no fixed height — the page scrolls, so the media panel gets a
  // usable height and the timeline shows every track.
  function editGridStyle() {
    const w = window.innerWidth;
    if (w <= 580) return tlNeed ? { "--cc-tl-h": `${tlNeed}px` } : {};
    if (w <= 1070) {
      const tl = tlNeed ? Math.round(Math.min(tlNeed, Math.max(170, gridHeight * 0.45))) : 210;
      return { height: gridHeight, gridTemplateRows: `minmax(240px, 1fr) ${tl}px` };
    }
    return {
      height: gridHeight,
      gridTemplateColumns: `${fit.left}px minmax(0, 1fr) ${fit.right}px`,
      gridTemplateRows: `minmax(200px, 1fr) ${fit.timeline}px`,
    };
  }
  // Drag a panel edge. kind: left | right | timeline.
  function resizePanel(e, kind) {
    e.preventDefault();
    const start = { x: e.clientX, y: e.clientY, v: fit[kind] ?? layout[kind] };
    document.body.classList.add(kind === "timeline" ? "resizing-row" : "resizing-col");
    const move = (ev) => {
      const d = kind === "left" ? ev.clientX - start.x : kind === "right" ? start.x - ev.clientX : start.y - ev.clientY;
      const v = kind === "timeline" ? timelineHeight(start.v + d, gridHeight) : start.v + d;
      setLayoutState((cur) => normaliseLayout({ ...cur, [kind]: v }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("resizing-row", "resizing-col");
      setLayout({});
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
  async function makeFirstDraft({ render = false, resolution = "480p" } = {}) {
    if (locked || !project) return;
    setBusy(true);
    setPlaying(false);
    try {
      await flushSave();
      const saved = (await cachedSetups().catch(() => [])).find(
        (entry) => entry.id === project.id,
      );
      if (saved && (await workingFiles(project.id).catch(() => [])).length) {
        const recovered = await restoreWorkingSession(
          saved.project,
          api,
          (progress) => setUploadProgress(progress),
        );
        if (recovered.missing) setRecoveredSetup(saved);
        else if (recoveredSetup?.id === saved.id) setRecoveredSetup(null);
        if (recovered.restored)
          notify(
            `Recovered ${recovered.restored} working file(s) from this browser.`,
            "info",
          );
      }
      const response = await api(
        `/api/projects/${project.id}/episode/first-draft`,
        "POST",
        {},
      );
      const p = response.project;
      pending.current = {};
      acceptProject(p);
      setSelectedId(response.preview.scene_id);
      setTime(response.preview.time);
      setTab("edit");
      if (!render)
        notify(
          "Your preview is ready. The timeline now uses your available source files; no final approvals were inferred.",
        );
      if (render) {
        const track = p.assets.find(
          (a) => a.id === p.narration_id && a.available_on_server !== false,
        );
        if (!track)
          throw new Error(
            "Picture preview is ready. Add the matching narration recording to make a video with sound.",
          );
        const job = await api(`/api/projects/${p.id}/render`, "POST", {
          resolution,
          draft: true,
          captions: p.captions,
          allow_guided_gaps: true,
          allow_inspection: true,
        });
        watched.current.add(job.job_id);
        setJobs(await api(`/api/projects/${p.id}/jobs`));
        setTab("review");
        setModal(null);
        notify(
          "Making your inspection video. It includes clearly marked gaps where sources are missing.",
          "info",
        );
      }
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }

  async function startRender(options) {
    setBusy(true);
    setPlaying(false);
    try {
      await flushSave();
      const result = await api(
        `/api/projects/${project.id}/render`,
        "POST",
        options,
      );
      watched.current.add(result.job_id);
      setJobs(await api(`/api/projects/${project.id}/jobs`));
      setModal(null);
      setTab("review");
      notify(
        "Rendering started. Long episodes can take a while on this CPU.",
        "info",
      );
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }

  async function openTool(name, targetTab) {
    try {
      await flushSave();
      setPlaying(false);
      if (targetTab) setTab(targetTab);
      setModal(name);
    } catch (e) {
      report(e);
    }
  }
  function navigateTool(action) {
    setPlaying(false);
    if (action.tab === "settings") {
      setModal("settings");
      return;
    }
    setTab(action.tab || "edit");
    if (action.scene_id) {
      const index = scenes.findIndex((s) => s.id === action.scene_id);
      if (index >= 0) {
        setSelectedId(action.scene_id);
        setTime(offsets[index] || 0);
      }
    }
    if (action.media) setMediaId(action.asset_id || assets[0]?.id || null);
    setModal(action.media ? "media" : null);
  }
  async function runProduction(options) {
    if (locked) return;
    setBusy(true);
    setPlaying(false);
    try {
      await flushSave();
      const result = await api(
        `/api/projects/${project.id}/produce`,
        "POST",
        options,
      );
      watched.current.add(result.job_id);
      const list = await api(`/api/projects/${project.id}/jobs`);
      setJobs(list);
      if (list.find((j) => j.id === result.job_id)?.status === "done")
        acceptProject(await api(`/api/projects/${project.id}`));
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function approveScript() {
    if (locked) return;
    if (
      !window.confirm(
        "Confirm that you read this AI-written script against its original sources. This approves the text for narration; it does not certify factual accuracy or media rights.",
      )
    )
      return;
    try {
      await flushSave();
      acceptProject(
        await api(`/api/projects/${project.id}/approve-script`, "POST", {
          acknowledge: true,
        }),
      );
      notify(
        "Script text approved for narration. Final factual and rights review is still required.",
      );
    } catch (e) {
      report(e);
    }
  }
  // v0.4.47 A video the browser cannot play (a transparent .MOV) gets preview stills, made once
  // (v0.4.50: made again when they are the old soft ones).
  function needPreview(assetId) {
    const id = project.id;
    const merge = (patch) =>
      setProject((p) => (p && p.id === id ? { ...p, assets: p.assets.map((x) => (x.id === assetId ? { ...x, ...patch } : x)) } : p));
    api(`/api/projects/${id}/assets/${assetId}/preview`, "POST")
      .then((a) => merge(a))
      .catch((e) => {
        merge({ preview_error: e.message || String(e) });
        report(e);
      });
  }
  function fullscreen() {
    // v0.4.47 Fullscreen the monitor, not the frame: the monitor's size watcher then sizes the frame
    // for the whole screen (kept 16:9 or 9:16), so the watermark, CTA, captions and titles, which are
    // all placed from that size, grow with the picture instead of staying where the small frame was.
    // v0.4.68 Where the page may not go fullscreen (an embedded preview, an iframe without
    // permission), the player fills the whole window instead.
    if (fullMode) return exitFull();
    const el = screenRef.current || document.querySelector(".monitor-screen");
    const go = el && document.fullscreenEnabled !== false && (el.requestFullscreen || el.webkitRequestFullscreen);
    if (!go) return setFullMode("window");
    Promise.resolve(go.call(el)).catch(() => setFullMode("window"));
  }
  // v0.4.68 open what you found in Search
  function goEdit() {
    setHome(false);
    if (tab !== "edit") setTab("edit");
  }
  function askDirector(q) {
    setSearchOpen(false);
    goEdit();
    setCommand(q);
    setLayout({ director: true });
    setTimeout(() => document.getElementById("direction")?.focus(), 60);
  }
  function runSearch(r) {
    const go = r.go || {};
    setSearchOpen(false);
    setMenuOpen(false);
    if (go.left) {
      goEdit();
      openLeft(go.left[0], go.left[1]);
    } else if (go.insp) {
      goEdit();
      setInspectorTab(go.insp[0]);
      (go.insp[0] === "audio" ? setAudioSub : setVideoSub)(go.insp[1]);
      if (!layout.showRight) setLayout({ showRight: true });
    } else if (go.page) {
      setHome(false);
      setPlaying(false);
      setTab(go.page);
    } else if (go.scene != null) {
      goEdit();
      const sc = scenes[go.scene];
      if (sc) selectVisualScene(sc, go.scene);
    } else if (go.asset) {
      setHome(false);
      setMediaId(go.asset);
      setModal("media");
    } else if (go.action) {
      const a = go.action;
      if (a.startsWith("import:")) {
        goEdit();
        const role = a.slice(7);
        openLeft("audio", role === "narration" ? "voice" : role);
        importAudio(role);
      } else if (a === "export") project.episode?.guide ? makeFirstDraft({ render: true }) : openTool("export", "review");
      else if (a === "produce") openTool("production");
      else if (a === "undo" || a === "redo") stepHistory(a);
      else if (a === "split") { goEdit(); splitAtPlayhead(); }
      else if (a === "addScene") { goEdit(); addScene(); }
      else if (a === "importMedia") fileRef.current?.click();
      else if (a === "director") askDirector("");
      else if (a === "fullscreen") { goEdit(); setTimeout(fullscreen, 60); }
      else if (a === "ratio") { setHome(false); setModal("format"); }
      else if (a === "mediaLibrary") { setMediaId(null); setModal("media"); }
      else if (a === "projects") { refreshProjects(); setModal("projects"); }
      else if (a === "newProject") setModal("new");
      else if (a === "backup") downloadProjectSnapshot(project, setDownloadGate);
      else if (a === "home") { setPlaying(false); setHome(true); }
      else if (a === "help") setModal("help");
      else if (a === "settings") setModal("settings");
    }
  }
  function exitFull() {
    if (fullMode === "window") return setFullMode("");
    const out = document.exitFullscreen || document.webkitExitFullscreen;
    if (out) Promise.resolve(out.call(document)).catch(() => {});
    setFullMode("");
  }

  if (!project)
    return (
      <div className="boot">
        <img src="/assets/favicon.svg" width="48" />
        <div className="brand-word">
          CASEFILE <span>STUDIO</span>
        </div>
        <LoaderCircle className="spin" size={20} />
        <p>{toast?.message || "Opening your documentary workspace…"}</p>
        {recoveredSetup && (
          <div className="recovery-notice">
            <b>A setup backup is saved in this browser</b>
            <p>
              {recoveredSetup.project.title} ·{" "}
              {recoveredSetup.project.assets?.length || 0} media references.
              Media bytes are not included.
            </p>
            <button
              className="btn primary"
              aria-label="Download recovered setup"
              onClick={() =>
                downloadProjectSnapshot(recoveredSetup.project, setDownloadGate)
              }
            >
              Download saved project setup
            </button>
          </div>
        )}
      </div>
    );

  // v0.4.67 CapCut layout. The panels the left icon tabs open (each as before, now one per tab).
  function effectsPanel(only) {
    return (
            <Effects
              only={only}
              project={project}
              scene={selected}
              sceneIndex={Math.max(0, scenes.indexOf(selected))}
              thumb={assets.find((a) => a.id === selected?.asset_id)?.thumbnail}
              prevThumb={(() => {
                const i = scenes.indexOf(selected);
                return i > 0 ? assets.find((a) => a.id === scenes[i - 1].asset_id)?.thumbnail : null;
              })()}
              disabled={locked}
              onProject={queueSave}
              onScene={updateScene}
              onHoverLook={setHoverLook}
              onAllScenes={(patch, label) => {
                queueSave({ scenes: scenes.map((x) => ({ ...x, ...patch })) });
                notify(`${label || "This transition"} is on every scene now. Undo puts the old ones back.`);
              }}
              ctaEvents={ctaEvents}
              ctaSpots={ctaSpots}
              ctaNatural={ctaSpots[0]?.natural || normaliseCta(project.cta).seconds}
              playhead={time}
              sceneStart={selected ? offsets[scenes.indexOf(selected)] || 0 : 0}
              onSeek={(t) => { setPlaying(false); setTime(Math.max(0, Math.min(duration, t))); }}
              onCrop={(id) => setCropId(id)}
              api={api}
              autoCard={selected ? nameCards[scenes.indexOf(selected)] : null}
              onPlayCta={(at) => {
                setTime(at);
                setPlaying(true);
              }}
              onUploadBanner={async (file, asAnimation = false) => {
                try {
                  const form = new FormData();
                  form.append("files", file);
                  const before = new Set((project.assets || []).map((a) => a.id));
                  const p = await api(`/api/projects/${project.id}/upload`, "POST", form);
                  const added = p.assets.filter((a) => !before.has(a.id) && a.kind === (asAnimation === true ? "video" : "image")).at(-1);
                  setProject(p);
                  if (added && asAnimation === "logo") queueSave({ watermark: { ...normaliseWatermark(p.watermark), enabled: true, asset_id: added.id } });
                  else if (added && asAnimation) queueSave({ cta: { ...normaliseCta(p.cta), enabled: true, source: "file", file_id: added.id } });
                  else if (added) queueSave({ cta: { ...normaliseCta(p.cta), enabled: true, asset_id: added.id } });
                } catch (e) {
                  report(e);
                }
              }}
            />
    );
  }
  function stickersPanel(mode) {
    return (
            <StickerPanel
              focus={mode === "focus"}
              listOnly={mode === "list"}
              project={project}
              time={time}
              selectedId={stickerId}
              onSelect={(id) => { setStickerId(id); if (id && mode === "list") focusRight("sticker"); }}
              onChange={(list) => queueSave({ stickers: list })}
              onOpenDialog={() => setStickerDialog(true)}
              onSeek={(t) => { setPlaying(false); setTime(Math.max(0, Math.min(duration, t))); }}
              disabled={locked || !!stickerTrack && !stickerTrack.done}
              tracking={stickerTrack}
              picking={!!stickerPick}
              onFollow={(id, pick) => { setStickerTrack(null); if (pick) { setPlaying(false); setStickerPick(id); } else followSticker(id); }}
              onStopFollow={() => { setStickerPick(null); if (trackRef.current) trackRef.current.stop = true; }}
            />
    );
  }
  function motionPanel(mode) {
    return (
            <MotionPanel
              focus={mode === "focus"}
              listOnly={mode === "list"}
              project={project}
              time={time}
              playing={playing}
              selectedId={motionId}
              onSelect={(id) => { setMotionId(id); if (id && mode === "list") focusRight("graphic"); }}
              onChange={(m) => queueSave({ motion: m })}
              onSuggest={async (body = {}) => {
                await flushSave();
                const r = await api(`/api/projects/${project.id}/motion/suggest`, "POST", body);
                acceptProject(r.project);
                const what = body.engine === "cinematic" ? "cinematic graphic" : "motion graphic";
                notify(r.added ? `${r.added} ${what}${r.added > 1 ? "s" : ""} suggested. Review each one, then approve it.` : `Nothing in the narration calls for a ${what}.`, "info");
              }}
              onDraft={async (body) => (await api(`/api/projects/${project.id}/motion/draft`, "POST", body)).item}
              onPresent={async (body = {}) => {
                await flushSave();
                const r = await api(`/api/projects/${project.id}/motion/present`, "POST", body);
                if (r.project) {
                  acceptProject(r.project);
                  notify(r.applied ? `Presentation applied to ${r.applied} graphic${r.applied > 1 ? "s" : ""}. Undo puts them back.` : "Nothing to change.", "info");
                }
                return r;
              }}
              onSeek={(t) => { setPlaying(false); setTime(Math.max(0, Math.min(duration, t))); }}
              onPlayFrom={(t) => { setTime(Math.max(0, Math.min(duration, t))); setPlaying(true); }}
              previewStatus={motionStatus}
              disabled={locked}
            />
    );
  }
  function soundPanel(mode) {
    return (
            <SoundPanel
              focus={mode === "focus"}
              listOnly={mode === "list"}
              project={project}
              plan={soundPlan}
              planError={soundPlanError}
              time={time}
              playing={playing}
              selectedId={soundId}
              onSelect={(id) => { setSoundId(id); if (id && mode === "list") focusRight("sound"); }}
              pin={sfxPin}
              onPin={setSfxPin}
              onChange={(v) => queueSave({ sound: v })}
              onGenerate={async () => {
                await flushSave();
                const r = await api(`/api/projects/${project.id}/sound/generate`, "POST", {});
                acceptProject(r.project);
                notify(`${r.added} sound${r.added === 1 ? "" : "s"} planned; ${r.silenced} moment${r.silenced === 1 ? "" : "s"} left silent on purpose.`, "info");
              }}
              onSeek={(t) => { setPlaying(false); setTime(Math.max(0, Math.min(duration, t))); }}
              onPlayFrom={(t) => { setTime(Math.max(0, Math.min(duration, t))); setPlaying(true); }}
              preview={sfxPreview.current}
              duckStatus={sfxDuck}
              narrationVolume={project.narration_volume ?? 1}
              onNarrationVolume={commitNarration}
              onLiveNarration={liveNarration}
              onLiveMaster={liveMaster}
              onSelectMany={setSoundIds}
              selectedIds={soundIds}
              mute={sfxMute}
              solo={sfxSolo}
              onMute={(v) => { setSfxMute(v); if (v) setSfxSolo(false); }}
              onSolo={(v) => { setSfxSolo(v); if (v) setSfxMute(false); }}
              onUploadSound={async (file) => {
                await flushSave();
                const form = new FormData();
                form.append("files", file);
                form.append("episode_role", "sfx");
                const before = new Set((project.assets || []).map((a) => a.id));
                const p = await api(`/api/projects/${project.id}/upload`, "POST", form);
                acceptProject(p);
                const added = p.assets.find((a) => !before.has(a.id));
                if (added) notify(`${added.name} is in your sounds: choose it for a sound, or add it at the playhead from the library.`, "info");
              }}
              disabled={locked}
            />
    );
  }
  function captionsPanel(section) {
    return (
            <CaptionStyles
              section={section}
              value={project.caption_style}
              enabled={project.captions}
              disabled={locked}
              onChange={(v) => queueSave({ caption_style: v })}
              onToggle={(v) => queueSave({ captions: v })}
            />
    );
  }
  // v0.4.70 the Director's history and its box: in the right panel when it is beside the player,
  // otherwise in the floating panel (only one of them is on the page, so #direction is unique)
  function directorBody() {
    return (
      <>
                  {directorHistory()}
                  <form className="director-bar" onSubmit={direct}>
                    <div className="director-input">
                      <label htmlFor="direction">Tell the Director what to change</label>
                      <input
                        id="direction"
                        value={command}
                        onChange={(e) => setCommand(e.target.value)}
                        placeholder={
                          project.episode?.guide
                            ? "Try “set music to 8%” or “use the archive look”…"
                            : "Try “use the archive look” or “set scene 2 to 12 seconds”…"
                        }
                        disabled={locked}
                      />
                    </div>
                    <button
                      className="send-btn"
                      type="submit"
                      aria-label="Apply editing instruction"
                      disabled={locked || !command.trim()}
                    >
                      {busy ? (
                        <LoaderCircle className="spin" size={16} />
                      ) : (
                        <ArrowUpRight size={18} />
                      )}
                    </button>
                  </form>
      </>
    );
  }
  function directorHistory() {
    return (
            <div className="director-panel">
              <div className="director-status">
                <span className="tiny-dot" />
                {config.connected
                  ? "AI service connected"
                  : "Local commands available"}
                <button onClick={() => setModal("settings")}>
                  <Settings2 size={13} />
                </button>
              </div>
              <div className="messages" ref={messagesRef}>
                {project.messages.map((m, i) => (
                  <div className={`message ${m.role}`} key={i}>
                    {m.role === "assistant" && (
                      <div className="message-author">
                        <Sparkles size={12} /> CASEFILE DIRECTOR
                      </div>
                    )}
                    <p>{m.text}</p>
                  </div>
                ))}
              </div>
              <div className="director-footnote">
                <LockKeyhole size={12} /> Creative rewrites need an API
                connection. No automatic factual verification.
              </div>
            </div>
    );
  }
  // One scene's track (picture, narration or music): split, remove and its own settings.
  function trackRows(kinds) {
    return kinds.map((kind) => {
                  const f = trackFields(kind, selected);
                  const isSel = selectedTrack?.kind === kind && selectedTrack?.sceneId === selected.id;
                  const Icon = trackIcon(kind);
                  return (
                    <div key={kind} className="track-row">
                      <div className="track-row-head">
                        <Icon size={13} />
                        <span>{trackLabel(kind)}</span>
                        {isSel && <span className="track-active">selected</span>}
                        <button
                          className="icon-btn"
                          title="Split track clip at playhead"
                          onClick={() => splitTrack(kind)}
                          disabled={locked || !scenes.length}
                        >
                          <Scissors size={12} />
                        </button>
                        <button
                          className="danger-link"
                          onClick={() => deleteTrack(kind)}
                          disabled={locked}
                        >
                          <Trash2 size={11} /> Remove track
                        </button>
                      </div>
                      <div className="track-row-fields">
                        {kind === "visual" && (
                          <>
                            <label className="field">Source in-point (sec)
                              <input
                                type="number" min="0" step="0.5"
                                value={f.inPoint}
                                onChange={(e) =>
                                  updateTrack(kind, { inPoint: Math.max(0, Number(e.target.value) || 0) })
                                }
                              />
                            </label>
                            <label className="field">Duration (sec)
                              <input
                                type="number" min="0.5" step="0.5"
                                value={f.duration}
                                onChange={(e) =>
                                  updateTrack(kind, { duration: Math.max(0.5, Number(e.target.value) || 0.5) })
                                }
                              />
                            </label>
                          </>
                        )}
                        {kind === "narration" && (
                          <>
                            <label className="field">Narration text
                              <textarea
                                rows="2"
                                value={f.text}
                                onChange={(e) => updateTrack(kind, { text: e.target.value })}
                              />
                            </label>
                            <label className="field">Start (sec)
                              <input
                                type="number" min="0" step="0.5"
                                value={f.start}
                                onChange={(e) =>
                                  updateTrack(kind, { start: Math.max(0, Number(e.target.value) || 0) })
                                }
                              />
                            </label>
                            <label className="field">Duration (sec)
                              <input
                                type="number" min="0.5" step="0.5"
                                value={f.duration}
                                onChange={(e) =>
                                  updateTrack(kind, { duration: Math.max(0.5, Number(e.target.value) || 0.5) })
                                }
                              />
                            </label>
                            {/* v0.4.58: the old per-scene volume was never heard (preview or export) and saved the
                                whole scene list on every move; this is the documentary's narration level, live */}
                            <LiveRange
                              label="Narration level (whole documentary)"
                              value={project.narration_volume ?? 1}
                              min={0}
                              max={2}
                              step={0.05}
                              disabled={locked}
                              format={(v) => `${Math.round(v * 100)}%`}
                              onLive={liveNarration}
                              onCommit={commitNarration}
                            />
                          </>
                        )}
                        {kind === "music" && (() => {
                          // v0.4.58 The music follows the project's music placement (Audio tab);
                          // here: does it play in this scene, and choose it for this scene / chapter.
                          const m = normaliseMusic(project.music);
                          const at = offsets[scenes.findIndex((x) => x.id === selected?.id)] ?? 0;
                          const len = selected ? Math.max(1, Math.round((+selected.duration || 0) * 24)) / 24 : 0;
                          const plays = !!musicLay?.runs.some((r) => r.at < at + len && r.end > at);
                          const sid = String(selected?.id ?? "");
                          return (
                            <>
                              <p className="micro-note block">
                                {music ? `${music.name}: ${plays ? "plays in this scene" : "silent in this scene"} (${{ whole: "the whole documentary", range: "a range", once: "once", scenes: "chosen chapters and scenes" }[m.mode]}).` : "No background music chosen yet."}
                              </p>
                              {music && m.mode === "scenes" && (
                                <>
                                  <label className="cs-check">
                                    <input type="checkbox" checked={m.scenes.includes(sid)} disabled={locked}
                                      onChange={(e) => queueSave({ music: { ...m, scenes: e.target.checked ? [...m.scenes, sid] : m.scenes.filter((x) => x !== sid) } })} />
                                    Music in this scene
                                  </label>
                                  {selected?.chapter && (
                                    <label className="cs-check">
                                      <input type="checkbox" checked={m.chapters.includes(selected.chapter)} disabled={locked}
                                        onChange={(e) => queueSave({ music: { ...m, chapters: e.target.checked ? [...m.chapters, selected.chapter] : m.chapters.filter((x) => x !== selected.chapter) } })} />
                                      Music in this chapter ({selected.chapter})
                                    </label>
                                  )}
                                </>
                              )}
                              {music && m.mode !== "scenes" && (
                                <button className="btn" disabled={locked} onClick={() => queueSave({ music: { ...m, mode: "scenes", scenes: [sid], chapters: [] } })}>
                                  Music only in chosen scenes (start with this one)
                                </button>
                              )}
                              <button className="text-link" onClick={() => { setInspectorTab("audio"); setAudioSub("music"); }}>Music settings: track part, loop, crossfade, fades, ducking…</button>
                            </>
                          );
                        })()}
                      </div>
                    </div>
                  );
    });
  }
  function voicePanel() {
    return (
      <>
            <label className="field">
              Narration track
              <select
                value={project.narration_id || ""}
                onChange={(e) =>
                  queueSave({ narration_id: e.target.value || null })
                }
              >
                <option value="">No narration assigned</option>
                {assets
                  .filter((a) => a.has_audio || a.kind === "audio")
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </label>
            {voice && (
              <div className="audio-summary">
                <Mic size={15} />
                <span>
                  {tc(voice.duration)}
                  <small>
                    {voice.generated ? "AI-generated voice" : "Uploaded audio"}
                  </small>
                </span>
                <IconButton
                  icon={Play}
                  label="Preview voice track"
                  onClick={() => {
                    setMediaId(voice.id);
                    setModal("media");
                  }}
                />
              </div>
            )}
            <Button
              className="full"
              icon={Sparkles}
              disabled={locked}
              onClick={() => requireAI("narrate")}
            >
              Generate AI narration
            </Button>
            <button
              className="text-link centered"
              onClick={() => {
                setModal("media");
                fileRef.current.click();
              }}
            >
              <Upload size={12} /> Upload your own voice-over
            </button>
            {voice && (
              <Button
                className="full subtle"
                icon={AudioLines}
                disabled={locked}
                onClick={() => transcribeAsset(voice)}
              >
                Transcribe & align
              </Button>
            )}
            <LiveRange
              label="Narration level"
              value={project.narration_volume ?? 1}
              min={0}
              max={2}
              step={0.05}
              format={(v) => `${Math.round(v * 100)}%`}
              onLive={liveNarration}
              onCommit={commitNarration}
            />
      </>
    );
  }
  function musicPanel() {
    return (
      <>
            <label className="field">
              Background music
              <select
                value={project.music_id || ""}
                onChange={(e) =>
                  queueSave({ music_id: e.target.value || null })
                }
              >
                <option value="">No music assigned</option>
                {assets
                  .filter((a) => a.has_audio || a.kind === "audio")
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </label>
            {music ? (
              <MusicPanel
                project={project}
                music={music}
                scenes={scenes}
                time={time}
                selected={selected}
                disabled={locked}
                preview={musicPreview.current}
                onSave={(m) => queueSave({ music: m })}
                onPlayFrom={(t) => { setTime(Math.max(0, Math.min(duration, t))); setPlaying(true); }}
                volume={project.music_volume ?? 0.12}
                onLiveVolume={liveMusicVolume}
                onCommitVolume={commitMusicVolume}
              />
            ) : (
              <p className="micro-note block">Choose a track to place it: the whole documentary, a range, once, or chosen chapters and scenes, with a seamless loop.</p>
            )}
            <div className="feature-note">
              <ShieldCheck size={15} />
              <div>
                <b>Speech stays in front</b>
                <p>
                  Exports normalize narration and duck music underneath it
                  (auto ducking). The preview applies the same dip.
                </p>
              </div>
            </div>
            <p className="micro-note block">
              The preview plays the music where the export puts it, with the same loops, fades,
              volume and ducking. Supply music you have permission to use.
            </p>
      </>
    );
  }
  // v0.4.67 CapCut layout: the left panel. One icon tab per kind of thing you add to the
  // video, a sub-menu where a tab has parts, and the tab's library or settings beside it.
  const LEFT_TABS = [
    ["media", "Media", Images, [["scenes", "Scenes"], ["all", "All media"], ["video", "Videos"], ["image", "Photos"], ["audio", "Audio files"]]],
    ["audio", "Audio", Music2, [["music", "Music"], ["sfx", "Sound effects"], ["voice", "Narration"]]],
    ["text", "Text", Type, [["templates", "Templates"], ["titles", "Scene titles"], ["names", "Name cards"]]],
    ["stickers", "Stickers", Sticker, [["mark", "Point & mark"], ["subscribe", "Subscribe"], ["shapes", "Arrows & shapes"], ["yours", "Yours"], ["placed", "On your video"]]],
    ["effects", "Effects", WandSparkles, [["video", "Video effects"], ["logo", "Logo"], ["subscribe", "Subscribe"]]],
    ["transitions", "Transitions", ArrowLeftRight, null],
    ["captions", "Captions", Captions, [["styles", "Styles"], ["text", "Text"], ["box", "Box & position"]]],
    ["filters", "Filters", Palette, null],
    ["graphics", "Graphics", Shapes, null],
  ];
  const MEDIA_SORTS = [["timeline", "Order in the edit"], ["newest", "Newest first"], ["oldest", "Oldest first"], ["name", "Name A–Z"], ["longest", "Longest first"]];
  function mediaCard(a, used) {
    return (
      <button
        key={a.id}
        className="cc-card"
        title={`${a.name} · open in the media library`}
        onClick={() => {
          setMediaId(a.id);
          setModal("media");
        }}
      >
        <span className="cc-card-thumb" style={a.thumbnail ? { backgroundImage: `url("${a.thumbnail}")` } : undefined}>
          {!a.thumbnail && (a.kind === "audio" ? <AudioLines size={22} /> : <ImageIcon size={20} />)}
          {used && <b className="cc-badge">Added</b>}
          {audioRoleOf(a, project) && <b className={`cc-role ${audioRoleOf(a, project)}`}>{{ narration: "Narration", music: "Music", sfx: "SFX" }[audioRoleOf(a, project)]}</b>}
          <i className="cc-dur">{a.duration ? tc(a.duration) : a.width ? `${a.width}×${a.height}` : a.kind}</i>
        </span>
        <span className="cc-card-name">{a.name}</span>
      </button>
    );
  }
  function audioRow(a, field, label) {
    const on = project[field] === a.id;
    return (
      <div key={a.id} className={`cc-audio-row ${on ? "on" : ""}`}>
        <span className="cc-audio-icon">{field === "music_id" ? <Music2 size={15} /> : <Mic size={15} />}</span>
        <span className="cc-audio-name" title={a.name}>
          {a.name}
          <span className="cc-audio-meta">
            <small>{a.duration ? tc(a.duration) : a.kind}</small>
            {kindPicker(a)}
          </span>
        </span>
        <button
          className={`btn ${on ? "cc-in-use" : ""}`}
          disabled={locked}
          aria-label={on ? `Stop using ${a.name} as ${label}` : `Use ${a.name} as ${label}`}
          onClick={() => queueSave({ [field]: on ? null : a.id })}
        >
          {on ? <><Check size={12} /> In use</> : <><Plus size={12} /> Use</>}
        </button>
      </div>
    );
  }
  // v0.4.68 what an audio file is: narration, music or a sound effect
  function kindPicker(a) {
    const now = audioRoleOf(a, project) || "";
    return (
      <select
        className="cc-kind"
        aria-label={`What ${a.name} is`}
        title="Narration, music and sound effects are kept apart. Move this file to another kind."
        value={now}
        disabled={locked}
        onChange={(e) => setAudioRole(a, e.target.value || null)}
      >
        {!now && <option value="">Not sorted</option>}
        {AUDIO_ROLES.map(([k, label]) => (
          <option key={k} value={k} disabled={!!roleBlock(a, k, project)}>{label}</option>
        ))}
      </select>
    );
  }
  // Audio imported elsewhere (the Media tab, an older project) waits here to be sorted.
  function unsortedAudio(only) {
    const loose = audioLists(project).unsorted;
    if (!loose.length) return null;
    return (
      <div className="cc-unsorted">
        <div className="section-label">
          <span>NOT SORTED YET · {loose.length}</span>
        </div>
        <p className="micro-note block">Audio you imported from the Media tab. Say what each file is, so narration, music and sound effects stay apart.</p>
        {loose.map((a) => (
          <div key={a.id} className="cc-audio-row">
            <span className="cc-audio-icon"><AudioLines size={15} /></span>
            <span className="cc-audio-name">
              {a.name}
              <small>{a.duration ? tc(a.duration) : a.kind}</small>
            </span>
            <span className="cc-sort-btns">
              {AUDIO_ROLES.filter(([k]) => !only || k === only).map(([k, label]) => (
                <button key={k} className="btn" disabled={locked || !!roleBlock(a, k, project)} title={roleBlock(a, k, project) || `This is ${k === "sfx" ? "a sound effect" : k}`}
                  aria-label={`Sort ${a.name} as ${label.toLowerCase()}`} onClick={() => setAudioRole(a, k)}>
                  {k === "narration" ? <Mic size={12} /> : k === "music" ? <Music2 size={12} /> : <Zap size={12} />} {label}
                </button>
              ))}
            </span>
          </div>
        ))}
      </div>
    );
  }
  // v0.4.69 Effects and Text start with a card for each overlay: a small preview, whether it is
  // on, and a switch. Clicking a card opens its settings below.
  function featureCards(current) {
    const fx = normaliseEffects(project.effects);
    const wm = normaliseWatermark(project.watermark);
    const cta = normaliseCta(project.cta);
    const nc = normaliseNameCards(project.name_cards);
    const thumb = assets.find((a) => a.id === (selected || scenes[0])?.asset_id)?.thumbnail;
    const logo = assets.find((a) => a.id === wm.asset_id);
    const fxOn = [fx.grain > 0, fx.vignette > 0, fx.letterbox].filter(Boolean).length;
    const cards = [
      ["effects", "video", "Video effects", fxOn ? `${fxOn} on` : "Off", fxOn > 0, null, "fx"],
      ["effects", "logo", "Logo", wm.enabled ? (logo ? "On" : "On · choose a logo") : "Off", wm.enabled, (v) => queueSave({ watermark: { ...wm, enabled: v } }), "logo"],
      ["effects", "subscribe", "Subscribe", cta.enabled ? (ctaReady(cta, assets) ? "On" : cta.source === "file" ? "On · choose the file" : "On · choose a banner") : "Off", cta.enabled, (v) => queueSave({ cta: { ...cta, enabled: v } }), "cta"],
      ["text", "names", "Name cards", nc.auto ? "Automatic" : scenes.some((x) => x.lower_third) ? "Typed on scenes" : "Off", nc.auto || scenes.some((x) => x.lower_third), null, "name"],
    ];
    return (
      <div className="cc-feature-cards" role="group" aria-label="Overlays on your video">
        {cards.map(([tab, sub, label, state, on, toggle, kind]) => {
          const open = current === `${tab}/${sub}`;
          return (
            <div key={kind} className={`cc-feature ${open ? "open" : ""} ${on ? "on" : ""}`}>
              <button className="cc-feature-main" aria-label={`${label} settings`} aria-current={open || undefined} onClick={() => openLeft(tab, sub)}>
                <span className={`cc-feature-prev fp-${kind}`} style={thumb ? { backgroundImage: `url("${thumb}")` } : undefined}>
                  {kind === "logo" && <i style={logo?.url ? { backgroundImage: `url("${logo.url}")` } : undefined} />}
                  {kind === "cta" && <i>Subscribe</i>}
                  {kind === "name" && <i><b>Name</b>Who they are</i>}
                  {kind === "fx" && <i />}
                </span>
                <span className="cc-feature-name">{label}</span>
                <small className="cc-feature-state">{state}</small>
              </button>
              {toggle && <Toggle checked={!!on} label={`${label} on the video`} onChange={(v) => !locked && toggle(v)} />}
            </div>
          );
        })}
      </div>
    );
  }
  function renderLeftPanel() {
    const def = LEFT_TABS.find((t) => t[0] === leftTab) || LEFT_TABS[0];
    const [key, , , subs] = def;
    const sub = subs ? (subs.some((x) => x[0] === leftSub[key]) ? leftSub[key] : subs[0][0]) : null;
    const q = mediaQuery.trim().toLowerCase();
    const used = new Set([...scenes.map((s) => s.asset_id), project.narration_id, project.music_id].filter(Boolean));
    const lists = audioLists(project);
    let content;
    if (key === "media") {
      const list = sub === "scenes" ? [] : sortMedia(assets.filter((a) => (sub === "all" || a.kind === sub) && (!q || a.name.toLowerCase().includes(q)) && (!unusedOnly || !used.has(a.id))), mediaSort, scenes);
      const kindCount = (k) => assets.filter((a) => k === "all" || a.kind === k).length;
      content = (
        <>
          <div className="cc-content-head">
            <button className="cc-import" onClick={() => fileRef.current.click()} disabled={locked}>
              <Upload size={13} /> {uploading ? "Uploading…" : "Import"}
            </button>
            {sub === "scenes" && (
              <button className="btn" onClick={addScene} disabled={locked} aria-label="Add scene">
                <Plus size={13} /> Scene
              </button>
            )}
            <label className="cc-search">
              <Search size={13} />
              <input aria-label={sub === "scenes" ? "Search scenes" : "Search media"} placeholder={sub === "scenes" ? "Search scenes" : "Search media"} value={mediaQuery} onChange={(e) => setMediaQuery(e.target.value)} />
            </label>
          </div>
          {sub === "scenes" ? (
            scenes.length ? (
              <div className="cc-grid scenes">
                {scenes.map((s, i) => {
                  if (q && !`${s.title} ${s.chapter || ""} ${s.narration || ""}`.toLowerCase().includes(q)) return null;
                  const a = assets.find((x) => x.id === s.asset_id);
                  return (
                    <div
                      key={s.id}
                      role="button"
                      tabIndex={0}
                      draggable={!q}
                      title={`${s.title} · drag to reorder`}
                      className={`cc-card scene-card ${selected?.id === s.id ? "selected" : ""}`}
                      onClick={() => selectVisualScene(s, i)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") selectVisualScene(s, i);
                      }}
                      onDragStart={() => (dragId.current = s.id)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        dropScene(s.id);
                      }}
                    >
                      <span className={`cc-card-thumb look-${project.look}`} style={a?.thumbnail ? { backgroundImage: `url("${a.thumbnail}")` } : undefined}>
                        {!a && <ImageIcon size={18} />}
                        <b className="cc-num">{String(i + 1).padStart(2, "0")}</b>
                        <i className="cc-dur">{Math.round(s.duration)}s</i>
                        {!s.asset_id && <em className="cc-need">Visual needed</em>}
                      </span>
                      <span className="cc-card-name">{s.title}</span>
                      <span className="cc-card-sub">{tc(offsets[i])} · {s.chapter || "Scene"}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <Empty icon={Clapperboard} title="Your timeline starts here">
                Paste a script, import narration, or add your first scene.
                <Button icon={Plus} onClick={addScene}>
                  Add scene
                </Button>
              </Empty>
            )
          ) : (
            <>
              <div className="cc-media-tools">
                <div className="cc-chips" role="group" aria-label="Show">
                  {[["all", "All"], ["video", "Videos"], ["image", "Photos"], ["audio", "Audio"]].map(([k, label]) => (
                    <button key={k} className={`cc-chip ${sub === k ? "on" : ""}`} aria-pressed={sub === k} onClick={() => openLeft("media", k)}>
                      {label} <small>{kindCount(k)}</small>
                    </button>
                  ))}
                  <button className={`cc-chip ${unusedOnly ? "on" : ""}`} aria-pressed={unusedOnly} title="Only files that are not in your edit yet" onClick={() => setUnusedOnly((v) => !v)}>
                    Not used yet
                  </button>
                </div>
                <label className="cc-sort">
                  <ArrowUpDown size={12} />
                  <select aria-label="Sort media" value={mediaSort} onChange={(e) => setMediaSort(e.target.value)}>
                    {MEDIA_SORTS.map(([k, label]) => (
                      <option key={k} value={k}>{label}</option>
                    ))}
                  </select>
                </label>
              </div>
              {list.length ? (
                <div className="cc-grid">{list.map((a) => mediaCard(a, used.has(a.id)))}</div>
              ) : (
            <div className="cc-empty">
              <Upload size={22} />
              <b>{q || unusedOnly ? "Nothing matches" : "Nothing here yet"}</b>
              <span>{unusedOnly && !q ? "Everything here is already in your edit." : "Import photos, clips and audio. Media: 512 MB/file · 30 files/batch."}</span>
            </div>
              )}
            </>
          )}
          <p className="cc-foot">
            <Info size={12} />
            {sub === "scenes" ? (project.is_demo ? "Sample imagery is AI-generated." : "Drag scenes to reorder your edit.") : "Click a file to preview it, rename it or place it in a scene."}
          </p>
        </>
      );
    } else if (key === "audio") {
      const role = sub === "music" ? "music" : "narration";
      const mine = lists[role];
      content =
        sub === "sfx" ? (
          <>
            {soundPanel(dock ? "list" : undefined)}
            <div className="inspector-content">{unsortedAudio("sfx")}</div>
          </>
        ) : (
          <div className="inspector-content">
            <div className="section-label">
              <span>{sub === "music" ? "BACKGROUND MUSIC" : "NARRATION (VOICE-OVER)"}</span>
              <small>{mine.length} file{mine.length === 1 ? "" : "s"}</small>
            </div>
            <div className="cc-content-head">
              <button className="cc-import" onClick={() => importAudio(role)} disabled={locked}>
                <Upload size={13} /> {uploading ? "Uploading…" : sub === "music" ? "Import music" : "Import a voice-over"}
              </button>
              {sub === "voice" && (
                <button className="btn" disabled={locked} onClick={() => requireAI("narrate")}>
                  <Sparkles size={13} /> AI voice
                </button>
              )}
            </div>
            {mine.length ? (
              mine.map((a) => audioRow(a, role + "_id", role))
            ) : (
              <p className="micro-note block">
                {sub === "music" ? "No music yet. Import an MP3, WAV or M4A you have permission to use." : "No voice-over yet. Import your recorded narration (MP3, WAV, M4A) or make an AI voice."}
              </p>
            )}
            {unsortedAudio()}
            <button className="text-link" onClick={() => { setInspectorTab("audio"); setAudioSub(sub === "music" ? "music" : "voice"); setLayout({ showRight: true }); }}>
              {sub === "music" ? "Music settings: part of the track, loop, fades, ducking" : "Voice settings: level, transcribe and align"} <ArrowUpRight size={12} />
            </button>
            {sub === "music" && <p className="micro-note block">Supply music you have permission to use.</p>}
          </div>
        );
    } else if (key === "text") {
      content =
        sub === "templates" ? (
          // v0.4.73 CapCut's Text → Templates: text stickers with an intro, words you type
          <div className="inspector-content">
            <div className="section-label">
              <span>CLICK TO ADD AT {tc(time)}</span>
            </div>
            <StickerGallery tab="text" assets={assets} grid="sticker-grid cc-sticker-grid" onAdd={(kind) => addSticker(kind)} onUpload={uploadSticker} />
          </div>
        ) : sub === "names" ? (
          <>
            {featureCards("text/names")}
            {effectsPanel(["namecards", "lowerthird"])}
          </>
        ) : (
          <div className="inspector-content">
            <div className="section-label">
              <span>SCENE TITLES</span>
            </div>
            <p className="micro-note block">A scene title shows its chapter and title over the picture. Switch it on for the scenes that open a new part of the story.</p>
            <div className="cc-title-list">
              {scenes.map((s, i) =>
                q && !s.title.toLowerCase().includes(q) ? null : (
                  <div key={s.id} className={`cc-title-row ${selected?.id === s.id ? "selected" : ""}`}>
                    <button className="cc-title-pick" onClick={() => selectVisualScene(s, i)} title="Select this scene">
                      <b>{String(i + 1).padStart(2, "0")}</b>
                      <span>{s.title}</span>
                    </button>
                    <Toggle
                      checked={!!s.show_title}
                      label={`Show the title of scene ${i + 1}`}
                      onChange={(v) => !locked && queueSave({ scenes: scenes.map((x) => (x.id === s.id ? { ...x, show_title: v } : x)) })}
                    />
                  </div>
                ),
              )}
            </div>
          </div>
        );
    } else if (key === "stickers") {
      // v0.4.69 the sticker gallery sits in the tab (as in CapCut); "On your video" lists and edits them
      const placed = normaliseStickers(project.stickers, project.assets).length;
      content =
        sub === "placed" ? (
          stickersPanel(dock ? "list" : undefined)
        ) : (
          <div className="inspector-content">
            <div className="section-label">
              <span>CLICK TO ADD AT {tc(time)}</span>
              {placed > 0 && (
                <button className="text-link" onClick={() => openLeft("stickers", "placed")}>
                  {placed} on your video <ArrowUpRight size={11} />
                </button>
              )}
            </div>
            <StickerGallery tab={sub} assets={assets} grid="sticker-grid cc-sticker-grid" onAdd={(kind, assetId) => addSticker(kind, assetId)} onUpload={uploadSticker} />
            <p className="cc-foot">
              <Info size={12} /> Drag a sticker in the preview to move it. Size, timing and keyframes are under “On your video”.
            </p>
          </div>
        );
    }
    else if (key === "effects")
      content = (
        <>
          {featureCards(`effects/${sub}`)}
          {effectsPanel(sub === "logo" ? ["watermark"] : sub === "subscribe" ? ["cta"] : ["fx"])}
        </>
      );
    else if (key === "transitions") content = effectsPanel(["transitions"]);
    else if (key === "captions") content = captionsPanel(sub);
    else if (key === "filters") content = effectsPanel(["looks"]);
    else content = motionPanel(dock ? "list" : undefined);
    return (
      <>
        <div className="cc-tabs-wrap">
          <div className="cc-tabs" role="tablist" aria-label="Add to your video">
            {LEFT_TABS.map(([k, label, Icon]) => (
              <button key={k} role="tab" aria-selected={leftTab === k} aria-label={label} title={label} className={leftTab === k ? "active" : ""} onClick={() => setLeftTab(k)}>
                <Icon size={17} />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>
        <div className={`cc-left-body ${subs ? "" : "no-sub"}`}>
          {subs && (
            <nav className="cc-subnav" aria-label={`${def[1]} sections`}>
              {subs.map(([k, label]) => {
                // v0.4.69 Media: Scenes and the Library; the chips above the grid pick videos, photos or audio
                if (key === "media" && k !== "scenes" && k !== "all") return null;
                const on = sub === k || (key === "media" && k === "all" && sub !== "scenes");
                return (
                  <button key={k} className={on ? "active" : ""} aria-current={on ? "true" : undefined} onClick={() => setLeftSub((cur) => ({ ...cur, [key]: k }))}>
                    {key === "media" && k === "all" ? "Library" : label}
                    {key === "media" && <small>{k === "scenes" ? scenes.length : assets.length}</small>}
                  </button>
                );
              })}
            </nav>
          )}
          <div className="cc-content inspector cc-inner">{content}</div>
        </div>
      </>
    );
  }
  // The right panel shows what is selected, as CapCut does: Video for the scene's clip,
  // Audio for the narration and the music.
  // v0.4.70 the Director as a tab of the right panel (the floating button still opens and closes it)
  function directorTab() {
    return (
      <button role="tab" aria-selected={false} className="cc-insp-director" title="Direct your edit in plain English" onClick={() => setLayout({ director: true })}>
        <Sparkles size={13} /> Director
      </button>
    );
  }
  function liveFocus() {
    if (!focus || !dock) return null;
    if (focus.kind === "sticker") {
      const st = overlayStickers.find((x) => x.id === stickerId);
      return st && { ...focus, title: stickerLabel(st, assets), when: `${tc(st.start)} · ${st.length.toFixed(1)} s` };
    }
    if (focus.kind === "graphic") {
      const g = overlayGraphics.find((x) => x.id === motionId);
      return g && { ...focus, title: g.title || g.heading || g.lines?.[0]?.text || "Graphic", when: `${tc(g.start)}–${tc(g.end)} · ${{ approved: "approved", suggested: "suggested, not approved yet" }[g.status] || g.status}` };
    }
    if (focus.kind === "sound") {
      const x = (soundPlan?.items || []).find((y) => y.id === soundId);
      return x && { ...focus, title: x.label || "Sound", when: x.t != null ? tc(x.t) : "not placed" };
    }
    if (focus.kind === "cta") return { ...focus, title: "Subscribe animation", when: `${tc(focus.at)}–${tc(focus.end)}` };
    if (focus.kind === "caption") {
      const i = scenes.findIndex((x) => x.id === focus.cap.sceneId);
      return i >= 0 && { ...focus, sceneIndex: i, title: `“${focus.cap.text}”`, when: `${tc(focus.cap.start)}–${tc(focus.cap.end)} · scene ${String(i + 1).padStart(2, "0")}` };
    }
    return null;
  }
  function renderFocus(f) {
    const KIND = { sticker: ["Sticker", Sticker], graphic: ["Graphic", Shapes], sound: ["Sound effect", Zap], cta: ["Subscribe", WandSparkles], caption: ["Caption", Captions] }[f.kind];
    const [kindLabel, Icon] = KIND;
    const capSubs = [["words", "Words"], ["styles", "Style"], ["text", "Text"], ["box", "Box & position"]];
    // Back shows the scene where this item is (under the playhead), as the player does
    const hereIndex = (() => {
      const i = scenes.findIndex((x, k) => time < (offsets[k] || 0) + x.duration);
      return i < 0 ? scenes.length - 1 : i;
    })();
    const back = hereIndex >= 0 ? `Scene ${String(hereIndex + 1).padStart(2, "0")}` : "the scene";
    return (
      <>
        <div className="inspector-tabs cc-insp-tabs" role="tablist" aria-label="Selected item">
          <button role="tab" aria-selected className="active">{kindLabel}</button>
          <span className="cc-insp-what" />
          {directorTab()}
        </div>
        <div className="cc-focus-head">
          <span className={`cc-focus-icon k-${f.kind}`}><Icon size={15} /></span>
          <div className="cc-focus-what">
            <b title={f.title}>{f.title}</b>
            <small>{f.when}</small>
          </div>
          <button className="btn cc-focus-back" aria-label="Back to the scene" title={`Show ${back} again`} onClick={() => { setFocus(null); if (scenes[hereIndex]) setSelectedId(scenes[hereIndex].id); }}>
            <ArrowLeft size={12} /> {back}
          </button>
        </div>
        {f.kind === "caption" && (
          <div className="cc-subtabs" role="tablist">
            {capSubs.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={captionSub === k} className={captionSub === k ? "active" : ""} onClick={() => setCaptionSub(k)}>
                {label}
              </button>
            ))}
          </div>
        )}
        {f.kind === "sticker" && stickersPanel("focus")}
        {f.kind === "graphic" && motionPanel("focus")}
        {f.kind === "sound" && soundPanel("focus")}
        {f.kind === "cta" && effectsPanel(["cta"])}
        {f.kind === "caption" &&
          (captionSub === "words" ? (
            <div className="inspector-content">
              <div className="section-label">
                <span>THIS CAPTION</span>
                <small>{f.when}</small>
              </div>
              <p className="cc-cap-line">{f.cap.text}</p>
              <p className="micro-note block">
                Captions are made from the narration of scene {String(f.sceneIndex + 1).padStart(2, "0")}, timed to the voice. To change the words, change the narration.
              </p>
              <div className="st-actions">
                <button className="btn" onClick={() => { setFocus(null); setInspectorTab("video"); setVideoSub("story"); }}>
                  Edit the narration of scene {String(f.sceneIndex + 1).padStart(2, "0")}
                </button>
                <button className="btn" onClick={() => { setTime(f.cap.start); setPlaying(true); }}>
                  <Play size={12} /> Play from here
                </button>
              </div>
              <label className="cs-toggle">
                <input type="checkbox" aria-label="Captions in the video" checked={!!project.captions} disabled={locked} onChange={(e) => queueSave({ captions: e.target.checked })} />
                <span>Captions in the video</span>
              </label>
            </div>
          ) : (
            captionsPanel(captionSub)
          ))}
      </>
    );
  }
  function renderDockedDirector() {
    return (
      <>
        <div className="inspector-tabs cc-insp-tabs" role="tablist" aria-label="Director">
          <button role="tab" aria-selected={false} onClick={() => setLayout({ director: false })}>
            {liveFocus() ? { sticker: "Sticker", graphic: "Graphic", sound: "Sound effect", cta: "Subscribe", caption: "Caption" }[focus.kind] : "Video"}
          </button>
          <span className="cc-insp-what" />
          <button role="tab" aria-selected className="cc-insp-director active">
            <Sparkles size={13} /> Director
          </button>
        </div>
        <section className="cc-director-dock" role="region" aria-label="Director">
          <header>
            <b>Tell the Director what to change</b>
            <small>{config.connected ? "AI connected" : "Local commands; AI when you connect a service"}</small>
            <button type="button" className="layout-btn" aria-label="Close the Director" title="Close the Director (your history is kept)" onClick={() => setLayout({ director: false })}>
              <X size={14} />
            </button>
          </header>
          {directorBody()}
        </section>
      </>
    );
  }
  function renderInspector() {
    if (layout.director && dock) return renderDockedDirector();
    const f = liveFocus();
    if (f) return renderFocus(f);
    const subs = inspectorTab === "audio"
      ? [["voice", "Voice"], ["music", "Music"]]
      : [["basic", "Basic"], ["picture", "Picture"], ["story", "Story"], ["tracks", "Tracks"]];
    const sub = inspectorTab === "audio" ? audioSub : videoSub;
    const setSub = inspectorTab === "audio" ? setAudioSub : setVideoSub;
    const clip = selectedTrack && selected && selectedTrack.sceneId === selected.id && selectedTrack.kind !== "visual" ? selectedTrack.kind : null;
    return (
      <>
        <div className="inspector-tabs cc-insp-tabs" role="tablist" aria-label="Selected clip">
          {[
            ["video", "Video"],
            ["audio", "Audio"],
          ].map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={inspectorTab === key}
              className={inspectorTab === key ? "active" : ""}
              onClick={() => setInspectorTab(key)}
            >
              {label}
            </button>
          ))}
          <span className="cc-insp-what">
            {selected ? `Scene ${String(scenes.indexOf(selected) + 1).padStart(2, "0")}` : "Nothing selected"}
          </span>
          {dock && directorTab()}
        </div>
        <div className="cc-subtabs" role="tablist">
          {subs.map(([key, label]) => (
            <button key={key} role="tab" aria-selected={sub === key} className={sub === key ? "active" : ""} onClick={() => setSub(key)}>
              {label}
            </button>
          ))}
        </div>
        {inspectorTab === "audio" ? (
          <div className="inspector-content">
            {clip && (
              <>
                <div className="section-label">
                  <span>SELECTED CLIP · {trackLabel(clip).toUpperCase()} · SCENE {String(scenes.indexOf(selected) + 1).padStart(2, "0")}</span>
                </div>
                {trackRows([clip])}
                <div className="inspector-divider" />
              </>
            )}
            {audioSub === "music" ? musicPanel() : voicePanel()}
          </div>
        ) : videoSub === "picture" ? (
          effectsPanel(["picture"])
        ) : (
          <div className="inspector-content">
            {selected ? (
              videoSub === "story" ? (
                <>
                <label className="field">
                  Source references
                  <input
                    aria-label="Scene source references"
                    key={
                      selected.id +
                      "refs" +
                      (selected.source_ids || []).join(",")
                    }
                    defaultValue={(selected.source_ids || []).join(", ")}
                    placeholder="S1, S2"
                    onBlur={(e) => {
                      const refs = e.target.value
                        .toUpperCase()
                        .split(/[,;\s]+/)
                        .filter(Boolean);
                      if (refs.some((ref) => !/^S\d+$/.test(ref))) {
                        notify(
                          "Use source IDs such as S1, S2. Add sources in Research first.",
                          "error",
                        );
                        return;
                      }
                      if (
                        JSON.stringify(refs) !==
                        JSON.stringify(selected.source_ids || [])
                      )
                        updateScene({ source_ids: [...new Set(refs)] });
                    }}
                  />
                </label>
                <p className="inspector-source-hint">
                  {project.sources.length
                    ? "Library: " + project.sources.map((x) => x.id).join(", ")
                    : "Add original records or notes in Research, then link their IDs here."}
                </p>
                <label className="field">
                  Chapter label
                  <input
                    aria-label="Scene chapter label"
                    value={selected.chapter || ""}
                    onChange={(e) => updateScene({ chapter: e.target.value })}
                  />
                </label>
                <label className="field">
                  Narration{" "}
                  <span className="field-note">
                    {wc(selected.narration)} words
                  </span>
                  <textarea
                    rows="5"
                    value={selected.narration}
                    placeholder="Add the narration for this scene…"
                    onChange={(e) => updateScene({ narration: e.target.value })}
                  />
                </label>
                <div className="micro-note">
                  <Clock3 size={12} />
                  {selected.timing === "imported-captions"
                    ? "Supplied caption timestamps · cue/audio review required"
                    : selected.timing === "transcribed"
                      ? "Source-aligned segment timing"
                      : selected.timing === "scene-aligned"
                        ? "Voice aligned by scene; captions estimated"
                        : "Estimated timing · review with narration"}
                </div>
                </>
              ) : videoSub === "tracks" ? (
                <>
                <div className="section-label">
                  <span>TRACKS</span>
                  <span className="track-pill">
                    {selectedTrack
                      ? trackLabel(selectedTrack.kind) + " · scene " + (scenes.indexOf(selected) + 1)
                      : "Click a clip on any timeline lane to select its track"}
                  </span>
                </div>
                  {trackRows(["visual", "narration", "music"])}
                </>
              ) : (
                <>
                <div className="section-label">
                  <span>
                    SCENE{" "}
                    {String(scenes.indexOf(selected) + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <IconButton
                      icon={ArrowUp}
                      label="Move scene earlier"
                      onClick={() => moveScene(selected.id, -1)}
                      disabled={scenes[0]?.id === selected.id}
                    />
                    <IconButton
                      icon={ArrowDown}
                      label="Move scene later"
                      onClick={() => moveScene(selected.id, 1)}
                      disabled={scenes.at(-1)?.id === selected.id}
                    />
                  </div>
                </div>
                <label className="field">
                  Scene title
                  <input
                    value={selected.title}
                    onChange={(e) => updateScene({ title: e.target.value })}
                  />
                </label>
                <div className="field-row">
                  <label className="field">
                    Duration
                    <div className="input-unit">
                      <input
                        aria-label="Scene duration"
                        type="number"
                        min="0.5"
                        max="600"
                        step="0.5"
                        value={selected.duration}
                        onChange={(e) =>
                          updateScene({
                            duration: Math.max(
                              0.5,
                              Math.min(600, Number(e.target.value) || 0.5),
                            ),
                          })
                        }
                      />
                      <span>sec</span>
                    </div>
                  </label>
                  <div className="field">
                    Transition in
                    <button className="fx-jump" onClick={() => openLeft("transitions")}>
                      {TRANS_LABEL[transitionId(selected.transition)]} <ArrowUpRight size={11} />
                    </button>
                  </div>
                </div>
                <div className="field rp-current">
                  Picture
                  <div className="rp-now">
                    <span className="rp-now-thumb" style={{ backgroundImage: (() => { const a = assets.find((x) => x.id === selected.asset_id); return a ? `url("${a.thumbnail || a.url}")` : undefined; })() }} />
                    <div>
                      <b>{assets.find((x) => x.id === selected.asset_id)?.name || "No picture"}</b>
                      {selected.replaced && <small className="rp-tag">Replaced by you</small>}
                      <div className="rp-now-actions">
                        <button className="btn" aria-label="Replace the picture" disabled={locked} onClick={() => setModal("replace")}>
                          Replace…
                        </button>
                        {selected.replaced && project.episode?.guide && (
                          <button className="text-link" disabled={locked} onClick={() =>
                            api(`/api/projects/${project.id}/episode/restore-scene`, "POST", { scene_id: selected.id })
                              .then((p) => { setProject(p); notify("The guide’s picture is back."); })
                              .catch(report)
                          }>
                            Restore the guide’s picture
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
                <button
                  className="text-link"
                  onClick={() => {
                    setMediaId(selected.asset_id);
                    setModal("media");
                  }}
                >
                  <Layers size={12} /> Browse media library{" "}
                  <ArrowUpRight size={12} />
                </button>
                <div className="inspector-divider" />
                <p className="micro-note block">
                  Crop, fill and movement are in{" "}
                  <button className="fx-jump" onClick={() => setVideoSub("picture")}>Picture</button>; transitions, filters and name cards in the tabs on the left.
                </p>
                {assets.find((a) => a.id === selected.asset_id)?.kind ===
                  "video" && (
                  <label className="field">
                    Source in-point (seconds)
                    <input
                      type="number"
                      min="0"
                      value={selected.trim_start || 0}
                      onChange={(e) =>
                        updateScene({
                          trim_start: Math.max(0, Number(e.target.value) || 0),
                        })
                      }
                    />
                  </label>
                )}
                <div className="switch-line">
                  <span>Show scene title</span>
                  <Toggle
                    checked={selected.show_title}
                    onChange={(v) => updateScene({ show_title: v })}
                    label="Show scene title"
                  />
                </div>
                <div className="switch-line">
                  <span>Subtitles</span>
                  <Toggle
                    checked={project.captions}
                    onChange={(v) => queueSave({ captions: v })}
                    label="Subtitles"
                  />
                </div>
                <div className="inspector-divider" />
                <button
                  className="danger-link"
                  onClick={() => {
                    if (
                      window.confirm("Remove this scene from the timeline?")
                    ) {
                      queueSave({
                        scenes: scenes.filter((s) => s.id !== selected.id),
                      });
                      setTime(0);
                      setSelectedId(null);
                    }
                  }}
                >
                  <Trash2 size={12} /> Remove scene
                </button>
                </>
              )
            ) : (
              <Empty title="No scene selected">
                Click a clip on the timeline, or a scene in Media, to edit it here.
              </Empty>
            )}
          </div>
        )}
      </>
    );
  }

  return (
    <div className={`app-shell ${home ? "" : "cc-shell"}`}>
      <aside className="rail">
        <button
          className="brand-mark"
          title="Home"
          onClick={() => {
            setPlaying(false);
            setHome(true);
          }}
        >
          <img src="/assets/favicon.svg" alt="Casefile Studio" />
        </button>
        <div className="rail-group">
          <IconButton
            className={home ? "active" : ""}
            icon={HomeIcon}
            label="Home"
            onClick={() => {
              setPlaying(false);
              setHome(true);
            }}
          />
          <IconButton
            icon={Sparkles}
            label={
              project.episode?.guide
                ? "Episode setup"
                : "Guided automatic production"
            }
            onClick={() =>
              project.episode?.guide
                ? (setTab("setup"), setPlaying(false))
                : openTool("production")
            }
          />
          <IconButton
            className={tab === "edit" ? "active" : ""}
            icon={Clapperboard}
            label="Editing workspace"
            onClick={() =>
              project.episode?.guide &&
              (!project.scenes.some((s) => s.asset_id) ||
                project.episode.plan?.mode === "inspection")
                ? makeFirstDraft()
                : setTab("edit")
            }
          />
          <IconButton
            icon={Layers}
            label="Media library"
            onClick={() => {
              setMediaId(null);
              setModal("media");
            }}
          />
          <IconButton
            icon={FolderOpen}
            label="Your projects"
            onClick={() => {
              refreshProjects();
              setModal("projects");
            }}
          />
          <IconButton
            className={tab === "review" ? "active" : ""}
            icon={Download}
            label="Exports and review"
            onClick={() => setTab("review")}
          />
        </div>
        <div className="rail-bottom">
          <IconButton
            icon={CircleHelp}
            label="How this workspace works"
            onClick={() => setModal("help")}
          />
          <IconButton
            icon={Settings2}
            label="Settings and AI connection"
            onClick={() => setModal("settings")}
          />
          <div
            className="workspace-avatar"
            title="Single workspace · working prototype"
          >
            CS
          </div>
        </div>
      </aside>
      {home && (
        <Home
          api={api}
          current={project}
          version={APP_VERSION}
          onCreate={() => setModal("new")}
          onOpen={(id) => (id === project.id ? setHome(false) : openProject(id))}
          onDelete={deleteProject}
          onTool={(t) => {
            setTab(t);
            setHome(false);
          }}
        />
      )}
      <div className={`workspace cc ${tab === "edit" ? "cc-edit" : ""} ${playing ? "is-playing" : ""}`} hidden={home}>
        {/* v0.4.67 one slim bar, as in CapCut: menu, project and save state · the pages · export */}
        <header className="topbar cc-topbar">
          <div className="cc-top-left">
            <div className="cc-menu">
              <button className="cc-menu-btn" aria-label="Menu" title="Menu: home, projects, media, help, settings" aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)}>
                <img src="/assets/favicon.svg" alt="" />
                <Menu size={14} />
              </button>
              {menuOpen && (
                <>
                  <div className="cc-menu-scrim" onClick={() => setMenuOpen(false)} />
                  <div className="cc-menu-list" role="menu" onClick={() => setMenuOpen(false)}>
                    <button role="menuitem" onClick={() => { setPlaying(false); setHome(true); }}>
                      <HomeIcon size={14} /> Home
                    </button>
                    <button role="menuitem" onClick={() => { refreshProjects(); setModal("projects"); }}>
                      <FolderOpen size={14} /> Your projects
                    </button>
                    <button role="menuitem" onClick={() => setModal("new")}>
                      <Plus size={14} /> New project
                    </button>
                    <button role="menuitem" onClick={() => { setMediaId(null); setModal("media"); }}>
                      <Layers size={14} /> Media library
                    </button>
                    <button role="menuitem" aria-label="Save project backup" title="Save project settings now; no server connection needed. Media is not included." onClick={() => downloadProjectSnapshot(project, setDownloadGate)}>
                      <FileJson size={14} /> Save backup
                    </button>
                    {!project.episode?.guide && (
                      <button role="menuitem" onClick={() => openTool("production")}>
                        <Sparkles size={14} /> Guided automatic production
                      </button>
                    )}
                    <i />
                    <button role="menuitem" onClick={() => setModal("help")}>
                      <CircleHelp size={14} /> How this workspace works
                    </button>
                    <button role="menuitem" onClick={() => setModal("settings")}>
                      <Settings2 size={14} /> Settings and AI connection
                    </button>
                    <small>Casefile Studio · working prototype · v{APP_VERSION}</small>
                  </div>
                </>
              )}
            </div>
            <div className="cc-title">
              <h1 title={project.title}>{project.title}</h1>
              <button
                className="project-switch"
                aria-label="Switch project"
                onClick={() => {
                  refreshProjects();
                  setModal("projects");
                }}
              >
                <ChevronDown size={15} />
              </button>
              {project.is_demo && tab !== "edit" && <Badge tone="demo">Fictional sample</Badge>}
            </div>
            <span
              className={`save-state ${saving === "error" ? "error" : ""}`}
              title={`${saving === "saved" ? `Auto saved${savedClock(project.updated_at)} · ` : ""}${project.target_minutes} min target · ${tc(duration)} ${project.episode?.guide ? (voice ? "planned" : project.episode?.timings ? "timed plan · audio missing" : "estimated plan") : "assembled"}`}
            >
              {saving === "saving" || saving === "pending" ? (
                <LoaderCircle size={12} className="spin" />
              ) : saving === "error" ? (
                <AlertTriangle size={12} />
              ) : (
                <CheckCircle2 size={12} />
              )}
              {/* v0.4.72 the words go when the bar is tight (the icon stays; the words are in the tooltip) */}
              <span className="save-text">
                {saving === "saved"
                  ? `Auto saved${savedClock(project.updated_at)}`
                  : saving === "error"
                    ? "Save failed — retry editing"
                    : "Saving…"}
              </span>
            </span>
          </div>
        <nav className="stage-nav cc-pages" aria-label="Pages">
          {[
            ["setup", "Episode setup", FolderOpen, null],
            ["desk", "Case desk", BookOpen, null],
            ["research", "Research", Search, project.sources.length],
            ["script", "Script", FileText, null],
            ["edit", "Edit", Clapperboard, scenes.length],
            ["review", "Review & export", ShieldCheck, null],
            ["recut", "Re-cut", Scissors, null],
          ].map(([key, label, Icon, count], i) => (
            <button
              key={key}
              className={`${tab === key ? "active" : ""} ${key === "setup" ? "setup-nav" : ""}`}
              title={label}
              aria-current={tab === key ? "page" : undefined}
              onClick={() => {
                if (
                  key === "edit" &&
                  project.episode?.guide &&
                  (!project.scenes.some((s) => s.asset_id) ||
                    project.episode.plan?.mode === "inspection")
                ) {
                  makeFirstDraft();
                  return;
                }
                setTab(key);
                setPlaying(false);
              }}
            >
              <Icon size={14} />
              <span>{label}</span>
              {count > 0 && <span className="stage-count">{count}</span>}
            </button>
          ))}
        </nav>
          <div className="cc-top-right">
            <button className="cc-search-btn" aria-label="Search" title="Search tools, settings, scenes and files (Ctrl+K / ⌘K)" onClick={() => setSearchOpen(true)}>
              <Search size={14} />
              <span>Search</span>
              <kbd>{IS_MAC ? "⌘K" : "Ctrl K"}</kbd>
            </button>
            {tab !== "edit" && (
              <>
                <IconButton
                  icon={Undo2}
                  label={historyLabel(project, "undo")}
                  onClick={() => stepHistory("undo")}
                  disabled={locked || !project.history?.undo?.length}
                />
                <IconButton
                  icon={Redo2}
                  label={historyLabel(project, "redo")}
                  onClick={() => stepHistory("redo")}
                  disabled={locked || !project.history?.redo?.length}
                />
              <div className="aspect-switch">
                <button className="aspect-label" aria-label="Video format" aria-expanded={modal === "format"} onClick={() => setModal(modal === "format" ? null : "format")}>
                  <Monitor size={12} /> {FORMATS[aspectOf(project)].label} <ChevronDown size={11} />
                </button>
                {modal === "format" && (
                  <div className="aspect-menu" role="menu">
                    {Object.entries(FORMATS).map(([k, f]) => (
                      <button
                        key={k}
                        role="menuitemradio"
                        aria-checked={aspectOf(project) === k}
                        className={aspectOf(project) === k ? "on" : ""}
                        disabled={locked}
                        onClick={() => queueSave({ aspect: k })}
                      >
                        <i className={`aspect-shape ${k === "9:16" ? "tall" : "wide"}`} />
                        <span>
                          <b>{k}</b> {f.label.split("·")[1]}
                        </span>
                      </button>
                    ))}
                    {aspectOf(project) === "9:16" && (
                      <div className="aspect-fit">
                        <small>Wide footage in a tall frame</small>
                        {FITS.map((f) => (
                          <label key={f.id}>
                            <input type="radio" name="vertical-fit" aria-label={f.label} checked={fitOf(project) === f.id} disabled={locked} onChange={() => queueSave({ vertical_fit: f.id })} />
                            {f.label}
                          </label>
                        ))}
                        <small>Captions stay above the app buttons at the bottom of the screen.</small>
                      </div>
                    )}
                    <button className="aspect-done" onClick={() => setModal(null)}>Done</button>
                  </div>
                )}
              </div>
              </>
            )}
            <button
              className={`connection ${config.connected ? "connected" : ""}`}
              onClick={() => setModal("settings")}
              title={config.connected ? "AI connected · settings" : "Connect an AI service"}
            >
              <Sparkles size={13} />
              <span>{config.connected ? "AI connected" : "Connect AI"}</span>
            </button>
            {!project.episode?.guide && (
              <Button
                icon={Sparkles}
                kind="produce"
                onClick={() => openTool("production")}
              >
                Produce draft
              </Button>
            )}
            {project.exports[0] && (
              <a
                className="btn cc-dl"
                title="Download the latest MP4"
                aria-label="Download latest MP4"
                onClick={(ev) => {
                  if (window.top !== window) {
                    ev.preventDefault();
                    setDownloadGate({
                      kind: "video",
                      url: new URL(
                        `/api/projects/${project.id}/exports/${project.exports[0].id}/download`,
                        window.location.origin,
                      ).href,
                    });
                  }
                }}
                href={`/api/projects/${project.id}/exports/${project.exports[0].id}/download`}
                download
              >
                <Download size={14} /> <span>MP4</span>
              </a>
            )}
            <Button
              kind="primary cc-export"
              icon={Upload}
              disabled={locked}
              aria-label={project.episode?.guide ? "Make video" : "Export video"}
              title={project.episode?.guide ? "Make the video (render an MP4)" : "Export the video"}
              onClick={() =>
                project.episode?.guide
                  ? makeFirstDraft({ render: true })
                  : openTool("export", "review")
              }
            >
              Export
            </Button>
          </div>
        </header>

        {recoveredSetup && (
          <div className="recovery-notice">
            <b>A newer saved setup was found in this browser.</b>
            <p>
              {recoveredSetup.project.title} ·{" "}
              {recoveredSetup.project.assets?.length || 0} media references.
              Download this before continuing with an older server copy; media
              files are not inside this JSON.
            </p>
            <button
              className="btn"
              aria-label="Download recovered setup"
              onClick={() =>
                downloadProjectSnapshot(recoveredSetup.project, setDownloadGate)
              }
            >
              Save recovered setup
            </button>
            <button className="btn" onClick={() => setRecoveredSetup(null)}>
              Dismiss
            </button>
          </div>
        )}
        {uploadProgress && (
          <div className="global-upload-progress">
            <UploadProgress progress={uploadProgress} />
          </div>
        )}
        {tab === "recut" && (
          <Recut
            key={"recut" + project.id}
            project={project}
            api={api}
            locked={locked}
            onProject={setProject}
            onError={report}
            onNotify={notify}
          />
        )}
        {tab === "desk" && (
          <CaseDesk
            key={"desk" + project.id}
            project={project}
            api={api}
            locked={locked}
            onError={report}
            onNotify={notify}
          />
        )}
        {tab === "setup" && (
          <EpisodeSetup
            key={project.id}
            project={project}
            api={api}
            locked={locked}
            onFlush={flushSave}
            onBusy={setBusy}
            onError={report}
            onNotify={notify}
            onProject={(p) => {
              acceptProject(p);
              if (!p.scenes.some((s) => s.id === selectedId)) {
                setSelectedId(p.scenes[0]?.id);
                setTime(0);
              }
            }}
            onNavigate={(next) => {
              setTab(next);
              setPlaying(false);
              if (next === "edit") {
                const firstVisual = project.scenes.findIndex(
                  (scene) => scene.asset_id,
                );
                if (firstVisual >= 0) {
                  setSelectedId(project.scenes[firstVisual].id);
                  setTime(
                    sum(project.scenes.slice(0, firstVisual)) +
                      Math.min(
                        1 / 24,
                        project.scenes[firstVisual].duration / 2,
                      ),
                  );
                }
              }
            }}
            onRender={startRender}
            onQuickDraft={makeFirstDraft}
            backupStatus={backupStatus}
            onNew={() => setModal("new")}
          />
        )}
        {tab === "edit" && (
          <div
            className={`edit-grid ${layout.showLeft ? "" : "no-left"} ${layout.showRight ? "" : "no-right"}`}
            ref={gridRef}
            style={editGridStyle()}
          >
            {layout.showLeft && (
              <div
                className="splitter col"
                role="separator"
                aria-label="Resize the media panel"
                title="Drag to resize · double-click to reset"
                style={{ left: fit.left + GRID_PAD, bottom: fit.timeline + 2 * GRID_PAD }}
                onPointerDown={(e) => resizePanel(e, "left")}
                onDoubleClick={() => setLayout({ left: LAYOUT_DEFAULTS.left })}
              />
            )}
            {layout.showRight && (
              <div
                className="splitter col"
                role="separator"
                aria-label="Resize the inspector"
                title="Drag to resize · double-click to reset"
                style={{ right: fit.right + GRID_PAD, bottom: fit.timeline + 2 * GRID_PAD }}
                onPointerDown={(e) => resizePanel(e, "right")}
                onDoubleClick={() => setLayout({ right: LAYOUT_DEFAULTS.right })}
              />
            )}
            <div
              className="splitter row"
              role="separator"
              aria-label="Resize the timeline"
              title="Drag to make the timeline taller or shorter · double-click to reset"
              style={{ bottom: fit.timeline + GRID_PAD }}
              onPointerDown={(e) => resizePanel(e, "timeline")}
              onDoubleClick={() => setLayout({ timeline: LAYOUT_DEFAULTS.timeline })}
            />
            <section className="scene-panel cc-left" hidden={!layout.showLeft}>{renderLeftPanel()}</section>
            <section className="monitor-panel">
              <div className="monitor-header cc-player-head">
                <span>
                  Player
                  <i>{scenes.length ? ` · Scene ${activeIndex + 1} of ${scenes.length}` : ""}</i>
                </span>
                <div>
                  {project.is_demo && <Badge>FICTIONAL DEMO</Badge>}
                  <button
                    className={`layout-btn ${layout.showLeft ? "on" : ""}`}
                    aria-label={layout.showLeft ? "Hide the left panel" : "Show the left panel"}
                    title={layout.showLeft ? "Hide the left panel (Media, Audio, Text …)" : "Show the left panel (Media, Audio, Text …)"}
                    onClick={() => setLayout({ showLeft: !layout.showLeft })}
                  >
                    <PanelLeft size={15} />
                  </button>
                  <button
                    className={`layout-btn ${layout.showRight ? "on" : ""}`}
                    aria-label={layout.showRight ? "Hide the inspector" : "Show the inspector"}
                    title={layout.showRight ? "Hide the right panel (the selected clip)" : "Show the right panel (the selected clip)"}
                    onClick={() => setLayout({ showRight: !layout.showRight })}
                  >
                    <PanelRight size={15} />
                  </button>
                  <IconButton
                    className="mobile-inspector"
                    icon={PanelRight}
                    label="Open scene inspector"
                    onClick={() => setModal("inspector")}
                  />
                </div>
              </div>
              <div className={`monitor-screen ${fullMode === "window" ? "full-window" : ""}`} ref={screenRef}>
                {fullMode && (
                  <div className="full-bar">
                    <button type="button" aria-label={playing ? "Pause (full screen)" : "Play (full screen)"} title="Play / pause (Space)" onClick={() => setPlaying((v) => !v)} disabled={!scenes.length}>
                      {playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
                    </button>
                    <span className="full-time">{tc(time, true)} / {tc(duration, true)}</span>
                    <input type="range" aria-label="Playhead (full screen)" min="0" max={duration || 0} step="0.04" value={Math.min(time, duration || 0)}
                      onChange={(e) => { setPlaying(false); setTime(+e.target.value); }} />
                    <button type="button" aria-label="Exit full screen" title="Exit full screen (Esc)" onClick={exitFull}>
                      <Minimize2 size={15} />
                    </button>
                  </div>
                )}
                <div
                  className={`video-frame look-${hoverLook || project.look} ${aspectOf(project) === "9:16" ? "tall" : ""} ${hoverLook && hoverLook !== project.look ? "look-trying" : ""}`}
                  data-trying={hoverLook && hoverLook !== project.look ? `Trying: ${lookOf(hoverLook).label}` : undefined}
                  style={{ width: frameSize.width, height: frameSize.height }}
                >
                  {(() => {
                    const local = time - (offsets[activeIndex] || 0);
                    const dur = activeScene?.duration || 1;
                    const look = lookOf(hoverLook || project.look); // v0.4.69 a look you point at shows here first
                    const trId = transitionId(activeScene?.transition);
                    const trD = activeScene ? transitionLength(activeScene, dur) : 0;
                    let q = trD > 0 && local < trD && (activeIndex > 0 || trId === "fade") ? local / trD : 1;
                    let fadeOut = 1;
                    if (trId === "fade" && trD > 0 && local > dur - trD) fadeOut = Math.max(0, (dur - local) / trD);
                    const prev = activeIndex > 0 ? scenes[activeIndex - 1] : null;
                    const prevAsset = prev && assets.find((x) => x.id === prev.asset_id);
                    const under = transitionUnder(trId, q);
                    const media = q < 1 ? transitionStyle(trId, q) : {};
                    const fx = normaliseEffects(project.effects);
                    const bar = fx.letterbox ? letterboxBar(frameSize.width, frameSize.height) : 0;
                    return (
                      <>
                        <div className="fx-under" style={{ background: under.colour || "#000" }}>
                          {q < 1 && prevAsset && under.prevOpacity > 0 && (
                            <img
                              src={prevAsset.kind === "image" ? prevAsset.url : prevAsset.thumbnail}
                              alt=""
                              style={{ opacity: under.prevOpacity, filter: look.css, transform: prevAsset.kind === "image" ? motionTransform(prev.motion, 1) : undefined }}
                            />
                          )}
                        </div>
                        <div className="fx-media" style={{ ...media, opacity: (media.opacity ?? 1) * fadeOut }}>
                          {visual && (visual.kind === "video" || visual.kind === "image") ? (
                            (() => {
                              // v0.4.49: the media file's crop, the scene's fill, then its
                              // keyframes or fixed movement — as the export builds it.
                              const keys = normaliseKeyframes(activeScene?.keyframes, dur);
                              const cam = keys.length ? cameraTransform(cameraAt(keys, local)) : null;
                              return (
                                <PictureLayer
                                  asset={visual}
                                  crop={cropOf(visual)}
                                  fit={pictureFit(project, activeScene, visual)}
                                  width={frameSize.width}
                                  height={frameSize.height}
                                  lookCss={look.css}
                                  alt={visual.name}
                                  transform={cam || (visual.kind === "image" ? motionTransform(activeScene?.motion, local / dur) : undefined)}
                                  origin={cam ? "0 0" : undefined}
                                  videoRef={videoRef}
                                  onLoadedMetadata={() => setTime((t) => t)}
                                />
                              );
                            })()
                          ) : (
                            <div className="missing-visual">
                              <ImageIcon size={30} />
                              <span>
                                {scenes.length
                                  ? "Visual needed"
                                  : "Your next story starts here"}
                              </span>
                              <button onClick={() => setModal("media")}>
                                Import media <ArrowUpRight size={12} />
                              </button>
                            </div>
                          )}
                          {visual && look.tint && <i className="fx-tint" style={{ background: look.tint }} />}
                        </div>
                        {fx.vignette > 0 && (
                          <div className="fx-vignette" style={{ background: `radial-gradient(ellipse at center, transparent 42%, rgba(0,0,0,${(0.9 * fx.vignette).toFixed(3)}) 100%)` }} />
                        )}
                        {fx.grain > 0 && <div className="fx-grain" style={{ opacity: (0.06 + 0.3 * fx.grain).toFixed(3) }} />}
                        {bar > 0 && (
                          <>
                            <div className="fx-bar top" style={{ height: bar }} />
                            <div className="fx-bar bottom" style={{ height: bar }} />
                          </>
                        )}
                      </>
                    );
                  })()}
                  <div className="film-shade" />
                  {activeScene?.show_title && (
                    <div
                      className="film-title"
                      style={{
                        fontSize: Math.max(16, frameSize.width * 0.045),
                      }}
                    >
                      <div className="film-rule" />
                      <p>
                        {String(activeIndex + 1).padStart(2, "0")} /{" "}
                        {activeScene.chapter || "DOCUMENTARY"}
                      </p>
                      <h2>{activeScene.title}</h2>
                    </div>
                  )}
                  {activeScene?.inspection_only && (
                    <div className="film-inspection-mark">
                      UNREVIEWED INSPECTION · NOT FOR PUBLICATION
                    </div>
                  )}
                  {visual && activeScene?.source_label && (
                    <div
                      className="film-source-label"
                      style={{
                        fontSize: Math.max(7, textUnit(frameSize.width, frameSize.height) * 0.018),
                      }}
                    >
                      {activeScene.source_label}
                    </div>
                  )}
                  {(() => {
                    const ev = ctaEvents.find(([a, b]) => time >= a && time < b);
                    const cc = normaliseCta(project.cta);
                    const banner = ev && assets.find((x) => x.id === cc.asset_id);
                    const file = ev && cc.source === "file" && assets.find((x) => x.id === cc.file_id);
                    return ev && (banner || file) ? (
                      <CtaOverlay project={project} banner={banner} file={file} t={time - ev[0]} fade={ctaSpotAlpha(time, ev[0], ev[1], ev[2]?.natural ?? 1e9)} width={frameSize.width} height={frameSize.height} playing={playing} onNeedPreview={needPreview} />
                    ) : null;
                  })()}
                  <StickerLayer
                    project={project}
                    time={time}
                    playing={playing}
                    width={frameSize.width}
                    height={frameSize.height}
                    selectedId={stickerId}
                    disabled={locked || !!stickerTrack && !stickerTrack.done}
                    onSelect={(id) => { setStickerId(id); focusRight("sticker"); }}
                    onMove={(id, x, y, local) => moveSticker(id, x, y, local)}
                    onResize={(id, patch, local) => resizeSticker(id, patch, local)}
                    picking={!!stickerPick}
                    onPick={(x, y) => { const id = stickerPick; setStickerPick(null); moveSticker(id, x, y, Math.max(0, time - (normaliseStickers(project.stickers, project.assets).find((q) => q.id === id)?.start || 0))); setTimeout(() => followSticker(id, { x, y }), 0); }}
                  />
                  {(() => {
                    // v0.4.52 a motion graphic: the one you are editing, else the approved ones
                    // (v0.4.62 stacked as the export stacks them: a cinematic graphic fades in over the one before)
                    const gs = graphicsAt(project.motion, time, motionEditing ? motionId : null);
                    return gs.map((g, k) => (
                      <div key={g.item.id} className={`motion-wrap ${g.exported ? "" : "draft"}`}>
                        <MotionLayer projectId={project.id} item={g.item} look={project.motion?.look} time={time} width={frameSize.width} height={frameSize.height} playing={playing}
                          onStatus={k === gs.length - 1 ? setMotionStatus : undefined} />
                        {!g.exported && <span className="motion-draft-tag">{g.item.status === "approved" ? "Approved · export is off" : "Preview · not approved"}</span>}
                      </div>
                    ));
                  })()}
                  {(() => {
                    // v0.4.36 your logo watermark, where the export puts it.
                    const wm = normaliseWatermark(project.watermark);
                    const logo = wm.enabled && assets.find((x) => x.id === wm.asset_id && x.kind === "image");
                    if (!logo) return null;
                    const b = watermarkBox(frameSize.width, frameSize.height, logo.width || 1, logo.height || 1, wm.position, wm.size);
                    return <img className="film-watermark" alt="" src={logo.url} style={{ left: b.x, top: b.y, width: b.w, height: b.h, opacity: wm.opacity }} />;
                  })()}
                  {project.captions && activeScene && !(graphicAt(project.motion, time, motionEditing ? motionId : null)?.item.hide_captions) && (() => {
                    const cap = captionAt(activeScene, time - (offsets[activeIndex] || 0), project.caption_style, clean);
                    if (!cap) return null;
                    const css = captionCss(project.caption_style, frameSize.width, frameSize.height);
                    return (
                      <div
                        className="film-captions styled"
                        style={css.wrap}
                        title="Drag up or down to move the captions"
                        onPointerDown={(e) => {
                          if (locked) return;
                          e.preventDefault();
                          const frame = e.currentTarget.parentElement.getBoundingClientRect();
                          const startY = e.clientY;
                          const start = normaliseStyle(project.caption_style).position;
                          let latest = start;
                          const move = (ev) => {
                            latest = Math.min(0.85, Math.max(0.03, start + (startY - ev.clientY) / frame.height));
                            setProject((cur) => ({ ...cur, caption_style: { ...normaliseStyle(cur.caption_style), position: Math.round(latest * 1000) / 1000 } }));
                          };
                          const up = () => {
                            window.removeEventListener("pointermove", move);
                            window.removeEventListener("pointerup", up);
                            if (latest !== start) queueSave({ caption_style: { ...normaliseStyle(projectRef.current.caption_style), position: Math.round(latest * 1000) / 1000 } });
                          };
                          window.addEventListener("pointermove", move);
                          window.addEventListener("pointerup", up);
                        }}
                      >
                        <span key={cap.key} className={`cap-text anim-${css.animation}`} style={css.text}>
                          {cap.words.map((w, i) => (
                            <React.Fragment key={i}>
                              {i > 0 && " "}
                              <span style={i === cap.active ? { color: css.highlight } : undefined}>{w}</span>
                            </React.Fragment>
                          ))}
                        </span>
                      </div>
                    );
                  })()}
                  {nameCards[activeIndex] && activeScene && (() => {
                    const card = nameCards[activeIndex];
                    const lt = lowerThirdAt(card, time - (offsets[activeIndex] || 0), activeScene.duration);
                    if (!lt) return null;
                    const css = lowerThirdCss(frameSize.width, frameSize.height, !!(activeScene.source_label && activeScene.asset_id));
                    return (
                      <div className="fx-lower" style={{ ...css.wrap, opacity: lt.opacity, transform: `translateX(${(lt.shift / 100) * frameSize.width}px)` }}>
                        {card.name && <span style={css.name}>{card.name}</span>}
                        {card.role && <span style={css.role}>{card.role}</span>}
                      </div>
                    );
                  })()}
                  {project.is_demo && (
                    <span className="film-disclosure">
                      FICTIONAL DEMO · AI ILLUSTRATION
                    </span>
                  )}
                  <div className="frame-corner tl" />
                  <div className="frame-corner br" />
                </div>
              </div>
              <div className="player-controls cc-transport">
                <div className="time-display" aria-label="Playhead time">
                  <span>{tc(time, true)}</span>
                  <i>/</i>
                  {tc(duration, true)}
                </div>
                <div className="transport">
                  <IconButton
                    icon={SkipBack}
                    label="Previous scene"
                    onClick={() => {
                      const i = Math.max(0, activeIndex - 1);
                      setTime(offsets[i] || 0);
                      setSelectedId(scenes[i]?.id);
                    }}
                  />
                  <button
                    className="play-btn"
                    aria-label={playing ? "Pause preview" : "Play preview"}
                    title="Play / pause (Space)"
                    onClick={() => setPlaying((v) => !v)}
                    disabled={!scenes.length}
                  >
                    {playing ? (
                      <Pause size={16} fill="currentColor" />
                    ) : (
                      <Play size={16} fill="currentColor" />
                    )}
                  </button>
                  <IconButton
                    icon={SkipForward}
                    label="Next scene"
                    onClick={() => {
                      const i = Math.min(scenes.length - 1, activeIndex + 1);
                      setTime(offsets[i] || 0);
                      setSelectedId(scenes[i]?.id);
                    }}
                  />
                </div>
                <div className="player-right">
                  <IconButton
                    icon={muted ? VolumeX : Volume2}
                    label={muted ? "Unmute preview" : "Mute preview"}
                    onClick={() => setMuted((v) => !v)}
                  />
                  <div className="aspect-switch">
                    <button className="aspect-label" aria-label="Video format" aria-expanded={modal === "format"} onClick={() => setModal(modal === "format" ? null : "format")}>
                      <Monitor size={13} /> <span className="cc-ratio-word">Ratio</span> <b>{aspectOf(project)}</b> <ChevronDown size={11} />
                    </button>
                    {modal === "format" && (
                      <div className="aspect-menu" role="menu">
                        {Object.entries(FORMATS).map(([k, f]) => (
                          <button
                            key={k}
                            role="menuitemradio"
                            aria-checked={aspectOf(project) === k}
                            className={aspectOf(project) === k ? "on" : ""}
                            disabled={locked}
                            onClick={() => queueSave({ aspect: k })}
                          >
                            <i className={`aspect-shape ${k === "9:16" ? "tall" : "wide"}`} />
                            <span>
                              <b>{k}</b> {f.label.split("·")[1]}
                            </span>
                          </button>
                        ))}
                        {aspectOf(project) === "9:16" && (
                          <div className="aspect-fit">
                            <small>Wide footage in a tall frame</small>
                            {FITS.map((f) => (
                              <label key={f.id}>
                                <input type="radio" name="vertical-fit" aria-label={f.label} checked={fitOf(project) === f.id} disabled={locked} onChange={() => queueSave({ vertical_fit: f.id })} />
                                {f.label}
                              </label>
                            ))}
                            <small>Captions stay above the app buttons at the bottom of the screen.</small>
                          </div>
                        )}
                        <button className="aspect-done" onClick={() => setModal(null)}>Done</button>
                      </div>
                    )}
                  </div>
                  <IconButton
                    icon={Maximize2}
                    label={fullMode ? "Exit full screen" : "Fullscreen preview"}
                    onClick={fullscreen}
                  />
                </div>
              </div>
            </section>
            <aside className="inspector" hidden={!layout.showRight}>{renderInspector()}</aside>
            <section className="timeline">
              <div className="timeline-toolbar cc-tl-toolbar">
                <div>
                  <IconButton
                    icon={Undo2}
                    label={historyLabel(project, "undo")}
                    onClick={() => stepHistory("undo")}
                    disabled={locked || !project.history?.undo?.length}
                  />
                  <IconButton
                    icon={Redo2}
                    label={historyLabel(project, "redo")}
                    onClick={() => stepHistory("redo")}
                    disabled={locked || !project.history?.redo?.length}
                  />
                  <span className="toolbar-sep" />
                    <button
                    className="timeline-tool cc-tool"
                    title="Split scene at playhead"
                    aria-label="Split scene at playhead"
                    onClick={splitAtPlayhead}
                    disabled={
                      locked ||
                      !activeScene ||
                      time - (offsets[activeIndex] || 0) < 0.5 ||
                      activeScene.duration -
                        (time - (offsets[activeIndex] || 0)) <
                      0.5
                    }
                  >
                    <Scissors size={13} />
                    <span>Split</span>
                  </button>
                  <IconButton icon={Plus} label="Add scene" onClick={addScene} disabled={locked} />
                  <span className="toolbar-sep" />
                  <div className="track-tools">
                      <button
                        className={`timeline-tool ${selectedTrack?.kind === 'visual' ? 'selected' : ''}`}
                        title="Edit Visuals track"
                        aria-label="Edit Visuals track"
                        onClick={() => setSelectedTrack({ kind: "visual", sceneId: selected.id })}
                        disabled={locked || !selected?.asset_id}
                      >
                        <Film size={12} />
                        <span>V1</span>
                      </button>
                      <button
                        className={`timeline-tool ${selectedTrack?.kind === 'narration' ? 'selected' : ''}`}
                        title="Edit Narration track"
                        aria-label="Edit Narration track"
                        onClick={() => setSelectedTrack({ kind: "narration", sceneId: selected.id })}
                        disabled={locked || !selected}
                      >
                        <Mic size={12} />
                        <span>A1</span>
                      </button>
                      <button
                        className={`timeline-tool ${selectedTrack?.kind === 'music' ? 'selected' : ''}`}
                        title="Edit Music track"
                        aria-label="Edit Music track"
                        onClick={() => setSelectedTrack({ kind: "music", sceneId: selected.id })}
                        disabled={locked || !selected}
                      >
                        <Music2 size={12} />
                        <span>A2</span>
                      </button>
                      <button
                        className="timeline-tool danger"
                        title="Remove selected track from scene"
                        aria-label="Remove track from scene"
                        onClick={() => {
                          if (!selectedTrack || !selected || selectedTrack.sceneId !== selected.id) return;
                          deleteTrack(selectedTrack.kind);
                          setSelectedTrack(null);
                        }}
                        disabled={locked || !selectedTrack || !selected || selectedTrack.sceneId !== selected.id}
                      >
                        <Trash2 size={12} />
                        <span>Delete</span>
                      </button>
                    </div>
                </div>
                <div>
                  {(() => {
                    // v0.4.67 the old timeline footer's hint, kept in the tool row (CapCut has no footer)
                    const hint = voice
                      ? "Review the timing and mix before final export."
                      : project.episode?.timings
                        ? "Imported clock active; upload the exact matching narration."
                        : "Timing estimated at 145 wpm. Add narration for a complete draft.";
                    return (
                      <span className="cc-tl-hint" title={hint + " Space plays and pauses."}>
                        <span className="tiny-dot amber" />
                        <span className="cc-tl-hint-text">{voice ? "Review timing and mix" : project.episode?.timings ? "Imported clock" : "Timing estimated"}</span>
                        <kbd title="Space to play / pause">␣</kbd>
                      </span>
                    );
                  })()}
                  <span className="cc-tl-count">{scenes.length} scenes · {tc(duration)}</span>
                  <span className="toolbar-sep" />
                  <IconButton
                    icon={ZoomOut}
                    label="Zoom timeline out"
                    onClick={() => zoomTo(zoom / 1.25)}
                  />
                  <input
                    className="zoom-slider"
                    type="range"
                    aria-label="Timeline zoom"
                    title="Timeline zoom (or Ctrl/⌘ + scroll on the timeline)"
                    min="0"
                    max="100"
                    value={Math.round((Math.log(zoom) / Math.log(20)) * 100)}
                    onChange={(e) => zoomTo(Math.pow(20, Number(e.target.value) / 100))}
                  />
                  <IconButton
                    icon={ZoomIn}
                    label="Zoom timeline in"
                    onClick={() => zoomTo(zoom * 1.25)}
                  />
                  <IconButton
                    icon={Scan}
                    label="Fit timeline"
                    onClick={() => zoomTo(1)}
                  />
                </div>
              </div>
              <div className="timeline-lanes">
                <div className="track-labels cc-heads">
                  <div className="ruler-spacer" />
                  {overlayOn && (
                    <div className="track-label overlay" title="Graphics, stickers and the subscribe animation">
                      <Shapes size={13} />
                      <span>Overlays</span>
                    </div>
                  )}
                  <div className="track-label captions">
                    <Captions size={13} />
                    <span>Captions</span>
                    <button
                      className="cc-track-btn"
                      aria-label={project.captions ? "Hide the captions" : "Show the captions"}
                      title={project.captions ? "Captions are on in the video · click to switch them off" : "Captions are off · click to switch them on"}
                      disabled={locked}
                      onClick={() => queueSave({ captions: !project.captions })}
                    >
                      {project.captions ? <Eye size={13} /> : <EyeOff size={13} />}
                    </button>
                  </div>
                  <div className="track-label video">
                    <Film size={13} />
                    <span>Visuals</span>
                  </div>
                  <div className="track-label narr">
                    <Mic size={13} />
                    <span>Narration</span>
                  </div>
                  <div className="track-label music">
                    <Music2 size={13} />
                    <span>Music</span>
                  </div>
                  {soundOn && (
                    <div className="track-label sfx">
                      <AudioWaveform size={13} />
                      <span>Sound FX</span>
                      <button
                        className={`cc-track-btn ${sfxMute ? "off" : ""}`}
                        aria-label={sfxMute ? "Unmute the sound effects in the preview" : "Mute the sound effects in the preview"}
                        title={sfxMute ? "Sound effects muted in the preview (the export keeps them)" : "Mute the sound effects in the preview (the export keeps them)"}
                        onClick={() => { setSfxMute(!sfxMute); if (!sfxMute) setSfxSolo(false); }}
                      >
                        {sfxMute ? <VolumeX size={13} /> : <Volume2 size={13} />}
                      </button>
                    </div>
                  )}
                </div>
                <div
                  className="timeline-scroll"
                  ref={timelineRef}
                  onWheel={(e) => {
                    if (!(e.ctrlKey || e.metaKey)) return;
                    e.preventDefault();
                    const rect = e.currentTarget.getBoundingClientRect();
                    zoomTo(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), e.clientX - rect.left);
                  }}
                >
                  <div
                    className="timeline-content"
                    style={{ width: `${zoom * 100}%` }}
                    onClick={seekTimeline}
                  >
                    <div className="ruler" onPointerDown={scrub} title="Drag to scrub">
                      {(() => {
                        const { major, minor } = rulerTicks(duration, laneWidth * zoom);
                        return (
                          <>
                            {minor.map((t) => (
                              <i key={"m" + t} style={{ left: `${(t / duration) * 100}%` }} />
                            ))}
                            {major.map((t) => (
                              <span key={t} style={{ left: `${(t / duration) * 100}%` }}>
                                {tc(t)}
                              </span>
                            ))}
                          </>
                        );
                      })()}
                    </div>
                    {overlayOn && (
                      <div className="overlay-lane">
                        {/* v0.4.67 graphics, stickers and the subscribe animation as clips on their own track (CapCut's effects track) */}
                        {ctaEvents.map(([a, b]) => (
                          <button key={"cta" + a} className="fx-clip cta" title={`Subscribe animation ${tc(a)}–${tc(b)}`}
                            style={{ left: `${(a / duration) * 100}%`, width: `${((b - a) / duration) * 100}%` }}
                            onClick={(e) => { e.stopPropagation(); setPlaying(false); setTime(a); focusRight("cta", { at: a, end: b }); }}>
                            <span>Subscribe</span>
                          </button>
                        ))}
                        {overlayGraphics.map((g) => (
                          <button key={"mg" + g.id} className={`fx-clip motion ${g.status} ${g.id === motionId ? "on" : ""}`}
                            title={`Graphic (${g.status}) ${tc(g.start)}–${tc(g.end)}${g.title ? ": " + g.title : ""}`}
                            style={{ left: `${(g.start / duration) * 100}%`, width: `${((Math.min(g.end, duration) - g.start) / duration) * 100}%` }}
                            onClick={(e) => { e.stopPropagation(); setPlaying(false); setTime(g.start + 0.05); setMotionId(g.id); focusRight("graphic"); }}>
                            <span>{g.title || g.heading || g.lines?.[0]?.text || "Graphic"}</span>
                          </button>
                        ))}
                        {overlayStickers.map((st) => (
                          <button key={"st" + st.id} className={`fx-clip sticker ${st.id === stickerId ? "on" : ""}`} title={`Sticker: ${stickerLabel(st, project.assets || [])} ${tc(st.start)}`}
                            style={{ left: `${(st.start / duration) * 100}%`, width: `${(Math.min(st.length, duration - st.start) / duration) * 100}%` }}
                            onClick={(e) => { e.stopPropagation(); setPlaying(false); setTime(st.start + 0.05); setStickerId(st.id); focusRight("sticker"); }}>
                            <span>{stickerLabel(st, project.assets || [])}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="caption-lane">
                      {project.captions ? (
                        scenes.flatMap((s, i) =>
                          captionChunks(sceneCaptions(s, clean), normaliseStyle(project.caption_style).words).map((c, k) => ({
                            key: `${s.id}-${k}`,
                            sceneId: s.id,
                            start: (offsets[i] || 0) + c.start,
                            end: (offsets[i] || 0) + c.end,
                            text: c.words.join(" "),
                          })),
                        ).map((c) => (
                          <button
                            key={c.key}
                            className={`caption-block ${time >= c.start && time < c.end ? "now" : ""}`}
                            title={c.text}
                            style={{
                              left: `${(c.start / duration) * 100}%`,
                              width: `${((c.end - c.start) / duration) * 100}%`,
                            }}
                            onClick={(e) => {
                              e.stopPropagation();
                              setTime(c.start + 0.001);
                              setSelectedId(c.sceneId);
                              setPlaying(false);
                              focusRight("caption", { cap: c }); // v0.4.70 this caption's words and style on the right
                            }}
                          >
                            {c.text}
                          </button>
                        ))
                      ) : (
                        <span className="lane-off">Captions are off</span>
                      )}
                    </div>
                    <div className="visual-lane">
                      {scenes.map((s, i) => {
                        const a = assets.find((a) => a.id === s.asset_id);
                        return (
                          <button
                            className={`clip ${selected?.id === s.id ? "selected" : ""}`}
                            key={s.id}
                            style={{
                              left: `${(offsets[i] / duration) * 100}%`,
                              width: `${(s.duration / duration) * 100}%`,
                              backgroundImage: a?.thumbnail
                                ? `linear-gradient(0deg,rgba(10,13,15,.75),rgba(10,13,15,.05)),url("${a.thumbnail}")`
                                : undefined,
                            }}
                            onClick={(e) => {
                              e.stopPropagation();
                              selectVisualScene(s, i);
                            }}
                          >
                            <span>
                              {String(i + 1).padStart(2, "0")} <i>{s.title}</i>
                            </span>
                            {i > 0 && transitionId(s.transition) !== "none" && (
                              <em
                                className="tr-marker"
                                title={`Transition: ${TRANS_LABEL[transitionId(s.transition)]} (${transitionLength(s, s.duration).toFixed(1)} s)`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  selectVisualScene(s, i);
                                  openLeft("transitions");
                                }}
                              />
                            )}
                            {selected?.id === s.id && (
                              <>
                                <b
                                  className="trim-handle left"
                                  title="Drag to trim start"
                                  onPointerDown={(e) => trimScene(e, s, "left")}
                                />
                                <b
                                  className="trim-handle right"
                                  title="Drag to trim end"
                                  onPointerDown={(e) =>
                                    trimScene(e, s, "right")
                                  }
                                />
                              </>
                            )}
                          </button>
                        );
                      })}
                    </div>
                    <div
                      className={`audio-lane voice-lane ${voice ? "has-audio" : ""}`}
                    >
                      {voice ? (
                        <>
                          {scenes.map((s, i) => {
                            const peaks = voice.waveform || [],
                              start = Math.floor(
                                ((s.audio_start || 0) / (voice.duration || 1)) *
                                  peaks.length,
                              ),
                              end = Math.ceil(
                                (((s.audio_start || 0) +
                                  Math.min(
                                    s.duration,
                                    s.audio_duration || s.duration,
                                  )) /
                                  (voice.duration || 1)) *
                                  peaks.length,
                              );
                            return (
                              <button
                                className="voice-region"
                                key={s.id}
                                style={{
                                  pointerEvents: "auto",
                                  left: `${(offsets[i] / duration) * 100}%`,
                                  width: `${(s.duration / duration) * 100}%`,
                                }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedTrack({ kind: "narration", sceneId: s.id });
                                  setInspectorTab("audio");
                                  setAudioSub("voice");
                                }}
                              >
                                <Wave
                                  values={peaks.slice(
                                    start,
                                    Math.max(start + 1, end),
                                  )}
                                />
                              </button>
                            );
                          })}
                          <span className="audio-lane-label">
                            <Mic size={10} />
                            {voice.name}
                          </span>
                        </>
                      ) : (
                        <button type="button" className="lane-empty" onClick={(e) => { e.stopPropagation(); openLeft("audio", "voice"); }}>
                          <Plus size={11} /> No narration — upload a track or
                          generate a voice
                        </button>
                      )}
                    </div>
                      <button
                        className={`audio-lane music-lane ${music ? "has-audio" : ""}`}
                        onClick={() => {
                          if (!music) return openLeft("audio", "music"); // v0.4.68 add music from the Audio tab
                          if (!selected) return;
                          setSelectedTrack({ kind: "music", sceneId: selected.id });
                          setInspectorTab("audio");
                          setAudioSub("music");
                        }}
                      >
                        {music ? (
                          <>
                            {(musicLay?.runs || []).map((r, i) => (
                              <i key={"mr" + i} className="music-run" title={`Music ${r.iters.length > 1 ? `(${r.iters.length} passes) ` : ""}${r.at.toFixed(1)}–${r.end.toFixed(1)} s`}
                                style={{ left: `${(r.at / duration) * 100}%`, width: `${((r.end - r.at) / duration) * 100}%` }} />
                            ))}
                            {(musicLay?.runs || []).flatMap((r) => r.iters.slice(1)).map((it, i) => (
                              <b key={"ms" + i} className="music-seam" title={`Loop seam at ${it.at.toFixed(1)} s (${musicLay.crossfade.toFixed(1)} s crossfade)`}
                                style={{ left: `${(it.at / duration) * 100}%`, width: `${Math.max(0.15, (musicLay.crossfade / duration) * 100)}%` }} />
                            ))}
                            {/* v0.4.58: the lane shows where the music plays (runs, loop seams), not the file's
                                own waveform stretched over the documentary */}
                            <span className="audio-lane-label">
                              <Music2 size={10} />
                              {music.name}
                            </span>
                          </>
                        ) : (
                          <span>
                            <Plus size={11} /> Add licensed background music
                          </span>
                        )}
                      </button>
                    {soundOn && (
                      <div className="audio-lane sfx-lane has-audio" onClick={(e) => e.stopPropagation()}
                        title="Double-click to add a sound here · click a sound to select it, drag to move it, Delete to remove it"
                        onDoubleClick={(e) => {
                          // v0.4.60 add a sound from the timeline: this moment is kept for the library's "+ at"
                          // (playback goes on; nothing is saved until a sound is picked)
                          if (locked || e.target.closest(".sfx-mark")) return;
                          const content = timelineRef.current?.querySelector(".timeline-content");
                          if (!content || !(duration > 0)) return;
                          const r = content.getBoundingClientRect();
                          const t = Math.round(Math.min(duration, Math.max(0, ((e.clientX - r.left) / r.width) * duration)) * 24) / 24;
                          if (!Number.isFinite(t)) return;
                          setSfxPin(t);
                          openLeft("audio", "sfx");
                        }}>
                        {(soundPlan?.zones || []).map((z, i) => (
                          <i key={"z" + i} className="sfx-zone" title={`No automatic sound: ${z.why}`}
                            style={{ left: `${(z.start / duration) * 100}%`, width: `${((z.end - z.start) / duration) * 100}%` }} />
                        ))}
                        {(soundPlan?.items || []).filter((x) => x.t != null).map((x) => (
                          <b key={x.id} className={`sfx-mark ${x.kind} ${x.status} ${x.id === soundId ? "on" : soundIds.includes(x.id) ? "scope" : ""}`}
                            title={`${x.label} · ${x.sound}${x.reason ? " · " + x.reason : ""} (drag to move)`}
                            style={{ left: `${(x.t / duration) * 100}%`, width: x.keys ? `${(Math.max(0.05, x.keys.at(-1)[0] - x.t) / duration) * 100}%` : undefined }}
                            tabIndex={0}
                            onKeyDown={(e) => {
                              // v0.4.60 Delete / Backspace on the selected sound: as the Remove button (playback goes on)
                              if ((e.key !== "Delete" && e.key !== "Backspace") || locked) return;
                              e.preventDefault();
                              e.stopPropagation();
                              const st = normaliseSound(project.sound);
                              queueSave({ sound: x.source === "manual" ? { ...st, items: st.items.filter((y) => y.id !== x.id) } : editSfx(st, x, { status: "removed" }) });
                              setSoundId(null);
                            }}
                            onPointerDown={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              // v0.4.60 selecting or moving a sound no longer pauses the playback
                              e.currentTarget.focus({ preventScroll: true });
                              setSoundId(x.id);
                              focusRight("sound"); // v0.4.70 its settings on the right
                              if (locked) return;
                              const content = timelineRef.current?.querySelector(".timeline-content");
                              if (!content) return;
                              const pps = content.getBoundingClientRect().width / duration, x0 = e.clientX, el = e.currentTarget, base = x.offset || 0;
                              let moved = 0;
                              const move = (ev) => {
                                moved = Math.round(((ev.clientX - x0) / pps) * 24) / 24; // whole frames
                                el.style.transform = `translateX(${moved * pps}px)`;
                              };
                              const up = () => {
                                window.removeEventListener("pointermove", move);
                                window.removeEventListener("pointerup", up);
                                el.style.transform = "";
                                if (moved) queueSave({ sound: editSfx(normaliseSound(project.sound), x, { offset: Math.round((base + moved) * 10000) / 10000 }) });
                                else if (!playingRef.current) setTime(Math.max(0, x.t - 0.02)); // while playing: selected only
                              };
                              window.addEventListener("pointermove", move);
                              window.addEventListener("pointerup", up);
                            }} />
                        ))}
                        {sfxPin != null && duration > 0 && (
                          <i className="sfx-pin" style={{ left: `${(sfxPin / duration) * 100}%` }} title="A sound you pick in the library (Audio › Sound effects) goes here" />
                        )}
                        {!soundPlan && <span>{soundPlanError || "Reading the timeline…"}</span>}
                      </div>
                    )}
                    {duration > 0 && (
                      <div
                        className="playhead"
                        style={{ left: `${(time / duration) * 100}%` }}
                      >
                        <span onPointerDown={scrub} title="Drag to scrub" />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </section>
            {/* v0.4.67 the Director, as CapCut's floating helper: plain-English edits and their history */}
            <div className={`cc-pilot ${layout.director ? "open" : ""} ${dock ? "docked" : ""}`}>
              {layout.director && !dock && (
                <div className="cc-pilot-panel" role="dialog" aria-label="Director">
                  <header>
                    <Sparkles size={14} />
                    <b>Director</b>
                    <small>{config.connected ? "AI connected" : "Local + AI-ready"}</small>
                    <button type="button" className="layout-btn" aria-label="Close the Director" title="Close the Director (your history is kept)" onClick={() => setLayout({ director: false })}>
                      <X size={14} />
                    </button>
                  </header>
                  {directorBody()}
                </div>
              )}
              <button
                className="cc-pilot-btn"
                aria-label={layout.director ? "Hide the Director" : "Show the Director"}
                aria-expanded={layout.director}
                title="Direct your edit in plain English"
                onClick={() => setLayout({ director: !layout.director })}
              >
                <Sparkles size={15} /> Director
              </button>
            </div>
          </div>
        )}

        {tab === "research" && (
          <main className="page research-page">
            <div className="page-heading">
              <div>
                <div className="eyebrow">01 / THE RESEARCH DESK</div>
                <h2>Start with the facts.</h2>
                <p>
                  Trace the record. Separate what is known from what is claimed.
                </p>
              </div>
              <Button icon={Plus} onClick={() => setModal("source")}>
                Add a source
              </Button>
            </div>
            {project.is_demo && (
              <div className="notice">
                <Info size={17} />
                <div>
                  <b>This is a fictional production study.</b> No real case
                  research is included. Create a new project to investigate a
                  topic.
                </div>
                <Button onClick={() => setModal("new")}>
                  New project <ArrowUpRight size={13} />
                </Button>
              </div>
            )}
            <div className="research-search-card">
              <label className="eyebrow" htmlFor="topic">
                CASE NAME OR TOPIC
              </label>
              <div className="case-search">
                <Search size={20} />
                <input
                  id="topic"
                  value={project.topic}
                  onChange={(e) => queueSave({ topic: e.target.value })}
                  placeholder="Case name, location, and any identifying context…"
                />
                <Button
                  kind="primary"
                  icon={Sparkles}
                  disabled={locked || project.is_demo}
                  onClick={() =>
                    startOperation(`/api/projects/${project.id}/research`)
                  }
                >
                  Research case
                </Button>
              </div>
              <p>
                <LockKeyhole size={12} /> Web research requires an AI
                connection. Results are source leads, not verified case facts.
              </p>
            </div>
            <div className="research-grid">
              <section className="content-card source-card">
                <div className="card-heading">
                  <h3>
                    <BookOpen size={16} /> Source library{" "}
                    <Badge>{project.sources.length}</Badge>
                  </h3>
                  <span>
                    {project.sources.filter((s) => s.reviewed).length} reviewed
                  </span>
                </div>
                {project.sources.length ? (
                  <div className="sources">
                    {project.sources.map((s) => (
                      <div className="source" key={s.id}>
                        <div className="source-top">
                          <Badge tone="source">{s.id}</Badge>
                          <span>{s.type}</span>
                          <button
                            className={`source-check ${s.reviewed ? "checked" : ""}`}
                            title="Mark as producer-reviewed"
                            onClick={() =>
                              setSource(s, { reviewed: !s.reviewed })
                            }
                          >
                            {s.reviewed ? (
                              <CheckCircle2 size={13} />
                            ) : (
                              <Circle size={13} />
                            )}{" "}
                            {s.reviewed ? "Reviewed" : "Needs review"}
                          </button>
                        </div>
                        <h4>
                          {s.url ? (
                            <a
                              href={s.url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {s.title}
                              <ExternalLink size={12} />
                            </a>
                          ) : (
                            s.title
                          )}
                        </h4>
                        {s.url && (
                          <span className="source-domain">
                            {new URL(s.url).hostname}
                          </span>
                        )}
                        <label className="field">
                          Producer-verified notes
                          <textarea
                            key={s.id + "-" + s.reviewed}
                            defaultValue={s.notes}
                            placeholder="Record the facts you checked, dates, and relevant quotations…"
                            rows="3"
                            onBlur={(e) => {
                              if (e.target.value !== s.notes)
                                setSource(s, { notes: e.target.value });
                            }}
                          />
                        </label>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty icon={BookOpen} title="A story needs a source trail">
                    Add records, reporting, or interview notes. Review the
                    original before marking it verified.
                    <Button icon={Plus} onClick={() => setModal("source")}>
                      Add your first source
                    </Button>
                  </Empty>
                )}
              </section>
              <section className="content-card">
                <div className="card-heading">
                  <h3>
                    <FileText size={16} /> Research brief
                  </h3>
                  <Badge tone="amber">DRAFT</Badge>
                </div>
                {project.research_report ? (
                  <div className="research-report">
                    {project.research_report}
                  </div>
                ) : (
                  <Empty icon={Search} title="The brief comes next">
                    Research a case to collect a sourced chronology, legal
                    status, and questions to investigate.
                  </Empty>
                )}
                <div className="card-footer">
                  <Button
                    icon={Sparkles}
                    disabled={locked}
                    onClick={() => {
                      setTab("script");
                      startOperation(`/api/projects/${project.id}/draft`);
                    }}
                  >
                    Draft from reviewed sources
                  </Button>
                  <a
                    className="text-link"
                    href={`/api/projects/${project.id}/sources.md`}
                    download
                  >
                    <Download size={12} /> Export notes
                  </a>
                </div>
              </section>
            </div>
          </main>
        )}

        {tab === "script" && (
          <main className="page script-page">
            <div className="page-heading">
              <div>
                <div className="eyebrow">02 / THE STORY</div>
                <h2>Give the record a voice.</h2>
                <p>
                  A measured opening. A clear chronology. Room for the facts.
                </p>
              </div>
              <div className="page-actions">
                <Button icon={Upload} onClick={() => fileRef.current.click()}>
                  Import script
                </Button>
                <Button
                  kind="primary"
                  icon={Clapperboard}
                  disabled={locked || !project.script.trim()}
                  onClick={doAssemble}
                >
                  Build timeline
                </Button>
              </div>
            </div>
            {project.script_origin === "ai" &&
              !project.script_approved_hash && (
                <div className="script-approval-notice">
                  <ShieldCheck size={19} />
                  <div>
                    <b>AI-written draft: producer review required</b>
                    <p>
                      Read the narration against its cited sources, resolve
                      unverified details, and approve the text before generating
                      a voice.
                    </p>
                  </div>
                  <Button
                    icon={CheckCircle2}
                    kind="primary"
                    disabled={locked}
                    onClick={approveScript}
                  >
                    Approve for narration
                  </Button>
                </div>
              )}
            {project.script_origin === "ai" &&
              !!project.script_approved_hash && (
                <div className="script-approved-tag">
                  <CheckCircle2 size={13} /> Producer-approved for narration ·
                  Final factual and rights checks still apply
                </div>
              )}
            {project.script_dirty && (
              <div className="notice">
                <Info size={15} />
                <span>
                  Your script has unapplied changes. Build the timeline to apply
                  them; the existing edit is unchanged until then.
                </span>
              </div>
            )}
            <div className="script-layout">
              <section className="script-editor content-card">
                <div className="script-document-header">
                  <div>
                    <FileText size={16} />
                    <strong>Narration script</strong>
                    <Badge>EDITABLE</Badge>
                  </div>
                  <span>Blank lines separate scenes</span>
                </div>
                <textarea
                  aria-label="Documentary narration script"
                  className="script-textarea"
                  placeholder={
                    "Paste your script here…\n\nUse blank lines between paragraphs. Each paragraph becomes an editable scene.\n\nOr research a case and draft from reviewed sources."
                  }
                  value={project.script}
                  onChange={(e) => queueSave({ script: e.target.value })}
                  spellCheck
                />
                <div className="script-footer">
                  <span>
                    {wc(clean(project.script)).toLocaleString()} spoken words
                  </span>
                  <span>
                    <Clock3 size={12} />
                    {tc((wc(clean(project.script)) / 145) * 60)} estimated
                    voice-over
                  </span>
                  <span>{project.target_minutes} min target</span>
                </div>
              </section>
              <aside className="script-side">
                <div className="content-card script-guide">
                  <div className="mini-icon">
                    <Sparkles size={19} />
                  </div>
                  <h3>From script to first cut.</h3>
                  <p>
                    Build a scene sequence, then add footage and a voice track.
                    You keep control of every cut.
                  </p>
                  <ol>
                    <li>
                      <span>1</span>Write or paste your narration
                    </li>
                    <li>
                      <span>2</span>Import licensed visuals
                    </li>
                    <li>
                      <span>3</span>Build and review the timeline
                    </li>
                    <li>
                      <span>4</span>Record or generate a voice
                    </li>
                  </ol>
                  <Button
                    className="full"
                    icon={Sparkles}
                    disabled={locked}
                    onClick={() =>
                      startOperation(`/api/projects/${project.id}/draft`)
                    }
                  >
                    Draft from reviewed sources
                  </Button>
                  <small>
                    <LockKeyhole size={11} /> AI connection required
                  </small>
                </div>
                <div className="content-card script-stat">
                  <span className="eyebrow">EPISODE LENGTH</span>
                  <strong>{tc((wc(clean(project.script)) / 145) * 60)}</strong>
                  <p>
                    Based on 145 spoken words per minute. Actual length follows
                    the recorded voice.
                  </p>
                  <label className="field">
                    Target duration
                    <select
                      value={project.target_minutes}
                      onChange={(e) =>
                        queueSave({ target_minutes: Number(e.target.value) })
                      }
                    >
                      {[20, 25, 30, 35, 40].map((n) => (
                        <option key={n} value={n}>
                          {n} minutes · ~{(n * 145).toLocaleString()} words
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {project.script.includes("[NEEDS SOURCE]") && (
                  <div className="notice warning">
                    <AlertTriangle size={16} />
                    <span>
                      This draft contains claims marked NEEDS SOURCE. Resolve
                      them before recording or publication.
                    </span>
                  </div>
                )}
              </aside>
            </div>
          </main>
        )}

        {tab === "review" && (
          <main className="page review-page">
            <div className="page-heading">
              <div>
                <div className="eyebrow">
                  {project.episode?.guide
                    ? "YOUR DRAFT VIDEO"
                    : "04 / THE FINAL CUT"}
                </div>
                <h2>
                  {project.episode?.guide
                    ? "Watch it. Save it. Then finish."
                    : "A final check. Then, the world."}
                </h2>
                <p>
                  Editorial care is part of the production—not an optional
                  extra.
                </p>
              </div>
              <div className="page-actions">
                <Button
                  icon={ShieldCheck}
                  onClick={() => openTool("preflight")}
                >
                  Preflight checks
                </Button>
                <Button
                  kind={project.episode?.guide ? "" : "primary"}
                  icon={Download}
                  disabled={locked || !scenes.length}
                  onClick={() => {
                    if (project.episode?.guide)
                      makeFirstDraft({ render: true });
                    else {
                      setExportFinal(false);
                      openTool("export");
                    }
                  }}
                >
                  {project.episode?.guide
                    ? "Make updated draft video"
                    : "Render video"}
                </Button>
                {project.episode?.guide && (
                  <Button
                    kind="primary"
                    icon={Download}
                    disabled={
                      locked ||
                      !scenes.length ||
                      project.episode?.plan?.mode === "inspection" ||
                      !Object.values(project.review).every(Boolean)
                    }
                    title="Render the clean, publication-ready video"
                    onClick={() => {
                      setExportFinal(true);
                      openTool("export");
                    }}
                  >
                    Make final video
                  </Button>
                )}
              </div>
            </div>
            {project.episode?.guide &&
              (project.episode?.plan?.mode === "inspection" ||
                !Object.values(project.review).every(Boolean)) && (
                <p className="micro-note block">
                  “Make final video” unlocks with the producer sign-off in the
                  editorial review card below. Until then, only inspection
                  drafts (with the banner) can render.
                </p>
              )}
            <details
              className="advanced-publication"
              open={!project.episode?.guide}
            >
              <summary>
                Advanced: final publication checks and session cleanup
              </summary>
              <div className="review-grid">
                <section className="content-card checklist-card">
                  <div className="card-heading">
                    <h3>
                      <ShieldCheck size={17} /> Editorial review
                    </h3>
                    <Badge
                      tone={
                        Object.values(project.review).every(Boolean)
                          ? "green"
                          : ""
                      }
                    >
                      {Object.values(project.review).filter(Boolean).length} / 4
                      complete
                    </Badge>
                  </div>
                  {[
                    [
                      "facts",
                      "Facts & allegations",
                      "I checked names, dates, quotations, legal status, and the distinction between allegations and established facts.",
                    ],
                    [
                      "rights",
                      "Media & music rights",
                      "I have permission to use the footage, images, recordings, and music in this production.",
                    ],
                    [
                      "disclosure",
                      "Disclosure & context",
                      "AI narration and illustrative or reconstructed visuals are disclosed, and none is presented as authentic evidence.",
                    ],
                    [
                      "picture",
                      "Picture, sound & pacing",
                      "I watched the full edit, checked captions and transitions, and listened to the narration and music.",
                    ],
                  ].map(([key, title, description]) => (
                    <button
                      className={`review-check ${project.review[key] ? "checked" : ""}`}
                      key={key}
                      onClick={() =>
                        queueSave({
                          review: {
                            ...project.review,
                            [key]: !project.review[key],
                          },
                        })
                      }
                    >
                      <span className="check-box">
                        {project.review[key] && <Check size={14} />}
                      </span>
                      <span>
                        <b>{title}</b>
                        <p>{description}</p>
                      </span>
                    </button>
                  ))}
                  {project.episode?.plan?.mode === "inspection" && (
                    <p className="inspection-final-help">
                      These are final-publication sign-offs. You may leave all
                      four unticked while viewing/rendering an inspection draft.
                      They do not import footage or perform editing for you.
                    </p>
                  )}
                  <div className="checklist-note">
                    <Info size={14} /> These are producer attestations, not
                    independent factual verification or legal clearance.
                  </div>
                  <button
                    className="btn full"
                    onClick={() => setSignoffOpen(true)}
                  >
                    <ShieldCheck size={14} /> Producer sign-off — skip the
                    itemized review
                  </button>
                </section>
                <div className="review-summary">
                  <div
                    className="export-preview"
                    style={{
                      backgroundImage:
                        assets.find((a) => a.thumbnail)?.thumbnail ||
                        project.is_demo
                          ? `linear-gradient(0deg,rgba(11,15,18,.95),rgba(11,15,18,.05)),url("${assets.find((a) => a.thumbnail)?.thumbnail || "/assets/blackwater-road.jpg"}")`
                          : "linear-gradient(130deg,#26313a,#14191e)",
                    }}
                  >
                    <Badge>
                      {project.is_demo
                        ? "FICTIONAL SAMPLE"
                        : "YOUR DOCUMENTARY"}
                    </Badge>
                    <div>
                      <h3>{project.title}</h3>
                      <p>
                        {tc(duration)} <span>·</span> {scenes.length} scenes{" "}
                        <span>·</span> {aspectOf(project)}
                      </p>
                    </div>
                  </div>
                  <div className="content-card readiness">
                    <div>
                      <span>Visuals assigned</span>
                      <b>
                        {scenes.filter((s) => s.asset_id).length} /{" "}
                        {scenes.length}
                      </b>
                    </div>
                    <div>
                      <span>Narration</span>
                      <b className={!voice ? "text-amber" : ""}>
                        {voice
                          ? voice.generated
                            ? "AI voice assigned"
                            : "Recorded voice assigned"
                          : "Not assigned"}
                      </b>
                    </div>
                    <div>
                      <span>Sources reviewed</span>
                      <b>
                        {project.sources.filter((s) => s.reviewed).length} /{" "}
                        {project.sources.length}
                      </b>
                    </div>
                    <div>
                      <span>Engine</span>
                      <b>H.264 · AAC · 24 fps</b>
                    </div>
                  </div>
                  {!project.is_demo && (
                    <details className="session-cleanup">
                      <summary>
                        Clear temporary session after saving your downloads
                      </summary>
                      <p>
                        This removes this project's uploaded copies, jobs,
                        rendered files and project record from this server. It
                        does not delete originals on your computer. A download
                        click alone is not proof that a file was saved.
                      </p>
                      <label className="ep-checkbox">
                        <input
                          type="checkbox"
                          aria-label="I saved my output before clearing"
                          checked={savedBeforeClear}
                          onChange={(ev) =>
                            setSavedBeforeClear(ev.target.checked)
                          }
                        />
                        <span>
                          I have saved and checked the output/backups I need on
                          my computer.
                        </span>
                      </label>
                      <button
                        className="btn"
                        aria-label="Clear this temporary session"
                        disabled={locked || !savedBeforeClear}
                        onClick={async () => {
                          setBusy(true);
                          try {
                            await flushSave();
                            await api(
                              `/api/projects/${project.id}/session`,
                              "DELETE",
                              { confirm_download_saved: true },
                            );
                            pending.current = {};
                            await forgetSetup(project.id).catch(() => {});
                            await clearWorkingFiles(project.id).catch(() => {});
                            window.location.reload();
                          } catch (error) {
                            report(error);
                            setBusy(false);
                          }
                        }}
                      >
                        <Trash2 size={13} /> Clear this session's uploaded
                        copies and exports
                      </button>
                    </details>
                  )}
                  <div className="review-downloads">
                    <a
                      href="#project-backup"
                      aria-label="Save project backup"
                      onClick={(ev) => {
                        ev.preventDefault();
                        downloadProjectSnapshot(project, setDownloadGate);
                      }}
                    >
                      Save project backup (no server needed)
                    </a>
                    <a
                      href={`/api/projects/${project.id}/chapters.txt`}
                      download
                    >
                      <Clapperboard size={14} /> Chapters <Download size={12} />
                    </a>
                    <a
                      href={`/api/projects/${project.id}/captions.srt`}
                      download
                    >
                      <FileText size={14} /> Captions .srt{" "}
                      <Download size={12} />
                    </a>
                    <a href={`/api/projects/${project.id}/sources.md`} download>
                      <BookOpen size={14} /> Source notes <Download size={12} />
                    </a>
                    <a
                      href="#project-backup"
                      onClick={(ev) => {
                        ev.preventDefault();
                        downloadProjectSnapshot(project, setDownloadGate);
                      }}
                    >
                      <FileJson size={14} /> Project .json{" "}
                      <Download size={12} />
                    </a>
                  </div>
                </div>
              </div>
            </details>
            <section className="content-card exports-card">
              <div className="card-heading">
                <h3>
                  <Film size={17} /> Export history{" "}
                  <Badge>{project.exports.length}</Badge>
                </h3>
                <span>Real rendered files, ready to download</span>
              </div>
              {project.exports[0] && (
                <div className="rendered-preview">
                  <b>
                    {project.exports[0].inspection_only
                      ? "UNREVIEWED INSPECTION · "
                      : ""}
                    Watch the rendered video before downloading
                  </b>
                  <div className="rendered-preview-actions">
                    <button
                      className="btn"
                      aria-label="Play rendered video"
                      onClick={(ev) =>
                        ev.currentTarget
                          .closest(".rendered-preview")
                          .querySelector("video")
                          .play()
                          .catch(report)
                      }
                    >
                      <Play size={13} /> Play rendered video
                    </button>
                    <button
                      className="btn"
                      aria-label="Pause rendered video"
                      onClick={(ev) =>
                        ev.currentTarget
                          .closest(".rendered-preview")
                          .querySelector("video")
                          .pause()
                      }
                    >
                      <Pause size={13} /> Pause
                    </button>
                  </div>
                  <video
                    aria-label="Rendered video preview"
                    src={project.exports[0].url}
                    controls
                    playsInline
                    preload="metadata"
                  />
                  <p>
                    This is the encoded MP4, not just the timeline simulation.
                    Save the file to your computer before clearing this session.
                  </p>
                </div>
              )}
              {project.exports.length ? (
                <div className="export-list">
                  {project.exports.map((ex) => (
                    <div className="export-row" key={ex.id}>
                      <div className="export-file-icon">
                        <Film size={20} />
                      </div>
                      <div>
                        <h4>
                          {ex.title}.mp4{" "}
                          <Badge tone={ex.draft ? "amber" : "green"}>
                            {ex.inspection_only
                              ? "UNREVIEWED INSPECTION"
                              : ex.draft
                                ? "DRAFT"
                                : "FINAL"}
                          </Badge>
                        </h4>
                        <p>
                          {ex.resolution} · {tc(ex.duration)} · {bytes(ex.size)}{" "}
                          · {ex.audio ? "Audio included" : "Silent video"} ·{" "}
                          {elapsed(ex.created_at)}
                          {ex.render_seconds
                            ? ` · rendered in ${
                                ex.render_seconds >= 60
                                  ? `${Math.floor(ex.render_seconds / 60)} min ${Math.round(ex.render_seconds % 60)} s`
                                  : `${Math.round(ex.render_seconds)} s`
                              }`
                            : ""}
                        </p>
                        {ex.warnings?.length > 0 && (
                          <ul className="export-warnings" role="alert">
                            {ex.warnings.map((w, i) => (
                              <li key={i}>{w}</li>
                            ))}
                          </ul>
                        )}
                        {ex.preflight_url && (
                          <div className="export-companion-links">
                            <a href={ex.preflight_url} download>
                              Preflight report
                            </a>
                            <a href={ex.chapters_url} download>
                              Chapter draft
                            </a>
                            <a href={ex.publication_url} download>
                              Publication notes
                            </a>
                            {ex.episode_plan_url && (
                              <a href={ex.episode_plan_url} download>
                                Frozen episode plan
                              </a>
                            )}
                            {ex.render_report_url && (
                              <a href={ex.render_report_url} download>
                                Render report
                              </a>
                            )}
                          </div>
                        )}
                      </div>
                      <a
                        className="btn"
                        onClick={(ev) => {
                          if (window.top !== window) {
                            ev.preventDefault();
                            setDownloadGate({
                              kind: "video",
                              url: new URL(
                                `/api/projects/${project.id}/exports/${ex.id}/download`,
                                window.location.origin,
                              ).href,
                            });
                          }
                        }}
                        href={`/api/projects/${project.id}/exports/${ex.id}/download`}
                        download={`${project.title.replace(/[^a-z0-9 -]/gi, "")}${ex.inspection_only ? "-unreviewed-inspection" : ""}.mp4`}
                      >
                        <Download size={14} /> Download
                      </a>
                      <details className="download-help">
                        <summary>Download not starting?</summary>
                        <p>
                          The preview frame may restrict downloads. Copy this
                          direct link and paste it into a new browser tab to
                          save the finished MP4. It does not start another
                          render.
                        </p>
                        <input
                          aria-label={`Direct MP4 download link ${ex.id}`}
                          readOnly
                          value={
                            new URL(
                              `/api/projects/${project.id}/exports/${ex.id}/download`,
                              window.location.origin,
                            ).href
                          }
                          onFocus={(ev) => ev.target.select()}
                        />
                        <a
                          href={`/api/projects/${project.id}/exports/${ex.id}/download`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Open download outside the preview
                        </a>
                      </details>
                      <a
                        className="icon-btn"
                        href={ex.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Open rendered video"
                      >
                        <ExternalLink size={15} />
                      </a>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="exports-empty">
                  <Film size={24} />
                  <div>
                    <h4>Your first export belongs here.</h4>
                    <p>
                      Render a review draft at any point. Final exports require
                      the editorial checks.
                    </p>
                  </div>
                  <Button
                    icon={Download}
                    disabled={locked || !scenes.length}
                    onClick={() => openTool("export")}
                  >
                    Render a draft
                  </Button>
                </div>
              )}
            </section>
            {project.episode?.guide && project.exports.length > 0 && (
              <details className="simple-finish">
                <summary>
                  Finished downloading? Clear this temporary session.
                </summary>
                <p>
                  Only do this after saving and opening the output you need.
                  This deletes this session's server copies and browser setup
                  cache, not originals on your computer.
                </p>
                <label className="ep-checkbox">
                  <input
                    type="checkbox"
                    aria-label="Quick confirm downloads saved"
                    checked={savedBeforeClear}
                    onChange={(ev) => setSavedBeforeClear(ev.target.checked)}
                  />
                  <span>I saved and checked my downloads.</span>
                </label>
                <button
                  className="btn"
                  aria-label="Finish and clear session"
                  disabled={locked || !savedBeforeClear}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await flushSave();
                      await api(
                        `/api/projects/${project.id}/session`,
                        "DELETE",
                        { confirm_download_saved: true },
                      );
                      pending.current = {};
                      await forgetSetup(project.id).catch(() => {});
                      await clearWorkingFiles(project.id).catch(() => {});
                      window.location.reload();
                    } catch (error) {
                      report(error);
                      setBusy(false);
                    }
                  }}
                >
                  Clear this session
                </button>
              </details>
            )}
          </main>
        )}
      </div>
      {voice && <audio ref={audioRef} src={voice.url} preload="metadata" />}
      {searchOpen && (
        <SearchPalette
          items={buildIndex({ scenes, assets, offsets, looks: LOOKS, transitions: TRANSITIONS })}
          onPick={runSearch}
          onClose={() => setSearchOpen(false)}
          onAskDirector={askDirector}
        />
      )}
      <input
        ref={fileRef}
        type="file"
        hidden
        multiple
        accept=".png,.jpg,.jpeg,.webp,.mp4,.mov,.webm,.mkv,.mp3,.wav,.m4a,.aac,.ogg,.flac,.txt,.md"
        onChange={(e) => uploadFiles(e.target.files)}
      />
      <input
        ref={audioFileRef}
        type="file"
        hidden
        multiple
        aria-label="Import audio"
        accept=".mp3,.wav,.m4a,.aac,.ogg,.flac,.mp4,.mov,.webm"
        onChange={(e) => uploadFiles(e.target.files, audioRoleRef.current)}
      />
      {activeJob && (
        <div className="job-card">
          <div className="job-card-title">
            <LoaderCircle size={15} className="spin" />
            <b>
              {{
                render: "Rendering video",
                research: "Researching case",
                script: "Drafting script",
                narration: "Generating narration",
                transcription: "Transcribing audio",
                direction: "Applying direction",
                production: "Producing review draft",
                fetch: "Fetching from YouTube",
                discovery: "Searching YouTube",
                voice: "Generating the narration",
                recut: "Re-cutting the video",
                timing: "Making the timing",
              }[activeJob.kind] || "Working"}
            </b>
            <span>{activeJob.progress}%</span>
            <IconButton
              icon={X}
              label="Cancel current operation"
              onClick={async () => {
                try {
                  await api(`/api/jobs/${activeJob.id}/cancel`, "POST", {});
                  notify("Cancellation requested.", "info");
                } catch (e) {
                  report(e);
                }
              }}
            />
          </div>
          <div className="progress-track">
            <div style={{ width: activeJob.progress + "%" }} />
          </div>
          <p>{activeJob.message}</p>
        </div>
      )}
      {toast && (
        <div role="status" className={`toast ${toast.tone}`}>
          {toast.tone === "error" ? (
            <AlertTriangle size={17} />
          ) : toast.tone === "info" ? (
            <Info size={17} />
          ) : (
            <CheckCircle2 size={17} />
          )}
          <span>{toast.message}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast(null)}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {modal === "new" && (
        <NewProjectModal
          onClose={() => setModal(null)}
          onCreate={async (data) => {
            try {
              await flushSave();
              const p = await api("/api/projects", "POST", data);
              pending.current = {};
              acceptProject(p);
              setHome(false);
              setTime(0);
              setSelectedId(null);
              setJobs([]);
              setModal(null);
              setTab(
                data.mode === "narration"
                  ? "setup"
                  : data.mode === "topic"
                    ? "research"
                    : data.mode === "script"
                      ? "script"
                      : "edit",
              );
              if (data.mode === "footage")
                setTimeout(() => setModal("media"), 50);
              notify("Project created. Start with your source material.");
            } catch (e) {
              report(e);
            }
          }}
        />
      )}
      {modal === "projects" && (
        <Modal
          title="Your documentaries"
          eyebrow="THE WORKSPACE"
          onClose={() => setModal(null)}
        >
          <div className="project-list-modal">
            {projectList.map((p) => (
              <div className="project-row" key={p.id}>
              <button
                className={p.id === project.id ? "selected" : ""}
                onClick={() => openProject(p.id)}
              >
                <div className="project-folder">
                  <Clapperboard size={20} />
                </div>
                <span>
                  <b>{p.title}</b>
                  <small>
                    {p.is_demo
                      ? "Fictional sample"
                      : `${p.target_minutes} min target`}{" "}
                    · {elapsed(p.updated_at)}
                  </small>
                </span>
                {p.id === project.id ? (
                  <Check size={16} />
                ) : (
                  <ChevronRight size={16} />
                )}
              </button>
              {!p.is_demo && (
                <button
                  className="project-delete"
                  aria-label={"Delete " + p.title}
                  title="Delete this project and its files"
                  onClick={() => deleteProject(p)}
                >
                  <Trash2 size={15} />
                </button>
              )}
              </div>
            ))}
          </div>
          <div className="modal-footer">
            <span>Projects are saved to this workspace.</span>
            <Button kind="primary" icon={Plus} onClick={() => setModal("new")}>
              New project
            </Button>
          </div>
        </Modal>
      )}
      {modal === "settings" && (
        <SettingsModal
          config={config}
          onClose={() => setModal(null)}
          onSaved={(c) => {
            setConfig(c);
            setModal(null);
            notify(
              c.connected
                ? "AI service connected. Provider usage charges may apply."
                : "AI service disconnected.",
            );
          }}
          onError={report}
        />
      )}
      {stickerDialog && (
        <StickerDialog
          time={time}
          assets={assets}
          onClose={() => setStickerDialog(false)}
          onAdd={(kind, assetId) => addSticker(kind, assetId)}
          onUpload={uploadSticker}
        />
      )}
      {cropId && assets.find((a) => a.id === cropId) && (
        <CropDialog
          asset={assets.find((a) => a.id === cropId)}
          fitFor={(crop) => pictureFit(project, selected, { crop })}
          aspect={aspectOf(project)}
          api={api}
          projectId={project.id}
          notify={notify}
          onClose={() => setCropId(null)}
          onSaved={(p) => {
            setProject(p);
            setCropId(null);
            notify("Crop saved. Every scene using this file shows it.");
          }}
        />
      )}
      {modal === "replace" && selected && (
        <ReplacePicker
          scene={selected}
          assets={assets}
          onClose={() => setModal(null)}
          onUpload={async (file) => {
            try {
              const form = new FormData();
              form.append("files", file);
              const p = await api(`/api/projects/${project.id}/upload`, "POST", form);
              setProject(p);
              return p.assets.at(-1)?.id;
            } catch (e) {
              report(e);
              return null;
            }
          }}
          onPick={(id, start) => {
            const a = assets.find((x) => x.id === id) || project.assets?.find((x) => x.id === id);
            updateScene({ asset_id: id, trim_start: a?.kind === "video" ? start : 0, replaced: true, source_label: "" });
            setModal(null);
            notify("Picture replaced. The scene keeps its length and narration.");
          }}
        />
      )}
      {modal === "media" && (
        <Modal
          title="Your media library"
          eyebrow="THE MATERIAL"
          wide
          className="media-modal"
          onClose={() => setModal(null)}
        >
          <div className="media-modal-toolbar">
            <p>
              {assets.length} assets <span>·</span> Images, footage, voice &
              music
            </p>
            <Button
              kind="primary"
              icon={uploading ? LoaderCircle : Upload}
              disabled={uploading}
              onClick={() => fileRef.current.click()}
            >
              {uploading ? "Importing…" : "Import media"}
            </Button>
          </div>
          <div className="media-privacy">
            <LockKeyhole size={12} />
            <span>
              Shared prototype workspace · no user authentication. Use only
              non-sensitive test media.
            </span>
          </div>
          <div className="media-modal-body">
            <div
              className="media-grid"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                uploadFiles(e.dataTransfer.files);
              }}
            >
              <p className="media-upload-limits">
                Media limit: {uploadLimits}. TXT/Markdown imports: 1 MB.
              </p>
              {!assets.length && (
                <div
                  className="dropzone"
                  onClick={() => fileRef.current.click()}
                >
                  <Upload size={28} />
                  <h3>Bring your story material.</h3>
                  <p>Drop images, video, audio, or a TXT script here.</p>
                  <small>Up to 512 MB per file · 30 files per batch</small>
                </div>
              )}
              {assets.map((a) => (
                <button
                  className={`media-card ${mediaId === a.id ? "selected" : ""}`}
                  key={a.id}
                  onClick={() => setMediaId(a.id)}
                >
                  <div className="media-card-image">
                    {a.thumbnail ? (
                      <img src={a.thumbnail} alt="" />
                    ) : (
                      <div>
                        <AudioLines size={32} />
                        {a.waveform && <Wave values={a.waveform} />}
                      </div>
                    )}
                    <Badge>
                      {a.kind === "video" ? (
                        <Film size={10} />
                      ) : a.kind === "audio" ? (
                        <AudioLines size={10} />
                      ) : (
                        <ImageIcon size={10} />
                      )}{" "}
                      {a.duration ? tc(a.duration) : "IMAGE"}
                    </Badge>
                    {a.generated && (
                      <span className="ai-asset">
                        <Sparkles size={10} /> AI
                      </span>
                    )}
                  </div>
                  <strong>{a.name}</strong>
                  <small>
                    {bytes(a.size)} {a.width ? `· ${a.width}×${a.height}` : ""}
                  </small>
                </button>
              ))}
            </div>
            <div className="media-detail">
              {(() => {
                const a = assets.find((a) => a.id === mediaId);
                if (!a)
                  return (
                    <Empty icon={Layers} title="Select an asset">
                      Assign visuals, choose a voice track, or document usage
                      rights.
                    </Empty>
                  );
                return (
                  <>
                    <div className="section-label">ASSET DETAILS</div>
                    <h3>{a.name}</h3>
                    <Badge>
                      {a.generated ? "AI-GENERATED" : a.kind.toUpperCase()}
                    </Badge>
                    {a.kind === "video" && (
                      <video src={a.url} controls playsInline />
                    )}
                    {a.kind === "audio" && <audio src={a.url} controls />}
                    {a.kind === "image" && (
                      <img className="detail-image" src={a.url} alt={a.name} />
                    )}
                    <label className="field">
                      Rights & attribution notes
                      <textarea
                        key={a.id}
                        defaultValue={a.license}
                        rows="4"
                        placeholder="Owner, license, permission, and required credit…"
                        onBlur={async (e) => {
                          if (e.target.value === a.license) return;
                          try {
                            await flushSave();
                            acceptProject(
                              await api(
                                `/api/projects/${project.id}/assets/${a.id}`,
                                "PATCH",
                                { license: e.target.value },
                              ),
                            );
                          } catch (e) {
                            report(e);
                          }
                        }}
                      />
                    </label>
                    {["image", "video"].includes(a.kind) && (
                      <Button
                        className="full"
                        kind="primary"
                        icon={Check}
                        disabled={!selected}
                        onClick={() => {
                          updateScene({
                            asset_id: a.id,
                            motion: a.kind === "video" ? "none" : "slow-zoom",
                          });
                          notify("Visual assigned to the selected scene.");
                          setModal(null);
                        }}
                      >
                        Use in selected scene
                      </Button>
                    )}
                    {(a.has_audio || a.kind === "audio") && (
                      <>
                        <label className="field cc-kind-field">
                          What this file is
                          {kindPicker(a)}
                        </label>
                        <Button
                          className="full"
                          icon={Mic}
                          disabled={locked || project.narration_id === a.id || project.music_id === a.id || audioRoleOf(a, project) === "sfx"}
                          title={project.music_id === a.id ? "This is your music. Narration and music are separate files." : undefined}
                          onClick={() => {
                            queueSave({ narration_id: a.id });
                            notify(
                              "Narration track assigned. Check alignment in the timeline.",
                            );
                          }}
                        >
                          {project.narration_id === a.id ? "Your narration" : "Use as narration"}
                        </Button>
                        <Button
                          className="full"
                          icon={Music2}
                          disabled={locked || project.music_id === a.id || project.narration_id === a.id || audioRoleOf(a, project) === "sfx"}
                          title={project.narration_id === a.id ? "This is your narration. Narration and music are separate files." : undefined}
                          onClick={() => {
                            queueSave({ music_id: a.id });
                            notify("Background music assigned.");
                          }}
                        >
                          {project.music_id === a.id ? "Your music" : "Use as music"}
                        </Button>
                        <Button
                          className="full"
                          icon={Sparkles}
                          disabled={locked}
                          onClick={() => transcribeAsset(a)}
                        >
                          Transcribe & assemble
                        </Button>
                        <p className="micro-note block">
                          Transcription sends audio to your connected AI service
                          and replaces the current timeline.
                        </p>
                      </>
                    )}
                    <button
                      className="danger-link"
                      onClick={async () => {
                        if (
                          !window.confirm(
                            "Remove this asset from the project? Existing rendered exports are not changed.",
                          )
                        )
                          return;
                        try {
                          await flushSave();
                          acceptProject(
                            await api(
                              `/api/projects/${project.id}/assets/${a.id}`,
                              "DELETE",
                            ),
                          );
                          setMediaId(null);
                        } catch (e) {
                          report(e);
                        }
                      }}
                    >
                      <Trash2 size={12} /> Remove from project
                    </button>
                  </>
                );
              })()}
            </div>
          </div>
        </Modal>
      )}
      {modal === "source" && (
        <SourceModal
          onClose={() => setModal(null)}
          onSave={async (data) => {
            try {
              await flushSave();
              acceptProject(
                await api(`/api/projects/${project.id}/sources`, "POST", data),
              );
              setModal(null);
              notify(
                "Source added. Open the original and record verified notes.",
              );
            } catch (e) {
              report(e);
            }
          }}
        />
      )}
      {modal === "narrate" && (
        <Modal
          title="Give your script a voice."
          eyebrow="AI NARRATION"
          onClose={() => setModal(null)}
        >
          <div className="modal-body">
            <div className="narrate-icon">
              <AudioLines size={32} />
            </div>
            <p className="modal-lead">
              Generate narration for <b>{scenes.length} scenes</b> using the{" "}
              <b>{config.voice}</b> voice. Scene lengths will follow the
              generated audio.
            </p>
            <div className="info-grid">
              <div>
                <span>Spoken words</span>
                <b>
                  {wc(
                    scenes.map((s) => s.narration).join(" "),
                  ).toLocaleString()}
                </b>
              </div>
              <div>
                <span>Estimated duration</span>
                <b>
                  {tc(
                    (wc(scenes.map((s) => s.narration).join(" ")) / 145) * 60,
                  )}
                </b>
              </div>
            </div>
            <div className="notice warning">
              <AlertTriangle size={16} />
              <span>
                Your script is sent to the connected AI provider. Usage charges
                apply. The voice is synthetic; disclose it to viewers.
              </span>
            </div>
            <p className="micro-note block">
              Review the script before generation. This creates new audio and
              replaces the assigned narration. Change the model or voice in
              Settings.
            </p>
          </div>
          <div className="modal-footer">
            <Button onClick={() => setModal("settings")}>Voice settings</Button>
            <Button
              kind="primary"
              icon={Sparkles}
              disabled={locked}
              onClick={() => {
                setModal(null);
                startOperation(`/api/projects/${project.id}/narrate`);
              }}
            >
              Generate narration
            </Button>
          </div>
        </Modal>
      )}
      {modal === "production" && (
        <ProductionModal
          project={project}
          config={config}
          jobs={jobs}
          api={api}
          onClose={() => setModal(null)}
          onRun={runProduction}
          onNavigate={navigateTool}
          onError={report}
          onConnect={() => setModal("settings")}
        />
      )}
      {modal === "preflight" && (
        <PreflightModal
          project={project}
          api={api}
          onClose={() => setModal(null)}
          onNavigate={navigateTool}
          onError={report}
        />
      )}
      {signoffOpen && (
        <Modal
          title="Producer sign-off"
          eyebrow="ONE ACTION — YOUR RESPONSIBILITY"
          onClose={() => setSignoffOpen(false)}
        >
          <div className="modal-body">
            <p>
              One action replaces the itemized checklist: every research
              source is marked reviewed, each linked file gets a
              reuse-responsibility note, every placement is approved using the
              windows currently in the plan, and the four attestations are
              ticked.
            </p>
            <p>
              <b>Nothing is independently verified.</b> You take
              responsibility for facts, rights and permissions, Care
              instructions, and the final picture. Placements with no usable
              file stay marked gaps.
            </p>
            <p>
              The reviewed plan is rebuilt automatically as part of the sign-off
              — export whenever you’re ready and the video carries no
              inspection banner. If you rebuild the plan later, re-confirm the
              picture attestation (or sign off again).
            </p>
          </div>
          <div className="modal-footer">
            <Button onClick={() => setSignoffOpen(false)}>Cancel</Button>
            <Button
              kind="primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const result = await api(
                    `/api/projects/${project.id}/signoff`,
                    "POST",
                    { confirmed: true },
                  );
                  setSignoffOpen(false);
                  acceptProject(await api(`/api/projects/${project.id}`));
                  notify(
                    `Sign-off recorded: ${result.placements_reviewed} placements approved` +
                      (result.placements_skipped?.length
                        ? `; ${result.placements_skipped.length} skipped (no usable file)`
                        : "") +
                      (result.ready_for_final
                        ? ". The reviewed plan is built — click “Make final video” when ready."
                        : `. Reviewed plan built; final export still needs: ${result.remaining_blockers?.join("; ")}. A review draft renders now without the inspection banner.`),
                    "info",
                  );
                } catch (error) {
                  report(error);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Take responsibility & sign off
            </Button>
          </div>
        </Modal>
      )}
      {downloadGate && (
        <Modal
          title="This preview frame blocks saving files"
          eyebrow="VIDEO READY — BROWSER RESTRICTION"
          onClose={() => setDownloadGate(null)}
        >
          <div className="modal-body">
            <p>
              The review checkboxes are not the problem. This embedded frame is
              not allowed to download files or open a new tab itself.
            </p>
            <p>
              <b>
                Copy the address below, open a normal browser tab, paste it in
                the address bar and press Enter.
              </b>{" "}
              {downloadGate.kind === "video"
                ? "It saves the existing MP4; no new render is started."
                : "It opens the full editor where Save backup can download normally."}
            </p>
            <input
              aria-label="Outside preview save address"
              className="outside-save-address"
              readOnly
              value={downloadGate.url}
              onFocus={(ev) => ev.target.select()}
            />
            <p>
              Your files are not deleted by opening this address. Finish-session
              cleanup still needs your confirmation.
            </p>
          </div>
        </Modal>
      )}
      {modal === "export" && (
        <ExportModal
          project={project}
          voice={voice}
          locked={locked}
          onPreflight={() => setModal("preflight")}
          onClose={() => setModal(null)}
          onExport={startRender}
          initialDraft={!exportFinal}
        />
      )}
      {modal === "inspector" && (
        <Modal
          title="Your scene controls"
          onClose={() => setModal(null)}
          className="inspector-modal"
        >
          {renderInspector()}
        </Modal>
      )}
      {modal === "help" && (
        <Modal
          title="A thoughtful first cut."
          eyebrow="WELCOME TO CASEFILE"
          onClose={() => setModal(null)}
        >
          <div className="modal-body help-content">
            <p className="modal-lead">
              A working documentary editing prototype, built around your 20–40
              minute true-crime workflow.
            </p>
            <div>
              <FolderOpen size={18} />
              <section>
                <h3>Already have narration and an editing guide?</h3>
                <p>
                  Open Episode setup. Keep the finished voice, background music,
                  narration script, and footage guide in separate cards. Link
                  actual authorized source files to the guide's IDs, review the
                  exact clip windows and Care rules, then preview the plan. A
                  source URL is not footage or permission. No AI key is needed
                  for this path.
                </p>
                <button
                  className="btn"
                  onClick={() => {
                    setModal(null);
                    setPlaying(false);
                    setTab("setup");
                  }}
                >
                  Open Episode setup <ArrowUpRight size={12} />
                </button>
              </section>
            </div>
            <div>
              <Images size={18} />
              <section>
                <h3>Finding your way in Edit (laid out like CapCut)</h3>
                <p>
                  Left: the icon tabs — Media, Audio, Text, Stickers, Effects,
                  Transitions, Captions, Filters and Graphics — hold everything
                  you add to the video. Middle: the player. Right: the settings
                  of whatever you clicked: Video for a picture clip, Audio for the
                  narration or the music, and a sticker, graphic, sound effect,
                  caption or the subscribe animation when you click it on the
                  timeline (“← Scene” goes back). Bottom: the timeline with its
                  tools (undo, split, zoom). The Director takes edits in plain
                  English: its tab sits in the right panel (or press the Director
                  button, bottom right). The pages (Episode setup, Research,
                  Script, Review & export …) are in the top bar; the menu beside
                  the logo has Home, your projects, backups, help and settings.
                  Can't find something? Press Search in the top bar (or Ctrl+K / ⌘K)
                  and type what you want: a tool, a setting, a scene or a word from
                  the narration. Narration, music and sound effects each have their
                  own place under Audio. The page fits your screen: on a 13-inch
                  laptop the side panels narrow a little so the player stays big,
                  and the timeline is never taller than its tracks (drag its top
                  edge to make it shorter). On a phone the page scrolls: player,
                  then the tabs, then the timeline.
                </p>
              </section>
            </div>
            <div>
              <Sticker size={18} />
              <section>
                <h3>Point at, blur or spotlight anything — and keep it there</h3>
                <p>
                  Stickers → Point &amp; mark has a spotlight (the rest of the
                  picture darkens), a blur for a face or a number plate, a black
                  bar, a box, a pulse ring, a pointer, a callout and a label. Add
                  one, then on the right press “Click what to follow” and click
                  the face, car or spot in the player: Casefile watches the
                  picture and moves the sticker with it until the sticker ends,
                  writing keyframes you can fix by hand (Esc cancels; “Stop”
                  keeps the path so far). Drag the corner handle to resize it,
                  the side handles to make it wider or taller. A callout, label
                  or button with words has a “Words on it” box. Text → Templates
                  has a message notification, subscribe + bell, a lower third, a
                  breaking-news bar, a quote, a place &amp; date stamp and a chapter
                  card: each line has its own box, and they move, resize, keyframe
                  and follow like any sticker. Spotlight
                  darkness and blur amount have their own setting. The export
                  draws exactly what the player shows.
                </p>
              </section>
            </div>
            <div>
              <Clapperboard size={18} />
              <section>
                <h3>Works without an AI key</h3>
                <p>
                  Saved projects, script-to-scene assembly, uploads, scene
                  controls, local text commands, captions, source notes, and
                  real FFmpeg video exports.
                </p>
              </section>
            </div>
            <div>
              <Sparkles size={18} />
              <section>
                <h3>Connect for AI production</h3>
                <p>
                  Web research with source leads, script drafts, synthetic
                  narration, audio transcription, and creative editing
                  instructions use a separately billed API key.
                </p>
              </section>
            </div>
            <div>
              <ShieldCheck size={18} />
              <section>
                <h3>The producer stays in control</h3>
                <p>
                  Review case facts, allegations, rights, captions, and pacing.
                  This app does not independently verify facts, obtain footage
                  licenses, or guarantee publication-ready results.
                </p>
              </section>
            </div>
            <div className="notice warning">
              <LockKeyhole size={16} />
              <span>
                Prototype: one shared workspace, without user authentication. Do
                not upload confidential evidence or sensitive personal files.
                Production deployment needs access controls, private storage,
                and a managed render queue.
              </span>
            </div>
          </div>
          <div className="modal-footer">
            <span>Space = play / pause · Edits save automatically</span>
            <Button kind="primary" onClick={() => setModal(null)}>
              Back to the story <ArrowUpRight size={13} />
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function NewProjectModal({ onClose, onCreate }) {
  const [title, setTitle] = useState(""),
    [mode, setMode] = useState("topic"),
    [minutes, setMinutes] = useState(25),
    [busy, setBusy] = useState(false);
  return (
    <Modal
      title="Every story starts somewhere."
      eyebrow="NEW DOCUMENTARY"
      onClose={onClose}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await onCreate({ title, mode, target_minutes: minutes });
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="modal-body">
          <label className="field large">
            Case name or working title
            <input
              autoFocus
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="What story are you telling?"
              maxLength="180"
            />
          </label>
          <label className="field">What are you starting with?</label>
          <div className="start-modes">
            {[
              ["topic", "A case or topic", "Research, then write", Search],
              ["script", "A finished script", "Narrate & assemble", FileText],
              ["narration", "Narration + media", "Build around the voice", Mic],
              ["footage", "Raw footage", "Transcribe & shape", Film],
            ].map(([id, label, desc, Icon]) => (
              <button
                type="button"
                key={id}
                className={mode === id ? "selected" : ""}
                onClick={() => setMode(id)}
              >
                <Icon size={19} />
                <strong>{label}</strong>
                <span>{desc}</span>
                {mode === id && (
                  <CheckCircle2 size={14} className="mode-check" />
                )}
              </button>
            ))}
          </div>
          <label className="field">
            Target episode length
            <select
              value={minutes}
              onChange={(e) => setMinutes(Number(e.target.value))}
            >
              {[20, 25, 30, 35, 40].map((n) => (
                <option key={n} value={n}>
                  {n} minutes
                </option>
              ))}
            </select>
          </label>
          <p className="micro-note block">
            <Info size={12} /> AI research, writing, narration, and
            transcription need a connected API key. Bring footage and music you
            have the right to use.
          </p>
        </div>
        <div className="modal-footer">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            kind="primary"
            icon={busy ? LoaderCircle : ArrowUpRight}
            disabled={!title.trim() || busy}
            type="submit"
          >
            Create project
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function SettingsModal({ config, onClose, onSaved, onError }) {
  const [key, setKey] = useState(""),
    [values, setValues] = useState({ ...config }),
    [busy, setBusy] = useState(false);
  const field = (id, label, placeholder) => (
    <label className="field">
      {label}
      <input
        value={values[id] || ""}
        placeholder={placeholder}
        onChange={(e) => setValues({ ...values, [id]: e.target.value })}
      />
    </label>
  );
  return (
    <Modal
      title="Your production connections."
      eyebrow="WORKSPACE SETTINGS"
      onClose={onClose}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            const r = await api("/api/config", "POST", { ...values, key });
            setKey("");
            onSaved(r);
          } catch (e) {
            onError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="modal-body">
          <div className="provider-card">
            <div className="provider-icon">
              <Sparkles size={23} />
            </div>
            <div>
              <h3>OpenAI API</h3>
              <p>Research, writing, speech & transcription</p>
            </div>
            <Badge tone={config.connected ? "green" : ""}>
              {config.connected ? "Connected" : "Not connected"}
            </Badge>
          </div>
          <label className="field">
            API key{" "}
            <span className="field-note">Private to this browser session</span>
            <input
              type="password"
              autoComplete="new-password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={
                config.connected
                  ? "Leave blank to keep the connected key"
                  : "Enter your API key"
              }
            />
          </label>
          <div className="field-row">
            {field("model", "Writing / editing model", "gpt-4.1")}
            {field("research_model", "Web research model", "gpt-4.1")}
          </div>
          <div className="field-row">
            {field("speech_model", "Speech model", "gpt-4o-mini-tts")}
            <label className="field">
              Narrator voice
              <select
                value={values.voice || "onyx"}
                onChange={(e) =>
                  setValues({ ...values, voice: e.target.value })
                }
              >
                {[
                  "onyx",
                  "alloy",
                  "echo",
                  "fable",
                  "nova",
                  "shimmer",
                  "coral",
                  "sage",
                  "ash",
                ].map((v) => (
                  <option value={v} key={v}>
                    {v[0].toUpperCase() + v.slice(1)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="notice">
            <LockKeyhole size={16} />
            <span>
              Your key is held in server memory and never written to project
              files. Restarting the server disconnects it. API charges are
              separate from a chat subscription.
            </span>
          </div>
          <p className="micro-note block">
            Defaults are configurable; model access depends on your provider
            account. The current Speech API defaults are scheduled for
            retirement in January 2027 and will need a provider adapter update.
            No paid AI calls were made to produce the sample.
          </p>
          <div className="settings-local">
            <CheckCircle2 size={16} />
            <div>
              <b>Local editing & FFmpeg rendering</b>
              <p>Already available. No AI key needed.</p>
            </div>
            <Badge tone="green">Ready</Badge>
          </div>
        </div>
        <div className="modal-footer">
          {config.connected ? (
            <Button
              type="button"
              kind="danger"
              onClick={async () => {
                try {
                  onSaved(await api("/api/config", "DELETE"));
                } catch (e) {
                  onError(e);
                }
              }}
            >
              Disconnect
            </Button>
          ) : (
            <span>Use non-sensitive test material in this prototype.</span>
          )}
          <Button
            kind="primary"
            icon={busy ? LoaderCircle : LockKeyhole}
            disabled={busy || (!key && !config.connected)}
            type="submit"
          >
            {busy ? "Verifying…" : "Connect & verify"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function SourceModal({ onClose, onSave }) {
  const [values, setValues] = useState({
      title: "",
      url: "",
      notes: "",
      type: "Producer source",
    }),
    [busy, setBusy] = useState(false);
  return (
    <Modal
      title="Keep the source trail clear."
      eyebrow="ADD A SOURCE"
      onClose={onClose}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await onSave(values);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="modal-body">
          <label className="field">
            Source title
            <input
              autoFocus
              required
              value={values.title}
              onChange={(e) => setValues({ ...values, title: e.target.value })}
              placeholder="Court record, article, or interview…"
            />
          </label>
          <label className="field">
            Original URL{" "}
            <span className="field-note">Optional for offline records</span>
            <input
              type="url"
              value={values.url}
              onChange={(e) => setValues({ ...values, url: e.target.value })}
              placeholder="https://…"
            />
          </label>
          <label className="field">
            Source type
            <select
              value={values.type}
              onChange={(e) => setValues({ ...values, type: e.target.value })}
            >
              {[
                "Producer source",
                "Court / official record",
                "Reporting",
                "Interview / recording",
                "Archive / document",
              ].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Verified facts & context
            <textarea
              rows="5"
              value={values.notes}
              onChange={(e) => setValues({ ...values, notes: e.target.value })}
              placeholder="Specific facts, dates, quotations, attribution, and uncertainties…"
            />
          </label>
          <p className="micro-note block">
            Adding a source does not mark it verified. Review the original, then
            mark it reviewed in the source library.
          </p>
        </div>
        <div className="modal-footer">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            kind="primary"
            icon={busy ? LoaderCircle : Plus}
            disabled={!values.title.trim() || busy}
          >
            Add source
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ExportModal({
  project,
  voice,
  onClose,
  onExport,
  locked,
  onPreflight,
  initialDraft = true,
}) {
  const [resolution, setResolution] = useState("720p"),
    [draft, setDraft] = useState(initialDraft),
    [captions, setCaptions] = useState(project.captions);
  const allReviewed = Object.values(project.review).every(Boolean);
  const inspectionPlan = project.episode?.plan?.mode === "inspection";
  const [allowGuideGaps, setAllowGuideGaps] = useState(false);
  const hasGuideGaps =
    !!project.episode?.guide && project.scenes.some((s) => !s.asset_id);
  const [preflight, setPreflight] = useState(null);
  const [preflightError, setPreflightError] = useState(false);
  useEffect(() => {
    let stopped = false;
    api(`/api/projects/${project.id}/preflight`)
      .then((r) => {
        if (!stopped) setPreflight(r);
      })
      .catch(() => {
        if (!stopped) setPreflightError(true);
      });
    return () => {
      stopped = true;
    };
  }, [project.updated_at]);
  return (
    <Modal
      title="Make the final cut real."
      eyebrow="RENDER & DOWNLOAD"
      onClose={onClose}
    >
      <div className="modal-body">
        <div className="export-spec">
          <div className="export-file-icon">
            <Film size={25} />
          </div>
          <div>
            <h3>{project.title}</h3>
            <p>
              {tc(sum(project.scenes))} · {project.scenes.length} scenes · {aspectOf(project)}
            </p>
          </div>
          <Badge>MP4</Badge>
        </div>
        <label className="field">
          Resolution
          <select
            aria-label="Export resolution"
            value={resolution}
            onChange={(e) => setResolution(e.target.value)}
          >
            <option value="480p">480p · Quick review render</option>
            <option value="720p">720p HD · Faster draft</option>
            <option value="1080p">1080p Full HD · Larger file</option>
          </select>
        </label>
        <div className="export-switch">
          <div>
            <b>Review draft</b>
            <p>
              Includes a visible draft watermark. Final exports require
              editorial review.
            </p>
          </div>
          <Toggle
            checked={draft}
            onChange={setDraft}
            label="Review draft watermark"
          />
        </div>
        <div className="export-switch">
          <div>
            <b>Burn in captions</b>
            <p>A separate SRT file is also saved with the export.</p>
          </div>
          <Toggle
            checked={captions}
            onChange={setCaptions}
            label="Burn in captions"
          />
        </div>
        {!voice && (
          <div className="notice warning">
            <VolumeX size={16} />
            <span>
              {project.episode?.guide ? (
                <>
                  <b>Upload your finished narration first.</b> A script-only
                  guide plan cannot render a video. Assign the recording in
                  Episode setup, card 1; it will not be regenerated.
                </>
              ) : (
                <>
                  <b>No narration assigned.</b> This draft will have no spoken
                  voice. Add a voice track in the Audio panel for a complete
                  episode.
                </>
              )}
            </span>
          </div>
        )}
        {draft && hasGuideGaps && (
          <label className="ep-checkbox" style={{ padding: "12px 0" }}>
            <input
              type="checkbox"
              aria-label="Allow marked guide gaps in review export"
              checked={allowGuideGaps}
              onChange={(ev) => setAllowGuideGaps(ev.target.checked)}
            />
            <span>
              I explicitly allow visibly marked missing-visual cards in this
              internal review-only video. No substitute footage will be invented
              or looped.
            </span>
          </label>
        )}
        {inspectionPlan && (
          <div className="notice warning">
            <AlertTriangle size={16} />
            <span>
              <b>Unreviewed inspection only.</b> This rendering is visibly
              marked and cannot be a final export. Complete real source reviews
              and rebuild a reviewed plan before publication.
            </span>
          </div>
        )}
        {!draft && !allReviewed && (
          <div className="notice warning">
            <ShieldCheck size={16} />
            <span>
              Complete all four editorial checks in Review before making a final
              export.
            </span>
          </div>
        )}
        {project.is_demo && (
          <p className="micro-note block">
            The fictional-demo disclosure is always included in this sample's
            renders.
          </p>
        )}
        <div className="preflight-summary-line">
          <ShieldCheck size={13} />
          <span>
            {preflight
              ? `${preflight.errors} final-export blockers · ${preflight.warnings} review warnings`
              : preflightError
                ? "Preflight unavailable. Final rendering remains locked."
                : "Checking export prerequisites…"}
          </span>
          <button onClick={onPreflight}>
            View checks <ArrowUpRight size={11} />
          </button>
        </div>
        <div className="render-details">
          <span>
            <Check size={12} /> H.264 video · 24 fps
          </span>
          <span>
            <Check size={12} />{" "}
            {project.episode?.guide
              ? "Preserved voice & music ducking"
              : "Audio leveling & music ducking"}
          </span>
          <span>
            <Check size={12} /> Downloadable MP4 + source notes
          </span>
        </div>
        <p className="micro-note block">
          Rendering runs on this server's CPU. A 20–40 minute episode may take a
          substantial amount of time. This prototype does not include GPU
          acceleration.
        </p>
      </div>
      <div className="modal-footer">
        <Button onClick={onClose}>Back to editing</Button>
        <Button
          kind="primary"
          icon={Download}
          disabled={
            locked ||
            !project.scenes.length ||
            !preflight ||
            (draft && hasGuideGaps && !allowGuideGaps) ||
            (preflight && !preflight.ready_for_draft) ||
            (!draft &&
              (inspectionPlan || !allReviewed || !preflight?.ready_for_final))
          }
          onClick={() =>
            onExport({
              resolution,
              draft,
              captions,
              allow_guided_gaps: allowGuideGaps,
              allow_inspection: inspectionPlan && draft,
            })
          }
        >
          Start render
        </Button>
      </div>
    </Modal>
  );
}

createRoot(document.getElementById("root")).render(<App />);
