# v0.4.59 QA scratch script kept for reproducibility (run from casefile-studio/ with PATH=$PWD/.venv/bin:$PATH, PYTHONPATH=$PWD).
import json, sys, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import motion, sound, sfxlib, effects
S = effects.SPEC["motion"]
def lines_for(tpl, t0):
    if tpl == "contrast":
        return [{"text": "I was home all night", "kind": "statement", "at": t0 + 1},
                {"text": "His phone pinged two miles away", "kind": "finding", "at": t0 + 3},
                {"text": "His car was on camera at 11:52", "kind": "finding", "at": t0 + 4.5}]
    if tpl == "legal":
        return [{"text": "Charged with murder", "label": "CHARGED", "at": t0 + 1}, {"text": "Jury trial", "label": "TRIAL", "at": t0 + 2.5},
                {"text": "Guilty on all counts", "label": "VERDICT", "at": t0 + 4}]
    if tpl == "timeline":
        return [{"text": "Last seen at the bar", "label": "MARCH 3", "at": t0 + 1}, {"text": "Car found", "label": "MARCH 5", "at": t0 + 2.5},
                {"text": "Arrest", "label": "APRIL 1", "at": t0 + 4}]
    return [{"text": "Phone records placed him near the scene", "at": t0 + 1}, {"text": "Video showed the car", "at": t0 + 2.5},
            {"text": "A receipt eleven minutes later", "at": t0 + 4}]
rows = []; bad = []
enters = [e[0] for e in S["enters"]]; exits = [e[0] for e in S["exits"]]
for aspect in ("16:9", "9:16"):
    for tpl, lays in S["layouts"].items():
        for lay, _ in lays:
            for en in enters:
                for ex in exits:
                    it = motion.normalise_item({"id": "g1", "status": "approved", "template": tpl, "layout": lay, "enter": en, "exit": ex,
                                                "start": 1.0, "end": 9.0, "heading": "HEAD", "title": "A title", "lines": lines_for(tpl, 1.0)})
                    p = {"id": "5d00000000000001", "aspect": aspect, "assets": [], "scenes": [{"id": "s1", "title": "", "chapter": "CHAPTER 3 — THE EVIDENCE", "duration": 12.0, "narration": ""}],
                         "motion": {"enabled": True, "items": [it]}, "sound": {"enabled": True}}
                    items, info = sound.plan(p)
                    cats = collections.Counter(sfxlib.BY_ID[i["sound"]][1] for i in items)
                    kinds = collections.Counter(i["kind"] for i in items)
                    rows.append({"aspect": aspect, "tpl": tpl, "layout": lay, "enter": en, "exit": ex, "n": len(items), "cats": dict(cats), "kinds": dict(kinds),
                                 "labels": [i["label"].split(" — ")[0] for i in items]})
                    if len(items) == 0 or (en == "type" and "typing" not in kinds):
                        bad.append(rows[-1])
print(len(rows), "combinations;", len(bad), "without a sound set")
for b in bad[:20]: print(b)
by = collections.defaultdict(set)
for r in rows: by[(r["tpl"], r["enter"])].update(r["cats"])
for k, v in sorted(by.items()): print(k, sorted(v))
mn = min(rows, key=lambda r: r["n"]); print("fewest:", mn)
json.dump(rows, open('/tmp/tpl_matrix.json', 'w'))
