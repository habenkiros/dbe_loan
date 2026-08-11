#!/usr/bin/env python3
"""Build printable HTML user manuals from Markdown sources (stdlib only)."""

from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from loans.manual_html import CHAPTERS, COMBINED_HTML, MANUAL_DIR, convert  # noqa: E402

OUT = MANUAL_DIR / COMBINED_HTML

CSS = """
  @page { size: A4; margin: 16mm 14mm; }
  :root {
    --ink: #1a1a1a;
    --brand: #0b3d5c;
    --brand-soft: #1f4e6e;
    --line: #c5d4de;
    --wash: #e8eef3;
    --zebra: #f7fafc;
    --code-bg: #f0f3f6;
  }
  * { box-sizing: border-box; }
  body {
    font-family: "Segoe UI", "Noto Sans Ethiopic", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.45;
    color: var(--ink);
    max-width: 920px;
    margin: 0 auto;
    padding: 24px 20px 48px;
  }
  .cover {
    border: 1px solid var(--line);
    background: linear-gradient(160deg, #f3f7fa 0%, #fff 55%);
    padding: 28px 24px;
    margin-bottom: 1.5rem;
  }
  .cover .eyebrow {
    color: var(--brand-soft);
    font-size: 9pt;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin: 0 0 0.4rem;
  }
  .cover h1 { border: none; margin: 0 0 0.4rem; font-size: 20pt; }
  .cover p { margin: 0.35rem 0; color: #334; }
  .toc { margin: 1rem 0 2rem; }
  .toc a { display: block; padding: 0.2rem 0; }
  .chapter { page-break-before: always; margin-top: 1.5rem; }
  .chapter:first-of-type { page-break-before: auto; }
  h1 {
    font-size: 16pt; border-bottom: 2px solid var(--brand); padding-bottom: 6px;
    color: var(--brand); page-break-after: avoid;
  }
  h2 {
    font-size: 12.5pt; color: var(--brand); margin-top: 1.2em;
    border-bottom: 1px solid var(--line); padding-bottom: 3px; page-break-after: avoid;
  }
  h3 { font-size: 11pt; color: var(--brand-soft); margin-top: 1em; page-break-after: avoid; }
  p { margin: 0.4em 0; }
  table {
    width: 100%; border-collapse: collapse; margin: 0.6em 0 0.9em;
    font-size: 9pt; page-break-inside: avoid;
  }
  th, td {
    border: 1px solid #b8c7d1; padding: 4px 6px; vertical-align: top; text-align: left;
  }
  th { background: var(--wash); color: var(--brand); font-weight: 600; }
  tr:nth-child(even) td { background: var(--zebra); }
  code {
    font-family: Consolas, Menlo, monospace; font-size: 8.5pt;
    background: var(--code-bg); padding: 1px 3px;
  }
  pre {
    background: #f4f6f8; border: 1px solid #d5dde3; padding: 8px 10px;
    font-size: 8pt; line-height: 1.35; page-break-inside: avoid; white-space: pre-wrap;
  }
  pre code { background: none; padding: 0; }
  ul, ol { margin: 0.35em 0 0.6em 1.15em; padding: 0; }
  li { margin: 0.15em 0; }
  hr { border: none; border-top: 1px solid var(--line); margin: 1em 0; }
  a { color: var(--brand); text-decoration: none; }
  blockquote.manual-shot {
    margin: 0.7em 0; padding: 7px 10px; border-left: 3px solid var(--brand); background: #f3f7fa;
  }
  .nav-print {
    position: sticky; top: 0; background: rgba(255,255,255,0.96);
    border-bottom: 1px solid var(--line); padding: 8px 0; margin: -8px 0 16px; z-index: 2; font-size: 9pt;
  }
  .nav-print a { margin-right: 0.85rem; }
  @media print {
    body { padding: 0; max-width: none; }
    .nav-print { display: none; }
    a { color: inherit; text-decoration: none; }
  }
"""


def main() -> None:
    sources = [(fn, label) for fn, label, _am in CHAPTERS if (MANUAL_DIR / fn).exists()]
    sections = []
    toc = []
    for idx, (name, label) in enumerate(sources):
        body = convert((MANUAL_DIR / name).read_text(encoding='utf-8'))
        anchor = f'ch-{idx}'
        toc.append(f'<a href="#{anchor}">{html.escape(label)}</a>')
        sections.append(
            f'<section class="chapter" id="{anchor}">\n'
            f'<p class="eyebrow" style="color:var(--brand-soft);font-size:9pt;'
            f'text-transform:uppercase;letter-spacing:0.04em;margin:0 0 0.25rem">'
            f'Chapter {idx + 1} · {html.escape(label)}</p>\n'
            f'{body}\n</section>'
        )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>DECSI Loan Hub — User Manuals</title>
<style>
{CSS}
</style>
</head>
<body>
<nav class="nav-print" aria-label="Chapters">
  {" ".join(f'<a href="#ch-{i}">{html.escape(label)}</a>' for i, (_, label) in enumerate(sources))}
</nav>
<header class="cover">
  <p class="eyebrow">DECSI · Seqela Technologies</p>
  <h1>Loan Hub User Manuals</h1>
  <p>Admin · Staff · Customers · Market · Screenshot captions (EN &amp; AM where available)</p>
  <p>Print this page (Ctrl/Cmd+P) to PDF. Screen navigation links are hidden when printing.</p>
</header>
<nav class="toc" aria-label="Table of contents">
  <h2>Contents</h2>
  {"".join(f"<div>{item}</div>" for item in toc)}
</nav>
{"".join(sections)}
</body>
</html>
"""
    OUT.write_text(doc, encoding='utf-8')
    print(f'Wrote {OUT}')


if __name__ == '__main__':
    main()
