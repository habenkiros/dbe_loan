"""Collateral type kind — which estimation engines apply to a loan.

Loan type (credit product) does not pick the math. CollateralType.kind does:
building BOQ, land m², movable estimated value, or mixed (sum of those that apply).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

KIND_BUILDING = 'building'
KIND_LAND = 'land'
KIND_MOVABLE = 'movable'
KIND_MIXED = 'mixed'
KIND_FINANCED = 'financed'

KIND_CHOICES = [
    (KIND_BUILDING, 'Building / house (BOQ)'),
    (KIND_LAND, 'Land (size × price)'),
    (KIND_MOVABLE, 'Vehicle / machinery / other movable (already owned)'),
    (KIND_MIXED, 'Mixed (sum engines that apply)'),
    (KIND_FINANCED, 'Financed by this loan (asset to be bought)'),
]


def infer_kind_from_name(name: str) -> str:
    """Best-effort map from the display name (used to backfill existing rows)."""
    n = (name or '').lower()
    if 'financed' in n or 'from this loan' in n:
        return KIND_FINANCED
    has_building = any(x in n for x in ('building', 'house', 'construction'))
    has_land = 'land' in n
    has_movable = any(x in n for x in ('vehicle', 'machinery', 'equipment', 'movable'))
    # "other" alone is movable; "other" inside mixed names is ignored if building/land already matched
    if 'other' in n and not has_building and not has_land:
        has_movable = True
    matched = sum(1 for flag in (has_building, has_land, has_movable) if flag)
    if matched > 1:
        return KIND_MIXED
    if has_building:
        return KIND_BUILDING
    if has_land:
        return KIND_LAND
    if has_movable:
        return KIND_MOVABLE
    return KIND_MIXED


def resolve_type_kind(collateral_type) -> str:
    if collateral_type is None:
        return KIND_MIXED
    kind = (getattr(collateral_type, 'kind', None) or '').strip()
    if kind in (KIND_BUILDING, KIND_LAND, KIND_MOVABLE, KIND_MIXED, KIND_FINANCED):
        return kind
    return infer_kind_from_name(getattr(collateral_type, 'name', '') or '')


def resolve_loan_kind(loan_request) -> str:
    return resolve_type_kind(getattr(loan_request, 'collateral', None))


def engines_for_kind(kind: str) -> Dict[str, bool]:
    if kind == KIND_BUILDING:
        return {'building': True, 'land': False, 'movable': False}
    if kind == KIND_LAND:
        return {'building': False, 'land': True, 'movable': False}
    if kind == KIND_MOVABLE or kind == KIND_FINANCED:
        return {'building': False, 'land': False, 'movable': True}
    return {'building': True, 'land': True, 'movable': True}


def engines_for_loan(loan_request) -> Dict[str, bool]:
    return engines_for_kind(resolve_loan_kind(loan_request))


def is_financed_asset(obj) -> bool:
    """True when the security *is* the asset this loan will buy (lease/project plant)."""
    if obj is None:
        return False
    if hasattr(obj, 'collateral') and not hasattr(obj, 'kind'):
        return resolve_loan_kind(obj) == KIND_FINANCED
    return resolve_type_kind(obj) == KIND_FINANCED


def uses_building(obj) -> bool:
    """obj is a CollateralType or a LoanRequest."""
    if obj is None:
        return True
    if hasattr(obj, 'collateral') and not hasattr(obj, 'kind'):
        return engines_for_loan(obj)['building']
    return engines_for_kind(resolve_type_kind(obj))['building']


def uses_land(obj) -> bool:
    if obj is None:
        return True
    if hasattr(obj, 'collateral') and not hasattr(obj, 'kind'):
        return engines_for_loan(obj)['land']
    return engines_for_kind(resolve_type_kind(obj))['land']


def uses_movable(obj) -> bool:
    if obj is None:
        return True
    if hasattr(obj, 'collateral') and not hasattr(obj, 'kind'):
        return engines_for_loan(obj)['movable']
    return engines_for_kind(resolve_type_kind(obj))['movable']


def compute_engine_totals(loan_request) -> Dict[str, Any]:
    """Raw engine totals plus grand_total using CollateralType.kind (not name parsing)."""
    from collateral.models import Building, BuildingValuation, LandValuation, OtherCollateralItem

    buildings = Building.objects.filter(loan_request=loan_request)
    total_buildings = Decimal('0')
    for building in buildings:
        rows = BuildingValuation.objects.filter(building=building)
        total_buildings += sum((r.total or Decimal('0')) for r in rows)
    try:
        land = LandValuation.objects.get(loan_request=loan_request)
        land_value = land.total_value or Decimal('0')
    except LandValuation.DoesNotExist:
        land_value = Decimal('0')
    other_items = OtherCollateralItem.objects.filter(loan_request=loan_request)
    total_other = sum((item.estimated_value or Decimal('0')) for item in other_items) or Decimal('0')

    engines = engines_for_loan(loan_request)
    grand = Decimal('0')
    immovable = Decimal('0')
    moveable = Decimal('0')
    if engines['building']:
        grand += total_buildings
        immovable += total_buildings
    if engines['land']:
        grand += land_value
        immovable += land_value
    if engines['movable']:
        grand += total_other
        moveable += total_other
    return {
        'total_buildings': total_buildings,
        'land_value': land_value,
        'total_other': total_other,
        'grand_total': grand,
        'collateral_immovable_value': immovable,
        'collateral_moveable_value': moveable,
        'engines': engines,
        'kind': resolve_loan_kind(loan_request),
    }
