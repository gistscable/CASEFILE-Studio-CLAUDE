"""Case Desk (v0.4.20): the script workflow's gates, inside the app.

The producer's method (Script Workflow Prompts A/B/C + Gate Reviewer) stays
exactly as it is: an AI chat of the producer's choice does the research and
writing, and a second chat reviews. The Case Desk removes the manual carrying
and the format send-backs around that:

- it holds each gate's document (Source Pack, Fact Ledger, Name Register,
  Footage Map, Outline, Chapters, Audit, Lock);
- it runs every check that needs no judgement, in code (counts, formats,
  one-fact-one-chapter, word budgets, repetition, YouTube-only footage,
  Project setup format, unchanged-since-audit);
- it writes the paste-ready messages: the prompt to start a phase, the reply
  that sends a gate back with its numbered problems, and the packet for the
  reviewer chat.

It never decides anything that is the producer's call (naming, sensitivity,
conflicts, rights) and it uses no AI model and no paid service.

No web-framework imports here; app.py wires it to the API.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import basefill

PROMPTS = Path(__file__).parent / "prompts"
GATES = [
    ("G1", "Source Pack", "The source pack: official and primary sources first, then news, each dated."),
    ("G2", "Fact Ledger", "The ledger table: ID, claim, source URL, date, status, footage on YouTube, soundbite."),
    ("G3", "Name Register", "The name and entity register with its Project setup block."),
    ("G4", "Footage & Soundbite Map", "The beat table (green, yellow or red, a base bucket for every gap), the soundbite sheet and the Re-cut candidates."),
    ("G5", "Outline", "The outline with the information budget: every ledger ID in one chapter, with words."),
    ("G6", "Chapters", "One chapter at a time, each with its audit footer."),
    ("G7", "Full audit", "The assembled script after the final audit."),
    ("G8", "Lock", "The locked package: v1.1 (record this), v1.0, soundbite sheet, footage map, recut_plan.md, read-aloud sheet."),
]
GATE_IDS = [g[0] for g in GATES]
STATUSES = ("empty", "submitted", "approved", "sent_back")
ID_RE = r"(?<![A-Za-z0-9_=/-])[A-Z]{1,3}\d{1,3}[a-z]?(?![A-Za-z0-9_-])"
YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
OFFICIAL_HINT = re.compile(
    r"\.gov\b|police|nypd|sheriff|court|docket|state attorney|district attorney|prosecutor|"
    r"department of|ministry|official|press release|statement to",
    re.I,
)
GUILT_WORDS = re.compile(r"\b(killer|murderer|shooter|gunman|culprit|perpetrator)s?\b", re.I)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def blank():
    return {
        "case": {"name": "", "channel": "", "target_words": 2200, "wpm": 145},
        "gates": {g: {"text": "", "status": "empty", "updated": None, "filename": ""} for g in GATE_IDS if g != "G6"},
        "chapters": {},
        "candidates": [],
        "searches": [],
        "voice": {"base": "", "model": "omnivoice", "voice": "", "key": ""},
        "timing": {},
        "recuts": [],
        "recut_list": "",
        "fetch_ack": None,
        "colab": {"emotion": 0.5, "pace": 0.5, "seed": 7, "sample": "", "sample_seconds": 0, "pack": None},
    }


def normalise(state):
    base = blank()
    state = state or {}
    base["case"].update({k: v for k, v in (state.get("case") or {}).items() if k in base["case"]})
    for g, v in (state.get("gates") or {}).items():
        if g in base["gates"] and isinstance(v, dict):
            base["gates"][g].update(v)
    base["chapters"] = {str(k): v for k, v in (state.get("chapters") or {}).items()}
    base["candidates"] = list(state.get("candidates") or [])
    base["searches"] = list(state.get("searches") or [])[-40:]
    base["voice"].update({k: str(v)[:300] for k, v in (state.get("voice") or {}).items() if k in base["voice"]})
    base["timing"] = dict(state.get("timing") or {})
    base["recuts"] = list(state.get("recuts") or [])[:30]
    base["recut_list"] = str(state.get("recut_list") or "")[:100000]
    base["fetch_ack"] = state.get("fetch_ack") or None
    base["colab"].update({k: v for k, v in (state.get("colab") or {}).items() if k in base["colab"]})
    return base


# --------------------------------------------------------------------------
# Reading the documents
# --------------------------------------------------------------------------


def tables(text):
    """Every Markdown table as {"header": [...], "rows": [[...], ...]}."""
    out, cur = [], None
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cur is None:
                cur = {"header": cells, "rows": []}
            elif all(re.fullmatch(r":?-{2,}:?", c or "--") for c in cells):
                continue
            else:
                cur["rows"].append(cells)
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


def _col(header, *words):
    for i, h in enumerate(header):
        low = h.lower()
        if all(w in low for w in words):
            return i
    return None


def urls(text):
    return [u.rstrip(".,;)*") for u in re.findall(r"https?://[^\s|<>\]\"']+", text or "")]


def is_youtube(url):
    try:
        return urlparse(url).hostname in YT_HOSTS
    except ValueError:
        return False


def plain(cell):
    return re.sub(r"[*_`]", "", cell or "").strip()


def ledger(text):
    """Rows of the Fact Ledger: id, claim, urls, date, status, footage."""
    for t in tables(text):
        i_id, i_status = _col(t["header"], "id"), _col(t["header"], "status")
        if i_id is None or i_status is None:
            continue
        i_claim = _col(t["header"], "claim")
        i_url = _col(t["header"], "source")
        i_date = _col(t["header"], "date")
        i_foot = _col(t["header"], "footage")
        rows = []
        for r in t["rows"]:
            if len(r) <= max(i_id, i_status):
                continue
            get = lambda i: r[i] if i is not None and i < len(r) else ""
            status_cell = plain(get(i_status)).upper()
            status = next((s for s in ("VERIFIED", "ATTRIBUTED", "EXCLUDED") if status_cell.startswith(s)), "")
            rows.append({
                "id": plain(get(i_id)), "claim": plain(get(i_claim)), "urls": urls(get(i_url)),
                "source": get(i_url), "date": plain(get(i_date)), "status": status,
                "status_cell": plain(get(i_status)), "footage": get(i_foot),
            })
        if rows:
            # A note or blank line inside the ledger splits the Markdown table;
            # pick up every later row that starts with an ID and has the same shape.
            have = {r["id"] for r in rows}
            width = len(t["header"])
            for line in (text or "").splitlines():
                s = line.strip()
                if not s.startswith("|"):
                    continue
                r = [c.strip() for c in s.strip("|").split("|")]
                if len(r) == width and re.fullmatch(ID_RE, plain(r[i_id]) or "-") and plain(r[i_id]) not in have:
                    get = lambda i: r[i] if i is not None and i < len(r) else ""
                    status_cell = plain(get(i_status)).upper()
                    status = next((x for x in ("VERIFIED", "ATTRIBUTED", "EXCLUDED") if status_cell.startswith(x)), "")
                    rows.append({
                        "id": plain(get(i_id)), "claim": plain(get(i_claim)), "urls": urls(get(i_url)),
                        "source": get(i_url), "date": plain(get(i_date)), "status": status,
                        "status_cell": plain(get(i_status)), "footage": get(i_foot),
                    })
                    have.add(plain(r[i_id]))
            return rows
    return []


def narration(text):
    """The spoken words of a chapter or script file: no headings, tables,
    metadata lines or audit footer."""
    lines, keep = [], True
    for line in (text or "").splitlines():
        s = line.strip()
        if re.match(r"^#{1,6}\s*(audit footer|compilation totals|self-audit|audit)\b", s, re.I):
            keep = False
        elif s.startswith("#"):
            keep = not re.search(r"audit|totals|not narrated", s, re.I)
            continue
        if s == "---":
            continue
        if not keep or not s or s.startswith("|") or s.startswith(">"):
            continue
        if re.match(r"^[-*]\s", s) or re.match(r"^\*\*[^*]{1,60}:\*\*", s):
            continue
        lines.append(s)
    return "\n".join(lines)


def words(text):
    return [w for w in re.split(r"\s+", text or "") if re.search(r"[A-Za-z0-9]", w)]


def ngrams(text, n):
    toks = re.findall(r"[a-z0-9']+", (text or "").lower().replace("’", "'"))
    return {" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)}


def footer(text):
    """The audit footer of a chapter: ids used, stated word count, untraceable."""
    m = re.search(r"^#{1,6}\s*audit footer.*?$(.*)", text or "", re.I | re.M | re.S)
    body = m.group(1) if m else ""
    ids_line = re.search(r"IDs used[^:\n]*:\**\s*([^\n]+)", body, re.I)
    count = re.search(r"Word count[^:\n]*:\**\s*([\d,]+)", body, re.I)
    untrace = re.search(r"Untraceable sentences[^:\n]*:\**\s*([^\n]+)", body, re.I)
    return {
        "present": bool(m),
        "ids": re.findall(ID_RE, ids_line.group(1)) if ids_line else [],
        "words": int(count.group(1).replace(",", "")) if count else None,
        "untraceable": plain(untrace.group(1)).strip(". ").lower() if untrace else None,
    }


def allocation(text):
    """Outline: {ledger id: placement} and {placement: words} from the row-level
    budget table, plus stated section totals when the outline gives them."""
    alloc, by_place, dup, totals = {}, {}, [], {}
    for t in tables(text):
        i_place = _col(t["header"], "placement")
        if i_place is None:
            i_place = _col(t["header"], "chapter")
        i_id = _col(t["header"], "ledger")
        i_words = _col(t["header"], "words")
        if i_place is not None and i_id is not None and i_words is not None and not alloc:
            for r in t["rows"]:
                if len(r) <= max(i_place, i_id, i_words):
                    continue
                place = place_key(r[i_place])
                n = re.search(r"\d[\d,]*", plain(r[i_words]))
                for lid in re.findall(ID_RE, plain(r[i_id])):
                    if lid in alloc:
                        dup.append(lid)
                    alloc[lid] = place
                if place and n:
                    by_place[place] = by_place.get(place, 0) + int(n.group(0).replace(",", ""))
        i_sec, i_tot = _col(t["header"], "section"), _col(t["header"], "total words")
        if i_sec is not None and i_tot is not None and not totals:
            for r in t["rows"]:
                if len(r) > max(i_sec, i_tot):
                    n = re.search(r"\d[\d,]*", plain(r[i_tot]))
                    if n:
                        totals[place_key(r[i_sec])] = int(n.group(0).replace(",", ""))
    return {"ids": alloc, "words": by_place, "duplicates": sorted(set(dup)), "totals": totals}


def place_key(cell):
    s = plain(cell).lower()
    m = re.search(r"chapter\s*(\d+)|\bch\.?\s*(\d+)", s)
    if m:
        return "CHAPTER " + (m.group(1) or m.group(2))
    if "total" in s:
        return "TOTAL"
    for k in ("hook", "warning", "subscribe"):
        if k in s:
            return k.upper()
    return s.upper()[:40]


def register(text):
    """Canonical forms and alternate spellings from the Name Register."""
    canon, alts = [], []
    for t in tables(text):
        i_c = _col(t["header"], "canonical")
        if i_c is None:
            continue
        i_a = _col(t["header"], "alternate")
        for r in t["rows"]:
            if i_c < len(r):
                canon += [c.strip() for c in re.findall(r"\*\*([^*]+)\*\*", r[i_c])]
            if i_a is not None and i_a < len(r):
                alts += [c.strip() for c in re.findall(r"\*\*([^*]+)\*\*", r[i_a])]
    canon_low = {c.lower() for c in canon}
    alts = [a for a in dict.fromkeys(alts) if a.lower() not in canon_low and len(a) > 3]
    return {"canonical": list(dict.fromkeys(canon)), "alternates": alts}


def editor_script(text):
    """The locked script as the editor wants it: narration only, under
    ``## HOOK`` (hook, warning, subscribe line) and ``## CHAPTER n``."""
    out, section, started = [], None, False
    for line in (text or "").splitlines():
        s = line.strip()
        h = re.match(r"^#{1,6}\s*(.+)$", s)
        if h:
            title = h.group(1).lower()
            m = re.search(r"chapter\s*(\d+)", title)
            if m:
                section, started = "CHAPTER " + m.group(1), True
                out.append(f"\n## {section}\n")
            elif re.search(r"\bhook\b", title):
                section, started = "HOOK", True
                out.append("## HOOK\n")
            elif re.search(r"warning|subscribe", title) and started:
                section = "HOOK" if section == "HOOK" else section
            elif re.search(r"totals|audit|not narrated|notes", title):
                section = None
            continue
        if s == "---":
            section = None if section and section != "HOOK" and "CHAPTER" in section and False else section
            continue
        if section and s and not s.startswith("|") and not re.match(r"^\*\*[^*]{1,60}:\*\*", s):
            out.append(s + "\n")
    return "\n".join(out).strip() + "\n"


