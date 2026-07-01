"""Map marker payloads for collateral site vs field-photo GPS verification."""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any, Dict, List, Optional


# Flag photos farther than this from registered site (metres) — policy for field verification.
PHOTO_MAX_DISTANCE_FROM_SITE_M = 200


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def haversine_m(lat1, lon1, lat2, lon2) -> Optional[float]:
    """Great-circle distance in metres."""
    a1, o1, a2, o2 = map(_to_float, (lat1, lon1, lat2, lon2))
    if None in (a1, o1, a2, o2):
        return None
    r = 6371000.0
    p1, p2 = math.radians(a1), math.radians(a2)
    dp = math.radians(a2 - a1)
    dl = math.radians(o2 - o1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def build_collateral_map_data(
    *,
    site_lat=None,
    site_lon=None,
    site_accuracy_m=None,
    site_label: str = 'Registered collateral site',
    registered_woreda: str = '',
    registered_address: str = '',
    photos: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build JSON-serialisable map config: registered site pin + field photo pins.
    photos: list of dicts with lat, lon, optional accuracy_m, label, image_url, id
    """
    photos = photos or []
    markers: List[Dict[str, Any]] = []
    site_f_lat = _to_float(site_lat)
    site_f_lon = _to_float(site_lon)

    if site_f_lat is not None and site_f_lon is not None:
        markers.append({
            'kind': 'site',
            'lat': site_f_lat,
            'lon': site_f_lon,
            'label': site_label,
            'accuracy_m': _to_float(site_accuracy_m),
        })

    photo_warnings = 0
    for p in photos:
        plat = _to_float(p.get('lat'))
        plon = _to_float(p.get('lon'))
        if plat is None or plon is None:
            continue
        dist = haversine_m(site_f_lat, site_f_lon, plat, plon) if site_f_lat is not None else None
        far = dist is not None and dist > PHOTO_MAX_DISTANCE_FROM_SITE_M
        if far:
            photo_warnings += 1
        markers.append({
            'kind': 'photo',
            'id': p.get('id'),
            'lat': plat,
            'lon': plon,
            'label': p.get('label') or 'Field photo',
            'accuracy_m': _to_float(p.get('accuracy_m')),
            'image_url': p.get('image_url') or '',
            'distance_m': round(dist) if dist is not None else None,
            'far_from_site': far,
        })

    return {
        'markers': markers,
        'registered_woreda': registered_woreda or '',
        'registered_address': registered_address or '',
        'max_distance_m': PHOTO_MAX_DISTANCE_FROM_SITE_M,
        'photo_warnings': photo_warnings,
        'has_site': site_f_lat is not None and site_f_lon is not None,
        'photo_count': sum(1 for m in markers if m['kind'] == 'photo'),
    }


def map_data_json(data: Dict[str, Any]) -> str:
    return json.dumps(data)


def building_map_data(building) -> Dict[str, Any]:
    from collateral.models import BuildingImage

    woreda = ''
    if building.city_id:
        city = building.city
        region = getattr(getattr(city, 'zone', None), 'region', None)
        zone = getattr(city, 'zone', None)
        parts = [p.name for p in (region, zone, city) if p is not None]
        woreda = ' → '.join(parts)

    photos = []
    for img in BuildingImage.objects.filter(building=building).order_by('created_at'):
        photos.append({
            'id': img.pk,
            'lat': img.gps_lat,
            'lon': img.gps_lon,
            'accuracy_m': img.gps_accuracy_m,
            'label': img.get_photo_type_display(),
            'image_url': img.image.url if img.image else '',
        })

    return build_collateral_map_data(
        site_lat=building.site_gps_lat,
        site_lon=building.site_gps_lon,
        site_accuracy_m=building.site_gps_accuracy_m,
        site_label=f'Registered site — {building.name}',
        registered_woreda=woreda,
        photos=photos,
    )


def land_map_data(land) -> Dict[str, Any]:
    from collateral.models import LandValuationImage

    loan = land.loan_request
    registered_address = ''
    try:
        bi = loan.basic_info
        registered_address = (bi.business_address or bi.home_address or '').strip()
    except Exception:
        pass

    photos = []
    for img in LandValuationImage.objects.filter(land_valuation=land).order_by('created_at'):
        photos.append({
            'id': img.pk,
            'lat': img.gps_lat,
            'lon': img.gps_lon,
            'accuracy_m': img.gps_accuracy_m,
            'label': img.get_photo_type_display(),
            'image_url': img.image.url if img.image else '',
        })

    return build_collateral_map_data(
        site_lat=land.site_gps_lat,
        site_lon=land.site_gps_lon,
        site_accuracy_m=land.site_gps_accuracy_m,
        site_label='Registered plot site',
        registered_address=registered_address,
        photos=photos,
    )


def other_item_map_data(item) -> Dict[str, Any]:
    from collateral.models import OtherCollateralItemImage

    photos = []
    for img in OtherCollateralItemImage.objects.filter(item=item).order_by('created_at'):
        photos.append({
            'id': img.pk,
            'lat': img.gps_lat,
            'lon': img.gps_lon,
            'accuracy_m': img.gps_accuracy_m,
            'label': img.get_photo_type_display(),
            'image_url': img.image.url if img.image else '',
        })

    return build_collateral_map_data(
        site_lat=item.site_gps_lat,
        site_lon=item.site_gps_lon,
        site_accuracy_m=item.site_gps_accuracy_m,
        site_label=f'Registered asset — {item.name}',
        photos=photos,
    )
