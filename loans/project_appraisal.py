"""Project-finance appraisal — NPV/IRR/DSCR scorecard + officer recommendation.

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
from loans.project_overlay import (
    compute_project_metrics,
    get_project_profile,
    is_project_file,
    plant_desk_blockers,
    sources_uses_totals,
)

ZERO = Decimal('0')
ALGORITHM = 'PROJECT_SCORE_V1'
MIN_DSCR = Decimal('1.00')
STRONG_DSCR = Decimal('1.25')


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


def _resolved_metrics(profile) -> Dict[str, Any]:
    computed = compute_project_metrics(profile) if profile is not None else {}
    return {
        'npv': profile.npv if profile is not None and profile.npv is not None else computed.get('npv'),
        'irr_pct': (
            profile.irr_pct if profile is not None and profile.irr_pct is not None
            else computed.get('irr_pct')
        ),
        'dscr': (
            profile.project_dscr if profile is not None and profile.project_dscr is not None
            else computed.get('dscr')
        ),
        'discount_rate_pct': (
            profile.discount_rate_pct if profile is not None and profile.discount_rate_pct is not None
            else Decimal('12')
        ),
        'payback_years': computed.get('payback_years'),
        'bcr': computed.get('bcr'),
    }


def build_project_scorecard(loan_request, profile=None) -> Dict[str, Any]:
    """Explainable 0–100 project score from NPV, IRR, DSCR, and structure completeness."""
    profile = profile or get_project_profile(loan_request)
    metrics = _resolved_metrics(profile)
    pillars: List[Dict[str, Any]] = []
    total = ZERO

    # --- NPV (max 25) ---
    npv = metrics['npv']
    if npv is None:
        npv_pts = ZERO
        npv_note = 'NPV not entered / not computable yet'
    elif npv < 0:
        npv_pts = ZERO
        npv_note = f'NPV {npv} is negative'
    else:
        # Positive NPV earns full band; very large vs cost can still only max 25
        npv_pts = Decimal('25')
        npv_note = f'NPV {npv} ≥ 0'
    pillars.append({'key': 'npv', 'label': 'Net present value', 'max': 25, 'earned': npv_pts, 'note': npv_note})
    total += npv_pts

    # --- IRR vs discount (max 25) ---
    irr = metrics['irr_pct']
    disc = _d(metrics['discount_rate_pct'])
    if irr is None:
        irr_pts = ZERO
        irr_note = 'IRR not entered / not computable yet'
    elif irr < disc:
        # Taper: at 0 earn 0; at discount earn 12
        if disc > 0 and irr > 0:
            irr_pts = _q(Decimal('12') * (irr / disc))
            irr_pts = max(ZERO, min(Decimal('12'), irr_pts))
        else:
            irr_pts = ZERO
        irr_note = f'IRR {irr}% below discount {disc}%'
    else:
        # At or above discount → 18–25
        spread = irr - disc
        irr_pts = _q(Decimal('18') + min(Decimal('7'), spread))
        irr_pts = min(Decimal('25'), irr_pts)
        irr_note = f'IRR {irr}% ≥ discount {disc}%'
    pillars.append({'key': 'irr', 'label': 'Internal rate of return', 'max': 25, 'earned': irr_pts, 'note': irr_note})
    total += irr_pts

    # --- DSCR (max 30) ---
    dscr = metrics['dscr']
    if dscr is None:
        dscr_pts = ZERO
        dscr_note = 'Project DSCR not entered / not computable yet'
    elif dscr < MIN_DSCR:
        dscr_pts = ZERO
        dscr_note = f'DSCR {dscr} below {MIN_DSCR} (committee hard gate)'
    elif dscr < STRONG_DSCR:
        # 1.00 → 18, 1.25 → 30
        span = STRONG_DSCR - MIN_DSCR
        dscr_pts = _q(Decimal('18') + (Decimal('12') * ((dscr - MIN_DSCR) / span)))
        dscr_note = f'DSCR {dscr} (target ≥ {STRONG_DSCR})'
    else:
        dscr_pts = Decimal('30')
        dscr_note = f'DSCR {dscr} ≥ {STRONG_DSCR}'
    pillars.append({'key': 'dscr', 'label': 'Project DSCR', 'max': 30, 'earned': dscr_pts, 'note': dscr_note})
    total += dscr_pts

    # --- Structure completeness (max 20) ---
    complete_pts = ZERO
    bits = []
    totals = sources_uses_totals(profile) if profile else sources_uses_totals(None)
    if totals.get('balanced'):
        complete_pts += Decimal('8')
        bits.append('S&U balanced')
    if profile and profile.promoter_equity and profile.promoter_equity > 0:
        complete_pts += Decimal('4')
        bits.append('equity')
    if profile and (profile.project_title or '').strip():
        complete_pts += Decimal('3')
        bits.append('title')
    plant_open = plant_desk_blockers(profile)
    if not plant_open:
        complete_pts += Decimal('5')
        bits.append('plant desks cleared')
    complete_note = ('Recorded: ' + ', '.join(bits)) if bits else 'Structure / plant desks still open'
    pillars.append({
        'key': 'completeness', 'label': 'Structure & plant desks',
        'max': 20, 'earned': complete_pts, 'note': complete_note,
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
        'modality': 'project',
        'total': total,
        'band': band,
        'band_label': band_label,
        'pillars': pillars,
        'npv': metrics['npv'],
        'irr_pct': metrics['irr_pct'],
        'dscr': metrics['dscr'],
        'discount_rate_pct': metrics['discount_rate_pct'],
        'payback_years': metrics.get('payback_years'),
        'bcr': metrics.get('bcr'),
    }


def default_project_term_months(profile) -> Optional[int]:
    if profile is None:
        return None
    impl = int(profile.implementation_months or 0)
    grace = int(profile.grace_months or 0)
    total = impl + grace
    return total if total > 0 else None


def sync_project_decision_to_appraisal(
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
    """Write officer decision onto LoanAppraisal and persist project scorecard."""
    from loans.models import LoanAppraisal

    appraisal, _ = LoanAppraisal.objects.get_or_create(
        loan_request=loan_request,
        defaults={'created_by': user},
    )
    term = term_approved_months or default_project_term_months(profile)
    appraisal.recommendation = recommendation or None
    appraisal.amount_approved = amount_approved
    appraisal.term_approved_months = term
    appraisal.rate_approved = rate_approved
    appraisal.recommendation_comment = (recommendation_comment or '').strip() or None
    appraisal.strengths = (strengths or '').strip() or None
    appraisal.weaknesses = (weaknesses or '').strip() or None
    if not appraisal.created_by_id:
        appraisal.created_by = user

    card = build_project_scorecard(loan_request, profile)
    appraisal.credit_score_total = card['total']
    appraisal.credit_score_band = card['band']
    appraisal.scorecard_detail = scorecard_for_storage(card)
    appraisal.save()
    if recommendation and not getattr(loan_request, 'appraisal_completed_at', None):
        loan_request.appraisal_completed_at = timezone.now()
        loan_request.save(update_fields=['appraisal_completed_at'])
    return appraisal, card


def project_appraisal_blockers(loan_request) -> List[str]:
    """Officer must stamp a project recommendation before committee."""
    if not is_project_file(loan_request):
        return []
    from loans.models import LoanAppraisal

    blockers = []
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    if appraisal is None or not appraisal.recommendation:
        blockers.append('Complete project appraisal: record Approve / Decline / Escalate on the project desk.')
    if appraisal is None or not appraisal.amount_approved or appraisal.amount_approved <= 0:
        blockers.append('Enter the recommended debt amount on the project appraisal desk.')
    if appraisal is None or appraisal.rate_approved is None:
        blockers.append('Enter the recommended interest rate (%) on the project appraisal desk.')
    if appraisal is None or not appraisal.term_approved_months:
        blockers.append('Enter the recommended term (months) on the project appraisal desk.')
    return blockers
