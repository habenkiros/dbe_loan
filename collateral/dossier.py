"""Export collateral dossier JSON + ZIP for audit and future AI training datasets."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.utils import timezone

from collateral.coverage import compute_coverage_adequacy
from collateral.field_utils import get_loan_collateral_readiness
from collateral.models import (
    Building, BuildingImage, BuildingValuation, CollateralFieldAuditLog,
    LandValuation, LandValuationImage, OtherCollateralItem, OtherCollateralItemImage,
)
from collateral.policy import get_collateral_policy
from loans.services.appraisal_prefill import compute_collateral_totals


def _json_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, 'pk'):
        return str(obj)
    raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')


def _user_ref(user) -> Optional[Dict[str, Any]]:
    if not user:
        return None
    return {
        'id': user.pk,
        'username': user.username,
        'full_name': user.get_full_name() or user.username,
        'role': getattr(user, 'role', ''),
    }


def _image_meta(img, *, relative_path: str = '') -> Dict[str, Any]:
    return {
        'id': img.pk,
        'photo_type': img.photo_type,
        'photo_type_display': img.get_photo_type_display(),
        'caption': img.caption or '',
        'captured_at': img.captured_at,
        'browser_gps': {
            'lat': img.gps_lat,
            'lon': img.gps_lon,
            'accuracy_m': img.gps_accuracy_m,
        },
        'exif_gps': {
            'lat': getattr(img, 'exif_gps_lat', None),
            'lon': getattr(img, 'exif_gps_lon', None),
        },
        'browser_vs_exif_distance_m': getattr(img, 'browser_vs_exif_distance_m', None),
        'gps_weak_acknowledged': img.gps_weak_acknowledged,
        'uploaded_by': _user_ref(img.uploaded_by),
        'created_at': img.created_at,
        'relative_path': relative_path,
        'has_file': bool(img.image),
    }


def build_collateral_dossier(loan_request) -> Dict[str, Any]:
    """
    Structured dossier for export / ML datasets.
    Values are JSON-serialisable (Decimals/datetimes handled by encoder).
    """
    policy = get_collateral_policy()
    totals = compute_collateral_totals(loan_request)
    coverage = compute_coverage_adequacy(loan_request)
    readiness = get_loan_collateral_readiness(loan_request)

    declared = {
        'text': getattr(loan_request, 'declared_address_text', '') or '',
        'lat': getattr(loan_request, 'declared_address_lat', None),
        'lon': getattr(loan_request, 'declared_address_lon', None),
        'source': getattr(loan_request, 'declared_address_source', '') or '',
        'geocoded_at': getattr(loan_request, 'declared_address_geocoded_at', None),
    }

    buildings: List[Dict[str, Any]] = []
    for b in Building.objects.filter(loan_request=loan_request).select_related(
        'city', 'city__zone', 'city__zone__region',
    ):
        vals = list(
            BuildingValuation.objects.filter(building=b).select_related('sub_work', 'sub_sub_work')
        )
        images = list(BuildingImage.objects.filter(building=b).order_by('created_at'))
        buildings.append({
            'id': b.pk,
            'name': b.name,
            'construction_type': b.construction_type,
            'floors': b.floors,
            'city': b.city.name if b.city_id else None,
            'woreda_path': (
                ' → '.join(
                    p.name for p in (
                        getattr(getattr(b.city, 'zone', None), 'region', None),
                        getattr(b.city, 'zone', None),
                        b.city,
                    ) if p is not None
                ) if b.city_id else ''
            ),
            'site_gps': {
                'lat': b.site_gps_lat,
                'lon': b.site_gps_lon,
                'accuracy_m': b.site_gps_accuracy_m,
                'captured_at': b.site_captured_at,
                'weak_acknowledged': b.site_gps_weak_acknowledged,
            },
            'boq_total': sum((v.total or Decimal('0')) for v in vals),
            'boq_lines': [
                {
                    'id': v.pk,
                    'description': (
                        v.sub_work.name if v.sub_work_id
                        else (v.sub_sub_work.name if v.sub_sub_work_id else '')
                    ),
                    'quantity': v.quantity,
                    'unit_price': v.unit_price,
                    'total': v.total,
                }
                for v in vals
            ],
            'images': [
                _image_meta(img, relative_path=f'photos/buildings/{b.pk}/{img.pk}.jpg')
                for img in images
            ],
        })

    land_payload = None
    land = LandValuation.objects.filter(loan_request=loan_request).first()
    if land:
        limages = list(LandValuationImage.objects.filter(land_valuation=land).order_by('created_at'))
        land_payload = {
            'id': land.pk,
            'land_size_sqm': land.land_size_sqm,
            'unit_price_per_sqm': land.unit_price_per_sqm,
            'total_value': land.total_value,
            'notes': land.notes,
            'site_gps': {
                'lat': land.site_gps_lat,
                'lon': land.site_gps_lon,
                'accuracy_m': land.site_gps_accuracy_m,
                'captured_at': land.site_captured_at,
                'weak_acknowledged': land.site_gps_weak_acknowledged,
            },
            'images': [
                _image_meta(img, relative_path=f'photos/land/{img.pk}.jpg')
                for img in limages
            ],
        }

    other_items: List[Dict[str, Any]] = []
    for item in OtherCollateralItem.objects.filter(loan_request=loan_request):
        oimages = list(OtherCollateralItemImage.objects.filter(item=item).order_by('created_at'))
        types_present = sorted({i.photo_type for i in oimages if i.photo_type})
        other_items.append({
            'id': item.pk,
            'name': item.name,
            'make_model': item.make_model,
            'year_made': item.year_made,
            'plate_number': item.plate_number,
            'chassis_vin': item.chassis_vin,
            'odometer_or_hours': item.odometer_or_hours,
            'condition_grade': item.condition_grade,
            'estimated_value': item.estimated_value,
            'notes': item.notes,
            'site_gps': {
                'lat': item.site_gps_lat,
                'lon': item.site_gps_lon,
                'accuracy_m': item.site_gps_accuracy_m,
            },
            'photo_types_present': types_present,
            'images': [
                _image_meta(img, relative_path=f'photos/other/{item.pk}/{img.pk}.jpg')
                for img in oimages
            ],
        })

    audit = [
        {
            'event_type': log.event_type,
            'event_display': log.get_event_type_display(),
            'subject_type': log.subject_type,
            'subject_id': log.subject_id,
            'payload': log.payload,
            'performed_by': _user_ref(log.performed_by),
            'performed_at': log.performed_at,
        }
        for log in CollateralFieldAuditLog.objects.filter(loan_request=loan_request)
        .select_related('performed_by')
        .order_by('performed_at')[:500]
    ]

    return {
        'schema_version': '1.0',
        'exported_at': timezone.now().isoformat(),
        'loan': {
            'id': loan_request.pk,
            'loan_request_id': loan_request.loan_request_id,
            'applicant_name': loan_request.applicant_name,
            'amount_requested': loan_request.amount_requested,
            'branch': loan_request.branch.name if loan_request.branch_id else None,
            'collateral_type': loan_request.collateral.name if loan_request.collateral_id else None,
            'status': loan_request.status,
            'queue_approved': loan_request.queue_approved,
            'collateral_submitted_at': loan_request.collateral_submitted_at,
            'collateral_submitted_by': _user_ref(loan_request.collateral_submitted_by),
            'collateral_engineering_status': getattr(
                loan_request, 'collateral_engineering_status', '',
            ),
            'assigned_loan_officer': _user_ref(loan_request.assigned_loan_officer),
            'assigned_engineer': _user_ref(loan_request.assigned_engineer),
        },
        'declared_address': declared,
        'policy_snapshot': {
            'min_images_per_building': policy.min_images_per_building,
            'min_images_per_land': policy.min_images_per_land,
            'min_images_per_other_item': policy.min_images_per_other_item,
            'min_coverage_ratio': policy.min_coverage_ratio,
            'photo_max_distance_from_site_m': policy.photo_max_distance_from_site_m,
            'require_movable_photo_types': policy.require_movable_photo_types,
            'exif_gps_mismatch_warn_m': policy.exif_gps_mismatch_warn_m,
        },
        'totals': {
            'grand_total': totals.get('grand_total'),
            'immovable': totals.get('collateral_immovable_value'),
            'moveable': totals.get('collateral_moveable_value'),
        },
        'coverage': {
            'ratio': coverage.get('coverage_ratio'),
            'pct': coverage.get('coverage_pct'),
            'flags': coverage.get('flags'),
            'adequate_for_submit': coverage.get('adequate_for_submit'),
        },
        'readiness': {
            'applies': readiness.get('applies'),
            'all_ready': readiness.get('all_ready'),
            'locked': readiness.get('locked'),
        },
        'buildings': buildings,
        'land': land_payload,
        'other_items': other_items,
        'audit_trail': audit,
    }


def dossier_json_bytes(loan_request) -> bytes:
    dossier = build_collateral_dossier(loan_request)
    return json.dumps(dossier, default=_json_default, indent=2, ensure_ascii=False).encode('utf-8')


def dossier_zip_bytes(loan_request) -> bytes:
    """ZIP containing dossier.json + photo files under photos/…"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('dossier.json', dossier_json_bytes(loan_request))

        for b in Building.objects.filter(loan_request=loan_request):
            for img in BuildingImage.objects.filter(building=b):
                if not img.image:
                    continue
                arc = f'photos/buildings/{b.pk}/{img.pk}.jpg'
                try:
                    with img.image.open('rb') as f:
                        zf.writestr(arc, f.read())
                except Exception:
                    continue

        land = LandValuation.objects.filter(loan_request=loan_request).first()
        if land:
            for img in LandValuationImage.objects.filter(land_valuation=land):
                if not img.image:
                    continue
                arc = f'photos/land/{img.pk}.jpg'
                try:
                    with img.image.open('rb') as f:
                        zf.writestr(arc, f.read())
                except Exception:
                    continue

        for item in OtherCollateralItem.objects.filter(loan_request=loan_request):
            for img in OtherCollateralItemImage.objects.filter(item=item):
                if not img.image:
                    continue
                arc = f'photos/other/{item.pk}/{img.pk}.jpg'
                try:
                    with img.image.open('rb') as f:
                        zf.writestr(arc, f.read())
                except Exception:
                    continue

    return buf.getvalue()
