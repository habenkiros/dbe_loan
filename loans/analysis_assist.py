"""Read-only credit analysis assist — insights from scorecard, gates, bureau, mode."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from .appraisal_mode import is_corporate, mode_label, resolve_appraisal_mode
from .appraisal_scorecard import (
    _corporate_has_verified_audit_doc,
    build_credit_scorecard,
    evaluate_analysis_gates,
)


def _d(v) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def build_analysis_assist(appraisal, basic_info=None) -> Dict[str, Any]:
    """
    Officer-facing assist panel (not auto-approve).
    Returns severity-ranked insights + blocks/warnings + score summary.
    """
    loan = appraisal.loan_request
    mode = resolve_appraisal_mode(loan, appraisal)
    card = build_credit_scorecard(appraisal)
    blocks, warnings = evaluate_analysis_gates(appraisal, basic_info)
    insights: List[Dict[str, str]] = []

    # Pillar weakness
    for p in card.get('pillars') or []:
        max_pts = float(p.get('max') or 0) or 1
        earned = float(p.get('earned') or 0)
        if earned / max_pts < 0.5:
            insights.append({
                'severity': 'high',
                'title': f'Weak {p.get("label") or p.get("key")} pillar',
                'detail': f'{earned:.0f}/{max_pts:.0f} — {p.get("remark") or "review this sheet"}',
                'sheet': _pillar_sheet(p.get('key')),
            })
        elif earned / max_pts < 0.7:
            insights.append({
                'severity': 'medium',
                'title': f'Thin {p.get("label") or p.get("key")} pillar',
                'detail': f'{earned:.0f}/{max_pts:.0f} — {p.get("remark") or ""}',
                'sheet': _pillar_sheet(p.get('key')),
            })

    # Bureau / NBE
    if appraisal.nbe_credit_report_obtained is False or appraisal.nbe_credit_report_obtained is None:
        insights.append({
            'severity': 'medium',
            'title': 'NBE / credit report not confirmed',
            'detail': 'Mark NBE obtained on Sheet 2 and enter bureau fields when available.',
            'sheet': 2,
        })
    if appraisal.bureau_thin_file:
        insights.append({
            'severity': 'medium',
            'title': 'Thin bureau file',
            'detail': 'Limited credit history — weight qualitative and cashflow more carefully.',
            'sheet': 2,
        })
    if appraisal.bureau_defaults_ever:
        insights.append({
            'severity': 'high',
            'title': 'Bureau defaults indicated',
            'detail': 'Prior defaults — ensure mitigation / committee notes.',
            'sheet': 2,
        })
    # Only flag weak/fair/poor bureau — good/excellent is not an action item.
    if appraisal.bureau_score_band in (
        getattr(appraisal, 'BUREAU_BAND_FAIR', 'fair'),
        getattr(appraisal, 'BUREAU_BAND_POOR', 'poor'),
        getattr(appraisal, 'BUREAU_BAND_THIN', 'thin'),
    ):
        insights.append({
            'severity': 'medium' if appraisal.bureau_score_band != 'poor' else 'high',
            'title': f'Bureau band: {appraisal.get_bureau_score_band_display()}',
            'detail': f'Score {appraisal.bureau_score}' if appraisal.bureau_score is not None else 'Review bureau on Sheet 2.',
            'sheet': 2,
        })
    elif appraisal.nbe_credit_report_obtained and appraisal.bureau_score is None:
        insights.append({
            'severity': 'medium',
            'title': 'Bureau score missing',
            'detail': 'NBE marked obtained but bureau score/band not entered on Sheet 2.',
            'sheet': 2,
        })

    # Capacity vs ask
    cap = _d(getattr(appraisal, 'max_loan_capacity', None))
    ask = _d(getattr(loan, 'amount_requested', None))
    if cap is not None and ask is not None and ask > 0 and cap < ask:
        insights.append({
            'severity': 'high',
            'title': 'Ask exceeds cashflow capacity',
            'detail': f'Max capacity {cap} vs requested {ask}.',
            'sheet': 3,
        })

    # Corporate-specific
    if is_corporate(loan, appraisal):
        if basic_info and not (basic_info.legal_registration_number or '').strip():
            insights.append({
                'severity': 'high',
                'title': 'Corporate CR / registration missing',
                'detail': 'Enter legal registration number on Sheet 1.',
                'sheet': 1,
            })
        if not _d(getattr(appraisal, 'corp_annual_revenue', None)):
            insights.append({
                'severity': 'medium',
                'title': 'Corporate revenue not entered',
                'detail': 'Add annual revenue on Sheet 3 for statement-based analysis.',
                'sheet': 3,
            })
        if not _corporate_has_verified_audit_doc(loan):
            insights.append({
                'severity': 'medium',
                'title': 'No verified audited-accounts document',
                'detail': 'Upload and verify audited financials (or similarly named doc type).',
                'sheet': 1,
            })

    # Score band
    band = card.get('band_label') or card.get('band') or ''
    total = card.get('total')
    if total is not None and float(total) < 60:
        insights.append({
            'severity': 'high',
            'title': f'Composite score weak ({total} — {band})',
            'detail': 'Review pillar contributions before recommending approval.',
            'sheet': 6,
        })

    severity_order = {'high': 0, 'medium': 1, 'info': 2}
    insights.sort(key=lambda x: severity_order.get(x.get('severity'), 9))

    return {
        'appraisal_mode': mode,
        'mode_label': mode_label(mode),
        'score_total': total,
        'score_band': band,
        'blocks': blocks,
        'warnings': warnings,
        'insights': insights[:12],
        'pillar_count': len(card.get('pillars') or []),
    }


def _pillar_sheet(key: Optional[str]) -> int:
    return {
        'qualitative': 2,
        'financial': 3,
        'banking': 2,
        'es': 4,
        'collateral': 5,
    }.get(key or '', 6)


def officer_checklist_for_mode(mode: str) -> List[str]:
    """Short mode-specific officer checklist (ops polish)."""
    from loans.appraisal_mode import (
        MODE_CONSUMER, MODE_CORPORATE, MODE_IDEA, MODE_IJARAH, MODE_LEASE,
        MODE_MURABAHA, MODE_PROJECT, MODE_WHOLESALE,
    )

    common_sheets = [
        'Confirm identity / TIN (banking or documents) matches Sheet 1',
        'Complete Sheets 1–6; resolve hard blocks before finish',
        'On Sheet 6: recommend approve/escalate, then finish and submit to committee',
        'Sheet 7 repayment schedule is optional (for the pack / disbursement)',
    ]
    if mode == MODE_CORPORATE:
        return [
            'Confirm legal entity name + CR / registration number',
            'Enter directors / UBO summary',
            'Complete governance factors (Sheet 2) to ≥75%',
            'Enter annual revenue / operating profit and BS ratios (Sheet 3)',
            'Verify audited accounts (or equivalent) document when available',
        ] + common_sheets
    if mode == MODE_PROJECT:
        return [
            'Clear CRM / Engineering / Legal KYC packs with the checklist',
            'Balance sources and uses; record NPV / IRR / DSCR on the project desk',
            'Clear civil / mechanical / electrical plant desks',
            'Stamp Approve/Decline with recommended debt, term, and rate',
        ]
    if mode == MODE_LEASE:
        return [
            'Clear KYC packs and authenticate supplier / asset documents',
            'Complete the lease asset register (supplier, serial, price)',
            'Confirm lessee contribution (≥20%) and insurance co-beneficiary',
            'Record Approve/Decline, financed amount, rate, and term',
            'CRM comments must clear before committee',
        ]
    if mode == MODE_IJARAH:
        return [
            'Clear KYC packs including Sharia questionnaire',
            'Complete the Ijarah asset register and rent schedule',
            'Record Approve/Decline, financed amount, term (rate 0 if rental-only)',
            'Record a Sharia trail before release',
            'CRM comments must clear before committee',
        ]
    if mode == MODE_MURABAHA:
        return [
            'Clear KYC packs including Sharia questionnaire',
            'Enter cost, markup, and computed selling price (not Sheet 7)',
            'Authenticate goods specification and supplier offer',
            'Record Approve/Decline, selling amount, markup %, and tenor',
            'Record a Sharia trail before confirm / release',
        ]
    if mode == MODE_WHOLESALE:
        return [
            'Treat this as a PFI institution file, not an SME LOS',
            'Clear KYC packs; authenticate license, AFS, ESMS, PAR',
            'Enter PAR 90 / NPL and facility amount on the PFI desk',
            'Record Approve/Decline, facility amount, DBE→PFI rate, and tenor',
            'CRM comments must clear before committee',
        ]
    if mode == MODE_IDEA:
        return [
            'Clear KYC packs; authenticate start-up / IP / cap-table evidence',
            'Complete the idea desk (venture, proposed DBE share)',
            'Record Approve/Decline, investment amount, DBE share %, and horizon',
            'Cap table after approval — not an installment schedule',
            'CRM comments must clear before committee',
        ]
    if mode == MODE_CONSUMER:
        return [
            'Clear KYC packs; authenticate ID, salary, employer letter',
            'Enter employer, salary, DTI and LTV on the consumer desk',
            'Record recommended amount, term, rate, and Approve/Decline',
            'DTI cap 50%; housing LTV 80% / vehicle LTV 70%; check installment vs pay',
        ]
    return [
        'Confirm personal + business details and purpose lines',
        'Complete MSME character factors (Sheet 2) to ≥75%',
        'Enter cashflow / DSCR and stress test (Sheet 3)',
        'Confirm collateral coverage (Sheet 5)',
    ] + common_sheets
