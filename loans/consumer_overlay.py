"""Consumer (housing / vehicle) scorecard. Not MSME Sheet 3."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from loans.fund_overlay import fund_file_summary
from loans.product_family import FAMILY_CONSUMER, resolve_product_family

MAX_DTI_PCT = Decimal('50.00')
MAX_LTV_HOUSING_PCT = Decimal('80.00')
MAX_LTV_VEHICLE_PCT = Decimal('70.00')
ZERO = Decimal('0')


def is_consumer_file(loan_request) -> bool:
    return resolve_product_family(loan_request) == FAMILY_CONSUMER


def get_consumer_profile(loan_request):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return loan_request.consumer_profile
    except ObjectDoesNotExist:
        return None


def _pct(numer, denom) -> Optional[Decimal]:
    if numer is None or denom is None or denom <= 0:
        return None
    return (Decimal(numer) / Decimal(denom) * Decimal('100')).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP,
    )


def dti_pct(profile) -> Optional[Decimal]:
    if profile is None:
        return None
    return _pct(profile.monthly_obligations or ZERO, profile.monthly_salary)


def ltv_pct(loan_request, profile) -> Optional[Decimal]:
    if profile is None:
        return None
    amount = getattr(loan_request, 'amount_requested', None)
    return _pct(amount, profile.asset_value)


def ltv_cap(profile) -> Decimal:
    if profile is not None and getattr(profile, 'purpose', '') == 'vehicle':
        return MAX_LTV_VEHICLE_PCT
    return MAX_LTV_HOUSING_PCT


def consumer_committee_blockers(loan_request) -> List[str]:
    if not is_consumer_file(loan_request):
        return []
    profile = get_consumer_profile(loan_request)
    if profile is None:
        return ['Open the consumer file: employer, salary, DTI, LTV, and officer recommendation.']
    blockers = []
    if not (profile.employer_name or '').strip():
        blockers.append('Employer name is required.')
    if not profile.monthly_salary or profile.monthly_salary <= 0:
        blockers.append('Enter monthly salary / net pay.')
    dti = dti_pct(profile)
    if dti is None:
        blockers.append('Enter existing monthly obligations so DTI can be calculated.')
    elif dti > MAX_DTI_PCT:
        blockers.append(f'DTI is {dti}% — cap is {MAX_DTI_PCT}%.')
    if not profile.asset_value or profile.asset_value <= 0:
        blockers.append('Enter the house or vehicle value for LTV.')
    ltv = ltv_pct(loan_request, profile)
    cap = ltv_cap(profile)
    if ltv is not None and ltv > cap:
        blockers.append(f'LTV is {ltv}% — cap for this purpose is {cap}%.')
    from loans.consumer_appraisal import consumer_appraisal_blockers
    blockers.extend(consumer_appraisal_blockers(loan_request))
    return blockers


def consumer_disbursement_blockers(loan_request) -> List[str]:
    return list(consumer_committee_blockers(loan_request))


def consumer_file_summary(loan_request) -> Optional[Dict[str, Any]]:
    if not is_consumer_file(loan_request):
        return None
    profile = get_consumer_profile(loan_request)
    from loans.consumer_appraisal import build_consumer_scorecard
    from loans.models import LoanAppraisal

    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    scorecard = None
    if profile is not None:
        scorecard = build_consumer_scorecard(loan_request, profile)
        if appraisal and appraisal.scorecard_detail and appraisal.scorecard_detail.get('modality') == 'consumer':
            scorecard = appraisal.scorecard_detail
    return {
        'is_consumer': True,
        'is_project': False,
        'is_wholesale': False,
        'is_lease': False,
        'profile': profile,
        'appraisal': appraisal,
        'scorecard': scorecard,
        'dti_pct': dti_pct(profile),
        'ltv_pct': ltv_pct(loan_request, profile),
        'dti_cap': MAX_DTI_PCT,
        'ltv_cap': ltv_cap(profile),
        'installment': (scorecard or {}).get('installment'),
        'payment_burden_pct': (scorecard or {}).get('payment_burden_pct'),
        'committee_blockers': consumer_committee_blockers(loan_request),
        'disbursement_blockers': consumer_disbursement_blockers(loan_request),
        'fund': fund_file_summary(loan_request),
    }


def can_view_consumer_file(user, loan_request) -> bool:
    if not is_consumer_file(loan_request):
        return False
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in (
        'admin', 'superadmin', 'credit_head', 'branch_manager',
        'finance_manager', 'risk_compliance', 'auditor',
    ):
        return True
    from loans.dbe_desks import DESK_HRM, user_desk_key
    if user_desk_key(user) == DESK_HRM:
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    from loans.delegation import can_access_loan_as_officer
    ok, _ = can_access_loan_as_officer(user, loan_request)
    return ok


def can_edit_consumer_file(user, loan_request) -> bool:
    if not can_view_consumer_file(user, loan_request):
        return False
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in (
        'admin', 'superadmin', 'credit_head', 'branch_manager',
    ):
        return True
    from loans.dbe_desks import DESK_HRM, user_desk_key
    if user_desk_key(user) == DESK_HRM:
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    from loans.delegation import can_access_loan_as_officer
    ok, _ = can_access_loan_as_officer(user, loan_request)
    return ok
