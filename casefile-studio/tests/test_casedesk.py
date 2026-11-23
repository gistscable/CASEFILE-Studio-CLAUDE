"""Case Desk (v0.4.20): gate checks in code, paste-ready packets, free
YouTube discovery through a stand-in yt-dlp. Synthetic case only."""
import json
import stat
import sys
import textwrap
import time

import app as server
import casedesk as cd
import discovery

LEDGER = textwrap.dedent("""\
    | ID | Claim | Source URL | Source date | Status | Footage on YouTube? |
    |---|---|---|---|---|---|
    | L01 | Ada Vale was 30. | https://police.example.gov/release-1 ; https://news.example.com/a | 2026-01-02 | VERIFIED | none verified |
    | L02 | She worked as a nurse, her brother said. | https://news.example.com/b | 2026-01-03 | ATTRIBUTED — brother | "Brother speaks", News 9, 2026-01-03, https://www.youtube.com/watch?v=AAAAAAAAAAA |
    | L03 | A rumour about the motive. | https://blog.example.net/x | 2026-01-04 | EXCLUDED | none verified |

    A note in the middle of the ledger.

    | L04 | The trial began on March 1. | https://news.example.com/c ; https://paper.example.org/d | 2026-03-01 | VERIFIED | none verified |
    """)
REGISTER = textwrap.dedent("""\
    | Entity | Canonical form for script | Alternate spelling / source note |
    |---|---|---|
    | Victim | **Ada Vale** | captions write **Ada Vail** |
    | Minor witness | **a neighbour** | never named |

    ## Project setup

    - Case: Ada Vale, Springfield, 2026
    - Victim: Ada Vale
    - Suspect: Tom Reed
    - Avoid tags: residential, graphic
    """)
OUTLINE = textwrap.dedent("""\
    Hook, content warning, subscribe line, then chapters.

    | Placement | Ledger ID | Words | Note |
    |---|---|---|---|
    | Hook | L01 | 12 | age |
    | Chapter 1 | L02 | 30 | work |
    | Chapter 2 | L04 | 30 | trial |
    """)
CH1 = "# Chapter 1\n\nAda Vale worked as a nurse, her brother said. He remembered long shifts and short holidays, and a sister who never complained about either of them. What happened next?\n\n### Audit footer\n\n- **IDs used:** L02.\n- **Word count:** 30.\n- **Untraceable sentences:** none.\n"


def state():
    s = cd.blank()
    s["case"].update(name="Ada Vale, Springfield, 2026", channel="Test", target_words=72)
    for g, t in (("G2", LEDGER), ("G3", REGISTER), ("G5", OUTLINE)):
        s = cd.submit(s, g, t)
    return s


def levels(findings, level):
    return [f["detail"] for f in findings if f["level"] == level]


def test_ledger_survives_a_note_in_the_middle_and_passes_when_clean():
    rows = cd.ledger(LEDGER)
    assert [r["id"] for r in rows] == ["L01", "L02", "L03", "L04"]
    found = cd.check_g2(LEDGER, cd.context(state()))
    assert not levels(found, "fail") and not levels(found, "warn")


def test_ledger_catches_the_known_failure_modes():
    bad = LEDGER.replace("| VERIFIED | none verified |\n| L02", "| VERIFIED | footage identified on https://news.example.com/video |\n| L02")
    bad += "| L05 | Single-outlet fact. | https://news.example.com/e | 2026-03-02 | VERIFIED | none verified |\n"
    bad += "| L05 | Duplicate. | https://news.example.com/f | | PROBABLY | |\n"
    text = " ".join(levels(cd.check_g2(bad, cd.context(state())), "fail") + levels(cd.check_g2(bad, cd.context(state())), "warn"))
    assert "not YouTube" in text and "L01" in text
    assert "one outlet" in text and "L05" in text
    assert "Duplicate IDs: L05" not in text  # the second L05 row is ignored as a continuation
    two = LEDGER.replace("| L03 |", "| L02 |")
    assert "Duplicate IDs: L02" in " ".join(levels(cd.check_g2(two, cd.context(state())), "fail"))


def test_project_setup_format_is_enforced():
    assert not levels(cd.check_g3(REGISTER, cd.context(state())), "fail")
    coded = REGISTER.replace("- Case", "```\nCase").replace("- Victim", "Victim").replace("- Suspect", "Suspect").replace("- Avoid tags: residential, graphic", "Avoid: none\n```")
    assert any("Victim" in d or "code block" in d for d in levels(cd.check_g3(coded, cd.context(state())), "fail"))
    aged = REGISTER.replace("- Victim: Ada Vale", "- Victim: Ada Vale (30)")
    assert any("Plain names only" in d for d in levels(cd.check_g3(aged, cd.context(state())), "fail"))


