"""Render docs/user_manual Markdown chapters to HTML (stdlib only)."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# Project root / docs / user_manual (no Django required for conversion)
MANUAL_DIR = Path(__file__).resolve().parents[1] / 'docs' / 'user_manual'

# (filename, label)
CHAPTERS: List[Tuple[str, str]] = [
    ('README.md', 'Overview'),
    ('01_admin.md', 'Admin'),
    ('02_staff.md', 'Staff'),
    ('03_customers.md', 'Customers'),
    ('04_market_partners.md', 'Market partners'),
    ('06_installation_it.md', 'IT installation'),
]

PUBLIC_CHAPTERS = {
    '03_customers.md',
}
MARKET_CHAPTERS = {
    '04_market_partners.md',
}
COMBINED_HTML = 'DECSI_Loan_Hub_User_Manuals.html'
COMBINED_PDF = 'DECSI_Loan_Hub_User_Manuals.pdf'


def chapter_path(filename: str) -> Path:
    return MANUAL_DIR / filename


def list_chapters(allowed: Optional[Iterable[str]] = None) -> List[Tuple[str, str, str, str]]:
    """Return (filename, label, label_secondary, slug). Secondary kept for template compat."""
    allowed_set = set(allowed) if allowed is not None else None
    rows = []
    for filename, label in CHAPTERS:
        if allowed_set is not None and filename not in allowed_set:
            continue
        if chapter_path(filename).exists():
            rows.append((filename, label, label, slug_for(filename)))
    return rows


def inline(text: str) -> str:
    # Images first (before link rewrite)
    def img_sub(m):
        alt = html.escape(m.group(1))
        src = m.group(2).strip()
        # Keep relative paths for HTML beside manuals; PDF builder uses base_url
        return (
            f'<figure class="manual-figure">'
            f'<img src="{html.escape(src)}" alt="{alt}" loading="lazy"/>'
            f'<figcaption>{alt}</figcaption>'
            f'</figure>'
        )

    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', img_sub, text)
    text = html.escape(text)
    # Unescape figure HTML we just embedded — careful: we escaped after img_sub
    # So do images AFTER escape instead:
    return text


def inline_with_images(text: str) -> str:
    """Escape text but preserve markdown images as HTML figures."""
    parts = []
    last = 0
    for m in re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', text):
        parts.append(html.escape(text[last:m.start()]))
        alt = html.escape(m.group(1))
        src = html.escape(m.group(2).strip())
        parts.append(
            f'<figure class="manual-figure">'
            f'<img src="{src}" alt="{alt}"/>'
            f'<figcaption>{alt}</figcaption>'
            f'</figure>'
        )
        last = m.end()
    parts.append(html.escape(text[last:]))
    text = ''.join(parts)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'(?<!\])\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    return text


def convert(md: str) -> str:
    lines = md.replace('\r\n', '\n').split('\n')
    out: List[str] = []
    i = 0
    in_code = False
    code_lang = ''
    code_buf: List[str] = []
    list_type = None

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f'</{list_type}>')
            list_type = None

    while i < len(lines):
        line = lines[i]

        if line.startswith('```'):
            if not in_code:
                close_list()
                in_code = True
                code_lang = line[3:].strip()
                code_buf = []
            else:
                cls = f' class="lang-{html.escape(code_lang)}"' if code_lang else ''
                body = html.escape('\n'.join(code_buf))
                out.append(f'<pre{cls}><code>{body}</code></pre>')
                in_code = False
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if not line.strip():
            close_list()
            i += 1
            continue

        if line.strip() == '---':
            close_list()
            out.append('<hr>')
            i += 1
            continue

        # Standalone image line
        img_m = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$', line.strip())
        if img_m:
            close_list()
            alt = html.escape(img_m.group(1))
            src = html.escape(img_m.group(2).strip())
            out.append(
                f'<figure class="manual-figure">'
                f'<img src="{src}" alt="{alt}"/>'
                f'<figcaption>{alt}</figcaption>'
                f'</figure>'
            )
            i += 1
            continue

        if line.lstrip().startswith('>'):
            close_list()
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith('>'):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i]))
                i += 1
            # If blockquote is only an image, render as figure
            joined = '\n'.join(buf)
            img_only = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$', joined.strip())
            if img_only:
                alt = html.escape(img_only.group(1))
                src = html.escape(img_only.group(2).strip())
                out.append(
                    f'<figure class="manual-figure">'
                    f'<img src="{src}" alt="{alt}"/>'
                    f'<figcaption>{alt}</figcaption>'
                    f'</figure>'
                )
            else:
                inner = '<br>'.join(inline_with_images(b) if b else '' for b in buf)
                out.append(f'<blockquote class="manual-shot">{inner}</blockquote>')
            continue

        if '|' in line and i + 1 < len(lines) and re.match(
            r'^\s*\|?\s*[-:| ]+\s*\|?\s*$', lines[i + 1]
        ):
            close_list()
            rows = []
            while i < len(lines) and '|' in lines[i]:
                raw = lines[i].strip()
                if re.match(r'^\|?\s*[-:| ]+\|?\s*$', raw):
                    i += 1
                    continue
                cells = [c.strip() for c in raw.strip('|').split('|')]
                rows.append(cells)
                i += 1
            if rows:
                out.append('<table>')
                out.append(
                    '<thead><tr>'
                    + ''.join(f'<th>{inline_with_images(c)}</th>' for c in rows[0])
                    + '</tr></thead>'
                )
                if len(rows) > 1:
                    out.append('<tbody>')
                    for row in rows[1:]:
                        out.append(
                            '<tr>'
                            + ''.join(f'<td>{inline_with_images(c)}</td>' for c in row)
                            + '</tr>'
                        )
                    out.append('</tbody>')
                out.append('</table>')
            continue

        m = re.match(r'^(#{1,3})\s+(.*)$', line)
        if m:
            close_list()
            level = len(m.group(1))
            out.append(f'<h{level}>{inline_with_images(m.group(2))}</h{level}>')
            i += 1
            continue

        m = re.match(r'^(\d+)\.\s+(.*)$', line)
        if m:
            if list_type != 'ol':
                close_list()
                out.append('<ol>')
                list_type = 'ol'
            out.append(f'<li>{inline_with_images(m.group(2))}</li>')
            i += 1
            continue

        m = re.match(r'^[-*]\s+(.*)$', line)
        if m:
            if list_type != 'ul':
                close_list()
                out.append('<ul>')
                list_type = 'ul'
            out.append(f'<li>{inline_with_images(m.group(1))}</li>')
            i += 1
            continue

        close_list()
        out.append(f'<p>{inline_with_images(line)}</p>')
        i += 1

    close_list()
    return '\n'.join(out)


def render_chapter(filename: str, *, web_image_prefix: str = '') -> str:
    path = chapter_path(filename)
    html_body = convert(path.read_text(encoding='utf-8'))
    if web_image_prefix:
        # Point relative screenshot paths at the Help screenshot URL
        html_body = html_body.replace(
            'src="screenshots/',
            f'src="{web_image_prefix}',
        )
    return html_body


def slug_for(filename: str) -> str:
    return filename.replace('.md', '').replace('_', '-')
