"""Offline PWA endpoints: service worker, manifest, loan bundle, sync queue."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .field_utils import (
    apply_site_gps_from_post,
    apply_site_gps_to_instance,
    get_building_readiness,
    get_land_readiness,
    get_other_item_readiness,
    save_field_visit_boq,
    save_field_visit_photo,
    save_land_field_photo,
    save_other_field_photo,
)
from .forms import BuildingForm, LandValuationForm, OtherCollateralItemForm
from .governance import collateral_is_locked
from .models import Building, LandValuation, OtherCollateralItem
from .views import (
    _build_work_items_flat,
    _can_access_collateral,
    _collateral_eligible_loans,
    _get_unit_price_for_building,
    _get_work_item_ids_with_unit_price,
    _user_can_edit_unit_price,
)


def _static_file(*parts: str) -> Path:
    return Path(settings.BASE_DIR) / 'static' / Path(*parts)


@require_GET
def collateral_service_worker(request):
    """Serve SW from /collateral/sw.js so scope can be /collateral/."""
    path = _static_file('js', 'collateral_sw.js')
    body = path.read_text(encoding='utf-8') if path.is_file() else ''
    response = HttpResponse(body, content_type='application/javascript; charset=utf-8')
    response['Service-Worker-Allowed'] = '/collateral/'
    response['Cache-Control'] = 'no-cache'
    return response


@require_GET
def collateral_offline_manifest(request):
    path = _static_file('manifest-collateral.webmanifest')
    body = path.read_text(encoding='utf-8') if path.is_file() else '{}'
    return HttpResponse(body, content_type='application/manifest+json; charset=utf-8')


def _image_files_from_payload(image: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not image or not image.get('data_base64'):
        return {}
    try:
        raw = base64.b64decode(image['data_base64'])
    except (ValueError, TypeError):
        return {}
    name = (image.get('name') or 'photo.jpg')[:120]
    content_type = image.get('type') or 'image/jpeg'
    return {
        'image': SimpleUploadedFile(name, raw, content_type=content_type),
    }


def _post_like(fields: Dict[str, Any]):
    """Normalize JSON fields dict for form / GPS helpers (get → str)."""
    class _BagLike(dict):
        def get(self, key, default=None):
            val = super().get(key, default)
            if val is None:
                return default
            return val
    return _BagLike(fields or {})


@login_required
@user_passes_test(_can_access_collateral)
@require_GET
@ensure_csrf_cookie
def offline_loan_bundle(request, loan_request_id):
    """Lightweight loan snapshot for IndexedDB prefetch before field work."""
    loan = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    buildings = []
    for b in Building.objects.filter(loan_request=loan).order_by('id'):
        r = get_building_readiness(b)
        buildings.append({
            'id': b.pk,
            'name': b.name,
            'site_gps_lat': str(b.site_gps_lat) if b.site_gps_lat is not None else None,
            'site_gps_lon': str(b.site_gps_lon) if b.site_gps_lon is not None else None,
            'city_id': b.city_id,
            'ready': r.get('ready'),
            'image_count': r.get('image_count'),
            'field_visit_path': f'/collateral/building/{b.pk}/field-visit/',
        })
    land_payload = None
    land = LandValuation.objects.filter(loan_request=loan).first()
    if land:
        lr = get_land_readiness(land)
        land_payload = {
            'id': land.pk,
            'site_gps_lat': str(land.site_gps_lat) if land.site_gps_lat is not None else None,
            'site_gps_lon': str(land.site_gps_lon) if land.site_gps_lon is not None else None,
            'ready': lr.get('ready'),
            'image_count': lr.get('image_count'),
            'field_visit_path': f'/collateral/loan/{loan.pk}/land/field-visit/',
        }
    other_items = []
    for item in OtherCollateralItem.objects.filter(loan_request=loan).order_by('id'):
        or_ = get_other_item_readiness(item)
        other_items.append({
            'id': item.pk,
            'name': item.name,
            'site_gps_lat': str(item.site_gps_lat) if item.site_gps_lat is not None else None,
            'site_gps_lon': str(item.site_gps_lon) if item.site_gps_lon is not None else None,
            'ready': or_.get('ready'),
            'image_count': or_.get('image_count'),
            'field_visit_path': f'/collateral/other-collateral/{item.pk}/field-visit/',
        })
    bundle = {
        'loan_request_id': loan.pk,
        'loan_request_code': loan.loan_request_id,
        'applicant_name': loan.applicant_name,
        'collateral_type': getattr(loan.collateral, 'name', '') or '',
        'locked': collateral_is_locked(loan),
        'buildings': buildings,
        'land': land_payload,
        'other_items': other_items,
        'summary_path': f'/collateral/loan/{loan.pk}/summary/',
    }
    # Full loan officer pack: every field step + static assets needed with no network
    precache = [
        '/collateral/',
        '/collateral/field-checklist/',
        '/collateral/offline/shell/',
        '/collateral/offline/setup/',
        '/collateral/sw.js',
        '/collateral/offline/manifest.webmanifest',
        '/static/css/styles.css',
        '/static/css/loan_workbench.css',
        '/static/css/collateral_field.css',
        '/static/css/collateral_offline.css',
        '/static/js/collateral_field.js',
        '/static/js/collateral_map.js',
        '/static/js/collateral_offline_db.js',
        '/static/js/collateral_offline.js',
        '/static/vendor/jquery/jquery-3.6.0.min.js',
        '/static/vendor/leaflet/leaflet.css',
        '/static/vendor/leaflet/leaflet.js',
        '/static/vendor/leaflet/images/marker-icon.png',
        '/static/vendor/leaflet/images/marker-icon-2x.png',
        '/static/vendor/leaflet/images/marker-shadow.png',
        '/static/img/collateral-pwa-192.png',
        '/static/img/collateral-pwa-512.png',
        '/static/manifest-collateral.webmanifest',
        bundle['summary_path'],
    ]
    for b in buildings:
        base = b['field_visit_path'].rstrip('/')
        precache.extend([f'{base}/', f'{base}/1/', f'{base}/2/', f'{base}/3/', f'{base}/4/'])
    if land_payload:
        base = land_payload['field_visit_path'].rstrip('/')
        precache.extend([f'{base}/', f'{base}/1/', f'{base}/2/', f'{base}/3/'])
    for item in other_items:
        base = item['field_visit_path'].rstrip('/')
        precache.extend([f'{base}/', f'{base}/1/', f'{base}/2/', f'{base}/3/'])
    # de-dupe preserve order
    seen = set()
    bundle['precache_urls'] = [u for u in precache if not (u in seen or seen.add(u))]
    return JsonResponse({'ok': True, 'bundle': bundle})


def _resolve_subject(loan, visit_kind: str, subject_id: Optional[int], subject_type: str = ''):
    visit_kind = (visit_kind or '').strip().lower()
    subject_type = (subject_type or '').strip().lower()
    # Prefer explicit visit_kind; otherwise infer from subject_type / subject existence.
    if not visit_kind:
        if subject_type in ('building', 'building_site'):
            visit_kind = 'building'
        elif subject_type in ('land', 'land_valuation'):
            visit_kind = 'land'
        elif subject_type in ('other', 'other_collateral', 'othercollateralitem'):
            visit_kind = 'other'
        elif subject_id and OtherCollateralItem.objects.filter(pk=subject_id, loan_request=loan).exists():
            visit_kind = 'other'
        elif subject_id and LandValuation.objects.filter(pk=subject_id, loan_request=loan).exists():
            visit_kind = 'land'
        elif subject_id and Building.objects.filter(pk=subject_id, loan_request=loan).exists():
            visit_kind = 'building'

    if visit_kind in ('building', 'building_site'):
        if not subject_id:
            return None, 'building subject_id required'
        building = Building.objects.filter(pk=subject_id, loan_request=loan).first()
        if not building:
            return None, 'Building not found for this loan'
        return ('building', building), None
    if visit_kind == 'land':
        land = LandValuation.objects.filter(loan_request=loan).first()
        if subject_id and land and land.pk != subject_id:
            land = LandValuation.objects.filter(pk=subject_id, loan_request=loan).first()
        if not land:
            land, _ = LandValuation.objects.get_or_create(loan_request=loan)
        return ('land', land), None
    if visit_kind == 'other':
        if not subject_id:
            return None, 'other subject_id required'
        item = OtherCollateralItem.objects.filter(pk=subject_id, loan_request=loan).first()
        if not item:
            return None, 'Other collateral item not found'
        return ('other', item), None
    return None, f'Unknown visit_kind: {visit_kind or "(empty)"}'


def _sync_building_site(building, fields, user) -> Tuple[bool, str]:
    post = _post_like(fields)
    form = BuildingForm(post, instance=building)
    if not form.is_valid():
        errs = '; '.join(f'{k}: {", ".join(v)}' for k, v in form.errors.items())
        return False, errs or 'Invalid building data'
    form.save()
    building.refresh_from_db()
    if post.get('site_gps_lat'):
        ok, err = apply_site_gps_from_post(building, post, user=user)
        if err:
            return False, err
        if not ok and err is None:
            pass
    return True, 'Building site saved'


def _sync_asset_site(kind: str, instance, fields, user) -> Tuple[bool, str]:
    post = _post_like(fields)
    if kind == 'land':
        form = LandValuationForm(post, instance=instance)
        if not form.is_valid():
            errs = '; '.join(f'{k}: {", ".join(v)}' for k, v in form.errors.items())
            return False, errs or 'Invalid land data'
        form.save()
        instance.refresh_from_db()
        if post.get('site_gps_lat'):
            ok, err = apply_site_gps_to_instance(instance, post, user=user)
            if err:
                return False, err
        return True, 'Land site saved'
    form = OtherCollateralItemForm(post, instance=instance)
    if not form.is_valid():
        errs = '; '.join(f'{k}: {", ".join(v)}' for k, v in form.errors.items())
        return False, errs or 'Invalid asset data'
    form.save()
    instance.refresh_from_db()
    # Vehicles: no site GPS — plate/VIN identity only.
    return True, 'Asset details saved'


def _sync_photo(kind: str, instance, fields, image_payload, user, client_uid: str = '') -> Tuple[bool, str]:
    post = _post_like(fields)
    files = _image_files_from_payload(image_payload)
    if not files:
        return False, 'No image in offline payload'
    # Idempotency: same offline queue item must not create duplicate photos on retry.
    uid = (client_uid or post.get('offline_client_uid') or '').strip()[:80]
    if uid:
        marker = f'offline:{uid}'
        existing_caption = (post.get('caption') or '').strip()
        if marker not in existing_caption:
            post['caption'] = (f'{existing_caption} {marker}'.strip())[:255]
        else:
            post['caption'] = existing_caption[:255]
        if kind == 'building':
            from collateral.models import BuildingImage
            if BuildingImage.objects.filter(building=instance, caption__contains=marker).exists():
                return True, 'Photo already synced'
        elif kind == 'land':
            from collateral.models import LandValuationImage
            if LandValuationImage.objects.filter(land_valuation=instance, caption__contains=marker).exists():
                return True, 'Photo already synced'
        else:
            from collateral.models import OtherCollateralItemImage
            if OtherCollateralItemImage.objects.filter(item=instance, caption__contains=marker).exists():
                return True, 'Photo already synced'
    if kind == 'building':
        return save_field_visit_photo(instance, post, files, user)
    if kind == 'land':
        return save_land_field_photo(instance, post, files, user)
    return save_other_field_photo(instance, post, files, user)


def _sync_boq(building, fields, user) -> Tuple[bool, str]:
    post = _post_like(fields)
    can_edit = _user_can_edit_unit_price(user)
    allowed_sub, allowed_subsub = (
        _get_work_item_ids_with_unit_price(building.city) if building.city_id else (set(), set())
    )
    work_items = _build_work_items_flat(
        set(), set(), allowed_sub_work_ids=allowed_sub, allowed_sub_sub_work_ids=allowed_subsub,
    )
    saved, errors = save_field_visit_boq(
        building,
        post,
        user,
        work_items=work_items,
        get_unit_price=_get_unit_price_for_building,
        can_edit_unit_price=can_edit,
    )
    if errors:
        return False, '; '.join(errors)
    return True, f'Saved {saved} BOQ line(s)'


@login_required
@user_passes_test(_can_access_collateral)
@require_GET
def offline_ping(request):
    """Cheap reachability probe (not cached by the service worker)."""
    return JsonResponse({'ok': True, 'ts': timezone_now_iso()})


def timezone_now_iso():
    from django.utils import timezone
    return timezone.now().isoformat()


@login_required
@user_passes_test(_can_access_collateral)
@require_POST
@ensure_csrf_cookie
def offline_sync_item(request):
    """Apply one queued offline field capture."""
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    loan_id = payload.get('loan_request_id')
    if not loan_id:
        return JsonResponse({'ok': False, 'error': 'loan_request_id required'}, status=400)
    loan = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_id)
    if collateral_is_locked(loan):
        return JsonResponse({'ok': False, 'error': 'Collateral is locked (already submitted)'}, status=403)

    kind = (payload.get('kind') or '').strip()
    visit_kind = (payload.get('visit_kind') or '').strip()
    subject_type = (payload.get('subject_type') or '').strip()
    subject_id = payload.get('subject_id')
    try:
        subject_id = int(subject_id) if subject_id is not None else None
    except (TypeError, ValueError):
        subject_id = None

    # Map queue kinds to visit context when visit_kind omitted (never guess other→land).
    if not visit_kind:
        if kind == 'building_site' or kind == 'boq':
            visit_kind = 'building'
        # asset_site / photo: resolve via subject_type / subject_id below

    resolved, err = _resolve_subject(loan, visit_kind, subject_id, subject_type=subject_type)
    if err:
        return JsonResponse({'ok': False, 'error': err}, status=400)
    subject_kind, instance = resolved
    fields = payload.get('fields') or {}
    image = payload.get('image')
    client_uid = (payload.get('client_uid') or payload.get('id') or '')
    if client_uid is not None:
        client_uid = str(client_uid)

    try:
        if kind == 'building_site':
            if subject_kind != 'building':
                return JsonResponse({'ok': False, 'error': 'building_site requires building subject'}, status=400)
            ok, msg = _sync_building_site(instance, fields, request.user)
        elif kind == 'asset_site':
            if subject_kind not in ('land', 'other'):
                return JsonResponse({'ok': False, 'error': 'asset_site requires land or other subject'}, status=400)
            ok, msg = _sync_asset_site(subject_kind, instance, fields, request.user)
        elif kind == 'photo':
            ok, msg = _sync_photo(subject_kind, instance, fields, image, request.user, client_uid=client_uid)
        elif kind == 'boq':
            if subject_kind != 'building':
                return JsonResponse({'ok': False, 'error': 'boq requires building subject'}, status=400)
            ok, msg = _sync_boq(instance, fields, request.user)
        else:
            return JsonResponse({'ok': False, 'error': f'Unknown kind: {kind}'}, status=400)
    except Exception as exc:  # noqa: BLE001 — surface to client for queue retry
        return JsonResponse({'ok': False, 'error': str(exc)[:500]}, status=500)

    if not ok:
        return JsonResponse({'ok': False, 'error': msg, 'permanent': True}, status=400)
    return JsonResponse({
        'ok': True,
        'message': msg,
        'client_id': payload.get('id'),
        'client_uid': client_uid,
        'kind': kind,
    })


@login_required
@user_passes_test(_can_access_collateral)
@require_GET
def field_tablet_checklist(request):
    """Ops checklist: HTTPS secure context, prepare offline, sync, submit online."""
    return render(request, 'collateral/field_tablet_checklist.html', {
        'page_host': request.get_host(),
        'page_is_secure': request.is_secure(),
        'site_url': getattr(settings, 'SITE_URL', ''),
        'https_proxy_enabled': os.getenv('USE_HTTPS_PROXY', '') == '1',
    })


@require_GET
def offline_shell(request):
    """
    Lightweight offline landing page (cached by Prepare Offline).
    No login required so the installed PWA can open when the server is unreachable.
    """
    return render(request, 'collateral/offline_shell.html', {
        'page_host': request.get_host(),
    })


@require_GET
def offline_ca_certificate(request):
    """Serve the local field CA so phones can install trust (required for SW on Android)."""
    for path in (
        Path(settings.BASE_DIR) / 'deploy' / 'https' / 'certs' / 'decsi-field-ca.crt',
        Path(settings.BASE_DIR) / 'static' / 'certs' / 'decsi-field-ca.crt',
    ):
        if path.is_file():
            body = path.read_bytes()
            response = HttpResponse(body, content_type='application/x-x509-ca-cert')
            response['Content-Disposition'] = 'attachment; filename="decsi-field-ca.crt"'
            response['Cache-Control'] = 'no-cache'
            return response
    return HttpResponse(
        'CA certificate not found. Run scripts/gen_field_https_certs.sh on the PC.',
        status=404,
        content_type='text/plain; charset=utf-8',
    )


@require_GET
def offline_phone_setup(request):
    """Phone-first instructions: install CA → trust HTTPS → download pack → Airplane test."""
    ca_path = Path(settings.BASE_DIR) / 'deploy' / 'https' / 'certs' / 'decsi-field-ca.crt'
    if not ca_path.is_file():
        ca_path = Path(settings.BASE_DIR) / 'static' / 'certs' / 'decsi-field-ca.crt'
    return render(request, 'collateral/offline_phone_setup.html', {
        'page_host': request.get_host(),
        'page_is_secure': request.is_secure(),
        'site_url': getattr(settings, 'SITE_URL', '') or f'https://{request.get_host()}',
        'ca_ready': ca_path.is_file(),
    })