def test_outline_every_id_once_and_no_excluded_rows():
    assert not levels(cd.check_g5(OUTLINE, cd.context(state())), "fail")
    twice = OUTLINE + "| Chapter 2 | L02 | 5 | again |\n| Chapter 2 | L03 | 5 | rumour |\n"
    fails = " ".join(levels(cd.check_g5(twice, cd.context(state())), "fail"))
    assert "more than once" in fails and "L02" in fails and "EXCLUDED" in fails and "L03" in fails


def test_chapter_checks_budget_ids_footer_names_and_repetition():
    s = state()
    ctx = cd.context(s)
    assert not levels(cd.check_chapter(1, CH1, ctx), "fail")
    wrong = CH1.replace("Ada Vale worked", "Ada Vail worked").replace("L02.", "L02, L04.").replace("none.", "one sentence.")
    fails = " ".join(levels(cd.check_chapter(1, wrong, ctx), "fail"))
    assert "Ada Vail" in fails and "L04 (Chapter 2)" in fails and 'must read "none"' in fails
    long = CH1.replace("What happened next?", "She did it again and again and again and again and again. What happened next?")
    assert any("Over budget" in d for d in levels(cd.check_chapter(1, long, ctx), "fail"))
    s = cd.set_status(cd.submit(s, "G6", CH1, chapter=1), "G6", "approved", 1)
    ch2 = "# Chapter 2\n\nThe trial began on March 1. He remembered long shifts and short holidays, and the court heard it.\n\n### Audit footer\n- **IDs used:** L04.\n- **Word count:** 19.\n- **Untraceable sentences:** none.\n"
    assert any("repeat an earlier chapter" in d for d in levels(cd.check_chapter(2, ch2, cd.context(s)), "warn"))


def test_lock_must_match_the_audited_script_word_for_word():
    s = state()
    script = "# Script v1.0 LOCKED\n\n## Hook\n\nAda Vale was 30.\n\n## Chapter 1\n\nShe worked as a nurse, her brother said. As of March 2, the trial continues.\n"
    s = cd.submit(s, "G7", script)
    assert any("word for word" in d for d in levels(cd.check_g8(script, cd.context(s)), "ok"))
    assert any("differs from the gate 7" in d for d in levels(cd.check_g8(script.replace("nurse", "doctor"), cd.context(s)), "fail"))
    assert cd.editor_script(script).startswith("## HOOK") and "## CHAPTER 1" in cd.editor_script(script)


def test_packets_are_filled_from_the_project():
    s = state()
    a = cd.packet(s, "G1", "start")
    assert "Case: Ada Vale, Springfield, 2026" in a and "[name / location / dates]" not in a and "FOOTAGE = YOUTUBE ONLY" in a
    b = cd.packet(s, "G6", "start", 2)
    assert "Write Chapter 2 only." in b and "L04" in b and "30 words" in b
    assert "Do not restate" not in cd.packet(s, "G6", "start", 1) and "from the hook" in cd.packet(s, "G6", "start", 1)
    bad = cd.submit(s, "G5", OUTLINE + "| Chapter 2 | L02 | 5 | again |\n")
    reply = cd.packet(bad, "G5", "reply")
    assert reply.startswith("Gate 5 (Outline): sent back") and "1. " in reply
    assert cd.packet(s, "G3", "reply").endswith("stop at its gate.")
    assert "already ran the mechanical checks" in cd.packet(s, "G2", "review") and "L04" in cd.packet(s, "G2", "review")


FAKE = textwrap.dedent("""\
    #!{python}
    import json, sys
    a = sys.argv[1:]
    if "--skip-download" in a:
        print(json.dumps({{"title": "Police briefing", "channel": "News 9", "upload_date": "20260105", "duration": 120, "view_count": 9, "description": "Briefing on the Ada Vale case."}}))
    else:
        q = a[-1]
        print(json.dumps({{"entries": [
            {{"id": "AAAAAAAAAAA", "title": "Ada Vale: police briefing", "channel": "News 9", "duration": 120, "view_count": 500}},
            {{"id": "BBBBBBBBBBB", "title": "Unrelated cooking video", "channel": "Food", "duration": 60, "view_count": 5}},
            {{"id": "bad", "title": "broken"}}]}}))
    """)


