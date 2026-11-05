# Trading Wiki — Schema & Workflow

This is the config for the trading knowledge base (the "CLAUDE.md" of the wiki). It
defines how pages are structured and how they are maintained. Based on Andrej Karpathy's
**LLM Wiki** pattern: instead of re-deriving knowledge from raw sources on every query,
the LLM compiles sources into an interlinked, compounding markdown wiki.

## Three layers
1. **Raw sources** (read-only): the holistic-analysis captures in `/tmp/holistic_<TICKER>/`
   (local facts, AI Mode, Finviz, QuiverQuant, EarningsHub, X). Immutable inputs.
2. **The wiki** (this repo, LLM-maintained): `tickers/<TICKER>.md` per-company pages +
   `entities/<name>.md` shared pages (sectors, themes, people), cross-linked with `[[name]]`.
3. **The schema** (this file): structure + the ingest/query/lint workflows.

## Who maintains what
- **Claude (me)** is the programmer of the wiki: I synthesize raw sources into the
  narrative sections, write cross-links, and resolve contradictions.
- **The user** edits freely via the dashboard Wiki tab (the Obsidian-style frontend).
  User edits are authoritative — never overwrite a section the user wrote without saying so.
- **`scripts/wiki.py`** does the deterministic bookkeeping only (snapshot facts, change
  log, index, lint). It never invents narrative.

## Per-ticker page structure (`tickers/<TICKER>.md`)
Sections, in order. The Snapshot block is machine-managed; everything else is synthesis.

- **Title + stance line** — `# TICKER — Company` and a one-line current stance + date.
- **Snapshot** — between `<!--SNAPSHOT-->`/`<!--/SNAPSHOT-->` markers. **Auto-written by
  `wiki.py ingest` from yfinance facts only.** Do not hand-edit; it gets overwritten.
- **Thesis** — Stance (Bull/Bear/Neutral) · Conviction (Low/Med/High); Bull case; Bear
  case. This is the compounding core — update it, don't replace its history wholesale.
- **Fundamentals & trend** — what the numbers say over time (revenue, margins, EPS, debt).
- **Catalysts & events** — dated, append-mostly: earnings, deals, filings, raises.
- **Flows & sentiment** — QuiverQuant (smart money / congress / insiders) + X (retail tone).
- **Cross-links** — `Peers: [[NVDA]] [[AMD]]`, `Sector/theme: [[semiconductors]]`. Every
  link should eventually have a page; orphans are flagged by lint.
- **Open questions** — unresolved unknowns to chase next time.
- **Change log** — append-only, dated. `wiki.py` appends a line per ingest; I append a
  line when I revise the thesis.

## Provenance & anti-hallucination rules
- Tag claims `[FACT src]` (yfinance/finviz/quiver/earningshub), `[EST]` (model/narrative
  opinion, e.g. AI Mode), `[USER]` (the user's own note). Never state a number that isn't
  in a captured source or a prior `[FACT]` entry.
- The AI Mode report is `[EST]` and can be stale/inconsistent — cross-check its hard
  numbers against the Snapshot before importing them. Note disagreements, don't paper over.
- When a new ingest contradicts an existing claim, don't silently overwrite: update the
  claim AND leave a Change-log line noting what changed and why.

## Operations
- `wiki.py new TICKER` — create the page from template (no-op if it exists), refresh index.
- `wiki.py ingest TICKER` — refresh the Snapshot block + append a change-log line from the
  latest `/tmp/holistic_<TICKER>/local.txt`; then I synthesize the narrative sections from
  the other captures.
- `wiki.py query TICKER` — print the page (load into context before answering about it).
- `wiki.py list` — pages + last-updated + staleness.
- `wiki.py lint` — health check: stale pages (>30d), orphan `[[links]]`, missing sections,
  `TODO`/`CONFLICT` markers.

## Staleness
A page older than **30 days** is stale — re-run a holistic gather + ingest before trusting it.
