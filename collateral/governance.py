"""
Collateral field-work governance: immutability after submit, audit trail, GPS attestation.

Designed for national-scale credit/collateral operations — every material field action
is attributable and preserved for committee review and future AI provenance pipelines.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Dict, Optional

from django.contrib import messages
from django.shortcuts import redirect

from collateral.policy import get_collateral_policy


def collateral_is_locked(loan_request) -> bool:
    return bool(getattr(loan_request, 'collateral_submitted_at', None))


def gps_is_weak(accuracy_m) -> bool:
    threshold = get_collateral_policy().gps_accuracy_weak_threshold_m
    if accuracy_m is None:
        return True
    try:
        return float(accuracy_m) > threshold
    except (TypeError, ValueError):
        return True


def log_collateral_event(
    loan_request,
    event_type: str,
    *,
    user=None,
    subject_type: str = '',
    subject_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
):
    from collateral.models import CollateralFieldAuditLog

    CollateralFieldAuditLog.objects.create(
        loan_request=loan_request,
        event_type=event_type,
        subject_type=subject_type or '',
        subject_id=subject_id,
        payload=payload or {},
        performed_by=user if user and user.is_authenticated else None,
    )


def block_if_collateral_locked(request, loan_request, redirect_view: str, *redirect_args, **redirect_kwargs):
    """Return redirect response if collateral is submitted; else None."""
    if collateral_is_locked(loan_request):
        messages.error(
            request,
            'Collateral estimation has been submitted and is locked. '
            'Contact a supervisor if corrections are required.',
        )
        return redirect(redirect_view, *redirect_args, **redirect_kwargs)
    return None


def require_collateral_mutable(get_loan_request):
    """Decorator: block POST when collateral is locked. get_loan_request(request, *a, **kw) -> LoanRequest."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.method == 'POST':
                loan_request = get_loan_request(request, *args, **kwargs)
                if loan_request and collateral_is_locked(loan_request):
                    messages.error(
                        request,
                        'Collateral estimation is locked after submission.',
                    )
                    return redirect(request.path)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def apply_site_gps_with_attestation(instance, post) -> tuple[bool, Optional[str]]:
    """
    Save site GPS + officer attestation when accuracy is weak or missing.
    Returns (saved, error_message).
    """
    from collateral.field_utils import _parse_gps_coord
    from django.utils import timezone

    lat = _parse_gps_coord(post.get('site_gps_lat', ''))
    lon = _parse_gps_coord(post.get('site_gps_lon', ''))
    if lat is None or lon is None:
        return False, None

    acc = _parse_gps_coord(post.get('site_gps_accuracy_m', ''))
    weak = gps_is_weak(acc)
    ack = (post.get('site_gps_weak_ack') or '').lower() in ('1', 'true', 'on', 'yes')
    note = (post.get('site_gps_attestation_note') or '').strip()

    if weak and not ack:
        threshold = get_collateral_policy().gps_accuracy_weak_threshold_m
        return False, (
            f'GPS accuracy is weak (>{threshold}m or unavailable). '
            'Check the attestation box and explain how the location was verified.'
        )
    if weak and len(note) < 10:
        return False, 'Provide a brief officer attestation (at least 10 characters) for weak GPS.'

    instance.site_gps_lat = lat
    instance.site_gps_lon = lon
    instance.site_gps_accuracy_m = acc
    instance.site_captured_at = timezone.now()
    instance.site_gps_weak_acknowledged = weak and ack
    instance.site_gps_attestation_note = note if weak else ''
    instance.save(update_fields=[
        'site_gps_lat', 'site_gps_lon', 'site_gps_accuracy_m', 'site_captured_at',
        'site_gps_weak_acknowledged', 'site_gps_attestation_note', 'updated_at',
    ])
    return True, None


def apply_photo_gps_attestation(image_instance, post) -> Optional[str]:
    """Set GPS + attestation on a photo model instance. Returns error or None."""
    from collateral.field_utils import _parse_gps_coord

    lat = _parse_gps_coord(post.get('gps_lat', ''))
    lon = _parse_gps_coord(post.get('gps_lon', ''))
    acc = _parse_gps_coord(post.get('gps_accuracy_m', ''))
    weak = gps_is_weak(acc) or lat is None or lon is None
    ack = (post.get('gps_weak_ack') or '').lower() in ('1', 'true', 'on', 'yes')
    note = (post.get('gps_attestation_note') or '').strip()

    if lat is not None and lon is not None:
        image_instance.gps_lat = lat
        image_instance.gps_lon = lon
    if acc is not None:
        image_instance.gps_accuracy_m = acc

    if weak:
        if not ack:
            return (
                'Weak or missing GPS on photo — acknowledge attestation and describe '
                'how the capture location was verified.'
            )
        if len(note) < 10:
            return 'Officer attestation note required (min 10 characters) for weak GPS.'
        image_instance.gps_weak_acknowledged = True
        image_instance.gps_attestation_note = note
    else:
        image_instance.gps_weak_acknowledged = False
        image_instance.gps_attestation_note = ''

    return None
