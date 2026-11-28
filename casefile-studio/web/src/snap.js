// v0.4.75 Snapping and guide lines while you drag something on the picture.
// Everything is in fractions of the frame (0..1); `tol` is how close counts (fraction of the frame width).
// The centre lines, the frame edges, the safe margins (5%), the thirds and the edges/centres of the
// other things on screen are the lines it snaps to. Hold Alt (Option) to move freely.

export const SAFE = 0.05;

export function lines(others = []) {
  const v = [
    { at: 0.5, kind: "centre" },
    { at: 0, kind: "edge" },
    { at: 1, kind: "edge" },
    { at: SAFE, kind: "safe" },
    { at: 1 - SAFE, kind: "safe" },
    { at: 1 / 3, kind: "third" },
    { at: 2 / 3, kind: "third" },
  ];
  const h = v.map((l) => ({ ...l }));
  for (const o of others) {
    v.push({ at: o.x - o.w / 2, kind: "item" }, { at: o.x, kind: "item" }, { at: o.x + o.w / 2, kind: "item" });
    h.push({ at: o.y - o.h / 2, kind: "item" }, { at: o.y, kind: "item" }, { at: o.y + o.h / 2, kind: "item" });
  }
  return { v, h };
}

const RANK = { centre: 0, item: 1, edge: 2, safe: 3, third: 4 };

// the best line for any of `anchors` ([offset from the centre]) of something centred at `c`
function best(c, anchors, targets, tol) {
  let pick = null;
  for (const a of anchors) {
    for (const t of targets) {
      const d = t.at - (c + a);
      const ad = Math.abs(d);
      if (ad > tol) continue;
      if (!pick || ad < pick.ad - 1e-9 || (Math.abs(ad - pick.ad) <= 1e-9 && RANK[t.kind] < RANK[pick.kind])) pick = { d, ad, kind: t.kind };
    }
  }
  return pick;
}

// every line that the box touches once it is placed (all of them are drawn)
function touching(c, anchors, targets) {
  const out = [];
  for (const t of targets) if (anchors.some((a) => Math.abs(t.at - (c + a)) < 1e-6)) out.push(t);
  const seen = new Set();
  return out.filter((t) => {
    const k = t.at.toFixed(5);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

// Moving a box (centre x, y; size w × h): {x, y, guides: [{axis: "v"|"h", at, kind}]}
export function snapMove(box, others, tolX, tolY = tolX * 1.7777) {
  const { v, h } = lines(others);
  const ax = [-box.w / 2, 0, box.w / 2];
  const ay = [-box.h / 2, 0, box.h / 2];
  const bx = best(box.x, ax, v, tolX);
  const by = best(box.y, ay, h, tolY);
  const x = bx ? box.x + bx.d : box.x;
  const y = by ? box.y + by.d : box.y;
  const guides = [
    ...(bx ? touching(x, ax, v).map((l) => ({ axis: "v", at: l.at, kind: l.kind })) : []),
    ...(by ? touching(y, ay, h).map((l) => ({ axis: "h", at: l.at, kind: l.kind })) : []),
  ];
  return { x, y, guides };
}

// Resizing about the centre: the edge that moves (right / bottom, or both for a corner) lands on a line.
// Returns {w, h, guides}; `keep` keeps the proportions (corner handle).
export function snapSize(box, others, tolX, tolY = tolX * 1.7777, { keep = false, edge = "right" } = {}) {
  const { v, h } = lines(others);
  let { w, h: hh } = box;
  const guides = [];
  if (edge === "right" || edge === "corner") {
    const b = best(box.x, [w / 2], v.filter((l) => l.at > box.x + 0.005), tolX);
    if (b) {
      const nw = w + 2 * b.d;
      if (keep) hh = hh * (nw / w);
      w = nw;
      guides.push({ axis: "v", at: box.x + w / 2, kind: b.kind });
    }
  }
  if (edge === "bottom" || (edge === "corner" && !guides.length)) {
    const b = best(box.y, [hh / 2], h.filter((l) => l.at > box.y + 0.005), tolY);
    if (b) {
      const nh = hh + 2 * b.d;
      if (keep) w = w * (nh / hh);
      hh = nh;
      guides.push({ axis: "h", at: box.y + hh / 2, kind: b.kind });
    }
  }
  return { w, h: hh, guides };
}
