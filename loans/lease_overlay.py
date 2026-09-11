"""Hire-purchase / Ijarah overlay. The bank owns the machine.

DECSI general files never hit these gates. Extra WC stays on another bank.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from loans.fund_overlay import fund_file_summary
from loans.product_family import FAMILY_IFB_IJARAH, FAMILY_LEASE, resolve_product_family

MIN_CONTRIBUTION = Decimal('0.20')
MAX_ANCILLARY = Decimal('0.15')
LESSEE_MIN = Decimal('500000')
LESSEE_MAX = Decimal('9000000')


def is_lease_file(loan_request) -> bool:
    return resolve_product_family(loan_request) in (FAMILY_LEASE, FAMILY_IFB_IJARAH)


def is_ijarah_file(loan_request) -> bool:
    return resolve_product_family(loan_request) == FAMILY_IFB_IJARAH


def get_lease_asset(loan_request):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return loan_request.lease_asset
    except ObjectDoesNotExist:
        return None


def _base(price: Optional[Decimal]) -> Decimal:
    return price if price and price > 0 else Decimal('0')


def contribution_share(profile) -> Optional[Decimal]:
    if profile is None:
        return None
    base = _base(profile.asset_price)
    if base <= 0 or profile.lessee_contribution is None:
        return None
    return profile.lessee_contribution / base


def ancillary_share(profile) -> Optional[Decimal]:
    if profile is None:
        return None
    base = _base(profile.asset_price)
    if base <= 0 or not profile.ancillary_amount:
        return Decimal('0') if profile.ancillary_amount == 0 else None
    return profile.ancillary_amount / base


def lease_policy_blockers(loan_request) -> List[str]:
    if not is_lease_file(loan_request):
        return []
    profile = get_lease_asset(loan_request)
    if profile is None:
        return ['Open the lease asset register: supplier, serial, price, and contribution.']
    blockers = []
    if not (profile.supplier_name or '').strip():
        blockers.append('Supplier name is required.')
    if not (profile.asset_description or '').strip():
        blockers.append('Asset description is required.')
    if not profile.is_new_goods:
        blockers.append('Lease is new capital goods only.')
    if profile.asset_price is None or profile.asset_price <= 0:
        blockers.append('Enter the asset invoice price.')
    else:
        if profile.asset_price < LESSEE_MIN or profile.asset_price > LESSEE_MAX:
            blockers.append(
                f'Lessee asset band is ETB {LESSEE_MIN:,.0f}–{LESSEE_MAX:,.0f}.'
            )
        share = contribution_share(profile)
        if share is None:
            blockers.append('Enter lessee contribution (at least 20% of asset price).')
        elif share + Decimal('0.001') < MIN_CONTRIBUTION:
            blockers.append(
                f'Lessee contribution is {(share * 100).quantize(Decimal("0.1"))}% of asset price; '
                f'minimum is 20%.'
            )
        anc = ancillary_share(profile)
        if anc is not None and anc > MAX_ANCILLARY + Decimal('0.001'):
            blockers.append(
                f'Ancillary costs are {(anc * 100).quantize(Decimal("0.1"))}% of asset price; '
                f'maximum is 15%.'
            )
    return blockers


def sharia_blockers(loan_request) -> List[str]:
    if not is_ijarah_file(loan_request):
        return []
    from loans.models import ShariaReview

    if not loan_request.sharia_reviews.filter(status=ShariaReview.STATUS_CLEARED).exists():
        return ['Ijarah cannot confirm without a cleared Sharia review.']
    return []


def ijarah_rent_blockers(loan_request) -> List[str]:
    if not is_ijarah_file(loan_request):
        return []
    profile = get_lease_asset(loan_request)
    if profile is None:
        return []
    has_lines = profile.rent_lines.exists()
    if not has_lines and (profile.monthly_rent is None or profile.monthly_rent <= 0):
        return ['Enter the Ijarah rental schedule (monthly rent or rent lines) — not Sheet 7 interest.']
    return []


def lease_committee_blockers(loan_request) -> List[str]:
    if not is_lease_file(loan_request):
        return []
    from loans.lease_appraisal import lease_appraisal_blockers

    blockers = list(lease_policy_blockers(loan_request))
    if is_ijarah_file(loan_request):
        blockers.extend(ijarah_rent_blockers(loan_request))
    blockers.extend(lease_appraisal_blockers(loan_request))
    return blockers


def lease_disbursement_blockers(loan_request) -> List[str]:
    if not is_lease_file(loan_request):
        return []
    blockers = list(lease_policy_blockers(loan_request))
    profile = get_lease_asset(loan_request)
    if profile:
        if not (profile.serial_number or '').strip():
            blockers.append('Record the asset serial number before release.')
        if not profile.price_checked:
            blockers.append('Price-check the invoice against the supplier quote.')
        if not (profile.delivery_date or profile.commencement_date):
            blockers.append(
                'Record delivery or commencement — lease timing does not start on approval day.'
            )
        if not profile.insurance_in_force:
            blockers.append('Asset insurance must be in force (bank as co-beneficiary).')
        if not profile.bank_holds_title:
            blockers.append('Bank must hold title until the last installment.')
    if not loan_request.own_contribution_verified_at:
        blockers.append('Verify lessee contribution before the first release.')
    blockers.extend(ijarah_rent_blockers(loan_request))
    blockers.extend(sharia_blockers(loan_request))
    return blockers


def lease_file_summary(loan_request) -> Optional[Dict[str, Any]]:
    if not is_lease_file(loan_request):
        return None
    from loans.models import LoanAppraisal
    from loans.lease_appraisal import build_lease_scorecard

    profile = get_lease_asset(loan_request)
    ijarah = is_ijarah_file(loan_request)
    latest_sharia = None
    if ijarah:
        latest_sharia = loan_request.sharia_reviews.order_by('-created_at', '-id').first()
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    scorecard = None
    if profile is not None:
        scorecard = build_lease_scorecard(loan_request, profile)
        if appraisal and appraisal.scorecard_detail and appraisal.scorecard_detail.get('modality') == 'lease':
            scorecard = appraisal.scorecard_detail
    return {
        'is_lease': True,
        'is_ijarah': ijarah,
        'is_project': False,
        'is_wholesale': False,
        'profile': profile,
        'appraisal': appraisal,
        'scorecard': scorecard,
        'contribution_share': contribution_share(profile),
        'latest_sharia': latest_sharia,
        'rent_lines': list(profile.rent_lines.all()) if profile else [],
        'committee_blockers': lease_committee_blockers(loan_request),
        'disbursement_blockers': lease_disbursement_blockers(loan_request),
        'fund': fund_file_summary(loan_request),
    }


def can_view_lease_file(user, loan_request) -> bool:
    if not is_lease_file(loan_request):
        return False
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in (
        'admin', 'superadmin', 'credit_head', 'branch_manager',
        'finance_manager', 'risk_compliance', 'auditor',
    ):
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    from loans.delegation import can_access_loan_as_officer
    ok, _ = can_access_loan_as_officer(user, loan_request)
    return ok


def can_edit_lease_file(user, loan_request) -> bool:
    if not can_view_lease_file(user, loan_request):
        return False
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in (
        'admin', 'superadmin', 'credit_head', 'branch_manager',
    ):
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    from loans.delegation import can_access_loan_as_officer
    ok, _ = can_access_loan_as_officer(user, loan_request)
    return ok