def test_search_candidates_approve_and_feed_the_script_chat(isolated, tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"
    exe.write_text(FAKE.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CASEFILE_YTDLP", str(exe))
    c, _ = isolated
    p = c.post("/api/projects", json={"title": "Desk QA", "mode": "narration"}).json()
    url = f"/api/projects/{p['id']}/casedesk"
    assert c.patch(url + "/case", json={"name": "Ada Vale, Springfield, 2026", "target_words": 72}).status_code == 200
    v = c.post(url + "/gate/G3", json={"text": REGISTER, "filename": "register.md"}).json()
    assert v["gates"][2]["verdict"] == "pass" and "Ada Vale police" in v["suggested_searches"]
    r = c.post(url + "/search", json={"queries": ["Ada Vale police", "Ada Vale court"]})
    assert r.status_code == 200, r.text
    end = time.time() + 30
    while server.JOBS[r.json()["job_id"]]["status"] in ("queued", "running") and time.time() < end:
        time.sleep(0.1)
    assert server.JOBS[r.json()["job_id"]]["result"]["added"] == 2
    v = c.get(url).json()
    assert [x["id"] for x in v["candidates"]] == ["AAAAAAAAAAA", "BBBBBBBBBBB"]
    assert v["candidates"][0]["score"] == 2 and v["candidates"][0]["status"] == "candidate"
    v = c.patch(url + "/candidate/AAAAAAAAAAA", json={"status": "approved", "kind": "press conference", "inspect": True}).json()
    assert v["candidates"][0]["source_id"] == "S01" and v["candidates"][0]["upload_date"] == "20260105"
    c.patch(url + "/candidate/BBBBBBBBBBB", json={"status": "rejected"})
    block = c.post(url + "/packet", json={"kind": "sources"}).json()["text"]
    assert "S01" in block and "2026-01-05" in block and "watch?v=AAAAAAAAAAA" in block and "BBBBBBBBBBB" not in block
    assert "approved for this case" in c.post(url + "/packet", json={"gate": "G2", "kind": "start"}).json()["text"]
    # Approving a gate needs its document; decisions survive a reload.
    assert c.post(url + "/gate/G2", json={"status": "approved"}).status_code == 422
    c.post(url + "/gate/G2", json={"text": LEDGER, "status": "approved"})
    assert c.get(url).json()["gates"][1]["status"] == "approved"
    assert "Ready. Which gate?" in c.post(url + "/packet", json={"kind": "reviewer_prompt"}).json()["text"]


def test_a_gate_is_not_approved_while_checks_or_the_reviewer_ask_for_corrections():
    s = state()
    # 1. Check failures block approval.
    bad = cd.submit(s, "G5", OUTLINE + "| Chapter 2 | L02 | 5 | again |\n")
    try:
        cd.set_status(bad, "G5", "approved")
        raise AssertionError("approved with open problems")
    except ValueError as e:
        assert "Not approved" in str(e) and "must be fixed" in str(e)
    assert cd.analyze(bad)["gates"][4]["blockers"]
    # 2. A clean document is approvable until the reviewer asks for changes.
    assert cd.analyze(s)["gates"][1]["blockers"] == []
    reviewed = cd.submit_review(s, "G2", "VERDICT: APPROVE WITH CHANGES\n\nPROBLEMS\n1. L02 needs a second outlet.\n\nYOUR CALL\nName the brother? I recommend no.\n\nPASTE-READY REPLY\nGate 2: approved with changes.\n1. Find a second outlet for L02.\n")
    g2 = cd.analyze(reviewed)["gates"][1]
    assert g2["review"]["verdict"] == "changes" and "Name the brother" in g2["review"]["your_call"] and g2["blockers"]
    try:
        cd.set_status(reviewed, "G2", "approved")
        raise AssertionError("approved against the reviewer")
    except ValueError as e:
        assert "APPROVE WITH CHANGES" in str(e)
    reply = cd.packet(reviewed, "G2", "reply")
    assert reply.startswith("Gate 2 (Fact Ledger): sent back") and "Find a second outlet for L02" in reply
    for words in ("VERDICT — SEND BACK\nPROBLEMS: many", "it looks fine to me"):
        assert cd.analyze(cd.submit_review(s, "G2", words))["gates"][1]["blockers"]
    # 3. The reviewer approves: now it can be approved, and the reply says continue.
    ok = cd.submit_review(s, "G2", "VERDICT: APPROVE\nWHAT I CHECKED: the verdict rows.\nPROBLEMS: none.")
    assert cd.set_status(ok, "G2", "approved")["gates"]["G2"]["status"] == "approved"
    assert "approved. Continue" in cd.packet(ok, "G2", "reply")
    # 4. A corrected version needs a fresh review; the old one does not carry over.
    again = cd.submit(reviewed, "G2", LEDGER)
    assert not cd.analyze(again)["gates"][1]["reviewed"]
    # 5. The producer can still overrule, on the record.
    over = cd.set_status(reviewed, "G2", "approved", override="I confirmed L02 with the family myself")
    assert over["gates"]["G2"]["status"] == "approved" and "family myself" in over["gates"]["G2"]["override"]["reason"]
