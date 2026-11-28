// v0.4.69 Sorting the Media library. Assets are stored in the order they were imported,
// so "newest" is simply the end of the list. "Order in the edit" puts files in the order
// their scenes play, then everything not used yet in import order.
export function sortMedia(list, how, scenes = []) {
  const at = new Map(list.map((a, i) => [a.id, i]));
  const firstUse = new Map();
  scenes.forEach((s, i) => {
    if (s && s.asset_id && !firstUse.has(s.asset_id)) firstUse.set(s.asset_id, i);
  });
  const name = (a) => String(a.name || "").toLowerCase();
  const out = [...list];
  if (how === "newest") return out.reverse();
  if (how === "name") return out.sort((a, b) => name(a).localeCompare(name(b), undefined, { numeric: true }) || at.get(a.id) - at.get(b.id));
  if (how === "longest") return out.sort((a, b) => (Number(b.duration) || 0) - (Number(a.duration) || 0) || at.get(a.id) - at.get(b.id));
  if (how === "timeline") {
    const key = (a) => (firstUse.has(a.id) ? firstUse.get(a.id) : Infinity);
    return out.sort((a, b) => key(a) - key(b) || at.get(a.id) - at.get(b.id));
  }
  return out; // "oldest": import order
}
