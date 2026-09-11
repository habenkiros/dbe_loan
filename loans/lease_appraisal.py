"""Lease / Ijarah appraisal — asset scorecard + officer recommendation.

Not MSME Sheets 1–7. Hire-purchase and Ijarah share the asset register;
Ijarah also uses rent lines + Sharia (disbursement), not Sheet 7 interest.
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
from loans.lease_overlay import (
    LESSEE_MAX,
    LESSEE_MIN,
    MAX_ANCILLARY,
    MIN_CONTRIBUTION,
    ancillary_share,
    contribution_share,
    get_lease_asset,
    is_ijarah_file,
    is_lease_file,
)

ZERO = Decimal('0')
ALGORITHM = 'LEASE_SCORE_V1'


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


def default_financed_amount(profile) -> Optional[Decimal]:
    if profile is None or not profile.asset_price or profile.asset_price <= 0:
        return None
    contrib = profile.lessee_contribution or ZERO
    anc = profile.ancillary_amount or ZERO
    financed = profile.asset_price - contrib + anc
    return financed if financed > 0 else None


def build_lease_scorecard(loan_request, profile=None) -> Dict[str, Any]:
    """Explainable 0–100 score from contribution, policy fit, controls, completeness."""
    profile = profile or get_lease_asset(loan_request)
    ijarah = is_ijarah_file(loan_request)
    pillars: List[Dict[str, Any]] = []
    total = ZERO

    # --- Lessee contribution (max 30) ---
    share = contribution_share(profile)
    if share is None:
        contrib_pts = ZERO
        contrib_note = 'Lessee contribution not entered'
    elif share + Decimal('0.001') < MIN_CONTRIBUTION:
        contrib_pts = ZERO
        contrib_note = f'Contribution {(share * 100).quantize(Decimal("0.1"))}% below 20% minimum'
    else:
        # 20% → 18, 25% → 24, 30%+ → 30
        over = max(ZERO, share - MIN_CONTRIBUTION)
        contrib_pts = _q(Decimal('18') + min(Decimal('12'), over / Decimal('0.10') * Decimal('12')))
        contrib_pts = min(Decimal('30'), contrib_pts)
        contrib_note = f'Contribution {(share * 100).quantize(Decimal("0.1"))}% of asset price'
    pillars.append({
        'key': 'contribution', 'label': 'Lessee contribution',
        'max': 30, 'earned': contrib_pts, 'note': contrib_note,
    })
    total += contrib_pts

    # --- Asset policy fit (max 25) ---
    pol_pts = ZERO
    pol_bits = []
    if profile and profile.is_new_goods:
        pol_pts += Decimal('10')
        pol_bits.append('new goods')
    if profile and profile.asset_price and LESSEE_MIN <= profile.asset_price <= LESSEE_MAX:
        pol_pts += Decimal('10')
        pol_bits.append('price in band')
    elif profile and profile.asset_price and profile.asset_price > 0:
        pol_pts += Decimal('3')
        pol_bits.append('price outside band')
    anc = ancillary_share(profile)
    if anc is not None and anc <= MAX_ANCILLARY + Decimal('0.001'):
        pol_pts += Decimal('5')
        pol_bits.append('ancillary ≤15%')
    elif anc is None and profile and profile.ancillary_amount is None:
        pol_pts += Decimal('5')
        pol_bits.append('no ancillary')
    pol_note = ('Ok: ' + ', '.join(pol_bits)) if pol_bits else 'New goods / price band / ancillary open'
    pillars.append({
        'key': 'policy', 'label': 'Asset policy fit',
        'max': 25, 'earned': pol_pts, 'note': pol_note,
    })
    total += pol_pts

    # --- Bank controls (max 25) ---
    ctrl_pts = ZERO
    ctrl_bits = []
    if profile and profile.bank_holds_title:
        ctrl_pts += Decimal('8')
        ctrl_bits.append('title')
    if profile and profile.insurance_in_force:
        ctrl_pts += Decimal('7')
        ctrl_bits.append('insurance')
    if profile and profile.price_checked:
        ctrl_pts += Decimal('5')
        ctrl_bits.append('price-check')
    if profile and (profile.serial_number or '').strip():
        ctrl_pts += Decimal('5')
        ctrl_bits.append('serial')
    ctrl_note = ('On file: ' + ', '.join(ctrl_bits)) if ctrl_bits else 'Title / insurance / price-check / serial open'
    pillars.append({
        'key': 'controls', 'label': 'Bank asset controls',
        'max': 25, 'earned': ctrl_pts, 'note': ctrl_note,
    })
    total += ctrl_pts

    # --- Completeness / rent (max 20) ---
    comp_pts = ZERO
    comp_bits = []
    if profile and (profile.supplier_name or '').strip():
        comp_pts += Decimal('5')
        comp_bits.append('supplier')
    if profile and (profile.asset_description or '').strip():
        comp_pts += Decimal('5')
        comp_bits.append('description')
    if ijarah:
        has_rent = bool(
            profile
            and (
                (profile.monthly_rent and profile.monthly_rent > 0)
                or profile.rent_lines.exists()
            )
        )
        if has_rent:
            comp_pts += Decimal('10')
            comp_bits.append('rental schedule')
        else:
            comp_bits.append('rental still open')
    else:
        if profile and (profile.delivery_date or profile.commencement_date):
            comp_pts += Decimal('5')
            comp_bits.append('timing')
        if profile and profile.rent_term_months:
            comp_pts += Decimal('5')
            comp_bits.append('term')
        elif profile and (profile.location or '').strip():
            comp_pts += Decimal('5')
            comp_bits.append('location')
    comp_note = ('Set: ' + ', '.join(comp_bits)) if comp_bits else 'Supplier / description open'
    pillars.append({
        'key': 'completeness', 'label': 'Ijarah rent' if ijarah else 'File completeness',
        'max': 20, 'earned': comp_pts, 'note': comp_note,
    })
    total += comp_pts

    total = _q(total)
    band = _band_for_total(total)
    band_label = {
        SCORE_BAND_STRONG: 'Strong',
        SCORE_BAND_ACCEPTABLE: 'Acceptable',
        SCORE_BAND_WEAK: 'Weak',
        SCORE_BAND_UNACCEPTABLE: 'Unacceptable',
    }.get(band, band)

    financed = default_financed_amount(profile)
    return {
        'algorithm': ALGORITHM,
        'modality': 'lease',
        'is_ijarah': ijarah,
        'total': total,
        'band': band,
        'band_label': band_label,
        'pillars': pillars,
        'contribution_pct': (
            (share * 100).quantize(Decimal('0.1')) if share is not None else None
        ),
        'ancillary_pct': (
            (anc * 100).quantize(Decimal('0.1')) if anc is not None else None
        ),
        'asset_price': getattr(profile, 'asset_price', None) if profile else None,
        'financed_amount': financed,
        'monthly_rent': getattr(profile, 'monthly_rent', None) if profile else None,
        'supplier_name': (profile.supplier_name if profile else '') or '',
        'asset_description': (profile.asset_description if profile else '') or '',
    }


def sync_lease_decision_to_appraisal(
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
    """Write officer lease/Ijarah decision onto LoanAppraisal and persist scorecard."""
    from loans.models import LoanAppraisal

    appraisal, _ = LoanAppraisal.objects.get_or_create(
        loan_request=loan_request,
        defaults={'created_by': user},
    )
    term = term_approved_months or getattr(profile, 'rent_term_months', None)
    amount = amount_approved
    if amount is None:
        amount = default_financed_amount(profile)
    if amount is None:
        amount = getattr(loan_request, 'amount_requested', None)

    appraisal.recommendation = recommendation or None
    appraisal.amount_approved = amount
    appraisal.term_approved_months = term
    appraisal.rate_approved = rate_approved
    appraisal.recommendation_comment = (recommendation_comment or '').strip() or None
    appraisal.strengths = (strengths or '').strip() or None
    appraisal.weaknesses = (weaknesses or '').strip() or None
    if not appraisal.created_by_id:
        appraisal.created_by = user

    card = build_lease_scorecard(loan_request, profile)
    appraisal.credit_score_total = card['total']
    appraisal.credit_score_band = card['band']
    appraisal.scorecard_detail = scorecard_for_storage(card)
    appraisal.save()
    if recommendation and not getattr(loan_request, 'appraisal_completed_at', None):
        loan_request.appraisal_completed_at = timezone.now()
        loan_request.save(update_fields=['appraisal_completed_at'])
    return appraisal, card


def lease_appraisal_blockers(loan_request) -> List[str]:
    if not is_lease_file(loan_request):
        return []
    from loans.models import LoanAppraisal

    ijarah = is_ijarah_file(loan_request)
    desk = 'Ijarah' if ijarah else 'lease'
    blockers = []
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    if appraisal is None or not appraisal.recommendation:
        blockers.append(
            f'Complete {desk} appraisal: record Approve / Decline / Escalate on the asset desk.'
        )
    if appraisal is None or not appraisal.amount_approved or appraisal.amount_approved <= 0:
        blockers.append(f'Enter the recommended financed amount on the {desk} asset desk.')
    if appraisal is None or appraisal.rate_approved is None:
        if ijarah:
            blockers.append(
                'Enter recommended rate on the Ijarah desk (use 0 if rental-only; not Sheet 7 interest).'
            )
        else:
            blockers.append('Enter the recommended hire-purchase rate (%) on the lease asset desk.')
    if appraisal is None or not appraisal.term_approved_months:
        blockers.append(f'Enter the recommended term (months) on the {desk} asset desk.')
    return blockers
