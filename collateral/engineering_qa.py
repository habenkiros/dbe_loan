"""Engineering QA workflow after collateral submit."""

from __future__ import annotations

from typing import Any, Dict, List

from loans.collateral_config import allows_engineering_team


def engineering_review_required() -> bool:
    return allows_engineering_team()


def user_can_see_unlock_queue(user) -> bool:
    """Unlock queue is an engineering desk, not admin Settings."""
    role = getattr(user, 'role', None)
    if role == 'engineering_head':
        return True
    if role == 'branch_manager' and not engineering_review_required():
        return True
    return False


def initial_engineering_status(submitter) -> str:
    """Status set on collateral submit when engineering mode is enabled."""
    from loans.models import LoanRequest

    if not engineering_review_required():
        return LoanRequest.ENG_COLLATERAL_NA
    role = getattr(submitter, 'role', None)
    if role == 'engineering_head':
        return LoanRequest.ENG_COLLATERAL_APPROVED
    return LoanRequest.ENG_COLLATERAL_PENDING


def can_review_engineering(user, loan_request) -> bool:
    if not engineering_review_required():
        return False
    from loans.models import LoanRequest

    if loan_request.collateral_engineering_status != LoanRequest.ENG_COLLATERAL_PENDING:
        return False
    if not loan_request.collateral_submitted_at:
        return False
    role = getattr(user, 'role', None)
    if role in ('engineering_head', 'admin', 'superadmin'):
        return True
    if role == 'engineer' and loan_request.assigned_engineer_id == user.id:
        return True
    return False


def engineering_pending_loans(user=None):
    from loans.models import LoanRequest

    qs = LoanRequest.objects.filter(
        collateral_submitted_at__isnull=False,
        collateral_engineering_status=LoanRequest.ENG_COLLATERAL_PENDING,
    ).select_related('branch', 'collateral', 'assigned_engineer', 'collateral_submitted_by')
    if user:
        role = getattr(user, 'role', None)
        if role == 'engineer':
            qs = qs.filter(assigned_engineer=user)
        elif role == 'branch_manager' and getattr(user, 'branch_id', None):
            qs = qs.filter(branch_id=user.branch_id)
    return qs.order_by('-collateral_submitted_at')


def engineering_qa_checklist(loan_request) -> Dict[str, Any]:
    """Five-point engineering review: coverage, GPS, evidence, valuation, ownership."""
    from collateral.coverage import compute_coverage_adequacy
    from collateral.field_utils import get_loan_collateral_readiness
    from collateral.models import (
        Building, BuildingImage, LandValuationImage,
    )
    from collateral.registration import failed_check_labels, ownership_checks

    coverage = compute_coverage_adequacy(loan_request)
    readiness = get_loan_collateral_readiness(loan_request)
    coverage_ok = bool(coverage.get('adequate_for_submit'))

    gps_ok = True
    gps_detail = []
    for row in readiness.get('buildings') or []:
        b = row['building']
        if b.site_gps_lat is None or b.site_gps_lon is None:
            gps_ok = False
            gps_detail.append(f'{b.name}: no site GPS')
        elif not BuildingImage.objects.filter(
            building=b, gps_lat__isnull=False, gps_lon__isnull=False,
        ).exists():
            gps_ok = False
            gps_detail.append(f'{b.name}: no photo GPS')
    land_row = readiness.get('land')
    if land_row:
        land = land_row['land']
        if land.site_gps_lat is None:
            gps_ok = False
            gps_detail.append('Land: no site GPS')
        elif not LandValuationImage.objects.filter(
            land_valuation=land, gps_lat__isnull=False, gps_lon__isnull=False,
        ).exists():
            gps_ok = False
            gps_detail.append('Land: no photo GPS')
    # Movable / vehicle: plate & VIN — GPS is not part of engineering GPS gate.
    if not gps_detail:
        gps_detail.append('GPS on file')

    evidence_ok = bool(readiness.get('all_ready')) if readiness.get('applies') else True
    evidence_detail = []
    if readiness.get('applies') and not evidence_ok:
        for row in readiness.get('buildings') or []:
            if not row['readiness']['ready']:
                evidence_detail.append(
                    f'{row["building"].name}: {"; ".join(failed_check_labels(row["readiness"]))}'
                )
        if land_row and not land_row['readiness']['ready']:
            evidence_detail.append(f'Land: {"; ".join(failed_check_labels(land_row["readiness"]))}')
        for row in readiness.get('other_items') or []:
            if not row['readiness']['ready']:
                evidence_detail.append(
                    f'{row["item"].name}: {"; ".join(failed_check_labels(row["readiness"]))}'
                )
    if not evidence_detail:
        evidence_detail.append('Field evidence complete' if evidence_ok else 'No collateral file yet')

    valuation_ok = True
    valuation_detail = []
    for row in readiness.get('buildings') or []:
        total = row['readiness'].get('building_total') or 0
        if total <= 0:
            valuation_ok = False
            valuation_detail.append(f'{row["building"].name}: BOQ is empty')
    if land_row:
        land = land_row['land']
        if not land.total_value:
            valuation_ok = False
            valuation_detail.append('Land: size × price missing')
    for row in readiness.get('other_items') or []:
        if not (row['item'].estimated_value or 0) > 0:
            valuation_ok = False
            valuation_detail.append(f'{row["item"].name}: estimated value is 0')
    if not valuation_detail:
        valuation_detail.append('Valuation on file')

    ownership_ok = True
    ownership_detail = []
    assets = [row['building'] for row in readiness.get('buildings') or []]
    if land_row:
        assets.append(land_row['land'])
    assets.extend(row['item'] for row in readiness.get('other_items') or [])
    for asset in assets:
        fails = [c['label'] for c in ownership_checks(asset, loan_request) if not c['ok']]
        if fails:
            ownership_ok = False
            ownership_detail.append(f'{asset}: {"; ".join(fails)}')
    if not ownership_detail:
        ownership_detail.append('Owner recorded')

    items = [
        {'key': 'coverage', 'label': 'Coverage vs loan amount', 'ok': coverage_ok,
         'detail': '; '.join(coverage.get('blockers') or ['Meets policy'])},
        {'key': 'gps', 'label': 'Site / photo GPS', 'ok': gps_ok, 'detail': '; '.join(gps_detail)},
        {'key': 'evidence', 'label': 'Photos and evidence pack', 'ok': evidence_ok,
         'detail': '; '.join(evidence_detail)},
        {'key': 'valuation', 'label': 'Valuation / BOQ complete', 'ok': valuation_ok,
         'detail': '; '.join(valuation_detail)},
        {'key': 'ownership', 'label': 'Owner and title recorded', 'ok': ownership_ok,
         'detail': '; '.join(ownership_detail)},
    ]
    return {
        'items': items,
        'all_ok': all(i['ok'] for i in items),
        'blockers': [i['label'] for i in items if not i['ok']],
    }


def engineering_qa_approve_blockers(loan_request, form_data) -> List[str]:
    """Reasons an engineer cannot approve yet — missing ticks or failed checks."""
    from collateral.forms import CollateralEngineeringReviewForm

    checklist = engineering_qa_checklist(loan_request)
    blockers = list(checklist.get('blockers') or [])
    for field in CollateralEngineeringReviewForm.QA_TICK_FIELDS:
        if not form_data.get(field):
            blockers.append('Tick every QA item before approving')
            break
    return blockers
