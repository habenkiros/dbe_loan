"""Consumer / HRM appraisal — DTI, LTV, affordability, and officer recommendation.

Not MSME Sheets 1–7. Persists the decision on LoanAppraisal so committee routing
and evidence packs reuse the same amount / term / rate fields.
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
from loans.consumer_overlay import (
    MAX_DTI_PCT,
    dti_pct,
    get_consumer_profile,
    is_consumer_file,
    ltv_cap,
    ltv_pct,
)

ZERO = Decimal('0')
HUNDRED = Decimal('100')
MAX_PAYMENT_BURDEN_PCT = Decimal('40.00')  # installment ÷ net pay soft cap
ALGORITHM = 'CONSUMER_SCORE_V1'


def _d(value) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(str(value))


def _q(value, places='0.01') -> Decimal:
    return _d(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def monthly_installment(amount, annual_rate_pct, term_months) -> Optional[Decimal]:
    """Standard amortizing payment. Flat interest if rate is zero."""
    principal = _d(amount)
    months = int(term_months or 0)
    if principal <= 0 or months <= 0:
        return None
    rate = _d(annual_rate_pct)
    if rate <= 0:
        return _q(principal / Decimal(months))
    r = (rate / HUNDRED) / Decimal('12')
    factor = (Decimal('1') + r) ** months
    payment = principal * (r * factor) / (factor - Decimal('1'))
    return _q(payment)


def payment_burden_pct(installment, monthly_salary) -> Optional[Decimal]:
    salary = _d(monthly_salary)
    if installment is None or salary <= 0:
        return None
    return _q((_d(installment) / salary) * HUNDRED)


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


def build_consumer_scorecard(loan_request, profile=None, *, amount=None, rate=None, term=None) -> Dict[str, Any]:
    """Explainable 0–100 consumer score from DTI, LTV, payment burden, completeness."""
    profile = profile or get_consumer_profile(loan_request)
    pillars: List[Dict[str, Any]] = []
    total = ZERO

    # --- DTI (max 30) ---
    dti = dti_pct(profile) if profile else None
    if dti is None:
        dti_pts = ZERO
        dti_note = 'Salary / obligations not entered'
    elif dti > MAX_DTI_PCT:
        dti_pts = ZERO
        dti_note = f'DTI {dti}% over cap {MAX_DTI_PCT}%'
    else:
        # 0% → 30, at cap → 12
        span = MAX_DTI_PCT if MAX_DTI_PCT > 0 else Decimal('1')
        dti_pts = _q(Decimal('30') * (Decimal('1') - (dti / span) * Decimal('0.6')))
        dti_pts = max(ZERO, min(Decimal('30'), dti_pts))
        dti_note = f'DTI {dti}% (cap {MAX_DTI_PCT}%)'
    pillars.append({'key': 'dti', 'label': 'Debt service (DTI)', 'max': 30, 'earned': dti_pts, 'note': dti_note})
    total += dti_pts

    # --- LTV (max 30) ---
    ltv = ltv_pct(loan_request, profile) if profile else None
    cap = ltv_cap(profile)
    if ltv is None:
        ltv_pts = ZERO
        ltv_note = 'Asset value not entered'
    elif ltv > cap:
        ltv_pts = ZERO
        ltv_note = f'LTV {ltv}% over cap {cap}%'
    else:
        span = cap if cap > 0 else Decimal('1')
        ltv_pts = _q(Decimal('30') * (Decimal('1') - (ltv / span) * Decimal('0.5')))
        ltv_pts = max(ZERO, min(Decimal('30'), ltv_pts))
        ltv_note = f'LTV {ltv}% (cap {cap}%)'
    pillars.append({'key': 'ltv', 'label': 'Loan to value', 'max': 30, 'earned': ltv_pts, 'note': ltv_note})
    total += ltv_pts

    # --- Payment burden (max 25) ---
    rec_amount = amount if amount is not None else getattr(
        getattr(loan_request, 'appraisal', None), 'amount_approved', None,
    )
    if rec_amount is None:
        rec_amount = getattr(loan_request, 'amount_requested', None)
    rec_rate = rate
    if rec_rate is None:
        appr = getattr(loan_request, 'appraisal', None)
        rec_rate = getattr(appr, 'rate_approved', None) if appr else None
    rec_term = term
    if rec_term is None:
        rec_term = getattr(profile, 'term_months', None) if profile else None
        if rec_term is None:
            appr = getattr(loan_request, 'appraisal', None)
            rec_term = getattr(appr, 'term_approved_months', None) if appr else None

    installment = monthly_installment(rec_amount, rec_rate or ZERO, rec_term)
    burden = payment_burden_pct(installment, getattr(profile, 'monthly_salary', None) if profile else None)
    if burden is None:
        pay_pts = ZERO
        pay_note = 'Need amount, term, rate, and salary for installment'
    elif burden > MAX_PAYMENT_BURDEN_PCT * Decimal('1.5'):
        pay_pts = ZERO
        pay_note = f'Installment {burden}% of pay (soft cap {MAX_PAYMENT_BURDEN_PCT}%)'
    elif burden > MAX_PAYMENT_BURDEN_PCT:
        # Between soft cap and 1.5× — taper
        over = burden - MAX_PAYMENT_BURDEN_PCT
        pay_pts = _q(Decimal('25') * (Decimal('1') - over / MAX_PAYMENT_BURDEN_PCT))
        pay_pts = max(ZERO, pay_pts)
        pay_note = f'Installment {burden}% of pay (soft cap {MAX_PAYMENT_BURDEN_PCT}%)'
    else:
        pay_pts = _q(Decimal('25') * (Decimal('1') - burden / (MAX_PAYMENT_BURDEN_PCT * Decimal('2'))))
        pay_pts = max(Decimal('12'), min(Decimal('25'), pay_pts))
        pay_note = f'Installment ~{installment} ETB/mo · {burden}% of pay'
    pillars.append({
        'key': 'affordability', 'label': 'Affordability (installment ÷ pay)',
        'max': 25, 'earned': pay_pts, 'note': pay_note,
    })
    total += pay_pts

    # --- Completeness (max 15) ---
    complete_pts = ZERO
    bits = []
    if profile and (profile.employer_name or '').strip():
        complete_pts += Decimal('5')
        bits.append('employer')
    if profile and profile.asset_value and profile.asset_value > 0:
        complete_pts += Decimal('5')
        bits.append('asset')
    if profile and profile.term_months:
        complete_pts += Decimal('5')
        bits.append('term')
    complete_note = ('Recorded: ' + ', '.join(bits)) if bits else 'Employer, asset, and term still open'
    pillars.append({
        'key': 'completeness', 'label': 'File completeness',
        'max': 15, 'earned': complete_pts, 'note': complete_note,
    })
    total += complete_pts

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
        'modality': 'consumer',
        'total': total,
        'band': band,
        'band_label': band_label,
        'pillars': pillars,
        'dti_pct': dti,
        'ltv_pct': ltv,
        'ltv_cap': cap,
        'installment': installment,
        'payment_burden_pct': burden,
        'max_payment_burden_pct': MAX_PAYMENT_BURDEN_PCT,
    }


def scorecard_for_storage(card: Dict[str, Any]) -> Dict[str, Any]:
    return _jsonable(card)


def sync_consumer_decision_to_appraisal(
    loan_request,
    profile,
    user,
    *,
    recommendation: str,
    amount_approved,
    rate_approved,
    recommendation_comment: str = '',
    strengths: str = '',
    weaknesses: str = '',
):
    """Write officer decision onto LoanAppraisal and persist consumer scorecard."""
    from loans.models import LoanAppraisal

    appraisal, _ = LoanAppraisal.objects.get_or_create(
        loan_request=loan_request,
        defaults={'created_by': user},
    )
    term = getattr(profile, 'term_months', None)
    appraisal.recommendation = recommendation or None
    appraisal.amount_approved = amount_approved
    appraisal.term_approved_months = term
    appraisal.rate_approved = rate_approved
    appraisal.recommendation_comment = (recommendation_comment or '').strip() or None
    appraisal.strengths = (strengths or '').strip() or None
    appraisal.weaknesses = (weaknesses or '').strip() or None
    if not appraisal.created_by_id:
        appraisal.created_by = user

    card = build_consumer_scorecard(
        loan_request, profile,
        amount=amount_approved, rate=rate_approved, term=term,
    )
    appraisal.credit_score_total = card['total']
    appraisal.credit_score_band = card['band']
    appraisal.scorecard_detail = scorecard_for_storage(card)
    appraisal.save()
    if recommendation and not getattr(loan_request, 'appraisal_completed_at', None):
        loan_request.appraisal_completed_at = timezone.now()
        loan_request.save(update_fields=['appraisal_completed_at'])
    return appraisal, card


def consumer_appraisal_blockers(loan_request) -> List[str]:
    """Extra gates: officer must record a consumer recommendation."""
    if not is_consumer_file(loan_request):
        return []
    profile = get_consumer_profile(loan_request)
    blockers = []
    from loans.models import LoanAppraisal

    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    if appraisal is None or not appraisal.recommendation:
        blockers.append('Complete Consumer / HRM appraisal: record Approve / Decline / Escalate.')
    if appraisal is None or not appraisal.amount_approved or appraisal.amount_approved <= 0:
        blockers.append('Enter the recommended amount on the consumer appraisal desk.')
    if profile is None or not profile.term_months:
        blockers.append('Set the recommended term (months) on the consumer file.')
    if appraisal is None or appraisal.rate_approved is None:
        blockers.append('Enter the recommended interest rate (%) on the consumer appraisal desk.')
    return blockers
