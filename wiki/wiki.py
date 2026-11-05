#!/usr/bin/env python3
"""Trading-wiki engine — deterministic bookkeeping for the LLM Wiki.

Does ONLY the mechanical parts (snapshot facts, change log, index, lint). It never
writes narrative — that's Claude's job per WIKI_SCHEMA.md. Pure stdlib.

Ops: new | ingest | query | list | lint | index | consolidate
"""

import os as _export_os
import pathlib as _export_pathlib
import argparse
import datetime
import glob
import os
import re
import sys

ROOT = os.environ.get("R2D2_WIKI_ROOT", os.path.dirname(os.path.abspath(__file__)))
TICKERS = os.path.join(ROOT, "tickers")
ENTITIES = os.path.join(ROOT, "entities")
INDEX = os.path.join(ROOT, "WIKI.md")
HOLISTIC = "/tmp/holistic_{t}"
STALE_DAYS = 30

SNAP_START, SNAP_END = "<!--SNAPSHOT-->", "<!--/SNAPSHOT-->"
SECTIONS = ["Snapshot", "Thesis", "Fundamentals & trend", "Catalysts & events",
            "Flows & sentiment", "Cross-links", "Open questions", "Change log"]


def today() -> str:
    return datetime.date.today().isoformat()


def page_path(ticker: str) -> str:
    return os.path.join(TICKERS, f"{ticker.upper()}.md")


# ---------- fact extraction from the holistic local capture ----------
def extract_facts(ticker: str) -> dict:
    """Pull hard facts from /tmp/holistic_<T>/local.txt (yfinance). All best-effort."""
    path = os.path.join(HOLISTIC.format(t=ticker.upper()), "local.txt")
    if not os.path.exists(path):
        return {}
    txt = open(path).read()
    def grab(pat):
        m = re.search(pat, txt)
        return m.group(1).strip() if m else None
    facts = {
        "company": grab(rf"===\s*{re.escape(ticker.upper())}\s*[—-]\s*(.+?)\s*==="),
        "price": grab(r"Price:\s*(\$[\d.,]+\s*\([^)]*\))"),
        "market_cap": grab(r"Market Cap:\s*(\$[\d.,A-Za-z]+)"),
        "pe": grab(r"P/E \(trail/fwd\):\s*(.+)"),
        "ps": grab(r"P/S \(TTM\):\s*(.+)"),
        "eps": grab(r"EPS \(trail/fwd\):\s*(.+)"),
        "rev_growth": grab(r"Revenue growth YoY:\s*(.+)"),
        "gross_margin": grab(r"Gross margin:\s*(.+)"),
        "op_margin": grab(r"Operating margin:\s*(.+)"),
        "short_float": grab(r"Short % float:\s*(.+)"),
        "beta": grab(r"Beta:\s*(.+)"),
    }
    return {k: v for k, v in facts.items() if v}


def _snapshot_rows(facts: dict) -> list:
    return [
        ("Price", facts.get("price")),
        ("Market cap", facts.get("market_cap")),
        ("P/E (t/f)", facts.get("pe")),
        ("P/S (TTM)", facts.get("ps")),
        ("EPS (t/f)", facts.get("eps")),
        ("Rev growth YoY", facts.get("rev_growth")),
        ("Gross margin", facts.get("gross_margin")),
        ("Op margin", facts.get("op_margin")),
        ("Short % float", facts.get("short_float")),
        ("Beta", facts.get("beta")),
    ]


def snapshot_block(ticker: str, facts: dict) -> str:
    rows = _snapshot_rows(facts)
    body = "\n".join(f"| {k} | {v} |" for k, v in rows if v)
    sources = ", ".join(sorted(
        os.path.splitext(f)[0] for f in os.listdir(HOLISTIC.format(t=ticker.upper()))
        if f.endswith(".txt"))) if os.path.isdir(HOLISTIC.format(t=ticker.upper())) else "—"
    return (f"{SNAP_START}\n"
            f"_Auto-updated {today()} — yfinance facts only. Captures on disk: {sources}._\n\n"
            f"| Field | Value |\n|---|---|\n{body}\n"
            f"{SNAP_END}")


