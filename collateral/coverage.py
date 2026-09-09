"""Collateral coverage vs loan amount and policy adequacy flags."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from collateral.policy import get_collateral_policy
from loans.services.appraisal_prefill import compute_collateral_totals


def compute_coverage_adequacy(loan_request) -> Dict[str, Any]:
    """
    Coverage ratio and policy flags for summary / loan detail / evidence pack.
    """
    policy = get_collateral_policy()
    totals = compute_collateral_totals(loan_request)
    requested = loan_request.amount_requested or Decimal('0')
    approved = getattr(loan_request, 'committee_final_amount', None)
    amount = approved if approved else requested
    grand = totals.get('grand_total') or Decimal('0')

    ratio = None
    ratio_pct = None
    if amount > 0 and grand > 0:
        ratio = (grand / amount).quantize(Decimal('0.0001'))
        ratio_pct = (ratio * 100).quantize(Decimal('0.01'))

    flags: List[Dict[str, str]] = []
    warnings: List[str] = []
    blockers: List[str] = []

    if amount > 0 and grand <= 0:
        flags.append({'level': 'warn', 'key': 'no_collateral_value', 'message': 'No collateral value recorded yet.'})
        warnings.append('No collateral value recorded.')
    elif ratio is not None:
        if ratio < policy.min_coverage_ratio:
            msg = (
                f'Coverage {ratio_pct}% is below minimum policy '
                f'({policy.min_coverage_ratio * 100:.0f}% of loan amount).'
            )
            flags.append({'level': 'block', 'key': 'coverage_below_min', 'message': msg})
            blockers.append(msg)
        elif ratio < policy.flag_coverage_below_ratio:
            msg = (
                f'Coverage {ratio_pct}% is below advisory threshold '
                f'({policy.flag_coverage_below_ratio * 100:.0f}%).'
            )
            flags.append({'level': 'warn', 'key': 'coverage_advisory', 'message': msg})
            warnings.append(msg)
        else:
            flags.append({'level': 'ok', 'key': 'coverage_ok', 'message': f'Coverage {ratio_pct}% meets policy.'})

    geo_flags = _geo_policy_flags(loan_request, policy)
    flags.extend(geo_flags['flags'])
    warnings.extend(geo_flags['warnings'])
    blockers.extend(geo_flags['blockers'])

    declared_flags = _declared_address_flags(loan_request, policy)
    flags.extend(declared_flags['flags'])
    warnings.extend(declared_flags['warnings'])
    blockers.extend(declared_flags['blockers'])

    exif_flags = _exif_gps_flags(loan_request, policy)
    flags.extend(exif_flags['flags'])
    warnings.extend(exif_flags['warnings'])
    blockers.extend(exif_flags['blockers'])

    return {
        'amount_requested': amount,
        'requested_amount': requested,
        'coverage_amount': amount,
        'uses_committee_amount': bool(approved),
        'grand_total': grand,
        'immovable': totals.get('collateral_immovable_value') or Decimal('0'),
        'moveable': totals.get('collateral_moveable_value') or Decimal('0'),
        'coverage_ratio': ratio,
        'coverage_pct': ratio_pct,
        'min_coverage_ratio': policy.min_coverage_ratio,
        'flag_coverage_below_ratio': policy.flag_coverage_below_ratio,
        'flags': flags,
        'warnings': warnings,
        'blockers': blockers,
        'adequate_for_submit': len(blockers) == 0,
    }


def _geo_policy_flags(loan_request, policy) -> Dict[str, List]:
    from collateral.map_utils import haversine_m
    from collateral.models import (
        Building, BuildingImage, LandValuation, LandValuationImage,
    )

    flags: List[Dict[str, str]] = []
    warnings: List[str] = []
    blockers: List[str] = []
    max_d = policy.photo_max_distance_from_site_m

    def check_photos(label, site_lat, site_lon, images_qs, image_label_fn):
        for img in images_qs:
            if img.gps_lat is None or img.gps_lon is None:
                msg = f'{label}: photo "{image_label_fn(img)}" has no GPS.'
                flags.append({'level': 'warn', 'key': 'photo_no_gps', 'message': msg})
                warnings.append(msg)
                if policy.block_submit_on_missing_photo_gps:
                    blockers.append(msg)
                continue
            if site_lat is None or site_lon is None:
                continue
            dist = haversine_m(site_lat, site_lon, img.gps_lat, img.gps_lon)
            if dist is not None and dist > max_d:
                msg = f'{label}: photo "{image_label_fn(img)}" is {round(dist)} m from site (max {max_d} m).'
                flags.append({'level': 'warn', 'key': 'photo_far', 'message': msg})
                warnings.append(msg)
                if policy.block_submit_on_far_photos:
                    blockers.append(msg)

    for b in Building.objects.filter(loan_request=loan_request):
        imgs = BuildingImage.objects.filter(building=b)
        check_photos(
            f'Building "{b.name}"', b.site_gps_lat, b.site_gps_lon, imgs,
            lambda i: i.get_photo_type_display(),
        )

    land = LandValuation.objects.filter(loan_request=loan_request).first()
    if land:
        imgs = LandValuationImage.objects.filter(land_valuation=land)
        check_photos('Land', land.site_gps_lat, land.site_gps_lon, imgs, lambda i: i.get_photo_type_display())

    # Vehicles / movables: identity is plate/VIN — do not gate on yard or photo GPS.
    return {'flags': flags, 'warnings': warnings, 'blockers': blockers}


def _declared_address_flags(loan_request, policy) -> Dict[str, List]:
    from collateral.geocoding import declared_address_for_loan, resolve_declared_address_coords
    from collateral.map_utils import haversine_m
    from collateral.models import Building, LandValuation

    flags: List[Dict[str, str]] = []
    warnings: List[str] = []
    blockers: List[str] = []
    address = declared_address_for_loan(loan_request)
    if not address:
        return {'flags': flags, 'warnings': warnings, 'blockers': blockers}

    coords = resolve_declared_address_coords(loan_request)
    if not coords:
        msg = 'Declared address on file but could not be geocoded for map verification.'
        flags.append({'level': 'warn', 'key': 'address_not_geocoded', 'message': msg})
        warnings.append(msg)
        return {'flags': flags, 'warnings': warnings, 'blockers': blockers}

    dlat, dlon = coords
    max_d = policy.declared_address_max_distance_from_site_m
    site_checks = []

    for b in Building.objects.filter(loan_request=loan_request):
        if b.site_gps_lat is not None and b.site_gps_lon is not None:
            site_checks.append((f'Building "{b.name}"', b.site_gps_lat, b.site_gps_lon))

    land = LandValuation.objects.filter(loan_request=loan_request).first()
    if land and land.site_gps_lat is not None:
        site_checks.append(('Land plot', land.site_gps_lat, land.site_gps_lon))

    # Skip movable yard pins — they are not the pledged place.
    if not site_checks:
        return {'flags': flags, 'warnings': warnings, 'blockers': blockers}

    for label, slat, slon in site_checks:
        dist = haversine_m(slat, slon, dlat, dlon)
        if dist is not None and dist > max_d:
            msg = (
                f'{label}: declared address is {round(dist)} m from field site GPS '
                f'(max {max_d} m).'
            )
            flags.append({'level': 'warn', 'key': 'declared_address_far', 'message': msg})
            warnings.append(msg)
            if policy.block_submit_on_declared_address_mismatch:
                blockers.append(msg)

    return {'flags': flags, 'warnings': warnings, 'blockers': blockers}


def _exif_gps_flags(loan_request, policy) -> Dict[str, List]:
    from collateral.models import (
        Building, BuildingImage, LandValuation, LandValuationImage,
        OtherCollateralItem, OtherCollateralItemImage,
    )

    flags: List[Dict[str, str]] = []
    warnings: List[str] = []
    blockers: List[str] = []
    max_d = policy.exif_gps_mismatch_warn_m

    def check_imgs(label, qs):
        for img in qs:
            dist = img.browser_vs_exif_distance_m
            if dist is None:
                continue
            try:
                d = float(dist)
            except (TypeError, ValueError):
                continue
            if d > max_d:
                msg = (
                    f'{label}: photo "{img.get_photo_type_display()}" EXIF GPS is '
                    f'{round(d)} m from browser GPS (max {max_d} m).'
                )
                flags.append({'level': 'warn', 'key': 'exif_gps_mismatch', 'message': msg})
                warnings.append(msg)
                if policy.block_submit_on_exif_gps_mismatch:
                    blockers.append(msg)

    for b in Building.objects.filter(loan_request=loan_request):
        check_imgs(f'Building "{b.name}"', BuildingImage.objects.filter(building=b))

    land = LandValuation.objects.filter(loan_request=loan_request).first()
    if land:
        check_imgs('Land', LandValuationImage.objects.filter(land_valuation=land))

    for item in OtherCollateralItem.objects.filter(loan_request=loan_request):
        check_imgs(f'Asset "{item.name}"', OtherCollateralItemImage.objects.filter(item=item))

    return {'flags': flags, 'warnings': warnings, 'blockers': blockers}
