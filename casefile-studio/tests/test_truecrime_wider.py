"""v0.4.66 The six true-crime detectors read more than the Javits script's wording.

* A third script (tests/fixtures/sheriff-script.md, fictional) says everything differently: a sheriff's office and
  deputies, "persons of interest", "remains under investigation", a magistrate, a bond, a plea, "more than five
  months". Before v0.4.66 it got two graphics (timeline, legal); now all six.
* Each new phrasing on its own, in a one-chapter script.
* Words on screen are still the script's: what the engine does not recognise is left out, a span the dates do not
  confirm is never shown, and the Javits graphics are unchanged (tests/test_cinegfx_engine.py + the stills check)."""
import re
from pathlib import Path

import pytest

import cinematic
from cinegfx import story as S
from cinegfx.collections import truecrime as TC

FIX = Path(__file__).resolve().parent / "fixtures" / "sheriff-script.md"
SIX = {"findings", "timeline", "contradiction", "legal", "digital", "turning"}


def sheriff_project():
    scenes, chapter = [], None
    for line in FIX.read_text().splitlines():
        m = re.match(r"## Chapter \d+ — (.+)", line)
        if m:
            chapter = m.group(1).strip().upper()
            continue
        if line.startswith("#"):
            chapter = None
            continue
        if chapter and line.strip() and not line.startswith("**"):
            scenes.append({"id": f"s{len(scenes)}", "title": "", "chapter": chapter, "narration": line.strip(),
                           "duration": round(len(line.split()) * 0.38 + 0.4, 2)})
    return {"id": "sh", "title": "The Last Timeline — Dana Whitfield", "topic": "Dana Whitfield", "created_at": "2026-11-24T09:00:00",
            "scenes": scenes, "assets": [], "motion": {"enabled": True, "items": []}}


@pytest.fixture(scope="module")
def sheriff():
    p = sheriff_project()
    return p, {x["category"]: x for x in cinematic.suggest(p, [])}


def story(text, title="# The Last Timeline — Dana Whitfield"):
    return S.parse_script(f"{title}\n**Recording date:** November 24, 2026\n## Chapter 1 — The case\n{text}\n")


def test_the_third_script_gets_all_six(sheriff):
    p, items = sheriff
    assert set(items) == SIX
    narration = " ".join(s["narration"] for s in p["scenes"])
    for x in items.values():  # every word on screen is the narration's own
        assert x["text"] in narration
        assert all(x["text"][w[3]:w[4]].lower().replace("\u2019", "'") == w[0] for w in x["words"])


def test_findings_in_other_words(sheriff):
    f = sheriff[1]["findings"]["payload"]
    assert f["source"] == "Ray Okafor" and f["agency"] == "SHERIFF’S OFFICE"
    assert [(i["label"], i["status"]) for i in f["items"]] == [
        ("TWO COWORKERS", "PERSON OF INTEREST"), ("HER MOTHER'S BOYFRIEND", "NOT BELIEVED INVOLVED"), ("THOMAS REED", "UNDER INVESTIGATION")]
    for i in f["items"]:
        assert i["phrase"] in " ".join(s["narration"] for s in sheriff[0]["scenes"])


def test_timeline_clock_times_take_that_night(sheriff):
    t = sheriff[1]["timeline"]["payload"]
    assert t["clock"] and [(e["clock"], e["ampm"]) for e in t["events"]] == [("10:12", "PM"), ("10:40", "PM"), ("11:05", "PM")]
    assert t["events"][0]["label"] == "She closed out the register"  # "deputies said" is not part of the event


def test_contradiction_alone_against_with_others(sheriff):
    c = sheriff[1]["contradiction"]["payload"]
    assert c["official"][0]["text"] == "Reed was alone at the boat ramp that night"
    assert c["family"][0]["text"] == "Reed was with two friends at a bar in Westbrook"
    assert "alone|with others" in c["topic"] and c["labels"]["family"] == "THE DEFENSE"


def test_legal_magistrate_bond_and_an_adult_named(sheriff):
    lg = sheriff[1]["legal"]["payload"]
    assert lg["charges"] == ["second-degree murder", "tampering with evidence"]
    assert lg["judge"] == "Helen Ortiz" and lg["judge_title"] == "Magistrate"
    assert lg["outcome"] == "bond $750,000" and lg["hearing"] == "bond hearing" and lg["date"] == "2025-08-18"
    assert lg["defendant"] == "Thomas Reed"  # "41-year-old Thomas Reed": an adult, named as the narration names him


def test_digital_statuses_moves_and_agency(sheriff):
    d = sheriff[1]["digital"]["payload"]
    st = {i["label"]: i["status"] for i in d["items"]}
    assert st["PHONE"] == "RECOVERED BY DEPUTIES" and st["FINGERPRINTS"] == "MATCHED"
    assert [r["what"] for r in d["route"]] == ["boat ramp", "Lakeview Road"]
    assert d["by"] == "SHERIFF’S OFFICE"


def test_turning_months_and_word_age(sheriff):
    t = sheriff[1]["turning"]["payload"]
    assert t["days"] == 158 and t["span_label"] == "more than five months" and t["age"] == 19 and t["who"] == "41-year-old"


