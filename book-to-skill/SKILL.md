---
name: book-to-skill
description: Use when the user wants to turn a book, PDF, or document (or a folder of them) into a reusable Claude Code skill — a compact, on-demand knowledge reference. Extracts + chapters the source deterministically, then you synthesize SKILL.md + per-chapter files + glossary/patterns/cheatsheet. Density over completeness, never raw text. Triggers: "make a skill from this book/pdf", "turn this doc into a skill", "book-to-skill <path>".
---

# book-to-skill

Turn a technical book/document into a structured, token-efficient skill: a small always-loaded core
plus per-chapter references loaded ON DEMAND, so studying or citing the book never dumps the whole
thing into context. Our own build (self-hosted, stdlib + `pdftotext`, no external service). Same
"synthesize into structured markdown" philosophy as the trading-wiki skill.

## Golden rules (do not violate)
- **Never raw text.** Every file you write is SYNTHESIS — frameworks, mental models, decision rules —
  not copied passages. A 1,000-token summary beats a 10,000-token excerpt.
- **Density over completeness.** Capture the load-bearing ideas; drop filler, anecdotes, repetition.
- **Read one chapter at a time.** Use the per-chapter raw files the extractor produced; do NOT read
  `full_text.txt` into context wholesale.
- **Attribute honestly.** If the book is thin or a chapter is fluff, say so — don't invent structure.

## Workflow

1. **Extract.** Run the deterministic extractor (writes raw text + per-chapter files, prints a JSON manifest):
   ```
   python3 ~/.claude/skills/book-to-skill/scripts/extract.py "<PATH>"
   ```
   (Run `... extract.py --check` first if a format might be unsupported.) Note the `out_dir`, chapter
   list, and est_tokens from the manifest. Multiple files: run per file and merge under one slug.

2. **Pick a slug.** `<slug>` = short kebab-case name (or the one the user gave). Target dir:
   `~/.claude/skills/<slug>/`. If it already exists, you are UPDATING — fold new material in, don't clobber.

3. **Synthesize per chapter.** For each chapter in the manifest, read ONLY its `out_dir/chapters/chNN.txt`,
   then write `~/.claude/skills/<slug>/chapters/chNN-<short-title>.md` (~800–1200 tokens each):
   - 3–8 bullet mental models / key claims from the chapter
   - the techniques/algorithms/rules it introduces (actionable form)
   - when-to-use / when-not conditions
   - any terms worth a glossary entry (collect these)

4. **Compile the core `~/.claude/skills/<slug>/SKILL.md`** (~4k tokens max) with frontmatter
   `name`/`description` (description = trigger phrases so it auto-loads) and:
   - one-paragraph "what this book gives you"
   - the top mental models across the whole book (the through-line)
   - a **chapter index**: `chNN — title — one-line what's inside` (so the reader loads only what they need)
   - a "load a chapter with: read chapters/chNN-*.md" note

5. **Write the reference files:**
   - `glossary.md` — alphabetical key terms → one-line definition + chapter ref
   - `patterns.md` — the reusable techniques/algorithms/design patterns, each: name · when · how · caveat
   - `cheatsheet.md` — decision tables / quick rules (the "if X then Y" distilled)

6. **Verify + report.** Confirm every chapter has a file, the SKILL.md index matches, and token budgets
   hold. Tell the user the slug, file count, and how to use it (`/<slug> <topic>` or "read chapters/chNN").
   Then clean up the temp `out_dir`.

## Output layout
```
~/.claude/skills/<slug>/
  SKILL.md            core mental models + chapter index (~4k tok, always loaded)
  chapters/chNN-*.md  per-chapter synthesis (~1k tok each, on-demand)
  glossary.md  patterns.md  cheatsheet.md
```

## Notes
- Supported: pdf (pdftotext), txt/md/rst, html, epub, docx (all stdlib). mobi/azw need calibre — tell the user.
- For our trading work, this is ideal for turning TA / market-structure / quant / risk books into
  references the analysis flows and models can consult. Keep synthesis in plain language ([[plain_language_default]]).
