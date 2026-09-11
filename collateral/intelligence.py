"""Assistive collateral intelligence — suggest and flag, never auto-value.

Five signals for officers / engineering / committee:
1. Market-band outlier flags (BOQ, land, movable)
2. Photo-type suggest + completeness hints
3. GPS confidence score (rules)
4. Collateral risk brief (committee-facing)
5. Duplicate / recycled evidence detection (hash + perceptual)

All outputs are assistive. Humans confirm valuation and QA.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from loans.services.document_forensics import hamming_hex, perceptual_hash_hex


# ---------- 1. Market outliers ----------

OUTLIER_SOFT = Decimal('0.25')   # 25% outside band edge → warn
OUTLIER_HARD = Decimal('0.50')   # 50% outside → strong flag


def _price_vs_band(price: Decimal, band) -> Optional[Dict[str, Any]]:
    if band is None or price is None or price <= 0:
        return None
    try:
        from partners.market_bands import suggest_payload
        payload = suggest_payload(band)
    except Exception:
        payload = None
    if not payload or not payload.get('is_suggestible'):
        return None
    p25 = band.p25_price
    p75 = band.p75_price
    median = band.median_price
    if p25 is None or p75 is None or median is None:
        return None
    level = 'ok'
    message = f'Within market band (median {median})'
    if price < p25:
        gap = (p25 - price) / p25 if p25 else Decimal('0')
        if gap >= OUTLIER_HARD:
            level = 'block'
            message = f'Well below market ({price} vs p25 {p25}, median {median})'
        elif gap >= OUTLIER_SOFT:
            level = 'warn'
            message = f'Below market band ({price} vs p25 {p25})'
    elif price > p75:
        gap = (price - p75) / p75 if p75 else Decimal('0')
        if gap >= OUTLIER_HARD:
            level = 'block'
            message = f'Well above market ({price} vs p75 {p75}, median {median})'
        elif gap >= OUTLIER_SOFT:
            level = 'warn'
            message = f'Above market band ({price} vs p75 {p75})'
    return {
        'level': level,
        'message': message,
        'price': price,
        'median': median,
        'p25': p25,
        'p75': p75,
        'sample_count': band.sample_count,
        'band_id': band.pk,
        'suggest': payload,
    }


def market_outlier_flags(loan_request) -> List[Dict[str, Any]]:
    """BOQ / land / movable prices vs market bands. Assistive only."""
    from collateral.models import Building, BuildingValuation, LandValuation, OtherCollateralItem
    from partners.market_bands import (
        find_band_for_land, find_band_for_movable, find_band_for_unit_price, normalize_item_key,
    )
    from partners.models import MarketObservation

    flags: List[Dict[str, Any]] = []

    for b in Building.objects.filter(loan_request=loan_request).select_related('city'):
        city_id = b.city_id
        for row in BuildingValuation.objects.filter(building=b).select_related(
            'sub_work', 'sub_sub_work',
        ):
            if not row.unit_price or row.unit_price <= 0:
                continue
            sw_id = row.sub_work_id
            ssw_id = row.sub_sub_work_id
            if ssw_id and not sw_id and row.sub_sub_work_id:
                sw_id = row.sub_sub_work.sub_work_id
            band = find_band_for_unit_price(
                city_id=city_id, sub_work_id=sw_id, sub_sub_work_id=ssw_id,
            ) if city_id else None
            hit = _price_vs_band(row.unit_price, band)
            if hit and hit['level'] != 'ok':
                label = (
                    row.sub_sub_work.name if row.sub_sub_work_id
                    else (row.sub_work.name if row.sub_work_id else 'BOQ line')
                )
                flags.append({
                    **hit,
                    'key': 'boq_outlier',
                    'asset': f'Building "{b.name}" — {label}',
                })

    land = LandValuation.objects.filter(loan_request=loan_request).first()
    if land and land.unit_price_per_sqm and land.unit_price_per_sqm > 0:
        city_id = None
        building = Building.objects.filter(loan_request=loan_request).select_related('city').first()
        if building:
            city_id = building.city_id
        band = find_band_for_land(city_id=city_id, item_key='land sqm')
        hit = _price_vs_band(land.unit_price_per_sqm, band)
        if hit and hit['level'] != 'ok':
            flags.append({**hit, 'key': 'land_outlier', 'asset': 'Land ETB/m²'})

    for item in OtherCollateralItem.objects.filter(loan_request=loan_request):
        if not item.estimated_value or item.estimated_value <= 0:
            continue
        name = (item.name or item.make_model or '').strip()
        key = normalize_item_key(name)
        asset_class = MarketObservation.ASSET_VEHICLE
        lower = name.lower()
        if any(x in lower for x in ('tractor', 'machine', 'mill', 'generator', 'plant')):
            asset_class = MarketObservation.ASSET_MACHINERY
        band = find_band_for_movable(asset_class=asset_class, item_key=key)
        hit = _price_vs_band(item.estimated_value, band)
        if hit and hit['level'] != 'ok':
            flags.append({
                **hit,
                'key': 'movable_outlier',
                'asset': f'Asset "{item.name}"',
            })

    return flags


# ---------- 2. Photo-type suggest ----------

_BUILDING_KEYWORDS = {
    'front': ('front', 'facade', 'façade', 'elevation', 'entrance', 'gate'),
    'side': ('side', 'flank', 'lateral'),
    'rear': ('rear', 'back', 'behind'),
    'roof': ('roof', 'rooftop', 'terrace'),
    'interior': ('interior', 'inside', 'room', 'hall'),
}
_LAND_KEYWORDS = {
    'plot': ('plot', 'overview', 'aerial', 'site'),
    'boundary': ('boundary', 'corner', 'becon', 'beacon', 'fence'),
    'title_deed': ('title', 'deed', 'certificate', 'libretto', 'karita'),
}
_MOVABLE_KEYWORDS = {
    'plate': ('plate', 'number plate', 'registration', 'libretto'),
    'asset': ('full', 'overview', 'whole', 'vehicle', 'truck', 'car'),
    'serial_label': ('serial', 'chassis', 'vin', 'engine', 'label'),
    'offer': ('offer', 'invoice', 'quotation', 'proforma', 'supplier'),
}


def suggest_photo_type(
    *,
    kind: str,
    filename: str = '',
    caption: str = '',
    missing_types: Optional[Sequence[str]] = None,
) -> Optional[Dict[str, str]]:
    """
    Heuristic photo-type suggest (assistive). Prefers keyword match, else first missing required type.
    kind: building | land | other
    """
    text = f'{filename} {caption}'.lower()
    table = {
        'building': _BUILDING_KEYWORDS,
        'land': _LAND_KEYWORDS,
        'other': _MOVABLE_KEYWORDS,
    }.get(kind) or {}
    for ptype, words in table.items():
        if any(w in text for w in words):
            return {'key': ptype, 'reason': f'Matched “{next(w for w in words if w in text)}” in filename/caption'}
    missing = [t for t in (missing_types or []) if t]
    if missing:
        return {'key': missing[0], 'reason': 'Next required photo type still missing'}
    return None


def photo_completeness_hints(loan_request) -> List[Dict[str, Any]]:
    from collateral.field_utils import get_loan_collateral_readiness
    from collateral.registration import failed_check_labels

    readiness = get_loan_collateral_readiness(loan_request)
    hints: List[Dict[str, Any]] = []
    for row in readiness.get('buildings') or []:
        if not row['readiness']['ready']:
            hints.append({
                'asset': row['building'].name,
                'labels': failed_check_labels(row['readiness']),
            })
    land = readiness.get('land')
    if land and not land['readiness']['ready']:
        hints.append({'asset': 'Land', 'labels': failed_check_labels(land['readiness'])})
    for row in readiness.get('other_items') or []:
        if not row['readiness']['ready']:
            hints.append({
                'asset': row['item'].name,
                'labels': failed_check_labels(row['readiness']),
            })
    return hints


# ---------- 3. GPS confidence ----------

def gps_confidence_for_site(instance, photos: Optional[Sequence] = None) -> Dict[str, Any]:
    """0–100 GPS confidence for an immovable site (building or land)."""
    from collateral.map_utils import haversine_m
    from collateral.policy import get_collateral_policy

    policy = get_collateral_policy()
    score = 100
    reasons: List[str] = []
    lat = getattr(instance, 'site_gps_lat', None)
    lon = getattr(instance, 'site_gps_lon', None)
    if lat is None or lon is None:
        return {
            'score': 0,
            'band': 'none',
            'label': 'No site GPS',
            'reasons': ['no_site_gps'],
            'source': '',
        }

    source = (getattr(instance, 'site_gps_source', None) or '').strip()
    if source == 'manual':
        score -= 25
        reasons.append('manual_coordinates')
    elif source == 'device':
        reasons.append('device_gps')
    else:
        score -= 5
        reasons.append('source_unknown')

    acc = getattr(instance, 'site_gps_accuracy_m', None)
    try:
        acc_f = float(acc) if acc is not None else None
    except (TypeError, ValueError):
        acc_f = None
    if acc_f is None:
        if source == 'manual':
            pass
        else:
            score -= 15
            reasons.append('accuracy_unknown')
    elif acc_f > policy.gps_accuracy_weak_threshold_m:
        score -= 20
        reasons.append('weak_accuracy')
    elif acc_f > 50:
        score -= 8
        reasons.append('moderate_accuracy')

    if getattr(instance, 'site_gps_weak_acknowledged', False):
        reasons.append('officer_attested')

    photos = list(photos or [])
    with_gps = [p for p in photos if getattr(p, 'gps_lat', None) is not None]
    if photos and not with_gps:
        score -= 30
        reasons.append('no_photo_gps')
    elif photos:
        far = 0
        exif_bad = 0
        for p in with_gps:
            dist = haversine_m(lat, lon, p.gps_lat, p.gps_lon)
            if dist is not None and dist > policy.photo_max_distance_from_site_m:
                far += 1
            exif_d = getattr(p, 'browser_vs_exif_distance_m', None)
            try:
                if exif_d is not None and float(exif_d) > policy.exif_gps_mismatch_warn_m:
                    exif_bad += 1
            except (TypeError, ValueError):
                pass
        if far:
            score -= min(30, 10 * far)
            reasons.append(f'{far}_photos_far_from_site')
        if exif_bad:
            score -= min(15, 5 * exif_bad)
            reasons.append(f'{exif_bad}_exif_mismatch')
        ratio = len(with_gps) / max(len(photos), 1)
        if ratio < 0.5:
            score -= 10
            reasons.append('few_photos_with_gps')

    score = max(0, min(100, score))
    if score >= 75:
        band, label = 'high', 'High'
    elif score >= 45:
        band, label = 'medium', 'Medium'
    else:
        band, label = 'low', 'Low'
    return {
        'score': score,
        'band': band,
        'label': label,
        'reasons': reasons,
        'source': source,
    }


def gps_confidence_for_loan(loan_request) -> Dict[str, Any]:
    from collateral.models import Building, BuildingImage, LandValuation, LandValuationImage

    sites: List[Dict[str, Any]] = []
    for b in Building.objects.filter(loan_request=loan_request):
        imgs = list(BuildingImage.objects.filter(building=b))
        sites.append({
            'asset': b.name,
            'kind': 'building',
            **gps_confidence_for_site(b, imgs),
        })
    land = LandValuation.objects.filter(loan_request=loan_request).first()
    if land:
        imgs = list(LandValuationImage.objects.filter(land_valuation=land))
        sites.append({
            'asset': 'Land',
            'kind': 'land',
            **gps_confidence_for_site(land, imgs),
        })
    if not sites:
        return {
            'score': None,
            'band': 'n_a',
            'label': 'N/A (no immovable site)',
            'sites': [],
            'reasons': ['movable_only_or_empty'],
        }
    scores = [s['score'] for s in sites]
    overall = min(scores)
    band = 'high' if overall >= 75 else ('medium' if overall >= 45 else 'low')
    label = {'high': 'High', 'medium': 'Medium', 'low': 'Low'}[band]
    return {
        'score': overall,
        'band': band,
        'label': label,
        'sites': sites,
        'reasons': [r for s in sites for r in s.get('reasons') or []],
    }


# ---------- 5. Duplicate evidence ----------

def hash_image_bytes(raw: bytes, filename: str = '') -> Tuple[str, str]:
    """Return (sha256_hex, perceptual_hash_hex)."""
    sha = hashlib.sha256(raw or b'').hexdigest() if raw else ''
    ext = ''
    if filename and '.' in filename:
        ext = filename.rsplit('.', 1)[-1].lower()
    else:
        ext = 'jpg'
    phash = perceptual_hash_hex(raw or b'', ext) if raw else ''
    return sha, phash


def find_collateral_duplicates(
    *,
    content_sha256: str = '',
    perceptual_hash: str = '',
    exclude_loan_id: Optional[int] = None,
    hamming_max: int = 10,
) -> List[Dict[str, Any]]:
    """Exact SHA or near-dupe perceptual matches across collateral photos."""
    from collateral.models import BuildingImage, LandValuationImage, OtherCollateralItemImage

    hits: List[Dict[str, Any]] = []

    def _add(kind, row, loan, match, dist):
        if exclude_loan_id and loan and loan.pk == exclude_loan_id:
            return
        hits.append({
            'kind': kind,
            'image_id': row.pk,
            'match': match,
            'distance': dist,
            'loan_pk': loan.pk if loan else None,
            'loan_request_id': getattr(loan, 'loan_request_id', '') if loan else '',
            'photo_type': row.photo_type,
            'same_loan': False,
        })

    if content_sha256:
        for row in BuildingImage.objects.filter(content_sha256=content_sha256).select_related(
            'building__loan_request',
        )[:30]:
            _add('building', row, row.building.loan_request, 'exact', 0)
        for row in LandValuationImage.objects.filter(content_sha256=content_sha256).select_related(
            'land_valuation__loan_request',
        )[:30]:
            _add('land', row, row.land_valuation.loan_request, 'exact', 0)
        for row in OtherCollateralItemImage.objects.filter(content_sha256=content_sha256).select_related(
            'item__loan_request',
        )[:30]:
            _add('other', row, row.item.loan_request, 'exact', 0)

    if perceptual_hash:
        for row in BuildingImage.objects.exclude(perceptual_hash='').select_related(
            'building__loan_request',
        )[:400]:
            dist = hamming_hex(perceptual_hash, row.perceptual_hash)
            if dist <= hamming_max:
                _add('building', row, row.building.loan_request, 'near' if dist else 'exact', dist)
        for row in LandValuationImage.objects.exclude(perceptual_hash='').select_related(
            'land_valuation__loan_request',
        )[:400]:
            dist = hamming_hex(perceptual_hash, row.perceptual_hash)
            if dist <= hamming_max:
                _add('land', row, row.land_valuation.loan_request, 'near' if dist else 'exact', dist)
        for row in OtherCollateralItemImage.objects.exclude(perceptual_hash='').select_related(
            'item__loan_request',
        )[:400]:
            dist = hamming_hex(perceptual_hash, row.perceptual_hash)
            if dist <= hamming_max:
                _add('other', row, row.item.loan_request, 'near' if dist else 'exact', dist)

    seen = set()
    unique = []
    for h in hits:
        key = (h['kind'], h['image_id'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)
    return unique[:8]


def duplicate_flags_for_loan(loan_request) -> List[Dict[str, Any]]:
    """Cross-loan recycled photos already on this file."""
    from collateral.models import (
        Building, BuildingImage, LandValuationImage, OtherCollateralItemImage,
    )

    flags: List[Dict[str, Any]] = []
    images = []
    for b in Building.objects.filter(loan_request=loan_request):
        images.extend(list(BuildingImage.objects.filter(building=b)))
    images.extend(list(LandValuationImage.objects.filter(land_valuation__loan_request=loan_request)))
    images.extend(list(OtherCollateralItemImage.objects.filter(item__loan_request=loan_request)))

    for img in images:
        if not img.content_sha256 and not img.perceptual_hash:
            continue
        dups = find_collateral_duplicates(
            content_sha256=img.content_sha256 or '',
            perceptual_hash=img.perceptual_hash or '',
            exclude_loan_id=loan_request.pk,
        )
        if dups:
            flags.append({
                'level': 'block' if any(d['match'] == 'exact' for d in dups) else 'warn',
                'key': 'duplicate_photo',
                'message': (
                    f'Photo ({img.get_photo_type_display()}) matches evidence on '
                    f'{dups[0]["loan_request_id"]}'
                    + (f' and {len(dups) - 1} other file(s)' if len(dups) > 1 else '')
                ),
                'matches': dups,
                'image_id': img.pk,
            })
    return flags


# ---------- 4. Risk brief ----------

def build_collateral_risk_brief(loan_request) -> Dict[str, Any]:
    """Committee / engineering assistive brief — never a decision."""
    from collateral.coverage import compute_coverage_adequacy
    from collateral.engineering_qa import engineering_qa_checklist
    from collateral.field_utils import get_loan_collateral_readiness
    from collateral.pipeline import collateral_pipeline_stage, pipeline_stage_label
    from collateral.registration import ownership_checks
    from loans.services.appraisal_prefill import compute_collateral_totals

    coverage = compute_coverage_adequacy(loan_request)
    readiness = get_loan_collateral_readiness(loan_request)
    gps = gps_confidence_for_loan(loan_request)
    outliers = market_outlier_flags(loan_request)
    dups = duplicate_flags_for_loan(loan_request)
    photo_hints = photo_completeness_hints(loan_request)
    try:
        qa = engineering_qa_checklist(loan_request)
    except Exception:
        qa = {'items': [], 'all_ok': True, 'blockers': []}

    ownership_flags = []
    from collateral.models import Building, LandValuation, OtherCollateralItem
    for b in Building.objects.filter(loan_request=loan_request):
        for c in ownership_checks(b, loan_request):
            if not c['ok']:
                ownership_flags.append(f'{b.name}: {c["label"]}')
    land = LandValuation.objects.filter(loan_request=loan_request).first()
    if land:
        for c in ownership_checks(land, loan_request):
            if not c['ok']:
                ownership_flags.append(f'Land: {c["label"]}')
    for item in OtherCollateralItem.objects.filter(loan_request=loan_request):
        for c in ownership_checks(item, loan_request):
            if not c['ok']:
                ownership_flags.append(f'{item.name}: {c["label"]}')

    warn_count = sum(1 for o in outliers if o['level'] == 'warn')
    block_count = sum(1 for o in outliers if o['level'] == 'block')
    block_count += sum(1 for d in dups if d['level'] == 'block')
    warn_count += sum(1 for d in dups if d['level'] == 'warn')

    if block_count or (gps.get('band') == 'low') or not coverage.get('adequate_for_submit'):
        overall = 'elevated'
        overall_label = 'Elevated — review carefully'
    elif warn_count or gps.get('band') == 'medium' or photo_hints or ownership_flags:
        overall = 'watch'
        overall_label = 'Watch — assistive flags present'
    else:
        overall = 'clear'
        overall_label = 'Clear — no major assistive flags'

    totals = compute_collateral_totals(loan_request)
    stage = collateral_pipeline_stage(loan_request)

    return {
        'assistive_only': True,
        'overall': overall,
        'overall_label': overall_label,
        'coverage': coverage,
        'totals': totals,
        'gps': gps,
        'market_outliers': outliers,
        'duplicates': dups,
        'photo_hints': photo_hints,
        'ownership_flags': ownership_flags,
        'qa': qa,
        'pipeline_stage': stage,
        'pipeline_label': pipeline_stage_label(stage),
        'readiness': readiness,
        'warn_count': warn_count,
        'block_count': block_count,
    }
