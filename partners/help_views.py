"""Market portal help — Seqela Market user manual."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import render

from loans.manual_html import (
    CHAPTERS,
    MARKET_CHAPTERS,
    list_chapters,
    render_chapter,
    slug_for,
)


def help_index(request):
    return render(
        request,
        'help/market_index.html',
        {'chapters': list_chapters(MARKET_CHAPTERS)},
    )


def help_chapter(request, slug: str):
    filename = None
    label = slug
    for name, en in CHAPTERS:
        if slug_for(name) != slug:
            continue
        if name not in MARKET_CHAPTERS:
            raise Http404('Manual chapter not found')
        filename = name
        label = en
        break
    if not filename:
        raise Http404('Manual chapter not found')
    return render(
        request,
        'help/market_chapter.html',
        {
            'title': label,
            'slug': slug,
            'body_html': render_chapter(filename),
            'chapters': list_chapters(MARKET_CHAPTERS),
        },
    )
