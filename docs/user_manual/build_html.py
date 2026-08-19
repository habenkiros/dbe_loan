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

# DECSI / Seqela green brand — print-friendly, Ethiopic-capable
CSS = """
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Ethiopic:wght@400;600;700&family=Source+Sans+3:wght@400;600;700&family=Libre+Baskerville:wght@700&display=swap');

  @page {
    size: A4;
    margin: 18mm 15mm 20mm;
    @bottom-center {
      content: "DECSI Loan Hub · User Manuals · " counter(page);
      font-size: 8pt;
      color: #5a6f68;
      font-family: "Source Sans 3", "Noto Sans Ethiopic", sans-serif;
    }
  }
  :root {
    --ink: #0e2418;
    --muted: #4f6558;
    --brand: #064420;
    --brand-mid: #0a6b2e;
    --accent: #28b446;
    --line: #c9dbd1;
    --wash: #eef8f2;
    --soft: #f3f8f5;
    --zebra: #f7fbf8;
    --code-bg: #e8f4ec;
    --gold: #b8892c;
    --card: #ffffff;
  }
  * { box-sizing: border-box; }
  body {
    font-family: "Source Sans 3", "Noto Sans Ethiopic", "Segoe UI", sans-serif;
    font-size: 10.25pt;
    line-height: 1.5;
    color: var(--ink);
    max-width: 900px;
    margin: 0 auto;
    padding: 20px 18px 56px;
    background:
      radial-gradient(ellipse 70% 40% at 0% 0%, rgba(10, 107, 46, 0.07), transparent 55%),
      radial-gradient(ellipse 50% 30% at 100% 0%, rgba(40, 180, 70, 0.06), transparent 50%),
      #fafcfb;
  }
  .nav-print {
    position: sticky;
    top: 0;
    z-index: 5;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 0.75rem;
    align-items: center;
    padding: 0.65rem 0.85rem;
    margin: -8px -6px 1.25rem;
    background: rgba(255,255,255,0.94);
    border: 1px solid var(--line);
    border-radius: 12px;
    backdrop-filter: blur(8px);
    font-size: 8.5pt;
    box-shadow: 0 4px 18px rgba(6, 68, 32, 0.06);
  }
  .nav-print a {
    color: var(--brand-mid);
    text-decoration: none;
    font-weight: 600;
    padding: 0.15rem 0.35rem;
    border-radius: 6px;
  }
  .nav-print a:hover { background: var(--wash); }

  .cover {
    position: relative;
    overflow: hidden;
    border: 1px solid var(--line);
    border-radius: 16px;
    background:
      linear-gradient(145deg, #053d1e 0%, #064420 42%, #0a6b2e 78%, #0d8038 100%);
    color: #f4fbf6;
    padding: 2.4rem 2rem 2rem;
    margin-bottom: 1.75rem;
    box-shadow: 0 18px 40px rgba(6, 68, 32, 0.18);
  }
  .cover::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle at 90% 10%, rgba(40, 180, 70, 0.35), transparent 40%),
      radial-gradient(circle at 10% 90%, rgba(255, 255, 255, 0.08), transparent 45%);
    pointer-events: none;
  }
  .cover::after {
    content: "";
    position: absolute;
    right: -20px;
    bottom: -30px;
    width: 180px;
    height: 180px;
    border: 18px solid rgba(255,255,255,0.06);
    border-radius: 50%;
    pointer-events: none;
  }
  .cover-inner { position: relative; z-index: 1; }
  .cover .eyebrow {
    display: inline-block;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    opacity: 0.9;
    margin: 0 0 0.75rem;
    padding: 0.25rem 0.65rem;
    border: 1px solid rgba(255,255,255,0.28);
    border-radius: 999px;
    background: rgba(0,0,0,0.12);
  }
  .cover h1 {
    font-family: "Libre Baskerville", "Noto Sans Ethiopic", Georgia, serif;
    font-size: 26pt;
    font-weight: 700;
    line-height: 1.2;
    border: none;
    margin: 0 0 0.55rem;
    color: #fff;
    padding: 0;
  }
  .cover .lead {
    font-size: 11.5pt;
    max-width: 34rem;
    margin: 0 0 1.1rem;
    opacity: 0.95;
    line-height: 1.45;
  }
  .cover .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin: 0 0 1rem;
  }
  .cover .chip {
    font-size: 8.5pt;
    font-weight: 700;
    padding: 0.3rem 0.7rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.14);
    border: 1px solid rgba(255,255,255,0.22);
  }
  .cover .hint {
    margin: 0;
    font-size: 9pt;
    opacity: 0.82;
  }
  .cover .accent-bar {
    width: 3.5rem;
    height: 4px;
    background: var(--accent);
    border-radius: 2px;
    margin: 0 0 1rem;
  }

  .toc {
    margin: 0 0 2rem;
    padding: 1.15rem 1.2rem 1.25rem;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: 0 8px 24px rgba(6, 68, 32, 0.05);
  }
  .toc h2 {
    margin-top: 0;
    border: none;
    font-family: "Libre Baskerville", Georgia, serif;
    font-size: 14pt;
  }
  .toc-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.45rem 0.75rem;
    margin-top: 0.75rem;
  }
  .toc a {
    display: block;
    padding: 0.55rem 0.7rem;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--soft);
    color: var(--brand);
    text-decoration: none;
    font-weight: 600;
    font-size: 9.5pt;
    transition: background 0.15s, border-color 0.15s;
  }
  .toc a:hover {
    background: var(--wash);
    border-color: #8fc9a8;
  }
  .toc .num {
    display: inline-block;
    min-width: 1.4rem;
    color: var(--brand-mid);
    font-variant-numeric: tabular-nums;
    opacity: 0.85;
  }

  .chapter {
    page-break-before: always;
    margin-top: 1.75rem;
    padding: 1.15rem 1.2rem 1.4rem;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: 0 6px 20px rgba(6, 68, 32, 0.04);
  }
  .chapter:first-of-type { page-break-before: auto; }
  .chapter-label {
    display: inline-block;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--brand-mid);
    background: var(--wash);
    border: 1px solid #b7d9c8;
    border-radius: 999px;
    padding: 0.2rem 0.65rem;
    margin: 0 0 0.65rem;
  }

  h1 {
    font-family: "Libre Baskerville", "Noto Sans Ethiopic", Georgia, serif;
    font-size: 16.5pt;
    color: var(--brand);
    border-bottom: 3px solid var(--brand-mid);
    padding-bottom: 0.4rem;
    margin: 0.2rem 0 0.85rem;
    page-break-after: avoid;
  }
  h2 {
    font-size: 12.5pt;
    color: var(--brand);
    margin-top: 1.35em;
    padding: 0.35rem 0 0.3rem 0.65rem;
    border-left: 4px solid var(--accent);
    border-bottom: 1px solid var(--line);
    page-break-after: avoid;
  }
  h3 {
    font-size: 11pt;
    color: var(--brand-mid);
    margin-top: 1.05em;
    page-break-after: avoid;
  }
  p { margin: 0.45em 0; }
  strong { color: var(--brand); }

  table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    margin: 0.75em 0 1em;
    font-size: 9pt;
    page-break-inside: avoid;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
  }
  th, td {
    padding: 0.45rem 0.55rem;
    vertical-align: top;
    text-align: left;
    border-bottom: 1px solid var(--line);
  }
  th {
    background: linear-gradient(180deg, #e8f6ee, var(--wash));
    color: var(--brand);
    font-weight: 700;
  }
  tr:last-child td { border-bottom: none; }
  tr:nth-child(even) td { background: var(--zebra); }

  code {
    font-family: Consolas, Menlo, monospace;
    font-size: 8.5pt;
    background: var(--code-bg);
    padding: 0.1rem 0.35rem;
    border-radius: 4px;
    color: #053d1e;
  }
  pre {
    background: #f0f7f3;
    border: 1px solid var(--line);
    border-left: 4px solid var(--brand-mid);
    border-radius: 10px;
    padding: 0.75rem 0.9rem;
    font-size: 8pt;
    line-height: 1.4;
    page-break-inside: avoid;
    white-space: pre-wrap;
  }
  pre code { background: none; padding: 0; }
  ul, ol { margin: 0.4em 0 0.7em 1.2em; padding: 0; }
  li { margin: 0.2em 0; }
  hr {
    border: none;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--line), transparent);
    margin: 1.15em 0;
  }
  a { color: var(--brand-mid); text-decoration: none; font-weight: 600; }

  blockquote.manual-shot {
    margin: 0.9em 0;
    padding: 0.75rem 0.95rem;
    border-radius: 10px;
    border: 1px solid #b7d9c8;
    border-left: 5px solid var(--gold);
    background: linear-gradient(135deg, #fffdf7 0%, #f3f8f5 100%);
    color: #1a3326;
    font-size: 9.5pt;
    page-break-inside: avoid;
  }
  figure.manual-figure {
    margin: 1rem 0 1.25rem;
    padding: 0.55rem;
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 12px;
    box-shadow: 0 8px 22px rgba(6, 68, 32, 0.06);
    page-break-inside: avoid;
    text-align: center;
  }
  figure.manual-figure img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    border: 1px solid #dce8e1;
  }
  figure.manual-figure figcaption {
    margin-top: 0.45rem;
    font-size: 8.5pt;
    color: var(--muted);
    font-weight: 600;
  }

  @media print {
    body {
      padding: 0;
      max-width: none;
      background: #fff;
    }
    .nav-print { display: none; }
    .cover {
      box-shadow: none;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .chapter, .toc {
      box-shadow: none;
      break-inside: avoid;
    }
    a { color: inherit; text-decoration: none; font-weight: inherit; }
  }
  @media (max-width: 640px) {
    .toc-grid { grid-template-columns: 1fr; }
    .cover { padding: 1.5rem 1.15rem; }
    .cover h1 { font-size: 20pt; }
  }
"""


