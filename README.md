# R2D2 Knowledge Tools

Deterministic utilities for turning documents into manageable input, keeping a structured Markdown wiki and mapping Python source. The common idea is to do mechanical bookkeeping in code, then retrieve only the material needed for the next task.

These tools can run without a model provider, trading service or vector database. They do not automatically write an authoritative interpretation of a document.

## Three tools

### Document-to-skill preparation

`book-to-skill/scripts/extract.py` supports text/Markdown, HTML, EPUB and DOCX through the Python standard library, plus PDF through `pdftotext`. It extracts text, detects chapter-like boundaries or falls back to chunks, writes chapter files and reports a manifest with estimated token sizes.

This is the preparation step. The accompanying skill describes how an assistant can synthesize concise references from those chapters. Extraction itself does not make an LLM call or establish the source's accuracy.

```bash
python3 book-to-skill/scripts/extract.py --check
python3 book-to-skill/scripts/extract.py document.txt --out /tmp/document-extract
```

### Markdown wiki bookkeeping

`wiki/wiki.py` manages page creation, deterministic fact ingestion, querying, indexing, change logs and linting. It was designed around ticker/entity notes, but the storage is ordinary Markdown. Narrative research remains a separate human/assistant task.

```bash
R2D2_WIKI_ROOT=/tmp/example-wiki python3 wiki/wiki.py new EXAMPLE
R2D2_WIKI_ROOT=/tmp/example-wiki python3 wiki/wiki.py list
```

`wiki/WIKI_SCHEMA.md` describes the page structure. No private ticker notes or investment history are distributed.

### Python code graph

`codegraph/codegraph.py` uses Python's AST to record modules, definitions, imports and possible calls. It can build a local graph and answer symbol/caller/callee/path queries. Extracted relationships and inferred name matches are distinct; inferred edges are navigation leads rather than proof of runtime behavior.

```bash
python3 codegraph/codegraph.py --help
```

Read its module docstring for the subcommands and current root/store defaults before pointing it at another tree.

## Requirements and verification

Python 3.11 or newer is recommended. PDF support additionally needs Poppler's `pdftotext`; the other documented extraction formats use standard-library parsers. Run `python3 check.py` for source checks. Extraction and wiki creation have also been exercised with temporary local fixtures.

The repository contains code, schemas and recipes, not a library of books, extracted private documents or user notes. Respect source rights when building a knowledge collection. Extraction quality depends on the input, and scanned PDFs may require a separate OCR step. This tool does not silently call an OCR or cloud service.

## Privacy, provenance and updates

This repository is a sanitized source export. No provider credentials, personal contact information, configured IP addresses, private conversations or runtime databases are included. Example hostnames and local environment variables are intentional. Keep newly generated account data and captures outside version control.

A source manifest records exported files. Local adaptations and third-party material retain their own provenance/notices; public visibility does not apply a new blanket license to every file. Related repositories and the manual update process are listed in the [workspace catalogue](https://github.com/r2d2broooo/r2d2-workspace-catalog).

Updates are made only on explicit request. Cloning does not enable an automatic sync, scheduled publication or Git push.
