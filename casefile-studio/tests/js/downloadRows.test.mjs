import test from "node:test";
import assert from "node:assert/strict";
// DownloadRows.jsx is JSX: bundle it with esbuild (a dev dependency) to test
// its plain helpers in node. Skipped if esbuild is not installed.
const esbuild = await import("esbuild").catch(() => null);
const out = esbuild && await esbuild.build({
  entryPoints: ["web/src/DownloadRows.jsx"], bundle: true, write: false, format: "esm", platform: "node",
  external: ["react", "lucide-react"], logLevel: "silent",
});
const mod = out && await import("data:text/javascript;base64," + Buffer.from(out.outputFiles[0].text.replace(/^import .* from "(react|lucide-react)";$/gm, "")).toString("base64")).catch(() => null);

test("each row says what is happening", { skip: !mod && "could not bundle DownloadRows" }, () => {
  const { describe, STALL_SECONDS } = mod;
  assert.equal(describe({ status: "waiting" }).text, "Waiting");
  const d = describe({ status: "downloading", done: 2.5e6, total: 5e6, speed: 1.25e6, part: "video", idle: 1 });
  assert.equal(d.pct, 50);
  assert.equal(d.text, "50% · 1.3 MB/s · 2.5 MB of 5.0 MB · video");
  assert.equal(d.stalled, false);
  assert.equal(describe({ status: "downloading", done: 1e6, idle: STALL_SECONDS + 1 }).stalled, true);
  assert.equal(describe({ status: "downloading", done: 3e6 }).text, "3.0 MB so far");
  assert.equal(describe({ status: "failed", error: "Video unavailable" }).text, "Video unavailable");
  const cut = describe({ status: "downloading", secs: 72, secs_total: 168, done: 12e6 });
  assert.equal(cut.pct, 43);
  assert.equal(cut.text, "43% · 1:12 of 2:48 of video · 12.0 MB so far");
});
