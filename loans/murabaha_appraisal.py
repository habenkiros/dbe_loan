"""Murabaha appraisal — cost-plus scorecard + officer recommendation.

Not MSME Sheets 1–7 and not an interest schedule. Selling price is cost + markup.
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
from loans.murabaha_overlay import (
    HO_COST_THRESHOLD,
    compute_selling_price,
    get_murabaha,
    is_murabaha_file,
)

ZERO = Decimal('0')
ALGORITHM = 'MURABAHA_SCORE_V1'
# Soft band for markup quality — not a hard product ban (policy blockers handle required fields).
MARKUP_SOFT_MAX = Decimal('25')
MARKUP_EXPORT_SOFT_MAX = Decimal('15')


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


def build_murabaha_scorecard(loan_request, contract=None) -> Dict[str, Any]:
    """Explainable 0–100 score from cost-plus structure, pack, routing, delivery."""
    contract = contract or get_murabaha(loan_request)
    pillars: List[Dict[str, Any]] = []
    total = ZERO

    selling = None
    if contract:
        selling = contract.selling_price or compute_selling_price(
            contract.cost_price, contract.markup_pct,
        )

    # --- Cost-plus structure (max 30) ---
    struct_pts = ZERO
    struct_bits = []
    if contract and contract.cost_price and contract.cost_price > 0:
        struct_pts += Decimal('12')
        struct_bits.append('cost')
    if contract and contract.markup_pct is not None and contract.markup_pct >= 0:
        soft_max = MARKUP_EXPORT_SOFT_MAX
        from loans.models import MurabahaContract
        if contract.scope != MurabahaContract.SCOPE_EXPORT:
            soft_max = MARKUP_SOFT_MAX
        if contract.markup_pct <= soft_max:
            struct_pts += Decimal('12')
            struct_bits.append(f'markup {contract.markup_pct}%')
        else:
            struct_pts += Decimal('5')
            struct_bits.append(f'markup {contract.markup_pct}% elevated')
    if selling and selling > 0:
        struct_pts += Decimal('6')
        struct_bits.append('selling price')
    struct_note = ('Set: ' + ', '.join(struct_bits)) if struct_bits else 'Cost / markup / selling open'
    pillars.append({
        'key': 'structure', 'label': 'Cost-plus structure',
        'max': 30, 'earned': struct_pts, 'note': struct_note,
    })
    total += struct_pts

    # --- Contract pack (max 25) ---
    pack_pts = ZERO
    pack_bits = []
    if contract and (contract.goods_description or '').strip():
        pack_pts += Decimal('7')
        pack_bits.append('goods')
    if contract and (contract.supplier_name or '').strip():
        pack_pts += Decimal('6')
        pack_bits.append('supplier')
    if contract and (contract.supplier_offer_ref or '').strip():
        pack_pts += Decimal('6')
        pack_bits.append('offer ref')
    if contract and contract.tenor_months:
        pack_pts += Decimal('6')
        pack_bits.append('tenor')
    pack_note = ('On file: ' + ', '.join(pack_bits)) if pack_bits else 'Goods / supplier / offer / tenor open'
    pillars.append({
        'key': 'pack', 'label': 'Contract pack',
        'max': 25, 'earned': pack_pts, 'note': pack_note,
    })
    total += pack_pts

    # --- Scope / HO routing (max 25) ---
    route_pts = ZERO
    route_bits = []
    if contract and contract.scope:
        route_pts += Decimal('10')
        route_bits.append(contract.get_scope_display() if hasattr(contract, 'get_scope_display') else str(contract.scope))
    cost = getattr(contract, 'cost_price', None) if contract else None
    if cost and cost >= HO_COST_THRESHOLD:
        if contract.routed_to_ifb_ho:
            route_pts += Decimal('15')
            route_bits.append('IFB HO routed')
        else:
            route_bits.append('IFB HO still required')
    else:
        route_pts += Decimal('15')
        route_bits.append('branch-scale')
    route_note = ('Ok: ' + ', '.join(route_bits)) if route_bits else 'Scope / HO routing open'
    pillars.append({
        'key': 'routing', 'label': 'Scope / HO routing',
        'max': 25, 'earned': route_pts, 'note': route_note,
    })
    total += route_pts

    # --- Delivery readiness (max 20) — soft for committee; hard at disbursement ---
    del_pts = ZERO
    del_note = 'Delivery status open'
    if contract:
        from loans.models import MurabahaContract
        status = contract.delivery_status
        if status in (MurabahaContract.DELIVERY_RECEIVED, MurabahaContract.DELIVERY_SOLD):
            del_pts = Decimal('20')
            del_note = contract.get_delivery_status_display()
        elif status == MurabahaContract.DELIVERY_ORDERED:
            del_pts = Decimal('8')
            del_note = 'Ordered — release still needs received/sold'
        elif status:
            del_pts = Decimal('4')
            del_note = contract.get_delivery_status_display()
    pillars.append({
        'key': 'delivery', 'label': 'Delivery readiness',
        'max': 20, 'earned': del_pts, 'note': del_note,
    })
    total += del_pts

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
        'modality': 'murabaha',
        'total': total,
        'band': band,
        'band_label': band_label,
        'pillars': pillars,
        'cost_price': getattr(contract, 'cost_price', None) if contract else None,
        'markup_pct': getattr(contract, 'markup_pct', None) if contract else None,
        'selling_price': selling,
        'tenor_months': getattr(contract, 'tenor_months', None) if contract else None,
        'goods_description': (contract.goods_description if contract else '') or '',
        'supplier_name': (contract.supplier_name if contract else '') or '',
        'ho_threshold': HO_COST_THRESHOLD,
    }


def sync_murabaha_decision_to_appraisal(
    loan_request,
    contract,
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
    """Write officer Murabaha decision onto LoanAppraisal and persist scorecard."""
    from loans.models import LoanAppraisal

    appraisal, _ = LoanAppraisal.objects.get_or_create(
        loan_request=loan_request,
        defaults={'created_by': user},
    )
    term = term_approved_months or getattr(contract, 'tenor_months', None)
    amount = amount_approved
    if amount is None:
        amount = (
            getattr(contract, 'selling_price', None)
            or compute_selling_price(
                getattr(contract, 'cost_price', None),
                getattr(contract, 'markup_pct', None),
            )
        )
    rate = rate_approved
    if rate is None:
        rate = getattr(contract, 'markup_pct', None)

    appraisal.recommendation = recommendation or None
    appraisal.amount_approved = amount
    appraisal.term_approved_months = term
    appraisal.rate_approved = rate
    appraisal.recommendation_comment = (recommendation_comment or '').strip() or None
    appraisal.strengths = (strengths or '').strip() or None
    appraisal.weaknesses = (weaknesses or '').strip() or None
    if not appraisal.created_by_id:
        appraisal.created_by = user

    card = build_murabaha_scorecard(loan_request, contract)
    appraisal.credit_score_total = card['total']
    appraisal.credit_score_band = card['band']
    appraisal.scorecard_detail = scorecard_for_storage(card)
    appraisal.save()
    if recommendation and not getattr(loan_request, 'appraisal_completed_at', None):
        loan_request.appraisal_completed_at = timezone.now()
        loan_request.save(update_fields=['appraisal_completed_at'])
    return appraisal, card


def murabaha_appraisal_blockers(loan_request) -> List[str]:
    if not is_murabaha_file(loan_request):
        return []
    from loans.models import LoanAppraisal

    blockers = []
    appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
    if appraisal is None or not appraisal.recommendation:
        blockers.append(
            'Complete Murabaha appraisal: record Approve / Decline / Escalate on the Murabaha desk.'
        )
    if appraisal is None or not appraisal.amount_approved or appraisal.amount_approved <= 0:
        blockers.append('Enter the recommended selling / financed amount on the Murabaha desk.')
    if appraisal is None or appraisal.rate_approved is None:
        blockers.append('Enter the recommended markup % on the Murabaha desk (not an interest rate).')
    if appraisal is None or not appraisal.term_approved_months:
        blockers.append('Enter the recommended tenor (months) on the Murabaha desk.')
    return blockers
