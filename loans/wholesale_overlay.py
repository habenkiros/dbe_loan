"""Wholesale / PFI engine. The borrower is an institution.

DBE takes PFI risk. The PFI on-lends. Not MSME Sheet 3.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from loans.fund_overlay import fund_file_summary
from loans.product_family import FAMILY_WHOLESALE, resolve_product_family


DEFAULT_PAR90_CAP = Decimal('10')


def is_wholesale_file(loan_request) -> bool:
    return resolve_product_family(loan_request) == FAMILY_WHOLESALE


def get_pfi_profile(loan_request):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return loan_request.pfi_profile
    except ObjectDoesNotExist:
        return None


def pfi_profile_blockers(loan_request) -> List[str]:
    if not is_wholesale_file(loan_request):
        return []
    profile = get_pfi_profile(loan_request)
    if profile is None:
        return ['Open the PFI institution file: license, MIS, capital, PAR, ESMS, and facility.']
    blockers = []
    if not (profile.institution_name or '').strip():
        blockers.append('Institution name is required.')
    if not (profile.license_number or '').strip():
        blockers.append('PFI license number is required.')
    if not profile.has_adequate_mis:
        blockers.append('Confirm the PFI has adequate MIS.')
    if profile.capital is None or profile.capital <= 0:
        blockers.append('Enter PFI capital.')
    if profile.npl_pct is None:
        blockers.append('Enter PFI NPL %.')
    if profile.par30_pct is None:
        blockers.append('Enter PFI PAR>30 %.')
    if profile.par90_pct is None:
        blockers.append('Enter PFI PAR>90 %.')
    elif profile.par90_pct > DEFAULT_PAR90_CAP:
        blockers.append(
            f'PFI PAR>90 is {profile.par90_pct}%; wholesale files allow at most {DEFAULT_PAR90_CAP}%.'
        )
    if not profile.audited_year:
        blockers.append('Enter the latest audited year.')
    if not profile.credit_policy_on_file:
        blockers.append('Confirm the PFI credit policy is on this pack.')
    if not profile.on_lending_policy_on_file:
        blockers.append('Confirm the on-lending policy is on this pack.')
    if not profile.has_governance:
        blockers.append('Confirm credit-risk / governance controls.')
    if not profile.has_esms:
        blockers.append('Confirm the PFI has an ESMS.')
    if profile.facility_amount is None or profile.facility_amount <= 0:
        blockers.append('Enter the proposed facility amount.')
    if not profile.tenor_months:
        blockers.append('Enter facility tenor (months).')
    if profile.end_user_rate_ceiling_pct is None:
        blockers.append('Enter the end-user on-lending rate ceiling.')
    return blockers


def wholesale_committee_blockers(loan_request) -> List[str]:
    if not is_wholesale_file(loan_request):
        return []
    return list(pfi_profile_blockers(loan_request))


def wholesale_disbursement_blockers(loan_request) -> List[str]:
    if not is_wholesale_file(loan_request):
        return []
    blockers = list(pfi_profile_blockers(loan_request))
    profile = get_pfi_profile(loan_request)
    released = loan_request.disbursement_status in (
        getattr(loan_request, 'DISBURSE_PARTIAL', 'partial'),
        getattr(loan_request, 'DISBURSE_DISBURSED', 'disbursed'),
    ) or loan_request.disbursement_tranches.filter(status='disbursed').exists()
    if released and profile:
        latest = profile.utilization_reports.order_by('-as_of', '-id').first()
        if latest is None:
            blockers.append(
                'Record PFI utilization (amount on-lent, repayment to DBE, sub-portfolio PAR) '
                'before the next release — not a factory site visit.'
            )
        elif latest.sub_par90_pct is not None and latest.sub_par90_pct > DEFAULT_PAR90_CAP:
            blockers.append(
                f'Sub-portfolio PAR>90 is {latest.sub_par90_pct}%; '
                f'next release needs at most {DEFAULT_PAR90_CAP}%.'
            )
    return blockers


def wholesale_file_summary(loan_request) -> Optional[Dict[str, Any]]:
    if not is_wholesale_file(loan_request):
        return None
    profile = get_pfi_profile(loan_request)
    latest = None
    if profile:
        latest = profile.utilization_reports.order_by('-as_of', '-id').first()
    fund_summary = fund_file_summary(loan_request)
    return {
        'is_wholesale': True,
        'is_project': False,
        'is_fund': bool(fund_summary),
        'profile': profile,
        'latest_report': latest,
        'committee_blockers': wholesale_committee_blockers(loan_request),
        'disbursement_blockers': wholesale_disbursement_blockers(loan_request),
        'fund': fund_summary,
    }


def can_view_wholesale_file(user, loan_request) -> bool:
    if not is_wholesale_file(loan_request):
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


def can_edit_wholesale_file(user, loan_request) -> bool:
    if not can_view_wholesale_file(user, loan_request):
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