# ---------- page template ----------
def template(ticker: str, facts: dict) -> str:
    company = facts.get("company", "")
    title = f"{ticker.upper()} — {company}".rstrip(" —")
    return f"""# {title}

> _Stance: TBD. No synthesis yet — run a holistic gather + ingest. ({today()})_

## Snapshot
{snapshot_block(ticker, facts)}

## Thesis
**Stance:** TBD · **Conviction:** TBD
- **Bull:** TODO
- **Bear:** TODO

## Fundamentals & trend
TODO

## Catalysts & events
- {today()} — page created.

## Flows & sentiment
TODO

## Cross-links
- Peers:
- Sector/theme:

## Open questions
- TODO

## Change log
- {today()} — page created from template.
"""


# ---------- ops ----------
def op_new(ticker: str, quiet=False) -> str:
    os.makedirs(TICKERS, exist_ok=True)
    p = page_path(ticker)
    if os.path.exists(p):
        if not quiet:
            print(f"exists: {p}")
        return p
    facts = extract_facts(ticker)
    open(p, "w").write(template(ticker, facts))
    rebuild_index()
    if not quiet:
        print(f"created: {p}")
    return p


# ---------- contradiction detection (snapshot vs prior snapshot) ----------
def _parse_snapshot_table(txt: str) -> dict:
    """Pull the {label: value} rows out of the current snapshot block. {} if none."""
    m = re.search(re.escape(SNAP_START) + r"(.*?)" + re.escape(SNAP_END), txt, re.S)
    if not m:
        return {}
    out = {}
    for row in re.finditer(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", m.group(1), re.M):
        label, val = row.group(1).strip(), row.group(2).strip()
        if label in ("Field", "---") or set(label) <= {"-"}:
            continue
        out[label] = val
    return out


def _first_num(s):
    """First signed number in a string (handles %, $, commas, 't/f' pairs → trailing).
    None if no number."""
    if not s:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", s.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


# fields where a sign flip is a real thesis event (growth turning negative, a swing to a loss)
_SIGN_FIELDS = {"Rev growth YoY", "Gross margin", "Op margin", "EPS (t/f)"}


def _detect_contradictions(old_rows: dict, new_facts: dict) -> list:
    """Compare the prior snapshot table to fresh facts; return change-log lines for
    material moves. Sign flips on growth/margins/EPS → CONTRADICT; big price move → ⚠️."""
    if not old_rows:
        return []
    new_rows = dict((k, v) for k, v in _snapshot_rows(new_facts) if v)
    lines = []
    for label, new_val in new_rows.items():
        old_val = old_rows.get(label)
        if not old_val or old_val == new_val:
            continue
        o, n = _first_num(old_val), _first_num(new_val)
        if o is None or n is None:
            continue
        if label in _SIGN_FIELDS and (o > 0) != (n > 0) and abs(o - n) > 0.05:
            lines.append(f"- {today()} — ⚠️ CONTRADICT: {label} flipped {old_val} → "
                         f"{new_val} vs prior snapshot. Revisit thesis.")
        elif label == "Price" and o > 0:
            pct = (n - o) / abs(o) * 100
            if abs(pct) >= 15:
                lines.append(f"- {today()} — ⚠️ Price moved {pct:+.0f}% since last snapshot "
                             f"({old_val} → {new_val}). Check what changed.")
    return lines


def op_ingest(ticker: str):
    p = page_path(ticker)
    facts = extract_facts(ticker)
    if not facts:
        # No fresh facts — do NOT clobber an existing snapshot with an empty one.
        print(f"[warn] no facts in /tmp/holistic_{ticker.upper()}/local.txt — snapshot "
              f"left untouched. Run the holistic gather first:\n  cd <workspace>/telegram-bots"
              f" && venv/bin/python <workspace>/.claude/skills/holistic-stock-analysis/"
              f"scripts/gather.py {ticker.upper()}")
        if not os.path.exists(p):
            op_new(ticker, quiet=True)  # at least create the shell page
        return
    if not os.path.exists(p):
        op_new(ticker, quiet=True)
    txt = open(p).read()
    old_rows = _parse_snapshot_table(txt)  # capture BEFORE we overwrite the block
    contradictions = _detect_contradictions(old_rows, facts)
    new_snap = snapshot_block(ticker, facts)
    if SNAP_START in txt and SNAP_END in txt:
        txt = re.sub(re.escape(SNAP_START) + r".*?" + re.escape(SNAP_END),
                     lambda _m: new_snap, txt, count=1, flags=re.S)
    elif "## Snapshot\n" in txt:  # section exists but no markers yet — insert under it
        txt = txt.replace("## Snapshot\n", f"## Snapshot\n{new_snap}\n", 1)
    else:  # no Snapshot section at all (user reshaped the page) — prepend one
        txt = txt.rstrip() + f"\n\n## Snapshot\n{new_snap}\n"
    # append change-log line
    delta = ", ".join(x for x in [facts.get("price"), facts.get("market_cap") and
                                  f"mcap {facts['market_cap']}", facts.get("ps") and
                                  f"P/S {facts['ps']}"] if x)
    logline = f"- {today()} — snapshot refreshed: {delta or 'facts updated'}.\n"
    if "## Change log" in txt:
        txt = txt.rstrip() + "\n" + logline
        for c in contradictions:  # material moves get their own flagged lines
            txt = txt.rstrip() + "\n" + c + "\n"
    open(p, "w").write(txt)
    rebuild_index()
    caps = sorted(glob.glob(os.path.join(HOLISTIC.format(t=ticker.upper()), "*.txt")))
    print(f"ingested facts into {p}")
    if contradictions:
        print(f"\n⚠️  {len(contradictions)} material change(s) flagged in the change log:")
        for c in contradictions:
            print("  ", c.strip())
    print("raw captures to synthesize from:")
    for c in caps:
        print("  ", c)
    print("\nNext (Claude): read the captures above and update Thesis / Fundamentals / "
          "Catalysts / Flows / Cross-links / Open questions per WIKI_SCHEMA.md "
          "(tag FACT/EST/USER), then add a Change-log line for any thesis change.")


def op_consolidate(ticker: str, keep: int = 3):
    """Collapse routine 'snapshot refreshed' noise in the change log (keep the most
    recent `keep` verbatim, roll the rest into one line) while preserving every
    non-routine entry (thesis changes, ⚠️/CONTRADICT flags, catalysts). Then print a
    Claude prompt for narrative consolidation. Mechanical only — never edits prose."""
    p = page_path(ticker)
    if not os.path.exists(p):
        print(f"[no page for {ticker.upper()}]")
        return
    txt = open(p).read()
    m = re.search(r"(## Change log\n)(.*)\Z", txt, re.S)
    if not m:
        print(f"[no change log in {p}]")
        return
    head, body = m.group(1), m.group(2)
    entries = [ln for ln in body.splitlines() if ln.strip().startswith("- ")]
    routine_idx = [i for i, ln in enumerate(entries) if "snapshot refreshed" in ln]
    drop = set(routine_idx[:-keep]) if len(routine_idx) > keep else set()
    if not drop:
        print(f"change log already tidy ({len(routine_idx)} routine line(s) ≤ keep={keep}); "
              f"nothing to collapse.")
    else:
        def _date(ln):
            d = re.search(r"(\d{4}-\d{2}-\d{2})", ln)
            return d.group(1) if d else "?"
        dropped = [entries[i] for i in sorted(drop)]
        span = f"{_date(dropped[0])}…{_date(dropped[-1])}"
        rollup = (f"- {span} — snapshot refreshed ×{len(dropped)} "
                  f"(routine auto-updates collapsed).")
        new_entries, inserted = [], False
        for i, ln in enumerate(entries):
            if i in drop:
                if not inserted:
                    new_entries.append(rollup)
                    inserted = True
                continue
            new_entries.append(ln)
        txt = txt[:m.start()] + head + "\n".join(new_entries) + "\n"
        open(p, "w").write(txt)
        print(f"consolidated {p}: collapsed {len(dropped)} routine lines into 1 "
              f"(kept {len(new_entries)} change-log entries).")
    # narrative-consolidation prompt for Claude (this engine never writes prose)
    print("\nNext (Claude) — narrative consolidation pass per WIKI_SCHEMA.md:")
    print(f"  read {p} and: (1) fold any resolved Open questions into Thesis/Fundamentals; "
          "(2) merge duplicate or stale points; (3) if a ⚠️/CONTRADICT line is unaddressed, "
          "update the thesis to reconcile it and note the resolution; (4) keep tags "
          "FACT/EST/USER. Do not touch the auto Snapshot block or the Change log dates.")


def op_query(ticker: str):
    p = page_path(ticker)
    if not os.path.exists(p):
        print(f"[no page for {ticker.upper()}] — create with: wiki.py new {ticker.upper()}")
        return
    sys.stdout.write(open(p).read())


def _pages():
    return sorted(glob.glob(os.path.join(TICKERS, "*.md")))


def op_list():
    rows = []
    for p in _pages():
        t = os.path.splitext(os.path.basename(p))[0]
        age = (datetime.date.today() - datetime.date.fromtimestamp(os.path.getmtime(p))).days
        stale = " STALE" if age > STALE_DAYS else ""
        rows.append(f"  {t:8} updated {age}d ago{stale}")
    print(f"{len(rows)} ticker page(s):")
    print("\n".join(rows) if rows else "  (none)")


def op_lint():
    issues = []
    known = {os.path.splitext(os.path.basename(p))[0].upper() for p in _pages()}
    known |= {os.path.splitext(os.path.basename(p))[0].lower()
              for p in glob.glob(os.path.join(ENTITIES, "*.md"))}
    for p in _pages():
        t = os.path.basename(p)
        txt = open(p).read()
        age = (datetime.date.today() - datetime.date.fromtimestamp(os.path.getmtime(p))).days
        if age > STALE_DAYS:
            issues.append(f"[stale] {t}: {age}d old")
        for sec in SECTIONS:
            if f"## {sec}" not in txt and sec != "Snapshot":
                issues.append(f"[missing-section] {t}: '{sec}'")
        for marker in ("TODO", "CONFLICT", "CONTRADICT"):
            n = txt.count(marker)
            if n:
                issues.append(f"[{marker.lower()}] {t}: {n} marker(s)")
        for link in set(re.findall(r"\[\[([^\]]+)\]\]", txt)):
            if link.upper() not in known and link.lower() not in known:
                issues.append(f"[orphan-link] {t}: [[{link}]] has no page")
    print(f"lint: {len(issues)} issue(s)")
    for i in issues:
        print("  ", i)


def rebuild_index():
    os.makedirs(ROOT, exist_ok=True)
    lines = ["# Trading Wiki — Index", "",
             "Per-ticker knowledge pages, LLM-maintained, compounding. See "
             "[WIKI_SCHEMA.md](WIKI_SCHEMA.md) for structure & workflow.", "",
             "## Tickers"]
    for p in _pages():
        t = os.path.splitext(os.path.basename(p))[0]
        first = ""
        for line in open(p):
            if line.startswith(">"):
                first = line.lstrip("> ").strip()
                break
        age = (datetime.date.today() - datetime.date.fromtimestamp(os.path.getmtime(p))).days
        lines.append(f"- [{t}](tickers/{t}.md) — {first} _(updated {age}d ago)_")
    ents = sorted(glob.glob(os.path.join(ENTITIES, "*.md")))
    if ents:
        lines += ["", "## Entities / themes"]
        for p in ents:
            n = os.path.splitext(os.path.basename(p))[0]
            lines.append(f"- [{n}](entities/{n}.md)")
    open(INDEX, "w").write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("op", choices=["new", "ingest", "query", "list", "lint", "index",
                                   "consolidate"])
    ap.add_argument("ticker", nargs="?")
    a = ap.parse_args()
    if a.op in ("new", "ingest", "query", "consolidate") and not a.ticker:
        ap.error(f"{a.op} needs a TICKER")
    {"new": lambda: op_new(a.ticker), "ingest": lambda: op_ingest(a.ticker),
     "query": lambda: op_query(a.ticker), "list": op_list, "lint": op_lint,
     "index": rebuild_index, "consolidate": lambda: op_consolidate(a.ticker)}[a.op]()


if __name__ == "__main__":
    main()