# --------------------------------------------------------------------------
# Checks. Each returns findings: {"level": fail|warn|info|ok, "detail": str}
# --------------------------------------------------------------------------


def F(level, detail):
    return {"level": level, "detail": detail}


def check_g1(text, ctx):
    out = []
    all_urls = urls(text)
    if not all_urls:
        return [F("fail", "No source links found. Paste the whole source pack.")]
    rows = [r for t in tables(text) for r in t["rows"]]
    src_rows = [r for r in rows if urls(" ".join(r))]
    out.append(F("ok", f"{len(src_rows)} sources with links in {len(tables(text))} tables; {len(set(all_urls))} different links."))
    if not re.search(r"official|primary", text, re.I):
        out.append(F("fail", "No official or primary section. Rule: official and primary sources come first."))
    date_re = re.compile(r"\b20\d\d-\d\d-\d\d\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", re.I)
    undated = []
    for t in tables(text):
        i_date = _col(t["header"], "date")
        for r in t["rows"]:
            if not urls(" ".join(r)):
                continue
            in_col = i_date is not None and i_date < len(r) and re.search(r"\d", r[i_date])
            if not in_col and not date_re.search(" ".join(r)):
                undated.append(plain(r[0])[:14])
    if undated:
        out.append(F("fail", f"{len(undated)} sources have no date: {', '.join(undated[:10])}."))
    noconf = [plain(r[0])[:12] for r in src_rows if not re.search(r"confidence", " ".join(r), re.I)]
    if noconf and len(noconf) < len(src_rows):
        out.append(F("warn", f"{len(noconf)} sources have no confidence note: {', '.join(noconf[:10])}."))
    elif noconf:
        out.append(F("warn", "Sources carry no confidence notes."))
    listing = [u for u in set(all_urls) if re.search(r"[?&]page=\d|/(category|tag|topics?|search|news)/?$", u) or urlparse(u).path in ("", "/")]
    if listing:
        out.append(F("warn", f"{len(listing)} links look like listing or home pages, not the article or release: {', '.join(sorted(listing)[:4])}."))
    if not re.search(r"transcript", text, re.I):
        out.append(F("warn", "The pack does not say how the reference transcript was treated (it must be a lead only)."))
    if not re.search(r"exclu", text, re.I):
        out.append(F("warn", "No exclusions listed. A pack normally says what was left out and why."))
    if not re.search(r"conflict|disagree|differ", text, re.I):
        out.append(F("info", "No conflicts between outlets are mentioned. Fine if there are none; ask if unsure."))
    return out


