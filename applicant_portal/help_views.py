"""Public Digital Apply help / user manuals."""

from __future__ import annotations

from django.http import FileResponse, Http404
from django.shortcuts import render
from pathlib import Path

from loans.manual_html import (
    CHAPTERS,
    MANUAL_DIR,
    PUBLIC_CHAPTERS,
    list_chapters,
    render_chapter,
    slug_for,
)


def help_index(request):
    return render(
        request,
        'help/applicant_index.html',
        {'chapters': list_chapters(PUBLIC_CHAPTERS)},
    )


def help_screenshot(request, name: str):
    safe = Path(name).name
    path = MANUAL_DIR / 'screenshots' / safe
    if not path.exists() or not path.is_file():
        raise Http404('Screenshot not found')
    content_type = 'image/png' if path.suffix.lower() == '.png' else 'application/octet-stream'
    return FileResponse(path.open('rb'), content_type=content_type)


def help_chapter(request, slug: str):
    filename = None
    label = slug
    for name, en in CHAPTERS:
        if slug_for(name) != slug:
            continue
        if name not in PUBLIC_CHAPTERS:
            raise Http404('Manual chapter not found')
        filename = name
        label = en
        break
    if not filename:
        raise Http404('Manual chapter not found')
    return render(
        request,
        'help/applicant_chapter.html',
        {
            'title': label,
            'slug': slug,
            'body_html': render_chapter(
                filename,
                web_image_prefix='/help/screenshots/',
            ),
            'chapters': list_chapters(PUBLIC_CHAPTERS),
        },
    )
