"""One graphic of every template x layout (+ typed entrances) in one project, 14 s apart; print each element's sound."""
import sys, json, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import motion, sound
from test_sound import gitem, proj
LINES = {
 "findings": [{"text": "Phone records placed him near the scene", "at": 2.0}, {"text": "Video showed the car on Nebraska Avenue", "at": 3.5}, {"text": "A receipt eleven minutes later", "at": 5.0}],
 "timeline": [{"text": "Last seen leaving work", "label": "MARCH 3", "at": 2.0}, {"text": "Phone goes silent", "label": "MARCH 4", "at": 3.5}, {"text": "Car found", "label": "MARCH 9", "at": 5.0}],
 "contrast": [{"text": "I was home all night", "kind": "statement", "label": "HE SAID", "at": 2.0}, {"text": "Phone pinged two miles away at 11:40", "kind": "finding", "label": "THE RECORD", "at": 4.0}, {"text": "His car was on camera at 11:52", "kind": "finding", "label": "VIDEO", "at": 5.5}],
 "legal": [{"text": "Charged with first-degree murder", "label": "CHARGED", "at": 2.0}, {"text": "Jury trial in Hillsborough County", "label": "TRIAL", "at": 3.5}, {"text": "Guilty on all counts", "label": "CONVICTED", "at": 5.0}],
}
def build(extra=None):
    items, t = [], 1.0
    for tpl, lays in motion.SPEC["layouts"].items():
        for lay, _ in lays:
            if lay == "auto": continue
            for enter in (["default", "type"] if lay in ("stack", "horizontal", "columns", "list") else ["default"]):
                kw = dict(id=f"{tpl}-{lay}-{enter}"[:24].replace("-", "x"), template=tpl, layout=lay, start=t, end=t + 8.0, lines=[dict(l, at=l["at"] + t - 1) for l in LINES[tpl]],
                          heading=motion.TEMPLATES[tpl]["heading"], title={"findings": "What the records showed", "timeline": "Eleven days in March", "contrast": "Two versions of one night", "legal": "The case in court"}[tpl])
                if enter == "type": kw["enter"] = "type"
                items.append((f"{tpl}/{lay}/{enter}", gitem(**kw))); t += 40.0
    n = int(t // 20) + 1
    scenes = [{"id": f"s{k}", "title": f"Scene {k}", "chapter": "CHAPTER 3 — THE EVIDENCE", "duration": 20.0, "narration": ""} for k in range(n)]
    return items, proj(scenes, items=[g for _, g in items], **(extra or {}))
if __name__ == "__main__":
    items, p = build()
    pl, _ = sound.resolve(p, __import__("pathlib").Path("/tmp/qa/data"))
    by = collections.defaultdict(list)
    for r in pl:
        a = r.get("anchor") or ""
        for name, g in items:
            if r["label"].endswith(f"graphic at {int(round(g['start']*24)/24 // 60)}:{int(round(g['start']*24)/24 % 60):02d}") and r["label"].split(" — ")[-1].startswith(g["template"]):
                by[name].append(f'{r["label"].split(" — ")[0]}={r["sound"]}' + (f'x{len(r["keys"])}' if r.get("keys") else ""))
    for name, _ in items: print(f"{name:28s}", ", ".join(by[name]) or "(nothing)")
