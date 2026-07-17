from django import template
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()

SOURCE_CSS = {
    'registration': 'src-registration',
    'document': 'src-document',
    'banking': 'src-banking',
    'manual': 'src-manual',
    'default': 'src-default',
}

SOURCE_SHORT = {
    'registration': 'Registration',
    'document': 'Document',
    'banking': 'Core banking',
    'manual': 'Officer',
    'default': 'Default',
}


def render_field_source_badge(field_sources, field_name):
    """Render a small provenance badge for a Sheet 1 field, or empty string."""
    meta = (field_sources or {}).get(field_name) or {}
    source = meta.get('source')
    if not source:
        return ''
    short = SOURCE_SHORT.get(source, source.replace('_', ' ').title())
    detail = (meta.get('label') or '').strip()
    css = SOURCE_CSS.get(source, 'src-default')
    if detail and detail.lower() != short.lower():
        text = f'{short} · {detail}'
    else:
        text = short
    title = text
    if meta.get('document_id'):
        title = f'{text} (doc #{meta["document_id"]})'
    return format_html(
        '<span class="src-badge {}" title="{}">{}</span>',
        css,
        title,
        text,
    )


@register.simple_tag
def field_source_badge(field_sources, field_name):
    return render_field_source_badge(field_sources, field_name)


@register.simple_tag
def field_with_badge(form, field_sources, field_name, full=False):
    """Label + source badge + input for one Sheet 1 field."""
    bound = form[field_name]
    badge = render_field_source_badge(field_sources, field_name)
    full_cls = ' full' if full else ''
    label = conditional_escape(bound.label)
    errors = bound.errors.as_ul() if bound.errors else ''
    return mark_safe(
        f'<div class="field{full_cls}">'
        f'<label for="{bound.id_for_label}">{label} {badge}</label>'
        f'{bound}'
        f'{errors}'
        f'</div>'
    )
