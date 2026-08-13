"""In-app user manual / Help views for the staff hub."""

from __future__ import annotations

from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import render

from loans.manual_html import (
    CHAPTERS,
    COMBINED_HTML,
    COMBINED_PDF,
    MANUAL_DIR,
    list_chapters,
    render_chapter,
    slug_for,
)


@login_required
def help_index(request):
    pdf_ready = (MANUAL_DIR / COMBINED_PDF).exists()
    return render(
        request,
        'help/hub_index.html',
        {
            'chapters': list_chapters(),
            'combined_name': COMBINED_HTML,
            'pdf_ready': pdf_ready,
        },
    )


@login_required
def help_chapter(request, slug: str):
    filename = None
    label = slug
    for name, en in CHAPTERS:
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
            'body_html': render_chapter(
                filename,
                web_image_prefix='/hub/help/screenshots/',
            ),
            'chapters': list_chapters(),
        },
    )


@login_required
def help_screenshot(request, name: str):
    # Prevent path traversal
    safe = Path(name).name
    path = MANUAL_DIR / 'screenshots' / safe
    if not path.exists() or not path.is_file():
        raise Http404('Screenshot not found')
    content_type = 'image/png' if path.suffix.lower() == '.png' else 'application/octet-stream'
    return FileResponse(path.open('rb'), content_type=content_type)


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


@login_required
def help_combined_pdf(request):
    path = Path(MANUAL_DIR) / COMBINED_PDF
    if not path.exists():
        raise Http404('Combined manual PDF is not built yet')
    return FileResponse(
        path.open('rb'),
        content_type='application/pdf',
        as_attachment=True,
        filename=COMBINED_PDF,
    )
