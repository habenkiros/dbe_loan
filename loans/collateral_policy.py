"""Which security types a product family may use.

DECSI general: any pledged type. Lease / Ijarah: the machine or vehicle this
loan buys (bank holds title) — not the customer's existing land. Project: site
(land/building) and/or plant financed by the loan; the mix is per file.
"""

from __future__ import annotations

from typing import Sequence

from loans.collateral_kind import (
    KIND_BUILDING,
    KIND_FINANCED,
    KIND_LAND,
    KIND_MIXED,
    KIND_MOVABLE,
)
from loans.product_family import (
    FAMILY_CONSUMER,
    FAMILY_EXTERNAL_FUND,
    FAMILY_GENERAL,
    FAMILY_IDEA_EQUITY,
    FAMILY_IFB_IJARAH,
    FAMILY_IFB_MURABAHA,
    FAMILY_LEASE,
    FAMILY_PROJECT,
    FAMILY_WHOLESALE,
)

# Empty tuple = no physical security (wholesale PFI, idea/equity).
FAMILY_COLLATERAL_KINDS = {
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

FINANCED_TYPE_SPECS = (
    ('Financed machinery / plant (from this loan)', KIND_FINANCED),
    ('Financed vehicle (from this loan)', KIND_FINANCED),
)


def kinds_for_family(family: str) -> Sequence[str]:
    return FAMILY_COLLATERAL_KINDS.get(family or FAMILY_GENERAL, FAMILY_COLLATERAL_KINDS[FAMILY_GENERAL])


def family_restricts_collateral(family: str) -> bool:
    """True when empty M2M must not mean 'any type'."""
    family = family or FAMILY_GENERAL
    return family not in (FAMILY_GENERAL, FAMILY_EXTERNAL_FUND)


def ensure_financed_collateral_types():
    from loans.models import CollateralType

    created = []
    for name, kind in FINANCED_TYPE_SPECS:
        obj, was = CollateralType.objects.get_or_create(
            name=name, defaults={'kind': kind},
        )
        if not was and obj.kind != kind:
            obj.kind = kind
            obj.save(update_fields=['kind'])
        created.append(obj)
    return created


def types_for_kinds(kinds: Sequence[str]):
    from loans.models import CollateralType

    if not kinds:
        return CollateralType.objects.none()
    return CollateralType.objects.filter(kind__in=list(kinds)).order_by('name')


def default_types_for_family(family: str):
    return types_for_kinds(kinds_for_family(family))


def collateral_queryset_for_category(category):
    """Prefer category.allowed_collateral; else family policy."""
    from loans.models import CollateralType

    all_types = CollateralType.objects.order_by('name')
    if category is None or not getattr(category, 'pk', None):
        return all_types
    from loans.family_policy import category_requires_collateral
    if not category_requires_collateral(category):
        return CollateralType.objects.none()
    family = getattr(category, 'product_family', None) or FAMILY_GENERAL
    if category.allowed_collateral.exists():
        return category.allowed_collateral.order_by('name')
    if not family_restricts_collateral(family):
        return all_types
    qs = default_types_for_family(family)
    if qs.exists():
        return qs
    return CollateralType.objects.none()
