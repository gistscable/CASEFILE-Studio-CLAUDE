"""v0.4.64 Layout check for cinematic graphics (used by the tests and qa scripts, not by the app).

Draws a graphic at its settled moments with `draw.RECORD` on and checks every line of text it drew:
  - overlap:  two pieces of text whose inked pixels' boxes cross (labels running into each other),
  - clipped:  text cut by its own reveal box once the reveal has finished (type too big for its slot),
  - touching: one text right above another with less than TIGHT px between them (not the wrapped lines of
              one paragraph: same font, size and left edge),
  - outside:  text closer than MARGIN to the frame edge, or off it.
Only the text itself is measured (the inked box of each sprite), so a photo or a panel behind text is never
reported. Pure function of the graphic: the same check runs on the approved demos and on the app's items."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cinegfx import draw as D  # noqa: E402

MARGIN = 16
TIGHT = 5   # px: stacked texts closer than this read as one block


def settled_times(g):
    """When everything drawn so far has landed: shortly after each cue, and just before the exit."""
    ts = {round(c.t + 0.75, 3) for c in g.cues if c.t + 0.75 < g.out}
    ts.add(round(g.out - 0.02, 3))
    cut = getattr(g, "t_cut", None)  # a two-phase graphic (the turning point): the end of the first phase
    if cut:
        ts.add(round(cut - 0.05, 3))
    return sorted(t for t in ts if t > 0)


def _ink(entry):
    s, key, size, x, y, sp, clip, alpha = entry
    bb = sp.getchannel("A").getbbox()
    if not bb:
        return None, None
    x, y = int(round(x)), int(round(y))
    box = (x + bb[0], y + bb[1], x + bb[2], y + bb[3])
    shown = box
    if clip:
        cx0, cy0, cx1, cy1 = clip
        shown = (max(box[0], cx0), max(box[1], cy0), min(box[2], cx1), min(box[3], cy1))
    return box, shown


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _cross(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def check_frame(g, t, final=False, draw=None):
    """Problems in the frame at time t: [(kind, text, other text or '', t)]."""
    D.RECORD = []
    try:
        (draw or g.frame)(t)
        rec = list(D.RECORD)
    finally:
        D.RECORD = None
    out = []
    boxes = []
    for e in rec:
        if e[7] < 0.9:  # still fading in or out
            continue
        box, shown = _ink(e)
        if not box:
            continue
        if final and e[6] is not None and _area(shown) < _area(box) - max(4, 0.02 * _area(box)):
            out.append(("clipped", e[0], "", t))
        vis = shown if _area(shown) > 0 else None
        if vis:
            if vis[0] < MARGIN or vis[1] < MARGIN or vis[2] > D.W - MARGIN or vis[3] > D.H - MARGIN:
                out.append(("outside", e[0], "", t))
            boxes.append((e[0], vis, (e[1], e[2], int(round(e[3])))))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (sa, a, ka), (sb, b, kb) = boxes[i], boxes[j]
            if _area(_cross(a, b)) > 6:
                out.append(("overlap", sa, sb, t))
            elif ka != kb and min(a[2], b[2]) - max(a[0], b[0]) > 0 and 0 <= max(a[1], b[1]) - min(a[3], b[3]) < TIGHT:
                out.append(("touching", sa, sb, t))  # one above the other with (almost) no room between
    return out


def check(g, draw=None):
    """Every problem at the graphic's settled moments (each reported once)."""
    seen, out = set(), []
    ts = settled_times(g)
    for t in ts:
        for p in check_frame(g, t, final=(t == ts[-1] or t == round((getattr(g, "t_cut", 0) or 0) - 0.05, 3)), draw=draw):
            k = p[:3]
            if k not in seen:
                seen.add(k)
                out.append(p)
    return out
