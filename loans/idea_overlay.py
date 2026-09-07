"""Idea / quasi-equity. Not a loan — cap table after approval."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from loans.fund_overlay import fund_file_summary
from loans.product_family import FAMILY_IDEA_EQUITY, resolve_product_family

MAX_STARTUP_AGE_YEARS = 5


def is_idea_file(loan_request) -> bool:
    return resolve_product_family(loan_request) == FAMILY_IDEA_EQUITY


def get_idea_profile(loan_request):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return loan_request.idea_profile
    except ObjectDoesNotExist:
        return None


def startup_age_years(profile) -> Optional[int]:
    if profile is None or not profile.founded_year:
        return None
    return date.today().year - int(profile.founded_year)


def cap_table_totals(profile) -> Dict[str, Decimal]:
    total = Decimal('0')
    dbe = Decimal('0')
    if profile is None:
        return {'total': total, 'dbe': dbe}
    for row in profile.cap_table.all():
        pct = row.share_pct or Decimal('0')
        total += pct
        if row.role == row.ROLE_DBE:
            dbe += pct
    return {'total': total, 'dbe': dbe}


def idea_gate_blockers(loan_request) -> List[str]:
    if not is_idea_file(loan_request):
        return []
    profile = get_idea_profile(loan_request)
    if profile is None:
        return ['Open the idea file: start-up gates, Ethiopia, and proposed DBE share.']
    blockers = []
    if not (profile.venture_name or '').strip():
        blockers.append('Venture name is required.')
    age = startup_age_years(profile)
    if age is None:
        blockers.append('Enter the year the start-up was founded.')
    elif age > MAX_STARTUP_AGE_YEARS:
        blockers.append(f'Idea financing is for start-ups ≤ {MAX_STARTUP_AGE_YEARS} years old.')
    if not profile.implements_in_ethiopia:
        blockers.append('The venture must implement in Ethiopia.')
    if not (profile.has_ip or profile.has_mols_training or profile.has_startup_label):
        blockers.append('Need IP, MoLS training, or a start-up label certificate.')
    if profile.proposed_dbe_share_pct is None or profile.proposed_dbe_share_pct <= 0:
        blockers.append('Enter the proposed DBE share % — this is quasi-equity, not an installment.')
    return blockers


def idea_cap_table_blockers(loan_request) -> List[str]:
    if not is_idea_file(loan_request):
        return []
    profile = get_idea_profile(loan_request)
    if profile is None:
        return ['Enter the cap table before the investment is released.']
    totals = cap_table_totals(profile)
    if totals['total'] <= 0:
        return ['Enter the cap table (founders + DBE share) — not an amortization table.']
    blockers = []
    if abs(totals['total'] - Decimal('100')) > Decimal('0.5'):
        blockers.append(
            f'Cap table sums to {totals["total"]}%; it must add to 100%.'
        )
    if totals['dbe'] <= 0:
        blockers.append('Cap table must show DBE’s share.')
    if (
        profile.proposed_dbe_share_pct
        and abs(totals['dbe'] - profile.proposed_dbe_share_pct) > Decimal('0.5')
    ):
        blockers.append(
            f'DBE share on the cap table ({totals["dbe"]}%) must match the proposed '
            f'{profile.proposed_dbe_share_pct}%.'
        )
    return blockers


def idea_committee_blockers(loan_request) -> List[str]:
    if not is_idea_file(loan_request):
        return []
    return list(idea_gate_blockers(loan_request))


def idea_disbursement_blockers(loan_request) -> List[str]:
    if not is_idea_file(loan_request):
        return []
    return list(idea_gate_blockers(loan_request)) + idea_cap_table_blockers(loan_request)


def idea_file_summary(loan_request) -> Optional[Dict[str, Any]]:
    if not is_idea_file(loan_request):
        return None
    profile = get_idea_profile(loan_request)
    return {
        'is_idea': True,
        'is_project': False,
        'is_wholesale': False,
        'is_lease': False,
        'profile': profile,
        'age_years': startup_age_years(profile),
        'cap_totals': cap_table_totals(profile),
        'committee_blockers': idea_committee_blockers(loan_request),
        'disbursement_blockers': idea_disbursement_blockers(loan_request),
        'fund': fund_file_summary(loan_request),
    }


def can_view_idea_file(user, loan_request) -> bool:
    if not is_idea_file(loan_request):
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


def can_edit_idea_file(user, loan_request) -> bool:
    if not can_view_idea_file(user, loan_request):
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
