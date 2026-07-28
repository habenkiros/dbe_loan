"""Server-side appraisal pack PDF (WeasyPrint preferred, ReportLab fallback)."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, Optional, Tuple

from django.http import HttpResponse
from django.template.loader import render_to_string

from loans.appraisal_pack import build_committee_appraisal_pack


def pdf_engine_name() -> str:
    """Return 'weasyprint' if importable, else 'reportlab'."""
    try:
        import weasyprint  # noqa: F401
        return 'weasyprint'
    except Exception:
        return 'reportlab'


def build_appraisal_pack_pdf(loan_request, base_url: Optional[str] = None) -> Tuple[bytes, str]:
    """
    Build appraisal pack PDF bytes.

    Returns (pdf_bytes, engine_name).
    Prefers WeasyPrint HTML render; falls back to ReportLab if WeasyPrint
    (or its system libs) is unavailable.
    """
    pack = build_committee_appraisal_pack(loan_request)
    if not pack.get('appraisal'):
        raise ValueError('No appraisal record found for this loan.')

    if pdf_engine_name() == 'weasyprint':
        try:
            return _pdf_via_weasyprint(pack, base_url=base_url), 'weasyprint'
        except Exception:
            # Cairo/Pango missing, broken CSS, etc. — still deliver a PDF.
            pass
    return _pdf_via_reportlab(pack), 'reportlab'


def pdf_response(pdf_bytes: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Content-Length'] = str(len(pdf_bytes))
    return response


def _pdf_via_weasyprint(pack: Dict[str, Any], base_url: Optional[str] = None) -> bytes:
    from weasyprint import HTML

    html = render_to_string('loans/committee_appraisal_pack_pdf.html', pack)
    return HTML(string=html, base_url=base_url or '').write_pdf()


def _pdf_via_reportlab(pack: Dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    loan = pack['loan_request']
    appraisal = pack['appraisal']
    basic = pack.get('basic_info')
    scorecard = pack.get('scorecard') or {}

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title=f'Appraisal pack {loan.loan_request_id}',
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        'PackTitle', parent=styles['Heading1'], fontSize=14, textColor=colors.HexColor('#064420'), spaceAfter=8,
    )
    h2 = ParagraphStyle(
        'PackH2', parent=styles['Heading2'], fontSize=11, textColor=colors.HexColor('#064420'), spaceBefore=10, spaceAfter=4,
    )
    body = ParagraphStyle('PackBody', parent=styles['Normal'], fontSize=9, leading=12)
    small = ParagraphStyle('PackSmall', parent=styles['Normal'], fontSize=8, leading=10, textColor=colors.HexColor('#555555'))

    def p(text, style=body):
        return Paragraph(_esc(text), style)

    def kv_table(rows):
        data = [[p(f'<b>{k}</b>', small), p(str(v if v not in (None, '') else '—'), body)] for k, v in rows]
        t = Table(data, colWidths=[4.2 * cm, 12.5 * cm])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        return t

    story = []
    mode = pack.get('mode_label') or ''
    story.append(p(f'Appraisal pack — {loan.loan_request_id}', title))
    story.append(p(
        f'{loan.applicant_name} | Branch: {loan.branch.name if loan.branch_id else "—"}'
        f' | Requested: {_fmt(loan.amount_requested)}'
        + (f' | Mode: {mode}' if mode else ''),
        small,
    ))
    story.append(Spacer(1, 6))

    story.append(p('Decision snapshot', h2))
    story.append(kv_table([
        ('Recommendation', appraisal.get_recommendation_display() if appraisal.recommendation else '—'),
        ('Recommended amount', _fmt(appraisal.amount_approved)),
        ('Term / rate', f'{appraisal.term_approved_months or "—"} months · {appraisal.rate_approved or "—"}%'),
        ('Credit score', f'{scorecard.get("total", "—")}/100 — {scorecard.get("band_label", "")}'.strip(' —')),
    ]))

    if basic:
        story.append(p('Sheet 1 — Basic information', h2))
        story.append(kv_table([
            ('TIN', basic.tin_number),
            ('Business', f'{basic.business_name or "—"} — {basic.economic_sector or ""}'),
            ('Home address', basic.home_address),
            ('Business address', basic.business_address),
            ('Term / rate', f'{basic.term_months or "—"} months @ {basic.interest_rate or "—"}%'),
        ]))

    story.append(p('Sheet 2 — Business & character', h2))
    story.append(kv_table([
        ('Business assessment', (appraisal.business_assessment or '—')[:800]),
        ('Character assessment', (appraisal.character_assessment or '—')[:800]),
        ('Qualitative total', appraisal.qualitative_total_score),
    ]))

    story.append(p('Sheet 3 — Cashflow & bureau', h2))
    story.append(kv_table([
        ('Monthly sales', appraisal.cf_monthly_sales),
        ('Annual net CF', appraisal.cf_annual_net_cashflow),
        ('DSCR', appraisal.dscr_annual),
        ('Bureau score', appraisal.bureau_score),
        ('Stressed DSCR', appraisal.stressed_dscr),
    ]))

    story.append(p('Sheet 4 — E&S', h2))
    story.append(kv_table([
        ('Risk', appraisal.get_es_risk_category_display() if appraisal.es_risk_category else '—'),
        ('Decision', appraisal.get_es_eligibility_decision_display() if appraisal.es_eligibility_decision else '—'),
        ('Notes', (appraisal.es_notes or '—')[:500]),
    ]))

    story.append(p('Sheet 5 — Collateral', h2))
    story.append(kv_table([
        ('Total value', appraisal.collateral_total_value),
        ('Coverage', appraisal.collateral_coverage_ratio),
    ]))

    story.append(p('Sheet 6 — Summary & decision', h2))
    if scorecard.get('pillars'):
        for pillar in scorecard['pillars']:
            story.append(p(
                f'{pillar.get("label")}: {pillar.get("earned")}/{pillar.get("max")} — {pillar.get("remark") or ""}',
                small,
            ))
    story.append(kv_table([
        ('Strengths', (appraisal.strengths or '—')[:600]),
        ('Weaknesses', (appraisal.weaknesses or '—')[:600]),
    ]))
    conditions = pack.get('conditions') or []
    if conditions:
        story.append(p('Conditions', h2))
        for c in conditions:
            story.append(p(f'• {getattr(c, "description", "")}', body))

    amort = pack.get('amortization') or []
    if amort:
        story.append(p('Sheet 7 — Amortization (first 24 rows)', h2))
        header = ['#', 'Date', 'Payment', 'Principal', 'Interest', 'Balance']
        data = [header]
        for row in amort[:24]:
            data.append([
                str(row.period_number),
                row.payment_date.isoformat() if row.payment_date else '—',
                _fmt(row.payment_amount),
                _fmt(row.principal),
                _fmt(row.interest),
                _fmt(row.balance_after),
            ])
        t = Table(data, colWidths=[1.2 * cm, 2.6 * cm, 2.6 * cm, 2.6 * cm, 2.6 * cm, 2.8 * cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8f4ec')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(t)
        if len(amort) > 24:
            story.append(p(f'… {len(amort) - 24} more periods omitted in PDF summary.', small))

    doc.build(story)
    return buf.getvalue()


def _esc(text) -> str:
    if text is None:
        return '—'
    s = str(text)
    return (
        s.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('\n', '<br/>')
    )


def _fmt(val) -> str:
    if val is None or val == '':
        return '—'
    try:
        return f'{float(val):,.2f}'
    except (TypeError, ValueError):
        return str(val)
