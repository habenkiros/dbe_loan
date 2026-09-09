"""Registration identity for collateral assets — owner, title paper, financed vs owned."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Sequence, Tuple

from collateral.models import CollateralTitleMixin, OtherCollateralItem
from loans.collateral_kind import is_financed_asset


TITLE_FIELDS = ('owner_kind', 'owner_name', 'title_reference', 'title_office')

FINANCED_PHOTO_TYPES = (
    ('offer', 'Supplier offer / invoice'),
    ('asset', 'Full asset / specification'),
)


def resolved_owner_name(asset, loan_request) -> str:
    named = (getattr(asset, 'owner_name', None) or '').strip()
    if named:
        return named
    kind = getattr(asset, 'owner_kind', None) or CollateralTitleMixin.OWNER_BORROWER
    if kind == CollateralTitleMixin.OWNER_BORROWER:
        return (getattr(loan_request, 'applicant_name', None) or '').strip()
    if kind == CollateralTitleMixin.OWNER_BANK:
        try:
            from loans.branding import institution_short
            return institution_short()
        except Exception:
            return 'Bank'
    return ''


def ownership_checks(asset, loan_request) -> List[dict]:
    kind = getattr(asset, 'owner_kind', None) or CollateralTitleMixin.OWNER_BORROWER
    name = resolved_owner_name(asset, loan_request)
    ref = (getattr(asset, 'title_reference', None) or '').strip()
    checks = [
        {
            'key': 'owner',
            'label': 'Owner recorded',
            'ok': bool(name),
            'detail': name or 'Name the owner (or leave borrower as the applicant)',
        },
    ]
    if kind == CollateralTitleMixin.OWNER_THIRD_PARTY:
        checks.append({
            'key': 'third_party_title',
            'label': 'Third-party title / deed reference',
            'ok': bool(ref),
            'detail': ref or 'Deed or plot number is required when the owner is not the borrower',
        })
    return checks


def item_is_to_be_purchased(item) -> bool:
    if item is None:
        return False
    if getattr(item, 'acquisition_status', None) == OtherCollateralItem.ACQ_TO_BUY:
        return True
    return is_financed_asset(getattr(item, 'loan_request', None))


def required_movable_photo_types(item) -> Sequence[Tuple[str, str]]:
    from collateral import constants

    if item_is_to_be_purchased(item):
        return FINANCED_PHOTO_TYPES
    return constants.REQUIRED_MOVABLE_PHOTO_TYPES


def movable_identity_ok(item) -> bool:
    if item_is_to_be_purchased(item):
        return True
    plate = (getattr(item, 'plate_number', None) or '').strip()
    vin = (getattr(item, 'chassis_vin', None) or '').strip()
    return bool(plate or vin)


def apply_financed_defaults(item, loan_request) -> None:
    """Stamp bank-title / to-buy when this product finances the asset."""
    if not is_financed_asset(loan_request):
        return
    item.acquisition_status = OtherCollateralItem.ACQ_TO_BUY
    item.owner_kind = CollateralTitleMixin.OWNER_BANK
    from django.core.exceptions import ObjectDoesNotExist

    try:
        lease = loan_request.lease_asset
    except (ObjectDoesNotExist, AttributeError):
        lease = None
    if lease is not None:
        item.name = (lease.asset_description or lease.make_model or item.name or 'Financed asset').strip()
        item.make_model = item.make_model or (lease.make_model or '')
        if not item.estimated_value and lease.asset_price:
            item.estimated_value = lease.asset_price
        item.title_reference = item.title_reference or (lease.supplier_invoice_ref or '')
        return
    try:
        contract = loan_request.murabaha
    except (ObjectDoesNotExist, AttributeError):
        contract = None
    if contract is not None:
        item.name = (contract.goods_description or item.name or 'Murabaha goods').strip()
        item.title_reference = item.title_reference or (contract.supplier_offer_ref or '')
        if not item.estimated_value and contract.cost_price:
            item.estimated_value = contract.cost_price


def new_movable_item(loan_request):
    item = OtherCollateralItem(
        loan_request=loan_request,
        name='Collateral item',
        estimated_value=Decimal('0'),
    )
    apply_financed_defaults(item, loan_request)
    item.save()
    return item


def failed_check_labels(readiness: dict) -> List[str]:
    labels = []
    for check in readiness.get('checks') or []:
        if check.get('ok') or check.get('optional'):
            continue
        labels.append(check.get('label') or check.get('key') or 'incomplete')
    return labels
