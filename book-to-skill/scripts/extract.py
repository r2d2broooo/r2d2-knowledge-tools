#!/usr/bin/env python3
"""book-to-skill extractor — turn a book/doc into clean text + per-chapter raw files + a manifest.

Deterministic and dependency-light: `pdftotext` (poppler) for PDF; Python stdlib for txt/md/rst/html/
epub/docx (epub & docx are just zips of markup). The AGENT running the /book-to-skill skill does the
SYNTHESIS — this only prepares the raw material and splits it by chapter so the agent reads one chapter
at a time instead of dumping the whole book into context.

Usage:
  extract.py --check              # report available extractors + install hints (JSON)
  extract.py PATH [--out DIR]     # extract → writes full_text.txt + chapters/chNN.txt, prints manifest JSON
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

SUPPORTED = (".pdf", ".txt", ".md", ".markdown", ".rst", ".text", ".html", ".htm", ".epub", ".docx")


def _strip_tags(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)</(p|div|h[1-6]|li|br)\s*>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", html.unescape(s))


def _from_pdf(path: str) -> str:
    r = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"pdftotext failed: {r.stderr.strip()}")
    return r.stdout


def _from_epub(path: str) -> str:
    out = []
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm")))
        for n in names:
            try:
                out.append(_strip_tags(z.read(n).decode("utf-8", "replace")))
            except Exception:
                pass
    return "\n\n".join(out)


def _from_docx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"(?i)</w:p>", "\n", xml)
    return _strip_tags(xml)


def extract_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _from_pdf(path)
    if ext in (".txt", ".md", ".markdown", ".rst", ".text"):
        return open(path, encoding="utf-8", errors="replace").read()
    if ext in (".html", ".htm"):
        return _strip_tags(open(path, encoding="utf-8", errors="replace").read())
    if ext == ".epub":
        return _from_epub(path)
    if ext == ".docx":
        return _from_docx(path)
    raise SystemExit(f"unsupported format {ext!r} (supported: {', '.join(SUPPORTED)}; mobi/azw need calibre)")


_CH_PATTERNS = [
    re.compile(r"(?m)^#{1,2}\s+(.+)$"),                                  # markdown h1/h2
    re.compile(r"(?im)^\s*(chapter\s+[\w.]+.{0,70})$"),
    re.compile(r"(?im)^\s*(part\s+[\w.]+.{0,70})$"),
    re.compile(r"(?m)^\s*(\d{1,2}[.)]\s+[A-Z].{2,60})$"),                # "3. Market Structure"
]


def detect_chapters(text: str) -> list:
    for pat in _CH_PATTERNS:
        hits = list(pat.finditer(text))
        if len(hits) >= 3:
            chs = []
            for i, m in enumerate(hits):
                end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
                title = re.sub(r"\s+", " ", m.group(1)).strip()[:80]
                chs.append({"title": title, "start": m.start(), "end": end})
            return chs
    size = 12000                                                         # ~3k-token fallback chunks
    return [{"title": f"Section {i // size + 1}", "start": i, "end": min(i + size, len(text))}
            for i in range(0, len(text), size)]


def _est_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    if a.check:
        print(json.dumps({
            "pdftotext": bool(shutil.which("pdftotext")),
            "calibre_ebook_convert": bool(shutil.which("ebook-convert")),
            "stdlib_formats": ["txt", "md", "rst", "html", "epub", "docx"],
            "install_hints": {"pdf": "apt install poppler-utils", "mobi/azw": "apt install calibre"},
        }, indent=2))
        return

    if not a.path:
        raise SystemExit("give a PATH to a document, or --check")
    text = extract_text(a.path).strip()
    if not text:
        raise SystemExit("no text extracted (empty or image-only source)")

    out_dir = a.out or tempfile.mkdtemp(prefix="book2skill_")
    os.makedirs(os.path.join(out_dir, "chapters"), exist_ok=True)
    open(os.path.join(out_dir, "full_text.txt"), "w").write(text)

    chapters = detect_chapters(text)
    manifest_chs = []
    for i, ch in enumerate(chapters, 1):
        body = text[ch["start"]:ch["end"]].strip()
        fn = f"chapters/ch{i:02d}.txt"
        open(os.path.join(out_dir, fn), "w").write(body)
        manifest_chs.append({"idx": i, "title": ch["title"], "file": fn, "est_tokens": _est_tokens(body)})

    print(json.dumps({
        "source": os.path.abspath(a.path),
        "format": os.path.splitext(a.path)[1].lower().lstrip("."),
        "chars": len(text), "est_tokens": _est_tokens(text),
        "out_dir": out_dir, "full_text": "full_text.txt",
        "n_chapters": len(manifest_chs), "chapters": manifest_chs,
    }, indent=2))


if __name__ == "__main__":
    main()
