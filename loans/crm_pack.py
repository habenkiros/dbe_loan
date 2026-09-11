"""Modality-aware CRM / committee pack snippets (product desks, not Sheets 1–7)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.product_family import (
    FAMILY_CONSUMER,
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
    family_label,
    resolve_product_family,
)


def uses_sheet_pack(loan_request) -> bool:
    from loans.engines import get_engine

    return bool(get_engine(loan_request).requires_appraisal_sheets())


def build_modality_pack_section(loan_request) -> Optional[Dict[str, Any]]:
    """Structured pack body for CRM / committee when the file is a product desk."""
    if uses_sheet_pack(loan_request):
        return None

    family = resolve_product_family(loan_request)
    from loans.committee_evidence import build_committee_vote_evidence

    evidence = build_committee_vote_evidence(loan_request)
    scorecard = evidence.get('scorecard') or {}
    appraisal = evidence.get('appraisal')
    rows: List[Dict[str, str]] = []
    desk_url_name = None
    title = f'{family_label(family)} appraisal pack'

    if family == FAMILY_CONSUMER:
        desk_url_name = 'consumer_file'
        title = 'Consumer / HRM appraisal pack'
        from loans.consumer_overlay import get_consumer_profile
        cons = get_consumer_profile(loan_request)
        rows = [
            {'label': 'DTI', 'value': _pct(scorecard.get('dti_pct'))},
            {'label': 'LTV', 'value': f"{_pct(scorecard.get('ltv_pct'))} (cap {_pct(scorecard.get('ltv_cap'))})"},
            {'label': 'Installment', 'value': _money(scorecard.get('installment'))},
            {'label': 'Payment burden', 'value': _pct(scorecard.get('payment_burden_pct'))},
            {'label': 'Employer', 'value': (cons.employer_name if cons else '') or '—'},
        ]
    elif family == FAMILY_PROJECT:
        desk_url_name = 'project_file'
        title = 'Project appraisal pack'
        rows = [
            {'label': 'NPV', 'value': _money(scorecard.get('npv'))},
            {'label': 'IRR', 'value': _pct(scorecard.get('irr_pct'))},
            {'label': 'DSCR', 'value': _num(scorecard.get('dscr'))},
        ]
    elif family == FAMILY_WHOLESALE:
        desk_url_name = 'wholesale_file'
        title = 'Wholesale / PFI appraisal pack'
        rows = [
            {'label': 'Institution', 'value': str(scorecard.get('institution_name') or '—')},
            {'label': 'PAR>90', 'value': f"{_pct(scorecard.get('par90_pct'))} (cap {_pct(scorecard.get('par90_cap'))})"},
            {'label': 'NPL', 'value': _pct(scorecard.get('npl_pct'))},
            {'label': 'Facility', 'value': _money(scorecard.get('facility_amount'))},
        ]
    elif family in (FAMILY_LEASE, FAMILY_IFB_IJARAH):
        desk_url_name = 'lease_file'
        is_ij = bool(scorecard.get('is_ijarah') or family == FAMILY_IFB_IJARAH)
        title = 'Ijarah appraisal pack' if is_ij else 'Lease appraisal pack'
        rows = [
            {'label': 'Asset', 'value': str(scorecard.get('asset_description') or '—')},
            {'label': 'Asset price', 'value': _money(scorecard.get('asset_price'))},
            {'label': 'Contribution', 'value': _pct(scorecard.get('contribution_pct'))},
            {'label': 'Ancillary', 'value': _pct(scorecard.get('ancillary_pct'))},
            {'label': 'Financed', 'value': _money(scorecard.get('financed_amount'))},
        ]
        if is_ij and scorecard.get('monthly_rent') is not None:
            rows.append({'label': 'Monthly rent', 'value': _money(scorecard.get('monthly_rent'))})
    elif family == FAMILY_IFB_MURABAHA:
        desk_url_name = 'murabaha_file'
        title = 'Murabaha appraisal pack'
        rows = [
            {'label': 'Goods', 'value': str(scorecard.get('goods_description') or '—')},
            {'label': 'Cost', 'value': _money(scorecard.get('cost_price'))},
            {'label': 'Markup', 'value': _pct(scorecard.get('markup_pct'))},
            {'label': 'Selling price', 'value': _money(scorecard.get('selling_price'))},
            {'label': 'Tenor', 'value': f"{scorecard.get('tenor_months') or '—'} months"},
        ]
    elif family == FAMILY_IDEA_EQUITY:
        desk_url_name = 'idea_file'
        title = 'Idea / quasi-equity appraisal pack'
        rows = [
            {'label': 'Venture', 'value': str(scorecard.get('venture_name') or '—')},
            {'label': 'Age', 'value': f"{scorecard.get('age_years') if scorecard.get('age_years') is not None else '—'}y (max {scorecard.get('max_age_years') or 5}y)"},
            {'label': 'DBE share', 'value': _pct(scorecard.get('proposed_dbe_share_pct'))},
            {'label': 'Ethiopia', 'value': 'Yes' if scorecard.get('implements_in_ethiopia') else 'No'},
            {'label': 'Sector', 'value': str(scorecard.get('sector') or '—')},
        ]
    else:
        return None

    pillars = []
    for p in (scorecard.get('pillars') or []):
        pillars.append({
            'label': p.get('label') or p.get('key') or '',
            'earned': p.get('earned'),
            'max': p.get('max'),
            'note': p.get('note') or p.get('remark') or '',
        })

    return {
        'family': family,
        'title': title,
        'desk_url_name': desk_url_name,
        'modality': evidence.get('modality') or scorecard.get('modality') or family,
        'scorecard': scorecard,
        'pillars': pillars,
        'rows': rows,
        'recommendation': appraisal.get_recommendation_display() if appraisal and appraisal.recommendation else '—',
        'amount_approved': getattr(appraisal, 'amount_approved', None) if appraisal else None,
        'term_approved_months': getattr(appraisal, 'term_approved_months', None) if appraisal else None,
        'rate_approved': getattr(appraisal, 'rate_approved', None) if appraisal else None,
        'strengths': (appraisal.strengths or '').strip() if appraisal else '',
        'weaknesses': (appraisal.weaknesses or '').strip() if appraisal else '',
        'comment': (appraisal.recommendation_comment or '').strip() if appraisal else '',
        'algorithm': scorecard.get('algorithm') or '',
        'band_label': scorecard.get('band_label') or '',
        'total': scorecard.get('total'),
    }


def default_crm_send_note(loan_request) -> str:
    """Officer note prefilled when sending the pack to CRM."""
    section = build_modality_pack_section(loan_request)
    if section is None:
        return (
            'MSME/corporate appraisal pack ready for CRM comment. '
            'Please review Sheets 1–6 decision and documents.'
        )
    bits = [f"{section['title']} ready for CRM comment."]
    if section.get('total') is not None:
        bits.append(f"Score {section['total']}/100 ({section.get('band_label') or '—'}).")
    if section.get('recommendation') and section['recommendation'] != '—':
        bits.append(f"Officer: {section['recommendation']}.")
    for row in (section.get('rows') or [])[:4]:
        if row.get('value') and row['value'] != '—':
            bits.append(f"{row['label']}: {row['value']}.")
    if section.get('comment'):
        bits.append(section['comment'][:180])
    return ' '.join(bits)


def default_crm_clear_note(loan_request) -> str:
    section = build_modality_pack_section(loan_request)
    if section is None:
        return 'Pack consistent with KYC and banking history. Cleared for committee.'
    return (
        f"{section['title']} reviewed — product metrics and officer recommendation "
        f"are consistent with KYC. Cleared for committee."
    )


def _pct(value) -> str:
    if value is None or value == '':
        return '—'
    return f'{value}%'


def _money(value) -> str:
    if value is None or value == '':
        return '—'
    try:
        return f'{float(value):,.2f}'
    except (TypeError, ValueError):
        return str(value)


def _num(value) -> str:
    if value is None or value == '':
        return '—'
    return str(value)
