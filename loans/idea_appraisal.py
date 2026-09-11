"""Idea / quasi-equity appraisal — start-up scorecard + officer recommendation.

Not MSME Sheets 1–7 and not an installment loan. Cap table comes after approval.
Persists the decision on LoanAppraisal for committee routing.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from django.utils import timezone

from loans.appraisal_vision import (
    SCORE_BAND_ACCEPTABLE,
    SCORE_BAND_STRONG,
    SCORE_BAND_UNACCEPTABLE,
    SCORE_BAND_WEAK,
)
from loans.idea_overlay import (
    MAX_STARTUP_AGE_YEARS,
    get_idea_profile,
    is_idea_file,
    startup_age_years,
)

ZERO = Decimal('0')
ALGORITHM = 'IDEA_SCORE_V1'
DEFAULT_HORIZON_MONTHS = 60


def _d(value) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(str(value))


def _q(value, places='0.01') -> Decimal:
    return _d(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _band_for_total(total: Decimal) -> str:
    if total >= Decimal('80'):
        return SCORE_BAND_STRONG
    if total >= Decimal('60'):
        return SCORE_BAND_ACCEPTABLE
    if total >= Decimal('40'):
        return SCORE_BAND_WEAK
    return SCORE_BAND_UNACCEPTABLE


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def scorecard_for_storage(card: Dict[str, Any]) -> Dict[str, Any]:
    return _jsonable(card)


def build_idea_scorecard(loan_request, profile=None) -> Dict[str, Any]:
    """Explainable 0–100 score from age, Ethiopia/credentials, DBE share, pack."""
    profile = profile or get_idea_profile(loan_request)
    pillars: List[Dict[str, Any]] = []
    total = ZERO
    age = startup_age_years(profile)

    # --- Start-up age / eligibility (max 30) ---
    if age is None:
        age_pts = ZERO
        age_note = 'Founded year not entered'
    elif age > MAX_STARTUP_AGE_YEARS:
        age_pts = ZERO
        age_note = f'{age} years old — over {MAX_STARTUP_AGE_YEARS}-year gate'
    elif age <= 1:
        age_pts = Decimal('30')
        age_note = f'{age} year(s) — early start-up'
    elif age <= 3:
        age_pts = Decimal('24')
        age_note = f'{age} years — within band'
    else:
        age_pts = Decimal('16')
        age_note = f'{age} years — near age gate'
    pillars.append({
        'key': 'age', 'label': 'Start-up age',
        'max': 30, 'earned': age_pts, 'note': age_note,
    })
    total += age_pts

    # --- Ethiopia + credentials (max 25) ---
    cred_pts = ZERO
    cred_bits = []
    if profile and profile.implements_in_ethiopia:
        cred_pts += Decimal('10')
        cred_bits.append('Ethiopia')
    if profile and profile.has_ip:
        cred_pts += Decimal('5')
        cred_bits.append('IP')
    if profile and profile.has_mols_training:
        cred_pts += Decimal('5')
        cred_bits.append('MoLS')
    if profile and profile.has_startup_label:
        cred_pts += Decimal('5')
        cred_bits.append('start-up label')
    cred_note = ('On file: ' + ', '.join(cred_bits)) if cred_bits else 'Ethiopia / IP / MoLS / label open'
    pillars.append({
        'key': 'credentials', 'label': 'Ethiopia & credentials',
        'max': 25, 'earned': cred_pts, 'note': cred_note,
    })
    total += cred_pts

    # --- DBE share structure (max 25) ---
    share = getattr(profile, 'proposed_dbe_share_pct', None) if profile else None
    if share is None or share <= 0:
        share_pts = ZERO
        share_note = 'Proposed DBE share not entered'
    elif share > Decimal('49'):
        share_pts = Decimal('12')
        share_note = f'DBE share {share}% — high; confirm governance'
    elif share >= Decimal('10'):
        share_pts = Decimal('25')
        share_note = f'DBE share {share}%'
    else:
        share_pts = Decimal('18')
        share_note = f'DBE share {share}% — modest stake'
    pillars.append({
        'key': 'share', 'label': 'Proposed DBE share',
        'max': 25, 'earned': share_pts, 'note': share_note,
    })
    total += share_pts

    # --- Pack completeness (max 20) ---
    pack_pts = ZERO
    pack_bits = []
    if profile and (profile.venture_name or '').strip():
        pack_pts += Decimal('10')
        pack_bits.append('venture')
    if profile and (profile.sector or '').strip():
        pack_pts += Decimal('5')
        pack_bits.append('sector')
    if profile and (profile.notes or '').strip():
        pack_pts += Decimal('5')
        pack_bits.append('notes')
    elif profile and share and share > 0 and (profile.venture_name or '').strip():
        pack_pts += Decimal('5')
        pack_bits.append('core gates set')
    pack_note = ('Set: ' + ', '.join(pack_bits)) if pack_bits else 'Venture name / sector open'
    pillars.append({
        'key': 'pack', 'label': 'Idea pack',
        'max': 20, 'earned': pack_pts, 'note': pack_note,
    })
    total += pack_pts

    total = _q(total)
    band = _band_for_total(total)
    band_label = {
        SCORE_BAND_STRONG: 'Strong',
        SCORE_BAND_ACCEPTABLE: 'Acceptable',
        SCORE_BAND_WEAK: 'Weak',
        SCORE_BAND_UNACCEPTABLE: 'Unacceptable',
    }.get(band, band)

    return {
        'algorithm': ALGORITHM,
        'modality': 'idea',
        'total': total,
        'band': band,
        'band_label': band_label,
        'pillars': pillars,
        'age_years': age,
        'max_age_years': MAX_STARTUP_AGE_YEARS,
        'proposed_dbe_share_pct': share,
        'venture_name': (profile.venture_name if profile else '') or '',
        'sector': (profile.sector if profile else '') or '',
        'implements_in_ethiopia': bool(profile and profile.implements_in_ethiopia),
    }


def sync_idea_decision_to_appraisal(
    loan_request,
    profile,
    user,
    *,
    recommendation: str,
    amount_approved,
    rate_approved,
    term_approved_months=None,
    recommendation_comment: str = '',
    strengths: str = '',
    weaknesses: str = '',
):
    """Write officer idea decision onto LoanAppraisal and persist scorecard.

    rate_approved stores recommended DBE share % (not interest).
    term_approved_months is the expected investment horizon.
    """
    from loans.models import LoanAppraisal

    appraisal, _ = LoanAppraisal.objects.get_or_create(
        loan_request=loan_request,
        defaults={'created_by': user},
    )
    term = term_approved_months or DEFAULT_HORIZON_MONTHS
    amount = amount_approved
    if amount is None:
        amount = getattr(loan_request, 'amount_requested', None)
    rate = rate_approved
    if rate is None:
        rate = getattr(profile, 'proposed_dbe_share_pct', None)

    appraisal.recommendation = recommendation or None
    appraisal.amount_approved = amount
    appraisal.term_approved_months = term
    appraisal.rate_approved = rate
    appraisal.recommendation_comment = (recommendation_comment or '').strip() or None
    appraisal.strengths = (strengths or '').strip() or None
    appraisal.weaknesses = (weaknesses or '').strip() or None
    if not appraisal.created_by_id:
        appraisal.created_by = user

    card = build_idea_scorecard(loan_request, profile)
    appraisal.credit_score_total = card['total']
    appraisal.credit_score_band = card['band']
    appraisal.scorecard_detail = scorecard_for_storage(card)
    appraisal.save()
    if recommendation and not getattr(loan_request, 'appraisal_completed_at', None):
        loan_request.appraisal_completed_at = timezone.now()
        loan_request.save(update_fields=['appraisal_completed_at'])
    return appraisal, card


def idea_appraisal_blockers(loan_request) -> List[str]:
    if not is_idea_file(loan_request):
        return []
    from loans.models import LoanAppraisal

    blockers = []
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    if appraisal is None or not appraisal.recommendation:
        blockers.append(
            'Complete idea appraisal: record Approve / Decline / Escalate on the idea desk.'
        )
    if appraisal is None or not appraisal.amount_approved or appraisal.amount_approved <= 0:
        blockers.append('Enter the recommended investment amount on the idea desk.')
    if appraisal is None or appraisal.rate_approved is None or appraisal.rate_approved <= 0:
        blockers.append(
            'Enter the recommended DBE share % on the idea desk (stored as rate — not interest).'
        )
    if appraisal is None or not appraisal.term_approved_months:
        blockers.append('Enter the expected investment horizon (months) on the idea desk.')
    return blockers
