"""Appraisal intelligence for product desks (not the MSME/corporate 7-sheet wizard)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.engines import get_engine
from loans.product_family import FAMILY_GENERAL, family_label, resolve_product_family


_SKIP_HIGHLIGHT_KEYS = {
    'family', 'family_label', 'blockers', 'title', 'supplier', 'serial',
    'institution', 'venture', 'employer',
}


def build_product_intel(loan_request) -> Optional[Dict[str, Any]]:
    """Live desk card: product metrics, KYC, documents, CRM, engine gates."""
    engine = get_engine(loan_request)
    if engine.requires_appraisal_sheets():
        return None

    family = resolve_product_family(loan_request)
    brief = engine.assist_brief() or {}
    summary = engine.file_summary() or {}

    from loans.kyc_desk import kyc_committee_blockers, kyc_is_complete
    from loans.crm_cycle import crm_committee_blockers, crm_is_cleared
    from loans.services.document_auth import (
        document_committee_blockers,
        document_identity_findings,
        loan_documents_committee_readiness,
    )

    blockers: List[str] = []
    blockers.extend(kyc_committee_blockers(loan_request))
    blockers.extend(crm_committee_blockers(loan_request))
    blockers.extend(document_committee_blockers(loan_request))
    blockers.extend(list(engine.committee_blockers() or [])[:8])

    docs = loan_documents_committee_readiness(loan_request)
    identity = document_identity_findings(loan_request)
    identity_failed = [row for row in identity if not row.get('passed')]

    highlights = _highlights_from_brief(brief)
    from loans.analysis_assist import officer_checklist_for_mode
    from loans.appraisal_mode import mode_label, resolve_appraisal_mode

    mode = resolve_appraisal_mode(loan_request)
    actions = list(officer_checklist_for_mode(mode)[:4])
    if blockers:
        actions = blockers[:4] + actions[:2]
        decision = {
            'code': 'blocked',
            'label': 'Not ready for committee',
            'rationale': blockers[0],
        }
    elif not highlights:
        decision = {
            'code': 'review',
            'label': 'Complete the product desk',
            'rationale': (
                'Enter the product numbers so appraisal can see this file — '
                'NPV/DSCR, DTI/LTV, PAR, cost-plus, or cap table as this family requires.'
            ),
        }
    else:
        decision = {
            'code': 'ready',
            'label': 'Desk pack in shape',
            'rationale': (
                'Product gates, KYC, and documents are clear. '
                'Officer / committee recommendation is still required.'
            ),
        }

    sanctions = _latest_sanctions(loan_request)

    return {
        'family': family,
        'family_label': family_label(family),
        'mode': mode,
        'mode_label': mode_label(mode),
        'decision': decision,
        'highlights': highlights,
        'blockers': blockers[:10],
        'positives': _positives(brief, highlights, docs, kyc_is_complete(loan_request)),
        'risks': _risks(blockers, identity_failed, sanctions),
        'required_actions': actions[:6],
        'kyc': {
            'complete': kyc_is_complete(loan_request),
            'applies': family != FAMILY_GENERAL,
        },
        'documents': {
            'ready': bool(docs.get('ready')),
            'checklist_count': docs.get('checklist_count') or 0,
            'missing': (docs.get('missing_required') or [])[:6],
        },
        'crm_cleared': crm_is_cleared(loan_request),
        'identity_failed': identity_failed[:4],
        'sanctions': sanctions,
        'brief': brief,
        'overlay_keys': sorted(k for k in summary.keys() if k not in ('profile', 'fund')),
        'disclaimer': (
            'Assistive only — not an auto-approve. Officer / committee decision is authoritative.'
        ),
    }


def compact_product_desk(loan_request) -> Dict[str, Any]:
    intel = build_product_intel(loan_request)
    if not intel:
        return {}
    return {
        'family': intel['family'],
        'band': intel['decision']['code'],
        'blockers': intel['blockers'][:8],
        'highlights': intel['highlights'],
        'kyc_complete': intel['kyc']['complete'],
        'docs_ready': intel['documents']['ready'],
        'crm_cleared': intel['crm_cleared'],
    }


def intel_context(loan_request) -> Dict[str, Any]:
    return {'desk_intel': build_product_intel(loan_request)}


def _highlights_from_brief(brief: Dict[str, Any]) -> List[Dict[str, str]]:
    labels = {
        'npv': 'NPV',
        'irr_pct': 'IRR %',
        'dti_pct': 'DTI %',
        'ltv_pct': 'LTV %',
        'par90': 'PAR 90',
        'cost': 'Cost',
        'markup_pct': 'Markup %',
        'selling_price': 'Selling price',
        'monthly_rent': 'Monthly rent',
        'dbe_share': 'DBE share %',
        'cap_dbe': 'Cap table DBE',
        'asset_price': 'Asset price',
        'facility': 'Facility',
        'sources': 'Sources',
        'uses': 'Uses',
        'remaining': 'Fund remaining',
        'envelope': 'Envelope',
        'committed': 'Committed',
        'sharia': 'Sharia',
        'balanced': 'Sources/uses balanced',
        'fund_code': 'Fund',
    }
    out = []
    for key, label in labels.items():
        if key not in brief:
            continue
        value = brief.get(key)
        if value in (None, '', False):
            continue
        if value is True:
            value = 'Yes'
        out.append({'label': label, 'value': str(value)})
    for key, value in brief.items():
        if key in labels or key in _SKIP_HIGHLIGHT_KEYS or str(key).startswith('is_'):
            continue
        if value in (None, '', False, [], {}):
            continue
        if isinstance(value, (list, dict)):
            continue
        out.append({'label': key.replace('_', ' ').title(), 'value': str(value)})
    return out[:8]


def _positives(brief, highlights, docs, kyc_ok) -> List[str]:
    rows = []
    if kyc_ok:
        rows.append('KYC packs cleared (CRM, Engineering, Legal).')
    if docs.get('ready') and docs.get('checklist_count'):
        rows.append('Required documents authenticated.')
    if brief.get('balanced'):
        rows.append('Project sources and uses are balanced.')
    for h in highlights[:3]:
        rows.append(f"{h['label']}: {h['value']}")
    return rows[:6]


def _risks(blockers, identity_failed, sanctions) -> List[str]:
    rows = list(blockers[:6])
    for row in identity_failed[:2]:
        rows.append(f"Identity mismatch — {row.get('document')}: {row.get('summary') or 'failed OCR match'}")
    if sanctions.get('hit'):
        rows.append('Sanctions / PEP screen has a hit — compliance case must clear.')
    return rows[:8]


def _latest_sanctions(loan_request) -> Dict[str, Any]:
    try:
        from loans.models import SanctionsScreeningResult
        latest = (
            SanctionsScreeningResult.objects.filter(loan_request=loan_request)
            .order_by('-id')
            .first()
        )
        if not latest:
            return {'ran': False, 'hit': False}
        return {
            'ran': True,
            'hit': bool(latest.hit),
            'score': int(latest.score or 0),
        }
    except Exception:
        return {'ran': False, 'hit': False}