def main() -> None:
    sources = [(fn, label) for fn, label in CHAPTERS if (MANUAL_DIR / fn).exists()]
    sections = []
    toc_items = []
    for idx, (name, label) in enumerate(sources):
        body = convert((MANUAL_DIR / name).read_text(encoding='utf-8'))
        anchor = f'ch-{idx}'
        toc_items.append(
            f'<a href="#{anchor}"><span class="num">{idx + 1:02d}</span> {html.escape(label)}</a>'
        )
        sections.append(
            f'<section class="chapter" id="{anchor}">\n'
            f'<div class="chapter-label">Chapter {idx + 1:02d}</div>\n'
            f'{body}\n</section>'
        )

    nav = ' '.join(
        f'<a href="#ch-{i}">{html.escape(label.split("(")[0].strip())}</a>'
        for i, (_, label) in enumerate(sources)
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
<nav class="nav-print" aria-label="Chapters">{nav}</nav>
<header class="cover">
  <div class="cover-inner">
    <p class="eyebrow">DECSI · Seqela Technologies</p>
    <div class="accent-bar" aria-hidden="true"></div>
    <h1>Loan Hub User Manuals</h1>
    <p class="lead">
      Guides for administrators, staff, customers, market partners, and IT —
      with real product screenshots.
    </p>
    <div class="meta" aria-label="Topics">
      <span class="chip">Admin</span>
      <span class="chip">Staff</span>
      <span class="chip">Digital Apply</span>
      <span class="chip">Market</span>
      <span class="chip">IT install</span>
    </div>
    <p class="hint">Print or Save as PDF (Ctrl/Cmd+P). Navigation links are hidden when printing.</p>
  </div>
</header>
<nav class="toc" aria-label="Table of contents">
  <h2>Contents</h2>
  <div class="toc-grid">
    {''.join(toc_items)}
  </div>
</nav>
{''.join(sections)}
</body>
</html>
"""
    OUT.write_text(doc, encoding='utf-8')
    print(f'Wrote {OUT}')


if __name__ == '__main__':
    main()
