"""Application-level AI decision card — reuses scorecard + analysis assist."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.analysis_assist import build_analysis_assist, officer_checklist_for_mode
from loans.appraisal_mode import mode_label, resolve_appraisal_mode
from loans.appraisal_scorecard import build_credit_scorecard


def _decision_from_band(band: Optional[str], has_blocks: bool) -> Dict[str, str]:
    if has_blocks:
        return {
            'code': 'manual_review',
            'label': 'Manual review',
            'rationale': 'Hard analysis gates are blocking finish/submit — resolve Sheet blocks first.',
        }
    band = (band or '').lower()
    if band == 'strong':
        return {
            'code': 'approve',
            'label': 'Approve',
            'rationale': 'Strong score band — still verify conditions and officer judgment.',
        }
    if band == 'acceptable':
        return {
            'code': 'approve_with_conditions',
            'label': 'Approve with conditions',
            'rationale': 'Acceptable score — confirm mitigation and any advisory warnings.',
        }
    if band == 'weak':
        return {
            'code': 'manual_review',
            'label': 'Manual review',
            'rationale': 'Weak score band — escalate or strengthen collateral / cashflow evidence.',
        }
    if band == 'unacceptable':
        return {
            'code': 'reject',
            'label': 'Reject / escalate',
            'rationale': 'Unacceptable score band — do not auto-approve; document decline or return.',
        }
    return {
        'code': 'manual_review',
        'label': 'Manual review',
        'rationale': 'Scorecard incomplete — finish Sheets 1–6 before a confident call.',
    }


def build_application_decision(loan_request, appraisal=None, basic_info=None) -> Optional[Dict[str, Any]]:
    """
    Explainable decision card payload for Sheet 6 / loan detail / CI workspaces.
    Not an auto-approve — officer recommendation remains authoritative.
    """
    appraisal = appraisal or getattr(loan_request, 'appraisal', None)
    if appraisal is None:
        try:
            appraisal = loan_request.appraisal
        except Exception:
            return None
    if appraisal is None:
        return None

    if basic_info is None:
        basic_info = getattr(loan_request, 'basic_info', None)

    card = build_credit_scorecard(appraisal)
    assist = build_analysis_assist(appraisal, basic_info)
    mode = resolve_appraisal_mode(loan_request, appraisal)
    blocks = assist.get('blocks') or []
    warnings = assist.get('warnings') or []
    decision = _decision_from_band(card.get('band'), bool(blocks))

    positives: List[str] = []
    risks: List[str] = []
    for p in card.get('pillars') or []:
        max_pts = float(p.get('max') or 0) or 1
        earned = float(p.get('earned') or 0)
        label = p.get('label') or p.get('key') or 'Pillar'
        if earned / max_pts >= 0.7:
            positives.append(f'{label}: {earned:.0f}/{max_pts:.0f}')
        elif earned / max_pts < 0.5:
            risks.append(f'{label}: {earned:.0f}/{max_pts:.0f} — {p.get("remark") or "weak"}')

    for tip in (assist.get('insights') or [])[:6]:
        sev = tip.get('severity') or 'info'
        line = f'{tip.get("title")}: {tip.get("detail")}'
        if sev == 'high':
            risks.append(line)
        elif sev == 'info' and len(positives) < 6:
            positives.append(line)

    actions: List[str] = []
    if blocks:
        actions.extend(blocks[:4])
    for tip in (assist.get('insights') or [])[:4]:
        if tip.get('sheet'):
            actions.append(f'Sheet {tip["sheet"]}: {tip.get("title")}')
    if not actions:
        actions = officer_checklist_for_mode(mode)[:3]

    total = card.get('total')
    return {
        'loan_id': loan_request.id,
        'loan_request_id': loan_request.loan_request_id,
        'applicant_name': loan_request.applicant_name,
        'mode': mode,
        'mode_label': mode_label(mode),
        'score_total': total,
        'score_1000': int(float(total) * 10) if total is not None else None,
        'band': card.get('band'),
        'band_label': card.get('band_label'),
        'pillars': card.get('pillars') or [],
        'decision': decision,
        'positives': positives[:6],
        'risks': risks[:8],
        'required_actions': actions[:6],
        'blocks': blocks,
        'warnings': warnings,
        'insights': assist.get('insights') or [],
        'officer_recommendation': getattr(appraisal, 'recommendation', None) or '',
        'amount_approved': getattr(appraisal, 'amount_approved', None),
        'disclaimer': 'Assistive only — not an auto-approve. Officer / committee decision is authoritative.',
    }
