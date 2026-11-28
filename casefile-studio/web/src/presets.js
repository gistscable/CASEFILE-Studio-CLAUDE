import React from "react";

// v0.4.75 Your saved presets (presets.py): one list for the whole app, kept on the server so every
// project (and every browser on this computer) has them. One shared copy; every panel that shows
// presets uses usePresets() and sees changes at once.

let cache = null;
let loading = null;
const subs = new Set();
const emit = () => subs.forEach((f) => f(cache));

async function call(path, method = "GET", body) {
  const r = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data?.detail || "Could not save the preset.");
  return data;
}

export function loadPresets(force = false) {
  if (cache && !force) return Promise.resolve(cache);
  if (!loading)
    loading = call("/api/presets")
      .then((d) => {
        cache = d.presets || [];
        emit();
        return cache;
      })
      .catch(() => {
        cache = cache || [];
        emit();
        return cache;
      })
      .finally(() => {
        loading = null;
      });
  return loading;
}

export async function savePreset(kind, name, data) {
  const p = await call("/api/presets", "POST", { kind, name, data });
  cache = [...(cache || []), p];
  emit();
  return p;
}

export async function renamePreset(id, name) {
  const p = await call(`/api/presets/${id}`, "PATCH", { name });
  cache = (cache || []).map((x) => (x.id === id ? p : x));
  emit();
  return p;
}

export async function deletePreset(id) {
  await call(`/api/presets/${id}`, "DELETE");
  cache = (cache || []).filter((x) => x.id !== id);
  emit();
}

export function usePresets(kind) {
  const [list, setList] = React.useState(cache);
  React.useEffect(() => {
    subs.add(setList);
    loadPresets();
    return () => subs.delete(setList);
  }, []);
  return (list || []).filter((p) => !kind || p.kind === kind);
}

// A saved move put on something else: the same path and speeds, starting from where that thing is now
// (positions shifted, sizes scaled), squeezed in proportion when it is longer than `length`.
export function moveOnto(keys, base, length, fields = { shift: ["x", "y"], scale: ["size"] }) {
  if (!keys?.length) return [];
  const first = keys[0];
  const span = keys[keys.length - 1].t - first.t;
  const k = span > length && span > 0 ? length / span : 1;
  return keys.map((key) => {
    const out = { ...key, t: Math.round((key.t - first.t) * k * 1000) / 1000 };
    for (const f of fields.shift || []) if (f in key && f in base) out[f] = Math.round((base[f] + (key[f] - first[f])) * 10000) / 10000;
    for (const f of fields.scale || []) if (f in key && f in base && first[f] > 0) out[f] = Math.round(base[f] * (key[f] / first[f]) * 10000) / 10000;
    return out;
  });
}