def test_the_graphics_draw(sheriff):
    for x in sheriff[1].values():
        g = cinematic.build(x, {})
        g.frame(g.duration * 0.9)


# ---------------------------------------------------------------- each phrasing on its own

def test_findings_from_what_investigators_did():
    st = story("Detectives reported finding records of Thomas Reed calling Whitfield, along with text messages, notes and search history. "
               "Police said the material implicated Reed in her death. "
               "Police also said one message contained a detail about the killing that had not been publicly released.")
    r = TC.detect_findings(st, 0, 3)
    assert r
    items = [(i["label"], i["status"]) for i in r[1]["items"]]
    assert items[:4] == [("RECORDS", "FOUND"), ("TEXT MESSAGES", "FOUND"), ("NOTES", "FOUND"), ("SEARCH HISTORY", "FOUND")]
    assert ("REED", "IMPLICATED") in items
    assert r[1]["person"] is False and r[1]["source"] == "Detectives"  # no portrait asked for "Detectives"
    assert TC.slots_findings(r[1]) == []


def test_findings_unattributed_no_arrest_inside_a_sentence():
    st = story("At that point, no arrest had been announced.")
    assert [(i["label"], i["status"]) for i in TC._finding_items(st, st.sentences[0])] == [("ARREST", "NOT ANNOUNCED")]


def test_findings_quote_only_from_quotation_marks():
    base = "Sheriff Ray Okafor called two coworkers persons of interest. Okafor said deputies do not believe her mother's boyfriend was involved. " \
           "Okafor added that Thomas Reed remains under investigation. "
    quoted = TC.detect_findings(story(base + "Okafor described the killing as “a deliberate act.”"), 0, 4)
    plain = TC.detect_findings(story(base + "Okafor described the killing as a deliberate act."), 0, 4)
    assert quoted[1]["quote"]["quote"] == "a deliberate act" and plain[1]["quote"] is None


def test_timeline_new_event_verbs_split_the_label():
    st = story("On March 3, 2025, Dana Whitfield was last seen leaving the diner. On March 4, 2025, her car was found at a boat ramp. "
               "On March 9, 2025, the search ended.")
    ev = TC.detect_timeline(st, 0, 3)[1]["events"]
    assert [(e["label"], e["sub"]) for e in ev] == [("Dana Whitfield", "was last seen leaving the diner"),
                                                    ("Her car", "was found at a boat ramp"), ("The search", "ended")]


def test_contradiction_armed_against_unarmed():
    st = story("Detective Lena Cruz said Reed was armed with a knife that night. Defense attorney Paul Danner said Reed was unarmed when deputies arrived.")
    r = TC.detect_contradiction(st, 0, 2)
    assert r and "unarmed|armed" in r[1]["topic"]


def test_legal_plea_and_recognizance():
    st = story("On February 10, 2026, Reed pleaded guilty to voluntary manslaughter under a plea agreement. Circuit Judge Mark Haley accepted the plea.")
    lg = TC.detect_legal(st, 0, 2)[1]
    assert lg["charges"] == ["voluntary manslaughter"] and lg["outcome"] == "pleaded guilty" and lg["judge"] == "Mark Haley"
    assert "judge_title" not in lg  # "Circuit Judge Mark Haley" is said as "Judge Mark Haley": the graphic's own wording
    st = story("On June 2, 2025, Reed was charged with assault in Calder County Municipal Court. He was released on his own recognizance.")
    assert TC.detect_legal(st, 0, 2)[1]["outcome"] == "released on his own recognizance"


def test_digital_never_recovered_and_actor():
    assert TC._ev_status("The murder weapon was never recovered.", "weapon") == ("NEVER RECOVERED", "recovered")
    assert TC._ev_status("Police obtained footage from nearby homes.", "footage") == ("OBTAINED BY POLICE", "Police obtained")
    assert TC._ev_status("The footage was grainy.", "footage") is None  # nothing said about it: no status


def test_turning_span_must_agree_with_the_dates():
    head = "On March 9, 2025, Dana Whitfield was killed. "
    ok = story(head + "On August 14, 2025, deputies arrested Thomas Reed. Nearly six months later, the case was solved.")
    assert TC._turning_elapsed(ok, ok.sentences[1], ok.sentences[2])[1]["span_label"] == "nearly six months"
    wrong = story(head + "On August 14, 2025, deputies arrested Thomas Reed. Two months later, the case was solved.")
    assert TC._turning_elapsed(wrong, wrong.sentences[1], wrong.sentences[2]) is None  # never a span the dates do not confirm
    days = story(head + "On March 19, 2025, deputies arrested Thomas Reed. Ten days later, the case was solved.")
    p = TC._turning_elapsed(days, days.sentences[1], days.sentences[2])[1]
    assert p["days"] == 10 and "span_label" not in p


def test_turning_reads_a_word_age():
    st = story("Fourteen-year-old Dana Whitfield lived in Westbrook. Dana Whitfield was killed on March 9, 2025.")
    assert TC._subject_age(st) == 14
    st = story("Dana Whitfield was fourteen and in the eighth grade.")
    assert TC._subject_age(st) == 14
