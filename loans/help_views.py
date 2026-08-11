"""In-app user manual / Help views for the staff hub."""

from __future__ import annotations

from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import render

from loans.manual_html import (
    CHAPTERS,
    COMBINED_HTML,
    MANUAL_DIR,
    list_chapters,
    render_chapter,
    slug_for,
)


@login_required
def help_index(request):
    return render(
        request,
        'help/hub_index.html',
        {
            'chapters': list_chapters(),
            'combined_name': COMBINED_HTML,
        },
    )


@login_required
def help_chapter(request, slug: str):
    filename = None
    label = slug
    for name, en, _am in CHAPTERS:
        if slug_for(name) == slug:
            filename = name
            label = en
            break
    if not filename or not (MANUAL_DIR / filename).exists():
        raise Http404('Manual chapter not found')
    return render(
        request,
        'help/hub_chapter.html',
        {
            'title': label,
            'slug': slug,
            'body_html': render_chapter(filename),
            'chapters': list_chapters(),
        },
    )


@login_required
def help_combined_html(request):
    path = Path(MANUAL_DIR) / COMBINED_HTML
    if not path.exists():
        build_script = MANUAL_DIR / 'build_html.py'
        if build_script.exists():
            import runpy

            runpy.run_path(str(build_script), run_name='__main__')
        if not path.exists():
            raise Http404('Combined manual HTML is not built yet')
    return FileResponse(path.open('rb'), content_type='text/html; charset=utf-8')
