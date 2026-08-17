"""Printable / downloadable signed loan agreement PDF."""

from __future__ import annotations

from io import BytesIO
from typing import Tuple

from django.http import HttpResponse
from django.template.loader import render_to_string

from loans.agreement_signing import signature_slots
from loans.appraisal_pack_pdf import pdf_engine_name, pdf_response


def build_agreement_pdf(agreement, request=None) -> Tuple[bytes, str]:
    loan = agreement.loan_request
    ctx = {
        'loan_request': loan,
        'agreement': agreement,
        'slots': signature_slots(agreement),
        'is_pdf': True,
    }
    if pdf_engine_name() == 'weasyprint':
        try:
            from weasyprint import HTML

            html = render_to_string('loans/agreement_print.html', ctx, request=request)
            base = request.build_absolute_uri('/') if request else ''
            return HTML(string=html, base_url=base).write_pdf(), 'weasyprint'
        except Exception:
            pass
    return _pdf_via_reportlab(agreement), 'reportlab'


def agreement_pdf_response(agreement, request=None) -> HttpResponse:
    pdf_bytes, _ = build_agreement_pdf(agreement, request=request)
    code = getattr(agreement.loan_request, 'loan_request_id', agreement.pk)
    return pdf_response(pdf_bytes, f'DECSI-loan-agreement-{code}.pdf')


def _pdf_via_reportlab(agreement) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.4 * cm, bottomMargin=1.4 * cm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        'AgrTitle', parent=styles['Heading1'], fontSize=14, textColor=colors.HexColor('#064420'),
        spaceAfter=4,
    )
    h2 = ParagraphStyle(
        'AgrH2', parent=styles['Heading2'], fontSize=11, textColor=colors.HexColor('#064420'),
        spaceBefore=8, spaceAfter=4,
    )
    body = ParagraphStyle('AgrBody', parent=styles['Normal'], fontSize=9, leading=12)
    small = ParagraphStyle('AgrSmall', parent=styles['Normal'], fontSize=8, textColor=colors.grey)

    story = [
        Paragraph('DECSI — Loan Agreement', title),
        Paragraph(agreement.title, body),
        Paragraph(
            f'Status: {agreement.get_status_display()} · Hash {agreement.content_hash}',
            small,
        ),
        Spacer(1, 8),
    ]
    for para in (agreement.body_text or '').split('\n\n'):
        story.append(Paragraph((para or '').replace('\n', '<br/>'), body))
        story.append(Spacer(1, 4))

    story.append(Paragraph('Signatures', h2))
    rows = [['Role', 'Name', 'ID', 'Signed at', 'Mark']]
    for slot in signature_slots(agreement):
        sig = slot['signature']
        mark = '—'
        if sig and sig.signature_image:
            try:
                img = Image(sig.signature_image.path, width=3.2 * cm, height=1.1 * cm)
                mark = img
            except Exception:
                mark = 'on file'
        rows.append([
            slot['label'],
            sig.signer_name if sig else 'Awaiting',
            (sig.signer_id_number if sig else '') or '—',
            sig.signed_at.strftime('%Y-%m-%d %H:%M') if sig else '—',
            mark,
        ])
    table = Table(rows, colWidths=[3.2 * cm, 3.6 * cm, 2.8 * cm, 3.2 * cm, 3.6 * cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8f4ec')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#c5d4c9')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        'Electronic signature record — drawn mark, typed name, identity number, time and hash. '
        'Not a PKI certificate.',
        small,
    ))
    doc.build(story)
    return buf.getvalue()
