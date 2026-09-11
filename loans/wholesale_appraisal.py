"""Wholesale / PFI appraisal — institution scorecard + facility recommendation.

Not MSME Sheets 1–7. Persists the decision on LoanAppraisal for committee routing.
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
from loans.wholesale_overlay import (
    DEFAULT_PAR90_CAP,
    get_pfi_profile,
    is_wholesale_file,
)

ZERO = Decimal('0')
ALGORITHM = 'WHOLESALE_SCORE_V1'
NPL_SOFT_CAP = Decimal('8')


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


def build_wholesale_scorecard(loan_request, profile=None) -> Dict[str, Any]:
    """Explainable 0–100 PFI score from PAR, NPL, controls, and facility structure."""
    profile = profile or get_pfi_profile(loan_request)
    pillars: List[Dict[str, Any]] = []
    total = ZERO

    # --- PAR>90 (max 30) ---
    par90 = getattr(profile, 'par90_pct', None) if profile else None
    if par90 is None:
        par_pts = ZERO
        par_note = 'PAR>90 not entered'
    elif par90 > DEFAULT_PAR90_CAP:
        par_pts = ZERO
        par_note = f'PAR>90 {par90}% over hard cap {DEFAULT_PAR90_CAP}%'
    else:
        # 0% → 30, at cap → 12
        span = DEFAULT_PAR90_CAP if DEFAULT_PAR90_CAP > 0 else Decimal('1')
        par_pts = _q(Decimal('30') * (Decimal('1') - (par90 / span) * Decimal('0.6')))
        par_pts = max(Decimal('8'), min(Decimal('30'), par_pts))
        par_note = f'PAR>90 {par90}% (cap {DEFAULT_PAR90_CAP}%)'
    pillars.append({'key': 'par90', 'label': 'Portfolio at risk >90', 'max': 30, 'earned': par_pts, 'note': par_note})
    total += par_pts

    # --- NPL (max 20) ---
    npl = getattr(profile, 'npl_pct', None) if profile else None
    if npl is None:
        npl_pts = ZERO
        npl_note = 'NPL % not entered'
    elif npl > NPL_SOFT_CAP * Decimal('1.5'):
        npl_pts = ZERO
        npl_note = f'NPL {npl}% elevated'
    elif npl > NPL_SOFT_CAP:
        npl_pts = _q(Decimal('10') * (Decimal('1') - (npl - NPL_SOFT_CAP) / NPL_SOFT_CAP))
        npl_pts = max(ZERO, npl_pts)
        npl_note = f'NPL {npl}% above soft {NPL_SOFT_CAP}%'
    else:
        npl_pts = _q(Decimal('20') * (Decimal('1') - npl / (NPL_SOFT_CAP * Decimal('2'))))
        npl_pts = max(Decimal('10'), min(Decimal('20'), npl_pts))
        npl_note = f'NPL {npl}%'
    pillars.append({'key': 'npl', 'label': 'Non-performing loans', 'max': 20, 'earned': npl_pts, 'note': npl_note})
    total += npl_pts

    # --- Controls / pack (max 25) ---
    ctrl_pts = ZERO
    bits = []
    if profile and (profile.license_number or '').strip():
        ctrl_pts += Decimal('5')
        bits.append('license')
    if profile and profile.has_adequate_mis:
        ctrl_pts += Decimal('5')
        bits.append('MIS')
    if profile and profile.has_esms:
        ctrl_pts += Decimal('5')
        bits.append('ESMS')
    if profile and profile.has_governance:
        ctrl_pts += Decimal('5')
        bits.append('governance')
    if profile and profile.credit_policy_on_file and profile.on_lending_policy_on_file:
        ctrl_pts += Decimal('5')
        bits.append('policies')
    ctrl_note = ('On file: ' + ', '.join(bits)) if bits else 'License / MIS / ESMS / policies still open'
    pillars.append({
        'key': 'controls', 'label': 'Institution controls',
        'max': 25, 'earned': ctrl_pts, 'note': ctrl_note,
    })
    total += ctrl_pts

    # --- Facility structure (max 25) ---
    fac_pts = ZERO
    fac_bits = []
    if profile and profile.facility_amount and profile.facility_amount > 0:
        fac_pts += Decimal('10')
        fac_bits.append('facility amount')
    if profile and profile.tenor_months:
        fac_pts += Decimal('5')
        fac_bits.append('tenor')
    if profile and profile.end_user_rate_ceiling_pct is not None:
        fac_pts += Decimal('5')
        fac_bits.append('end-user ceiling')
    if profile and profile.capital and profile.capital > 0:
        fac_pts += Decimal('5')
        fac_bits.append('capital')
    fac_note = ('Set: ' + ', '.join(fac_bits)) if fac_bits else 'Facility amount / tenor / rates open'
    pillars.append({
        'key': 'facility', 'label': 'Facility structure',
        'max': 25, 'earned': fac_pts, 'note': fac_note,
    })
    total += fac_pts

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
        'modality': 'wholesale',
        'total': total,
        'band': band,
        'band_label': band_label,
        'pillars': pillars,
        'par90_pct': par90,
        'npl_pct': npl,
        'par90_cap': DEFAULT_PAR90_CAP,
        'facility_amount': getattr(profile, 'facility_amount', None) if profile else None,
        'tenor_months': getattr(profile, 'tenor_months', None) if profile else None,
        'institution_name': (profile.institution_name if profile else '') or '',
    }


def sync_wholesale_decision_to_appraisal(
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
    """Write officer facility decision onto LoanAppraisal and persist PFI scorecard."""
    from loans.models import LoanAppraisal

    appraisal, _ = LoanAppraisal.objects.get_or_create(
        loan_request=loan_request,
        defaults={'created_by': user},
    )
    term = term_approved_months or getattr(profile, 'tenor_months', None)
    amount = amount_approved
    if amount is None:
        amount = getattr(profile, 'facility_amount', None)
    rate = rate_approved
    if rate is None:
        rate = getattr(profile, 'dbe_to_pfi_rate_pct', None)

    appraisal.recommendation = recommendation or None
    appraisal.amount_approved = amount
    appraisal.term_approved_months = term
    appraisal.rate_approved = rate
    appraisal.recommendation_comment = (recommendation_comment or '').strip() or None
    appraisal.strengths = (strengths or '').strip() or None
    appraisal.weaknesses = (weaknesses or '').strip() or None
    if not appraisal.created_by_id:
        appraisal.created_by = user

    card = build_wholesale_scorecard(loan_request, profile)
    appraisal.credit_score_total = card['total']
    appraisal.credit_score_band = card['band']
    appraisal.scorecard_detail = scorecard_for_storage(card)
    appraisal.save()
    if recommendation and not getattr(loan_request, 'appraisal_completed_at', None):
        loan_request.appraisal_completed_at = timezone.now()
        loan_request.save(update_fields=['appraisal_completed_at'])
    return appraisal, card


def wholesale_appraisal_blockers(loan_request) -> List[str]:
    if not is_wholesale_file(loan_request):
        return []
    from loans.models import LoanAppraisal

    blockers = []
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    if appraisal is None or not appraisal.recommendation:
        blockers.append(
            'Complete wholesale appraisal: record Approve / Decline / Escalate on the PFI desk.'
        )
    if appraisal is None or not appraisal.amount_approved or appraisal.amount_approved <= 0:
        blockers.append('Enter the recommended facility amount on the PFI appraisal desk.')
    if appraisal is None or appraisal.rate_approved is None:
        blockers.append('Enter the recommended DBE→PFI rate (%) on the PFI appraisal desk.')
    if appraisal is None or not appraisal.term_approved_months:
        blockers.append('Enter the recommended facility tenor (months) on the PFI appraisal desk.')
    return blockers
