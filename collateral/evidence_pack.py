"""Collateral evidence pack for committee review and audit."""

from __future__ import annotations

from typing import Any, Dict, List

from collateral.coverage import compute_coverage_adequacy
from collateral.field_utils import get_loan_collateral_readiness
from collateral.map_utils import building_map_data, land_map_data, other_item_map_data
from collateral.models import (
    Building, BuildingImage, BuildingValuation, CollateralFieldAuditLog,
    LandValuation, LandValuationImage, OtherCollateralItem, OtherCollateralItemImage,
)
from collateral.policy import get_collateral_policy
from loans.services.appraisal_prefill import compute_collateral_totals


def build_collateral_evidence_pack(loan_request) -> Dict[str, Any]:
    """Read-only bundle: totals, coverage, maps, photos, audit trail."""
    policy = get_collateral_policy()
    totals = compute_collateral_totals(loan_request)
    coverage = compute_coverage_adequacy(loan_request)
    readiness = get_loan_collateral_readiness(loan_request)

    buildings_data: List[Dict[str, Any]] = []
    for b in Building.objects.filter(loan_request=loan_request).select_related(
        'city', 'city__zone', 'city__zone__region',
    ):
        vals = BuildingValuation.objects.filter(building=b).select_related('sub_work', 'sub_sub_work')
        building_total = sum(v.total for v in vals)
        images = list(BuildingImage.objects.filter(building=b).order_by('created_at'))
        buildings_data.append({
            'building': b,
            'total': building_total,
            'valuations': list(vals),
            'images': images,
            'map_data': building_map_data(b),
        })

    land_data = None
    land = LandValuation.objects.filter(loan_request=loan_request).first()
    if land:
        land_data = {
            'land': land,
            'images': list(LandValuationImage.objects.filter(land_valuation=land).order_by('created_at')),
            'map_data': land_map_data(land),
        }

    other_data: List[Dict[str, Any]] = []
    for item in OtherCollateralItem.objects.filter(loan_request=loan_request):
        other_data.append({
            'item': item,
            'images': list(OtherCollateralItemImage.objects.filter(item=item).order_by('created_at')),
            'map_data': other_item_map_data(item),
        })

    audit_logs = list(
        CollateralFieldAuditLog.objects.filter(loan_request=loan_request)
        .select_related('performed_by')
        .order_by('-performed_at')[:100]
    )

    pending_unlock = None
    from collateral.models import CollateralUnlockRequest
    pending_unlock = CollateralUnlockRequest.objects.filter(
        loan_request=loan_request,
        status=CollateralUnlockRequest.STATUS_PENDING,
    ).select_related('requested_by').first()

    return {
        'loan_request': loan_request,
        'policy': policy,
        'totals': totals,
        'coverage': coverage,
        'readiness': readiness,
        'buildings_data': buildings_data,
        'land_data': land_data,
        'other_data': other_data,
        'audit_logs': audit_logs,
        'pending_unlock': pending_unlock,
    }
