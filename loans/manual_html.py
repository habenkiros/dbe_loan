"""Render docs/user_manual Markdown chapters to HTML (stdlib only)."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# Project root / docs / user_manual (no Django required for conversion)
MANUAL_DIR = Path(__file__).resolve().parents[1] / 'docs' / 'user_manual'

# (filename, english label, optional Amharic label)
CHAPTERS: List[Tuple[str, str, str]] = [
    ('README.md', 'Overview', 'አጠቃላይ እይታ'),
    ('01_admin.md', 'Admin', 'አስተዳዳሪ'),
    ('01_admin_am.md', 'Admin (Amharic)', 'አስተዳዳሪ (አማርኛ)'),
    ('02_staff.md', 'Staff', 'ሰራተኛ'),
    ('02_staff_am.md', 'Staff (Amharic)', 'ሰራተኛ (አማርኛ)'),
    ('03_customers.md', 'Customers', 'ደንበኞች'),
    ('03_customers_am.md', 'Customers (Amharic)', 'ደንበኞች (አማርኛ)'),
    ('04_market_partners.md', 'Market partners', 'የገበያ አጋሮች'),
    ('05_screenshot_captions.md', 'Screenshot captions', 'የስክሪንሾት መግለጫዎች'),
    ('06_installation_it.md', 'IT installation', 'የIT ጭነት'),
]

PUBLIC_CHAPTERS = {
    '03_customers.md',
    '03_customers_am.md',
}
MARKET_CHAPTERS = {
    '04_market_partners.md',
}
COMBINED_HTML = 'DECSI_Loan_Hub_User_Manuals.html'


def chapter_path(filename: str) -> Path:
    return MANUAL_DIR / filename


def list_chapters(allowed: Optional[Iterable[str]] = None) -> List[Tuple[str, str, str, str]]:
    allowed_set = set(allowed) if allowed is not None else None
    rows = []
    for filename, label, label_am in CHAPTERS:
        if allowed_set is not None and filename not in allowed_set:
            continue
        if chapter_path(filename).exists():
            rows.append((filename, label, label_am, slug_for(filename)))
    return rows


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
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

        # Figure / screenshot callout: lines starting with "> **Screenshot:"
        if line.lstrip().startswith('>'):
            close_list()
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith('>'):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i]))
                i += 1
            inner = '<br>'.join(inline(b) if b else '' for b in buf)
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
                    + ''.join(f'<th>{inline(c)}</th>' for c in rows[0])
                    + '</tr></thead>'
                )
                if len(rows) > 1:
                    out.append('<tbody>')
                    for row in rows[1:]:
                        out.append(
                            '<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in row) + '</tr>'
                        )
                    out.append('</tbody>')
                out.append('</table>')
            continue

        m = re.match(r'^(#{1,3})\s+(.*)$', line)
        if m:
            close_list()
            level = len(m.group(1))
            out.append(f'<h{level}>{inline(m.group(2))}</h{level}>')
            i += 1
            continue

        m = re.match(r'^(\d+)\.\s+(.*)$', line)
        if m:
            if list_type != 'ol':
                close_list()
                out.append('<ol>')
                list_type = 'ol'
            out.append(f'<li>{inline(m.group(2))}</li>')
            i += 1
            continue

        m = re.match(r'^[-*]\s+(.*)$', line)
        if m:
            if list_type != 'ul':
                close_list()
                out.append('<ul>')
                list_type = 'ul'
            out.append(f'<li>{inline(m.group(1))}</li>')
            i += 1
            continue

        close_list()
        out.append(f'<p>{inline(line)}</p>')
        i += 1

    close_list()
    return '\n'.join(out)


def render_chapter(filename: str) -> str:
    path = chapter_path(filename)
    return convert(path.read_text(encoding='utf-8'))


def slug_for(filename: str) -> str:
    return filename.replace('.md', '').replace('_', '-')
