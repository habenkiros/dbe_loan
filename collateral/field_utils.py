"""Helpers for on-site collateral field visits."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone

from collateral.policy import get_collateral_policy


def _collateral_type_lower(loan_request) -> str:
    return (getattr(loan_request.collateral, 'name', '') or '').lower()


from collateral.governance import (
    apply_photo_gps_attestation,
    apply_site_gps_with_attestation,
    collateral_is_locked,
    log_collateral_event,
)


def apply_site_gps_to_instance(instance, post, *, user=None) -> Tuple[bool, Optional[str]]:
    """Save site GPS with officer attestation when accuracy is weak."""
    saved, err = apply_site_gps_with_attestation(instance, post)
    if err:
        return False, err
    if not saved:
        return False, None
    loan_request = getattr(instance, 'loan_request', None)
    subject_type = type(instance).__name__
    if loan_request:
        log_collateral_event(
            loan_request,
            'site_gps_marked',
            user=user,
            subject_type=subject_type,
            subject_id=instance.pk,
            payload={
                'lat': str(instance.site_gps_lat),
                'lon': str(instance.site_gps_lon),
                'accuracy_m': str(instance.site_gps_accuracy_m) if instance.site_gps_accuracy_m is not None else None,
                'weak_acknowledged': instance.site_gps_weak_acknowledged,
            },
        )
        if instance.site_gps_weak_acknowledged:
            log_collateral_event(
                loan_request,
                'weak_gps_attested',
                user=user,
                subject_type=subject_type,
                subject_id=instance.pk,
                payload={'context': 'site', 'note': (instance.site_gps_attestation_note or '')[:500]},
            )
    return True, None


def apply_site_gps_from_post(building, post, *, user=None) -> Tuple[bool, Optional[str]]:
    return apply_site_gps_to_instance(building, post, user=user)


def _save_field_image(
    instance,
    image_model,
    fk_field,
    post,
    files,
    user,
    photo_choices,
    *,
    loan_request,
    subject_type: str,
) -> Tuple[bool, str]:
    upload = files.get('image')
    if not upload:
        return False, 'No image received.'
    photo_type = (post.get('photo_type') or 'other').strip()
    valid_types = {c[0] for c in photo_choices}
    if photo_type not in valid_types:
        photo_type = 'other'
    kwargs = {fk_field: instance, 'image': upload, 'photo_type': photo_type}
    img = image_model(
        **kwargs,
        caption=(post.get('caption') or '').strip()[:255],
        captured_at=timezone.now(),
        uploaded_by=user if user.is_authenticated else None,
    )
    err = apply_photo_gps_attestation(img, post)
    if err:
        return False, err
    from collateral.exif_gps import apply_exif_gps_to_image
    exif_warn = apply_exif_gps_to_image(img, upload)
    img.save()
    log_collateral_event(
        loan_request,
        'photo_uploaded',
        user=user,
        subject_type=subject_type,
        subject_id=img.pk,
        payload={
            'photo_type': photo_type,
            'gps_lat': str(img.gps_lat) if img.gps_lat is not None else None,
            'gps_weak_acknowledged': img.gps_weak_acknowledged,
            'exif_gps_lat': str(img.exif_gps_lat) if img.exif_gps_lat is not None else None,
            'browser_vs_exif_distance_m': (
                str(img.browser_vs_exif_distance_m)
                if img.browser_vs_exif_distance_m is not None else None
            ),
        },
    )
    if img.gps_weak_acknowledged:
        log_collateral_event(
            loan_request,
            'weak_gps_attested',
            user=user,
            subject_type=subject_type,
            subject_id=img.pk,
            payload={'context': 'photo', 'note': img.gps_attestation_note[:500]},
        )
    msg = 'Photo saved.'
    if exif_warn:
        msg = f'Photo saved. Warning: {exif_warn}'
    return True, msg


def get_land_readiness(land) -> Dict[str, Any]:
    from collateral.models import LandValuationImage

    policy = get_collateral_policy()
    min_img = policy.min_images_per_land
    loan_request = land.loan_request
    image_count = LandValuationImage.objects.filter(land_valuation=land).count()
    total = land.total_value
    checks = [
        {
            'key': 'size',
            'label': 'Land size (sqm) set',
            'ok': land.land_size_sqm is not None and land.land_size_sqm > 0,
            'detail': str(land.land_size_sqm) if land.land_size_sqm else 'Enter on step 1',
        },
        {
            'key': 'price',
            'label': 'Unit price per sqm set',
            'ok': land.unit_price_per_sqm is not None and land.unit_price_per_sqm > 0,
            'detail': str(land.unit_price_per_sqm) if land.unit_price_per_sqm else 'Enter on step 1',
        },
        {
            'key': 'site_gps',
            'label': 'Plot site GPS marked',
            'ok': land.site_gps_lat is not None and land.site_gps_lon is not None,
            'detail': 'Mark location on step 1' if land.site_gps_lat is None else f'{land.site_gps_lat}, {land.site_gps_lon}',
        },
        {
            'key': 'photos',
            'label': f'At least {min_img} photos',
            'ok': image_count >= min_img,
            'detail': f'{image_count} / {min_img}',
        },
    ]
    required_ok = all(c['ok'] for c in checks)
    return {
        'locked': collateral_is_locked(loan_request),
        'image_count': image_count,
        'min_images': min_img,
        'total_value': total,
        'checks': checks,
        'ready': required_ok,
    }


def get_other_item_readiness(item) -> Dict[str, Any]:
    from collateral.models import OtherCollateralItemImage
    from collateral import constants

    policy = get_collateral_policy()
    min_img = policy.min_images_per_other_item
    loan_request = item.loan_request
    images = list(OtherCollateralItemImage.objects.filter(item=item))
    image_count = len(images)
    photos_with_gps = sum(1 for i in images if i.gps_lat is not None and i.gps_lon is not None)
    has_site = item.site_gps_lat is not None and item.site_gps_lon is not None
    types_present = {i.photo_type for i in images}
    required_types = [t[0] for t in constants.REQUIRED_MOVABLE_PHOTO_TYPES]
    missing_types = [t for t in required_types if t not in types_present]
    type_labels = dict(constants.REQUIRED_MOVABLE_PHOTO_TYPES)
    missing_labels = [type_labels.get(t, t) for t in missing_types]
    types_ok = (not policy.require_movable_photo_types) or (len(missing_types) == 0)

    checks = [
        {
            'key': 'name',
            'label': 'Asset name set',
            'ok': bool((item.name or '').strip()),
            'detail': item.name or 'Enter on step 1',
        },
        {
            'key': 'value',
            'label': 'Estimated value > 0',
            'ok': (item.estimated_value or 0) > 0,
            'detail': str(item.estimated_value),
        },
        {
            'key': 'photos',
            'label': f'At least {min_img} photos',
            'ok': image_count >= min_img,
            'detail': f'{image_count} / {min_img}',
        },
        {
            'key': 'required_photo_types',
            'label': 'Required photo types (plate, full asset, chassis)',
            'ok': types_ok,
            'detail': (
                'Complete' if types_ok
                else f'Missing: {", ".join(missing_labels)}'
            ),
        },
        {
            'key': 'photo_gps',
            'label': 'Photo GPS (recommended)',
            'ok': photos_with_gps >= 1 or image_count == 0,
            'detail': (
                f'{photos_with_gps} photo(s) with GPS — capture on step 2'
                if photos_with_gps < 1 else f'{photos_with_gps} with GPS'
            ),
        },
    ]
    if has_site:
        checks.insert(2, {
            'key': 'site_gps',
            'label': 'Storage / yard location (optional)',
            'ok': True,
            'detail': f'{item.site_gps_lat}, {item.site_gps_lon}',
        })
    required_ok = all(
        c['ok'] for c in checks
        if c['key'] != 'photo_gps'
    )
    return {
        'locked': collateral_is_locked(loan_request),
        'image_count': image_count,
        'min_images': min_img,
        'total_value': item.estimated_value,
        'checks': checks,
        'ready': required_ok,
        'missing_photo_types': missing_types if policy.require_movable_photo_types else [],
    }


def save_land_field_photo(land, post, files, user) -> Tuple[bool, str]:
    from collateral.models import LandValuationImage
    return _save_field_image(
        land, LandValuationImage, 'land_valuation', post, files, user,
        LandValuationImage.PHOTO_TYPE_CHOICES,
        loan_request=land.loan_request, subject_type='land_image',
    )


def save_other_field_photo(item, post, files, user) -> Tuple[bool, str]:
    from collateral.models import OtherCollateralItemImage
    return _save_field_image(
        item, OtherCollateralItemImage, 'item', post, files, user,
        OtherCollateralItemImage.PHOTO_TYPE_CHOICES,
        loan_request=item.loan_request, subject_type='other_image',
    )


def _parse_decimal(value: str) -> Optional[Decimal]:
    if value is None:
        return None
    raw = str(value).strip().replace(',', '.')
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _parse_gps_coord(value: str) -> Optional[Decimal]:
    d = _parse_decimal(value)
    if d is None:
        return None
    return d


def get_building_readiness(building) -> Dict[str, Any]:
    """Checklist for one building before collateral submit."""
    from collateral.models import BuildingImage, BuildingValuation

    policy = get_collateral_policy()
    min_img = policy.min_images_per_building
    loan_request = building.loan_request
    locked = collateral_is_locked(loan_request)
    image_count = BuildingImage.objects.filter(building=building).count()
    images_with_gps = BuildingImage.objects.filter(
        building=building, gps_lat__isnull=False, gps_lon__isnull=False,
    ).count()
    valuation_count = BuildingValuation.objects.filter(building=building).count()
    rows = BuildingValuation.objects.filter(building=building)
    building_total = sum((r.total or Decimal('0')) for r in rows)

    checks = [
        {
            'key': 'city',
            'label': 'Woreda (city) set',
            'ok': bool(building.city_id),
            'detail': building.city.name if building.city_id else 'Select Region → Zone → Woreda',
        },
        {
            'key': 'site_gps',
            'label': 'Building site GPS marked',
            'ok': building.site_gps_lat is not None and building.site_gps_lon is not None,
            'detail': (
                f'{building.site_gps_lat}, {building.site_gps_lon}'
                if building.site_gps_lat is not None else 'Use “Mark site location” on step 1'
            ),
        },
        {
            'key': 'boq',
            'label': 'At least one BOQ line with quantity',
            'ok': valuation_count > 0 and building_total > 0,
            'detail': f'{valuation_count} line(s), total {building_total:.2f}' if valuation_count else 'Enter quantities on step 2',
        },
        {
            'key': 'photos',
            'label': f'At least {min_img} photos',
            'ok': image_count >= min_img,
            'detail': f'{image_count} / {min_img}',
        },
        {
            'key': 'photo_gps',
            'label': 'Photos include GPS',
            'ok': images_with_gps >= min(image_count, min_img) if image_count else False,
            'detail': f'{images_with_gps} photo(s) with GPS',
            'optional': image_count < min_img,
        },
    ]

    required_ok = all(c['ok'] for c in checks if not c.get('optional'))
    return {
        'locked': locked,
        'image_count': image_count,
        'min_images': min_img,
        'valuation_count': valuation_count,
        'building_total': building_total,
        'checks': checks,
        'ready': required_ok,
    }


def get_loan_collateral_readiness(loan_request) -> Dict[str, Any]:
    """Readiness for buildings, land, and/or other collateral on this loan."""
    from collateral.models import Building, LandValuation, OtherCollateralItem

    ct = _collateral_type_lower(loan_request)
    locked = collateral_is_locked(loan_request)
    result: Dict[str, Any] = {
        'collateral_type': ct,
        'locked': locked,
        'buildings': [],
        'land': None,
        'other_items': [],
        'all_ready': True,
        'applies': False,
    }

    if any(x in ct for x in ('building', 'house', 'construction')):
        result['applies'] = True
        buildings = list(Building.objects.filter(loan_request=loan_request).select_related('city'))
        for b in buildings:
            r = get_building_readiness(b)
            result['buildings'].append({'building': b, 'readiness': r})
        if not buildings or not all(i['readiness']['ready'] for i in result['buildings']):
            result['all_ready'] = False

    if 'land' in ct:
        result['applies'] = True
        land = LandValuation.objects.filter(loan_request=loan_request).first()
        if land:
            lr = get_land_readiness(land)
            result['land'] = {'land': land, 'readiness': lr}
            if not lr['ready']:
                result['all_ready'] = False
        else:
            result['all_ready'] = False

    if any(x in ct for x in ('vehicle', 'machinery', 'equipment', 'other')):
        result['applies'] = True
        items = list(OtherCollateralItem.objects.filter(loan_request=loan_request))
        for item in items:
            r = get_other_item_readiness(item)
            result['other_items'].append({'item': item, 'readiness': r})
        if not items or not all(i['readiness']['ready'] for i in result['other_items']):
            result['all_ready'] = False

    if not result['applies']:
        result['all_ready'] = True

    return result


def collateral_submit_blockers(loan_request) -> List[str]:
    """Human-readable reasons collateral cannot be submitted yet."""
    readiness = get_loan_collateral_readiness(loan_request)
    blockers: List[str] = []
    if not readiness['applies']:
        return blockers
    for row in readiness.get('buildings', []):
        b = row['building']
        r = row['readiness']
        if not r['ready']:
            blockers.append(f'Building "{b.name}": {r["image_count"]}/{r["min_images"]} photos')
    if readiness.get('land'):
        land = readiness['land']['land']
        r = readiness['land']['readiness']
        if not r['ready']:
            blockers.append(f'Land: {r["image_count"]}/{r["min_images"]} photos — complete field visit')
    for row in readiness.get('other_items', []):
        item = row['item']
        r = row['readiness']
        if not r['ready']:
            missing = r.get('missing_photo_types') or []
            if missing:
                from collateral import constants
                labels = dict(constants.REQUIRED_MOVABLE_PHOTO_TYPES)
                miss_txt = ', '.join(labels.get(t, t) for t in missing)
                blockers.append(f'"{item.name}": missing required photos — {miss_txt}')
            else:
                blockers.append(
                    f'"{item.name}": {r["image_count"]}/{r["min_images"]} photos — complete field visit'
                )
    if readiness['applies'] and not readiness.get('buildings') and not readiness.get('land') and not readiness.get('other_items'):
        blockers.append('Add collateral data before submitting.')

    from collateral.coverage import compute_coverage_adequacy
    coverage = compute_coverage_adequacy(loan_request)
    blockers.extend(coverage.get('blockers', []))
    return blockers


def save_field_visit_photo(building, post, files, user) -> Tuple[bool, str]:
    """Create BuildingImage from field visit upload with GPS metadata."""
    from collateral.models import BuildingImage

    return _save_field_image(
        building,
        BuildingImage,
        'building',
        post,
        files,
        user,
        BuildingImage.PHOTO_TYPE_CHOICES,
        loan_request=building.loan_request,
        subject_type='building_image',
    )


def save_field_visit_boq(
    building,
    post,
    user,
    *,
    work_items: List[Tuple[str, str]],
    get_unit_price,
    can_edit_unit_price: bool,
) -> Tuple[int, List[str]]:
    """
    Upsert BOQ quantities from field visit step 2.
    work_items: list of (key, label) e.g. sub_work:5
    get_unit_price(building, sub_work, sub_sub_work) -> Decimal|None
    Returns (rows_saved, errors).
    """
    from collateral.models import BuildingValuation, SubWork, SubSubWork

    errors: List[str] = []
    saved = 0
    existing_by_key: Dict[str, BuildingValuation] = {}
    for row in BuildingValuation.objects.filter(building=building):
        if row.sub_sub_work_id:
            existing_by_key[f'sub_sub_work:{row.sub_sub_work_id}'] = row
        elif row.sub_work_id:
            existing_by_key[f'sub_work:{row.sub_work_id}'] = row

    for i, (key, _label) in enumerate(work_items):
        qty_val = post.get(f'quantity_{i}')
        if qty_val is None or str(qty_val).strip() == '':
            continue
        qty = _parse_decimal(qty_val)
        if qty is None:
            errors.append(f'Row {i + 1}: invalid quantity.')
            continue
        if qty <= 0:
            if key in existing_by_key:
                existing_by_key[key].delete()
                saved += 1
            continue

        kind, _, pk = key.partition(':')
        try:
            pk_int = int(pk)
        except ValueError:
            continue
        sub_work = SubWork.objects.filter(pk=pk_int).first() if kind == 'sub_work' else None
        sub_sub_work = SubSubWork.objects.filter(pk=pk_int).first() if kind == 'sub_sub_work' else None

        unit_price = None
        if can_edit_unit_price:
            unit_price = _parse_decimal(post.get(f'unit_price_{i}', ''))
        if unit_price is None:
            unit_price = get_unit_price(building, sub_work=sub_work, sub_sub_work=sub_sub_work)
        if unit_price is None:
            errors.append(f'Row {i + 1}: no unit price in catalog for this woreda.')
            continue

        if key in existing_by_key:
            obj = existing_by_key[key]
            obj.quantity = qty
            obj.unit_price = unit_price
            if user.is_authenticated:
                obj.quantity_entered_by = user
            obj.save()
        else:
            obj = BuildingValuation(
                building=building,
                sub_work=sub_work,
                sub_sub_work=sub_sub_work,
                quantity=qty,
                unit_price=unit_price,
            )
            if user.is_authenticated:
                obj.quantity_entered_by = user
            obj.save()
        saved += 1

    if saved and not errors:
        log_collateral_event(
            building.loan_request,
            'boq_saved',
            user=user,
            subject_type='Building',
            subject_id=building.pk,
            payload={'rows_saved': saved},
        )

    return saved, errors


def get_unit_price_for_building(building, sub_work=None, sub_sub_work=None):
    """Unit price from catalog for building's woreda."""
    from collateral.models import SubWorkUnitPrice

    if not building.city_id:
        return None
    if sub_sub_work:
        try:
            return SubWorkUnitPrice.objects.get(sub_sub_work=sub_sub_work, city=building.city).unit_price
        except SubWorkUnitPrice.DoesNotExist:
            return None
    if sub_work:
        try:
            return SubWorkUnitPrice.objects.get(sub_work=sub_work, city=building.city).unit_price
        except SubWorkUnitPrice.DoesNotExist:
            return None
    return None


