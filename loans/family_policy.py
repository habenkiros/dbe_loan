"""Configurable product-family defaults (appraisal desk + collateral).

Python FALLBACK_* is used until ProductFamilyPolicy rows exist, and if the
table cannot be read (migrations). Credit can change mappings in admin /
the category screen without a code deploy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loans.appraisal_mode import ALL_MODES, MODE_MSME
from loans.collateral_kind import (
    KIND_BUILDING,
    KIND_FINANCED,
    KIND_LAND,
    KIND_MIXED,
    KIND_MOVABLE,
)
from loans.product_family import (
    FAMILY_CHOICES,
    FAMILY_CONSUMER,
    FAMILY_EXTERNAL_FUND,
    FAMILY_GENERAL,
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
    SUGGESTED_APPRAISAL_MODE,
)

FALLBACK_REQUIRES_COLLATERAL = {
    FAMILY_GENERAL: True,
    FAMILY_EXTERNAL_FUND: True,
    FAMILY_PROJECT: True,
    FAMILY_LEASE: True,
    FAMILY_IFB_IJARAH: True,
    FAMILY_IFB_MURABAHA: True,
    FAMILY_CONSUMER: True,
    FAMILY_WHOLESALE: False,
    FAMILY_IDEA_EQUITY: False,
}

FALLBACK_COLLATERAL_KINDS = {
    FAMILY_GENERAL: (KIND_BUILDING, KIND_LAND, KIND_MOVABLE, KIND_MIXED),
    FAMILY_EXTERNAL_FUND: (KIND_BUILDING, KIND_LAND, KIND_MOVABLE, KIND_MIXED),
    FAMILY_PROJECT: (KIND_BUILDING, KIND_LAND, KIND_MIXED, KIND_FINANCED),
    FAMILY_LEASE: (KIND_FINANCED,),
    FAMILY_IFB_IJARAH: (KIND_FINANCED,),
    FAMILY_IFB_MURABAHA: (KIND_FINANCED, KIND_MOVABLE),
    FAMILY_CONSUMER: (KIND_BUILDING, KIND_FINANCED),
    FAMILY_WHOLESALE: (),
    FAMILY_IDEA_EQUITY: (),
}


def _policy_row(family: str):
    try:
        from loans.models import ProductFamilyPolicy
        return ProductFamilyPolicy.objects.filter(family=family).first()
    except Exception:
        return None


def default_appraisal_for_family(family: Optional[str]) -> Optional[str]:
    """None = General, officer may pick MSME vs corporate."""
    family = family or FAMILY_GENERAL
    if family == FAMILY_GENERAL:
        return None
    row = _policy_row(family)
    if row is not None:
        mode = (row.default_appraisal_mode or '').strip()
        if mode in ALL_MODES:
            return mode
    suggested = SUGGESTED_APPRAISAL_MODE.get(family)
    if suggested in ALL_MODES:
        return suggested
    if family in ALL_MODES:
        return family
    return MODE_MSME


def family_requires_collateral(family: Optional[str]) -> bool:
    family = family or FAMILY_GENERAL
    row = _policy_row(family)
    if row is not None:
        return bool(row.requires_collateral)
    return bool(FALLBACK_REQUIRES_COLLATERAL.get(family, True))


def category_requires_collateral(category) -> bool:
    """Per-category flag, or family default when the flag is blank."""
    if category is None:
        return True
    flag = getattr(category, 'requires_collateral', None)
    if flag is None:
        return family_requires_collateral(getattr(category, 'product_family', None))
    return bool(flag)


def default_collateral_ids_for_family(family: Optional[str]) -> List[int]:
    family = family or FAMILY_GENERAL
    row = _policy_row(family)
    if row is not None and row.pk:
        ids = list(row.default_collateral.values_list('id', flat=True))
        if ids:
            return ids
    from loans.collateral_policy import types_for_kinds
    kinds = FALLBACK_COLLATERAL_KINDS.get(family, FALLBACK_COLLATERAL_KINDS[FAMILY_GENERAL])
    return list(types_for_kinds(kinds).values_list('id', flat=True))


def policy_payload(family: Optional[str]) -> Dict[str, Any]:
    from loans.models import CollateralType, LoanCategory

    family = family or FAMILY_GENERAL
    appraisal = default_appraisal_for_family(family) or MODE_MSME
    requires = family_requires_collateral(family)
    coll_ids = default_collateral_ids_for_family(family) if requires else []
    collaterals = list(
        CollateralType.objects.filter(pk__in=coll_ids).order_by('name').values('id', 'name')
    )
    return {
        'family': family,
        'family_label': dict(FAMILY_CHOICES).get(family, family),
        'appraisal_mode': appraisal,
        'requires_collateral': requires,
        'collaterals': collaterals,
        'appraisal_choices': [
            {'id': k, 'label': v} for k, v in LoanCategory.APPRAISAL_MODE_CHOICES
        ],
    }


def ensure_family_policies():
    """Idempotent seed of one policy row per family."""
    from loans.collateral_policy import ensure_financed_collateral_types, types_for_kinds
    from loans.models import ProductFamilyPolicy

    ensure_financed_collateral_types()
    created = 0
    for family, label in FAMILY_CHOICES:
        default_mode = SUGGESTED_APPRAISAL_MODE.get(family) or MODE_MSME
        if family == FAMILY_GENERAL:
            default_mode = MODE_MSME
        row, was = ProductFamilyPolicy.objects.get_or_create(
            family=family,
            defaults={
                'name': label,
                'default_appraisal_mode': default_mode,
                'requires_collateral': FALLBACK_REQUIRES_COLLATERAL.get(family, True),
            },
        )
        if was:
            created += 1
            kinds = FALLBACK_COLLATERAL_KINDS.get(family) or ()
            if kinds:
                row.default_collateral.set(types_for_kinds(kinds))
        elif not row.name:
            row.name = label
            row.save(update_fields=['name'])
    return created
