"""Tier 3 collateral views: dossier JSON / ZIP export."""

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from .dossier import dossier_json_bytes, dossier_zip_bytes
from .models import CollateralFieldAuditLog
from .views import _can_access_collateral, _collateral_eligible_loans


@login_required
@user_passes_test(_can_access_collateral)
def collateral_dossier_json(request, loan_request_id):
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    payload = dossier_json_bytes(loan_request)
    log_collateral_event(
        loan_request,
        CollateralFieldAuditLog.EVT_DOSSIER_EXPORTED,
        user=request.user,
        payload={'format': 'json'},
    )
    filename = f'collateral-dossier-{loan_request.loan_request_id}.json'
    response = HttpResponse(payload, content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@user_passes_test(_can_access_collateral)
def collateral_dossier_zip(request, loan_request_id):
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    payload = dossier_zip_bytes(loan_request)
    log_collateral_event(
        loan_request,
        CollateralFieldAuditLog.EVT_DOSSIER_EXPORTED,
        user=request.user,
        payload={'format': 'zip'},
    )
    filename = f'collateral-dossier-{loan_request.loan_request_id}.zip'
    response = HttpResponse(payload, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