def build_field_boq_rows(building, work_items_flat, existing_valuations) -> List[Dict[str, Any]]:
    """Flat BOQ rows with index matching POST quantity_{index}."""
    from collateral.models import SubWork, SubSubWork

    by_key = {}
    for row in existing_valuations:
        if row.sub_sub_work_id:
            by_key[f'sub_sub_work:{row.sub_sub_work_id}'] = row
        elif row.sub_work_id:
            by_key[f'sub_work:{row.sub_work_id}'] = row

    rows: List[Dict[str, Any]] = []
    for i, (key, label) in enumerate(work_items_flat):
        existing = by_key.get(key)
        qty = existing.quantity if existing else ''
        unit_price = existing.unit_price if existing else None
        if unit_price is None:
            kind, _, pk = key.partition(':')
            try:
                pk_int = int(pk)
            except ValueError:
                pk_int = None
            if kind == 'sub_work' and pk_int:
                sw = SubWork.objects.filter(pk=pk_int).first()
                unit_price = get_unit_price_for_building(building, sub_work=sw) if sw else None
            elif kind == 'sub_sub_work' and pk_int:
                ssw = SubSubWork.objects.filter(pk=pk_int).first()
                unit_price = get_unit_price_for_building(building, sub_sub_work=ssw) if ssw else None
        rows.append({
            'key': key,
            'label': label,
            'index': i,
            'quantity': qty,
            'unit_price': unit_price,
            'has_row': key in by_key,
        })
    return rows
