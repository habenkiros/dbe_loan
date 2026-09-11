"""Murabaha cost-plus. Not Sheet 7 with the word interest removed."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from loans.fund_overlay import fund_file_summary
from loans.product_family import FAMILY_IFB_MURABAHA, resolve_product_family

# Project-scale files go to IFB Directorate / HO. Thresholds have moved; this is the gate, not a rate card.
HO_COST_THRESHOLD = Decimal('10000000')


def is_murabaha_file(loan_request) -> bool:
    return resolve_product_family(loan_request) == FAMILY_IFB_MURABAHA


def get_murabaha(loan_request):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return loan_request.murabaha
    except ObjectDoesNotExist:
        return None


def compute_selling_price(cost, markup_pct) -> Optional[Decimal]:
    if cost is None or markup_pct is None or cost <= 0:
        return None
    return (cost * (Decimal('1') + markup_pct / Decimal('100'))).quantize(Decimal('0.01'))


def murabaha_policy_blockers(loan_request) -> List[str]:
    if not is_murabaha_file(loan_request):
        return []
    contract = get_murabaha(loan_request)
    if contract is None:
        return ['Open the Murabaha contract: cost, markup, and selling price.']
    blockers = []
    if not (contract.goods_description or '').strip():
        blockers.append('Describe the goods being sold (cost-plus).')
    if not (contract.supplier_name or '').strip():
        blockers.append('Enter the supplier name.')
    if not (contract.supplier_offer_ref or '').strip():
        blockers.append('Enter the supplier offer / invoice reference.')
    if not contract.tenor_months:
        blockers.append('Enter Murabaha tenor (months).')
    if contract.cost_price is None or contract.cost_price <= 0:
        blockers.append('Enter the cost (purchase) price.')
    if contract.markup_pct is None or contract.markup_pct < 0:
        blockers.append('Enter the Murabaha markup % — not an interest rate.')
    selling = contract.selling_price or compute_selling_price(contract.cost_price, contract.markup_pct)
    if selling is None or selling <= 0:
        blockers.append('Selling price is cost plus markup.')
    if contract.cost_price and contract.cost_price >= HO_COST_THRESHOLD and not contract.routed_to_ifb_ho:
        blockers.append(
            'Project-scale Murabaha is routed to IFB Directorate / HO before committee.'
        )
    return blockers


def murabaha_sharia_blockers(loan_request) -> List[str]:
    if not is_murabaha_file(loan_request):
        return []
    from loans.models import ShariaReview

    if not loan_request.sharia_reviews.filter(
        kind=ShariaReview.KIND_MURABAHA,
        status=ShariaReview.STATUS_CLEARED,
    ).exists():
        return ['Murabaha cannot confirm without a cleared Sharia review.']
    return []


def murabaha_delivery_blockers(loan_request) -> List[str]:
    if not is_murabaha_file(loan_request):
        return []
    contract = get_murabaha(loan_request)
    if contract is None:
        return ['Open the Murabaha contract: cost, markup, and selling price.']
    from loans.models import MurabahaContract

    if contract.delivery_status not in (
        MurabahaContract.DELIVERY_RECEIVED,
        MurabahaContract.DELIVERY_SOLD,
    ):
        return ['Murabaha release needs goods received or sold — not merely ordered.']
    return []


def murabaha_committee_blockers(loan_request) -> List[str]:
    if not is_murabaha_file(loan_request):
        return []
    from loans.murabaha_appraisal import murabaha_appraisal_blockers

    blockers = list(murabaha_policy_blockers(loan_request))
    blockers.extend(murabaha_appraisal_blockers(loan_request))
    return blockers


def murabaha_disbursement_blockers(loan_request) -> List[str]:
    if not is_murabaha_file(loan_request):
        return []
    return (
        list(murabaha_policy_blockers(loan_request))
        + murabaha_sharia_blockers(loan_request)
        + murabaha_delivery_blockers(loan_request)
    )


def murabaha_file_summary(loan_request) -> Optional[Dict[str, Any]]:
    if not is_murabaha_file(loan_request):
        return None
    from loans.models import LoanAppraisal
    from loans.murabaha_appraisal import build_murabaha_scorecard

    contract = get_murabaha(loan_request)
    latest = loan_request.sharia_reviews.filter(kind='murabaha').order_by('-created_at', '-id').first()
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    scorecard = None
    if contract is not None:
        scorecard = build_murabaha_scorecard(loan_request, contract)
        if appraisal and appraisal.scorecard_detail and appraisal.scorecard_detail.get('modality') == 'murabaha':
            scorecard = appraisal.scorecard_detail
    return {
        'is_murabaha': True,
        'is_project': False,
        'is_wholesale': False,
        'is_lease': False,
        'contract': contract,
        'appraisal': appraisal,
        'scorecard': scorecard,
        'selling_price': (
            (contract.selling_price if contract else None)
            or compute_selling_price(
                getattr(contract, 'cost_price', None),
                getattr(contract, 'markup_pct', None),
            )
        ),
        'latest_sharia': latest,
        'committee_blockers': murabaha_committee_blockers(loan_request),
        'disbursement_blockers': murabaha_disbursement_blockers(loan_request),
        'fund': fund_file_summary(loan_request),
    }


def can_view_murabaha_file(user, loan_request) -> bool:
    if not is_murabaha_file(loan_request):
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


def can_edit_murabaha_file(user, loan_request) -> bool:
    if not can_view_murabaha_file(user, loan_request):
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