def check_g2(text, ctx):
    rows = ledger(text)
    if not rows:
        return [F("fail", "No ledger table found. It needs the columns ID, claim, source URL, date, status and footage.")]
    out = []
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("VERIFIED", "ATTRIBUTED", "EXCLUDED")}
    out.append(F("ok", f"{len(rows)} rows: {counts['VERIFIED']} verified, {counts['ATTRIBUTED']} attributed, {counts['EXCLUDED']} excluded."))
    ids = [r["id"] for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        out.append(F("fail", f"Duplicate IDs: {', '.join(dup)}."))
    bad_status = [r["id"] for r in rows if not r["status"]]
    if bad_status:
        out.append(F("fail", f"Status is not VERIFIED, ATTRIBUTED or EXCLUDED on: {', '.join(bad_status[:12])}."))
    no_url = [r["id"] for r in rows if not r["urls"] and r["status"] != "EXCLUDED"]
    if no_url:
        out.append(F("fail", f"No source link on: {', '.join(no_url[:12])}."))
    no_date = [r["id"] for r in rows if not re.search(r"\d{4}", r["date"]) and r["status"] != "EXCLUDED"]
    if no_date:
        out.append(F("fail", f"No source date on: {', '.join(no_date[:12])}."))
    foot_bad, foot_vague, with_footage = [], [], 0
    for r in rows:
        fu = urls(r["footage"])
        if any(not is_youtube(u) for u in fu):
            foot_bad.append(r["id"])
        elif fu:
            with_footage += 1
        elif not re.search(r"none|no footage|n/a|not found", r["footage"], re.I):
            foot_vague.append(r["id"])
    if foot_bad:
        out.append(F("fail", f"Footage column names a link that is not YouTube (rule 9): {', '.join(foot_bad[:12])}."))
    if foot_vague:
        out.append(F("fail", f"Footage column has neither a YouTube link nor \"none verified\": {', '.join(foot_vague[:12])}."))
    out.append(F("info", f"{with_footage} rows name a YouTube upload; {len(rows) - with_footage} have none."))
    single = []
    for r in rows:
        if r["status"] != "VERIFIED":
            continue
        hosts = {urlparse(u).hostname for u in r["urls"]}
        if len(hosts) < 2 and not OFFICIAL_HINT.search(r["source"] + " " + " ".join(r["urls"])):
            single.append(r["id"])
    if single:
        out.append(F("warn", f"VERIFIED on one outlet with no official source named (rule 10 says ATTRIBUTED): {', '.join(single[:12])}. Check each."))
    excl = [r["id"] for r in rows if r["status"] == "EXCLUDED"]
    if counts["ATTRIBUTED"] or excl:
        out.append(F("info", f"Yours to read: the {counts['ATTRIBUTED']} ATTRIBUTED and {len(excl)} EXCLUDED rows."))
    return out


def setup_findings(text):
    out = []
    setup = basefill.parse_setup(text or "", lambda s: s)
    if not setup["present"]:
        return [F("fail", "No \"## Project setup\" heading. The editor reads names only from that block.")], setup
    block = re.search(r"^##\s+Project setup[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S | re.I).group(1)
    if "```" in block:
        out.append(F("fail", "Project setup is inside a code block. It must be plain bullets: - Case:, - Victim:, - Suspect:, - Avoid tags:."))
    if not setup["case"]:
        out.append(F("fail", "Project setup has no \"- Case:\" line."))
    if not setup["victims"]:
        out.append(F("fail", "Project setup has no \"- Victim:\" name. The editor would protect nobody."))
    for label, names in (("Victim", setup["victims"]), ("Suspect", setup["suspects"])):
        for n in names:
            if re.search(r"[\d()\[\]]", n) or len(n.split()) > 5:
                out.append(F("fail", f"{label} name \"{n}\" has an age, brackets or a description in it. Plain names only."))
    if not setup["suspects"]:
        out.append(F("info", "Suspect is empty. Right when the accused is not named; the film then has no S pictures."))
    if not setup["avoid_tags"]:
        out.append(F("warn", "No \"- Avoid tags:\" line (for example residential, graphic)."))
    if not out or all(f["level"] == "info" for f in out):
        out.insert(0, F("ok", f"Project setup reads correctly: victim {', '.join(setup['victims']) or 'none'}; suspect {', '.join(setup['suspects']) or 'none'}; avoid {', '.join(setup['avoid_tags']) or 'none'}."))
    return out, setup


def check_g3(text, ctx):
    reg = register(text)
    out = []
    if not reg["canonical"]:
        out.append(F("fail", "No register table with a \"Canonical\" column found."))
    else:
        out.append(F("ok", f"{len(reg['canonical'])} canonical forms; {len(reg['alternates'])} alternate spellings will be flagged if they appear in a chapter."))
    found, _ = setup_findings(text)
    out += found
    if not re.search(r"minor|witness", text, re.I):
        out.append(F("warn", "The register does not mention minors or witnesses. Rule 12 needs them flagged."))
    return out


def check_g4(text, ctx):
    led = ctx["ledger"]
    out = []
    beat_tables = [t for t in tables(text) if _col(t["header"], "beat") is not None]
    if not beat_tables:
        return [F("fail", "No beat table found (a table with a \"Beat\" column).")]
    t = beat_tables[0]
    rows = [r for r in t["rows"] if not re.search(r"\btotal\b", plain(r[0]), re.I)]
    i_time, i_cover = _col(t["header"], "time"), _col(t["header"], "cover")
    i_colour = _col(t["header"], "colour") if _col(t["header"], "colour") is not None else _col(t["header"], "footage")
    total = cover = 0
    cover_by = {"V": 0, "S": 0, "C": 0}
    unmarked, nobucket, seen = [], [], []
    for r in rows:
        joined = " ".join(r)
        name = plain(r[0])[:40]
        seen += re.findall(ID_RE, plain(joined))
        if i_time is not None and i_time < len(r):
            m = re.search(r"(\d+)\s*sec", r[i_time])
            total += int(m.group(1)) if m else 0
        colour = plain(r[i_colour]) if i_colour is not None and i_colour < len(r) else joined
        mark = re.search(r"GREEN|YELLOW|RED|🟢|🟡|🔴", colour)
        if not mark:
            unmarked.append(name)
        cov = plain(r[i_cover]) if i_cover is not None and i_cover < len(r) else ""
        buckets = re.findall(r"\b([VSC])\b\s*[—–-]\s*(\d+)\s*sec", cov)
        for b, s in buckets:
            cover_by[b] += int(s)
            cover += int(s)
        needs = mark and mark.group(0) in ("RED", "YELLOW", "🔴", "🟡")
        if needs and not re.search(r"\b[VSC]\b", cov):
            nobucket.append(name)
    out.append(F("ok", f"{len(rows)} beats, {total} seconds planned ({total // 60}:{total % 60:02d})."))
    if unmarked:
        out.append(F("fail", f"No green, yellow or red mark on: {'; '.join(unmarked[:6])}."))
    if nobucket:
        out.append(F("fail", f"Yellow or red beat with no base bucket (V, S or C): {'; '.join(nobucket[:6])}."))
    bad = [u for u in urls(text) if not is_youtube(u)]
    if bad:
        out.append(F("fail", f"{len(bad)} links are not YouTube (rule 9), for example {bad[0]}."))
    if led:
        usable = [r["id"] for r in led if r["status"] != "EXCLUDED"]
        missing = [i for i in usable if i not in seen]
        twice = sorted({i for i in seen if seen.count(i) > 1 and i in usable})
        unknown = sorted({i for i in seen if i not in {r["id"] for r in led} and re.match(r"^L\d", i)})
        if missing:
            out.append(F("warn", f"{len(missing)} usable ledger IDs are in no beat: {', '.join(missing[:14])}."))
        if twice:
            out.append(F("fail", f"Ledger IDs in more than one beat: {', '.join(twice[:14])}."))
        if unknown:
            out.append(F("fail", f"IDs that are not in the ledger: {', '.join(unknown[:14])}."))
    else:
        out.append(F("info", "Paste the Fact Ledger at gate 2 and this gate will also check every ID is mapped once."))
    if cover:
        fills = math.ceil(cover / 6)
        need = {b: max(5, math.ceil(math.ceil(s / 6) / 4)) for b, s in cover_by.items() if s}
        out.append(F("info", f"{cover} seconds need base pictures (about {fills} shots). Smallest pool: " + ", ".join(f"{b} {n}" for b, n in need.items()) + "."))
        if cover_by["S"] and ctx["setup"]["present"] and not ctx["setup"]["suspects"]:
            out.append(F("fail", "The map uses the S bucket but Project setup names no suspect."))
    return out


def check_g5(text, ctx):
    led, case = ctx["ledger"], ctx["case"]
    a = allocation(text)
    out = []
    if not a["ids"]:
        return [F("fail", "No budget table found (columns: Placement, Ledger ID, Words).")]
    chapters = sorted(k for k in a["words"] if k.startswith("CHAPTER"))
    out.append(F("ok", f"{len(a['ids'])} ledger IDs allocated across {len(chapters)} chapters."))
    if a["duplicates"]:
        out.append(F("fail", f"IDs allocated more than once (rule 5): {', '.join(a['duplicates'])}."))
    if led:
        usable = [r["id"] for r in led if r["status"] != "EXCLUDED"]
        missing = [i for i in usable if i not in a["ids"]]
        excluded = [i for i in a["ids"] if i in {r["id"] for r in led if r["status"] == "EXCLUDED"}]
        unknown = [i for i in a["ids"] if i not in {r["id"] for r in led}]
        if missing:
            out.append(F("warn", f"{len(missing)} usable ledger IDs have no chapter: {', '.join(missing[:14])}. Fine only if dropped on purpose."))
        if excluded:
            out.append(F("fail", f"EXCLUDED rows are in the outline: {', '.join(excluded)}."))
        if unknown:
            out.append(F("fail", f"IDs that are not in the ledger: {', '.join(unknown[:14])}."))
    total = a["totals"].get("TOTAL") or sum(v for k, v in a["totals"].items() if k != "TOTAL") or sum(a["words"].values())
    target, wpm = int(case.get("target_words") or 0), int(case.get("wpm") or 145)
    secs = round(total / wpm * 60)
    out.append(F("info", f"Budget {total} words, about {secs // 60}:{secs % 60:02d} at {wpm} words a minute."))
    if target and abs(total - target) > target * 0.05:
        out.append(F("warn", f"Budget is {total} words against your target of {target}. Under target is right when the verified facts do not fill it; never pad."))
    for k in ("hook", "warning", "subscribe"):
        if not re.search(k, text, re.I):
            out.append(F("fail", f"The outline does not mention the {k}."))
    if secs > 240 and not re.search(r"re-?hook", text, re.I):
        out.append(F("warn", "No re-hooks planned. Rule: one every 3 to 4 minutes."))
    return out


def chapter_budget(a, n, with_opening=False):
    key = f"CHAPTER {n}"
    base = a["totals"].get(key) or a["words"].get(key)
    if base and with_opening:
        base += sum(a["totals"].get(k) or a["words"].get(k) or 0 for k in ("HOOK", "WARNING", "SUBSCRIBE"))
    return base


def check_chapter(n, text, ctx):
    out = []
    spoken = narration(text)
    count = len(words(spoken))
    if not count:
        return [F("fail", "No narration found in this chapter.")]
    ft = footer(text)
    a = ctx["allocation"]
    opening = int(n) == 1 and bool(re.search(r"^#{1,6}.*\b(hook|warning|subscribe)", text, re.I | re.M))
    budget = chapter_budget(a, n, opening) if a["ids"] else None
    out.append(F("ok", f"{count} spoken words" + (f" against a budget of {budget}" + (" (hook, warning and subscribe line included)." if opening else ".") if budget else ".")))
    if budget:
        if count > budget * 1.05:
            out.append(F("fail", f"Over budget by {count - budget} words (limit +5%)."))
        elif count < budget * 0.95:
            out.append(F("info", f"{budget - count} words under budget. Accept if the facts are all there; do not pad."))
    if not ft["present"]:
        out.append(F("fail", "No audit footer."))
    else:
        if ft["words"] is not None and abs(ft["words"] - count) > 3:
            out.append(F("warn", f"The footer says {ft['words']} words; the count here is {count}."))
        if ft["untraceable"] is None:
            out.append(F("fail", "The footer has no \"Untraceable sentences\" line."))
        elif not ft["untraceable"].startswith("none"):
            out.append(F("fail", f"Untraceable sentences must read \"none\". It reads: {ft['untraceable'][:80]}."))
        if not ft["ids"]:
            out.append(F("fail", "The footer lists no ledger IDs."))
        if a["ids"] and ft["ids"]:
            mine = {i for i, p in a["ids"].items() if p == f"CHAPTER {n}"}
            if int(n) == 1:
                mine |= {i for i, p in a["ids"].items() if p in ("HOOK", "WARNING", "SUBSCRIBE")}
            foreign = [i for i in ft["ids"] if i not in mine]
            unused = sorted(mine - set(ft["ids"]))
            if foreign:
                where = ", ".join(f"{i} ({a['ids'].get(i, 'not in the outline').title()})" for i in foreign[:10])
                out.append(F("fail", f"Uses IDs that belong elsewhere: {where}."))
            if unused:
                out.append(F("warn", f"Allocated here but not used: {', '.join(unused[:12])}."))
        led = {r["id"]: r for r in ctx["ledger"]}
        excl = [i for i in ft["ids"] if led.get(i, {}).get("status") == "EXCLUDED"]
        if excl:
            out.append(F("fail", f"Uses EXCLUDED ledger rows: {', '.join(excl)}."))
    alts = [x for x in ctx["register"]["alternates"] if re.search(r"(?<![A-Za-z])" + re.escape(x) + r"(?![A-Za-z])", spoken)]
    if alts:
        out.append(F("fail", f"Spellings the Name Register rules out: {', '.join(alts[:8])}."))
    guilt = sorted({m.group(0).lower() for m in GUILT_WORDS.finditer(spoken)})
    if guilt:
        out.append(F("warn", f"Check these words are attributed or inside a quote before conviction: {', '.join(guilt)}."))
    earlier = "\n".join(narration(c.get("text", "")) for k, c in ctx["chapters"].items() if k.isdigit() and int(k) < int(n))
    if earlier:
        shared = sorted(ngrams(spoken, 6) & ngrams(earlier, 6))
        if shared:
            out.append(F("warn", f"{len(shared)} six-word runs repeat an earlier chapter, for example \"{shared[0]}\". Callbacks may be one short clause."))
    if not spoken.rstrip().endswith("?") and not re.search(r"\?\s*$", spoken.strip().splitlines()[-1]):
        out.append(F("info", "The chapter does not end on a question. Fine for the last chapter; others should pull into the next."))
    return out


def script_hash(text):
    return hashlib.sha256(" ".join(words(narration(text))).encode()).hexdigest()[:16]


def check_g7(text, ctx):
    spoken = narration(text)
    count = len(words(spoken))
    if not count:
        return [F("fail", "No narration found.")]
    wpm = int(ctx["case"].get("wpm") or 145)
    secs = round(count / wpm * 60)
    out = [F("ok", f"{count} spoken words, about {secs // 60}:{secs % 60:02d} at {wpm} words a minute.")]
    stated = re.search(r"(?:final )?spoken word count[^:\n]*:\**\s*([\d,]+)", text, re.I)
    if stated and abs(int(stated.group(1).replace(",", "")) - count) > 5:
        out.append(F("warn", f"The file states {stated.group(1)} words; the count here is {count}."))
    flat = " ".join(words(spoken))
    changed, example = [], ""
    for k, c in sorted(ctx["chapters"].items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        if c.get("status") != "approved":
            continue
        sentences = [x.strip() for x in re.split(r"(?<=[.?!”\"])\s+", narration(c.get("text", ""))) if len(x.split()) > 3]
        gone = [x for x in sentences if " ".join(words(x)) not in flat]
        if gone:
            changed.append(f"{k} ({len(gone)} of {len(sentences)} sentences)")
            example = example or gone[0][:90]
    if changed:
        out.append(F("warn", f"Approved chapters whose wording differs in this script: {', '.join(changed)}. First one: \"{example}\". Every change after approval needs your yes."))
    alts = [x for x in ctx["register"]["alternates"] if re.search(r"(?<![A-Za-z])" + re.escape(x) + r"(?![A-Za-z])", spoken)]
    if alts:
        out.append(F("fail", f"Spellings the Name Register rules out: {', '.join(alts[:8])}."))
    toks = re.findall(r"[a-z0-9']+", spoken.lower().replace("’", "'"))
    seen, rep = {}, []
    for i in range(len(toks) - 7):
        g = " ".join(toks[i : i + 8])
        if g in seen and i - seen[g] > 8:
            rep.append(g)
        seen.setdefault(g, i)
    if rep:
        out.append(F("warn", f"{len(rep)} eight-word runs are said twice, for example \"{rep[0]}\"."))
    guilt = sorted({m.group(0).lower() for m in GUILT_WORDS.finditer(spoken)})
    if guilt:
        out.append(F("warn", f"Check attribution on: {', '.join(guilt)}."))
    aloud = sorted(set(re.findall(r"\b\d{1,2}:\d{2}\b|\bNo\. ?\d+|\$\d[\d,.]*|\d+%|\b[A-Z]{2,5}\b", spoken)))
    if aloud:
        out.append(F("info", f"Read-aloud check for the voice: {', '.join(aloud[:14])}."))
    if not re.search(r"as of [A-Z][a-z]+ \d{1,2}|as-of", text):
        out.append(F("warn", "No \"as of\" date found. Rule 7: case status is stated as of a date."))
    return out


def check_g8(text, ctx):
    out = check_g7(text, ctx)
    audited = ctx["gates"]["G7"]
    if not audited.get("text"):
        out.append(F("warn", "Gate 7 is empty here, so \"unchanged since the audit\" cannot be checked."))
    elif script_hash(audited["text"]) != script_hash(text):
        out.append(F("fail", "The narration differs from the gate 7 script. Nothing may change between the audit and the lock."))
    else:
        out.append(F("ok", "The narration is word for word the script audited at gate 7."))
    if not re.search(r"\bv\s?1\.0\b|locked", text, re.I):
        out.append(F("warn", "The file does not say v1.0 or LOCKED."))
    return out


CHECKS = {"G1": check_g1, "G2": check_g2, "G3": check_g3, "G4": check_g4, "G5": check_g5, "G7": check_g7, "G8": check_g8}


def context(state):
    g = state["gates"]
    _, setup = setup_findings(g["G3"]["text"]) if g["G3"]["text"] else ([], basefill.parse_setup("", lambda s: s))
    return {
        "case": state["case"], "gates": g, "chapters": state["chapters"],
        "ledger": ledger(g["G2"]["text"]), "register": register(g["G3"]["text"]),
        "setup": setup, "allocation": allocation(g["G5"]["text"]),
    }


def review(text):
    """What the reviewer chat decided, read from its reply (VERDICT · WHAT I
    CHECKED · PROBLEMS · YOUR CALL · PASTE-READY REPLY)."""
    text = text or ""
    if not text.strip():
        return {"has": False, "verdict": None, "your_call": "", "reply": "", "problems": ""}
    m = re.search(r"VERDICT\**\s*[:\-–—·]?\s*\**\s*(APPROVE WITH CHANGES|SEND BACK|APPROVED?)", text, re.I)
    word = m.group(1).upper() if m else ""
    verdict_ = "changes" if "WITH CHANGES" in word else "send_back" if "SEND" in word else "approve" if word else "unclear"

    def section(name, stops):
        mm = re.search(r"(?:^|\n)[#*\s]*" + name + r"\**\s*[:\-–—·]?\s*(.*?)(?=\n[#*\s]*(?:" + "|".join(stops) + r")\b|\Z)", text, re.I | re.S)
        return mm.group(1).strip() if mm else ""

    heads = ["VERDICT", "WHAT I CHECKED", "PROBLEMS", "YOUR CALL", "PASTE-READY REPLY"]
    reply = section("PASTE-READY REPLY", ["VERDICT"])
    reply = re.sub(r"^```\w*\n|\n```\s*$", "", reply.strip())
    call = section("YOUR CALL", heads)
    return {"has": True, "verdict": verdict_, "your_call": call[:4000], "reply": reply[:6000],
            "problems": section("PROBLEMS", heads)[:4000]}


def blockers(findings, rev):
    """Reasons this gate must not be approved yet."""
    out = []
    fails = sum(1 for f in findings if f["level"] == "fail")
    if fails:
        out.append(f"The checks found {fails} problem{'s' if fails != 1 else ''} that must be fixed.")
    if rev["has"] and rev["verdict"] == "send_back":
        out.append("Your reviewer said SEND BACK.")
    elif rev["has"] and rev["verdict"] == "changes":
        out.append("Your reviewer said APPROVE WITH CHANGES: the changes have to be made first.")
    elif rev["has"] and rev["verdict"] == "unclear":
        out.append("The reviewer's reply has no clear VERDICT line.")
    return out


def verdict(findings):
    levels = {f["level"] for f in findings}
    return "fail" if "fail" in levels else "warn" if "warn" in levels else "pass"


def analyze(state):
    state = normalise(state)
    ctx = context(state)
    gates = []
    for gid, name, what in GATES:
        if gid == "G6":
            chapters = []
            planned = sorted({int(k.split()[1]) for k in ctx["allocation"]["words"] if k.startswith("CHAPTER")} | {int(k) for k in state["chapters"] if k.isdigit()})
            for n in planned:
                c = state["chapters"].get(str(n), {"text": "", "status": "empty"})
                found = check_chapter(n, c["text"], ctx) if c.get("text") else []
                chapters.append({
                    "n": n, "status": c.get("status", "empty"), "updated": c.get("updated"),
                    "filename": c.get("filename", ""), "has_text": bool(c.get("text")),
                    "findings": found, "verdict": verdict(found) if found else None,
                    "review": review(c.get("review", "")), "blockers": blockers(found, review(c.get("review", ""))),
                    "reviewed": bool(c.get("review")), "override": c.get("override"),
                    "budget": chapter_budget(ctx["allocation"], n),
                    "ids": sorted(i for i, p in ctx["allocation"]["ids"].items() if p == f"CHAPTER {n}"),
                })
            done = [c for c in chapters if c["status"] == "approved"]
            status = "approved" if chapters and len(done) == len(chapters) else "submitted" if any(c["has_text"] for c in chapters) else "empty"
            gates.append({"id": gid, "name": name, "what": what, "status": status, "chapters": chapters, "findings": [], "verdict": None, "has_text": any(c["has_text"] for c in chapters)})
            continue
        g = state["gates"][gid]
        found = CHECKS[gid](g["text"], ctx) if g["text"] else []
        gates.append({
            "id": gid, "name": name, "what": what, "status": g["status"], "updated": g.get("updated"),
            "filename": g.get("filename", ""), "has_text": bool(g["text"]), "chars": len(g["text"]),
            "findings": found, "verdict": verdict(found) if found else None,
            "review": review(g.get("review", "")), "blockers": blockers(found, review(g.get("review", ""))),
            "reviewed": bool(g.get("review")), "override": g.get("override"),
        })
    order = [g for g in gates]
    current = next((g["id"] for g in order if g["status"] != "approved"), "G8")
    approved = [c for c in state["candidates"] if c.get("status") == "approved"]
    return {
        "case": state["case"], "gates": gates, "current": current,
        "setup": ctx["setup"], "ledger_rows": len(ctx["ledger"]),
        "candidates": state["candidates"], "searches": state["searches"],
        "approved_sources": len(approved),
        "locked": state["gates"]["G8"]["status"] == "approved",
    }


# --------------------------------------------------------------------------
# Paste-ready messages
# --------------------------------------------------------------------------


def prompt(name):
    return (PROMPTS / name).read_text(encoding="utf-8")


def _problems(findings):
    return [f["detail"] for f in findings if f["level"] in ("fail", "warn")]


def packet(state, gate, kind, chapter=None):
    """kind: start (prompt that opens the phase) | reply (answer to the working
    agent after the checks) | review (packet for the reviewer chat)."""
    state = normalise(state)
    ctx = context(state)
    case = state["case"]
    name = dict((g[0], g[1]) for g in GATES)[gate]
    if gate == "G6":
        n = int(chapter or 1)
        entry = state["chapters"].get(str(n), {"text": ""})
        text, findings = entry.get("text", ""), check_chapter(n, entry.get("text", ""), ctx) if entry.get("text") else []
        label = f"Chapter {n}"
    else:
        text = state["gates"][gate]["text"]
        findings = CHECKS[gate](text, ctx) if text else []
        label = f"Gate {gate[1:]} ({name})"
    if kind == "start":
        if gate == "G1":
            p = prompt("script_prompt_a.md")
            words_target = int(case.get("target_words") or 2200)
            mins = round(words_target / int(case.get("wpm") or 145))
            p = p.replace("[name / location / dates]", case.get("name") or "[name / location / dates]")
            if case.get("channel"):
                p = re.sub(r"\[(?:your channel name|The Last Timeline)\]", lambda m: case["channel"], p)
            p = re.sub(r"(- Target: )\[e\.g\. [^\]]*\]", lambda m: f"{m.group(1)}~{words_target:,} words of narration ≈ {mins} min at {case.get('wpm') or 145} wpm, plus any Re-cut clip time", p)
            return p
        if gate == "G6":
            n = int(chapter or 1)
            a = ctx["allocation"]
            ids = sorted((i for i, pl in a["ids"].items() if pl == f"CHAPTER {n}"), key=lambda s: (len(s), s))
            if n == 1:
                ids = sorted((i for i, pl in a["ids"].items() if pl in ("HOOK", "WARNING", "SUBSCRIBE")), key=lambda s: (len(s), s)) + ids
            budget = chapter_budget(a, n)
            p = prompt("script_prompt_b.md")
            p = p.replace("[N]", str(n)).replace("[list]", ", ".join(ids) or "[list]").replace("[X]", str(budget or "[X]"))
            if n == 1:
                p = p.replace("continues the open loop from the previous chapter", "continues the open loop from the hook")
                p = "\n".join(l for l in p.splitlines() if "Do not restate any fact" not in l)
                p = "Write the hook, the content warning, the subscribe line and Chapter 1.\n" + p.split("\n", 1)[1]
            else:
                p = p.replace("Chapters 1–[N-1]", "the earlier chapters").replace(f"Chapters 1–[{n}-1]", "the earlier chapters")
            return p
        if gate == "G7":
            return prompt("script_prompt_c.md")
        if gate == "G8":
            return ("The audit is approved. Run Phase 8: lock v1.0 and v1.1 without changing a word, and produce the package files exactly as "
                    "Prompt A lists them (script_v1_1.md, script_v1_1_narration.txt, script_v1_0.md, script_v1_0_narration.txt, soundbite_sheet.md, "
                    "footage_map.md, recut_plan.md in the exact table format, readaloud_and_setup.md). Print the word count of every file, with the "
                    "as-of date. After this any change needs my explicit approval.")
        nxt = {"G2": "Phase 2, the Fact Ledger", "G3": "Phase 3, the Name & Entity Register with the PROJECT SETUP block", "G4": "Phase 4, the Footage & Soundbite Map (footage map with safe windows, soundbite sheet, Re-cut candidates)", "G5": "Phase 5, the Outline with the Information Budget"}[gate]
        extra = ""
        if gate in ("G2", "G4"):
            approved = [c for c in state["candidates"] if c.get("status") == "approved"]
            if approved:
                extra = "\n\nYouTube uploads I have checked and approved for this case (use these for the footage column; anything else you find must also be a YouTube upload from its original uploader):\n" + sources_block(state)
        return f"Continue to {nxt}. Run the self-audit first and stop at the gate." + extra
    problems = _problems(findings)
    entry = state["chapters"].get(str(int(chapter or 1)), {}) if gate == "G6" else state["gates"][gate]
    rev = review(entry.get("review", ""))
    if kind == "reply":
        if not text:
            return f"Nothing is pasted for {label} yet."
        needs_changes = rev["has"] and rev["verdict"] in ("changes", "send_back", "unclear")
        fails = [f["detail"] for f in findings if f["level"] == "fail"]
        if not fails and not needs_changes:
            if problems:  # warnings only: pass them on without blocking
                lines = [f"{label}: approved. Before you continue, note these for the next phase:"]
                lines += [f"{i}. {p}" for i, p in enumerate(problems[:8], 1)]
                lines.append("Then continue to the next phase and stop at its gate.")
                return "\n".join(lines)
            return f"{label}: approved. Continue to the next phase and stop at its gate."
        lines = [f"{label}: sent back. Fix these, run the self-audit, and resubmit the whole file:"]
        lines += [f"{i}. {p}" for i, p in enumerate(problems[:12], 1)]
        if len(problems) > 12:
            lines.append(f"(and {len(problems) - 12} more of the same kinds)")
        if needs_changes and rev["reply"]:
            lines += ["", "From my reviewer:", rev["reply"]]
        elif needs_changes and rev["problems"]:
            lines += ["", "From my reviewer:", rev["problems"]]
        lines.append("Change nothing else. Stop at the gate.")
        return "\n".join(lines)
    if kind == "review":
        head = [f"GATE: {label}. Case: {case.get('name') or 'not set'}.",
                "Casefile Studio already ran the mechanical checks on this file. Results:"]
        head += [f"- {f['level'].upper()}: {f['detail']}" for f in findings] or ["- (nothing pasted yet)"]
        head += ["", "Do not repeat those. Review what code cannot: whether the claims hold against their sources (spot-check the five most load-bearing or weakest), attribution wording, sensitivity, and anything that is MY CALL. Reply in your usual shape.", "", "THE FILE:", "", text]
        return "\n".join(head)
    raise ValueError("Unknown packet kind.")


def sources_block(state):
    lines = []
    for c in normalise(state)["candidates"]:
        if c.get("status") != "approved":
            continue
        date = c.get("upload_date") or "date not read"
        if re.fullmatch(r"\d{8}", date):
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        kind = f" [{c['kind']}]" if c.get("kind") else ""
        note = f" Note: {c['note']}" if c.get("note") else ""
        lines.append(f"- {c.get('source_id', '')} “{c.get('title', '')}”, {c.get('channel') or 'channel not read'}, {date}, https://www.youtube.com/watch?v={c['id']}{kind}{note}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Storage (one small file per project, beside the project file)
# --------------------------------------------------------------------------


def path(data_dir, project_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
        raise ValueError("Bad project id.")
    folder = Path(data_dir) / "casedesk"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{project_id}.json"


def load(data_dir, project_id):
    p = path(data_dir, project_id)
    try:
        return normalise(json.loads(p.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        return blank()


def save(data_dir, project_id, state):
    p = path(data_dir, project_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(normalise(state), ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def submit(state, gate, text, filename="", chapter=None):
    state = normalise(state)
    text = (text or "")[:600000]
    entry = {"text": text, "status": "submitted" if text.strip() else "empty", "updated": now(), "filename": (filename or "")[:160]}
    if gate == "G6":
        n = str(int(chapter))
        state["chapters"][n] = entry
    elif gate in state["gates"]:
        state["gates"][gate] = entry
    else:
        raise ValueError("Unknown gate.")
    return state


def submit_review(state, gate, text, chapter=None):
    """Store the reviewer chat's reply for the document now at this gate."""
    state = normalise(state)
    entry = state["chapters"].get(str(int(chapter))) if gate == "G6" else state["gates"].get(gate)
    if not entry or not entry.get("text"):
        raise ValueError("Paste the document first, then the reviewer's reply to it.")
    entry["review"] = (text or "")[:60000]
    entry["reviewed_at"] = now()
    if entry.get("status") == "approved":  # a new review reopens the decision
        entry["status"] = "submitted"
    entry.pop("override", None)
    return state


def set_status(state, gate, status, chapter=None, override=""):
    if status not in ("approved", "sent_back", "submitted"):
        raise ValueError("Unknown status.")
    state = normalise(state)
    entry = state["chapters"].get(str(int(chapter))) if gate == "G6" else state["gates"].get(gate)
    if not entry or not entry.get("text"):
        raise ValueError("Paste the document before approving or sending it back.")
    if status == "approved":
        ctx = context(state)
        found = check_chapter(int(chapter), entry["text"], ctx) if gate == "G6" else CHECKS[gate](entry["text"], ctx)
        stops = blockers(found, review(entry.get("review", "")))
        if stops and not str(override or "").strip():
            raise ValueError("Not approved. " + " ".join(stops) + " Send it back, then paste the corrected version.")
        if stops:
            entry["override"] = {"reason": str(override).strip()[:300], "at": now(), "over": stops}
        else:
            entry.pop("override", None)
    entry["status"] = status
    entry["decided"] = now()
    return state
