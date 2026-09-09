"""Tier 2 collateral views: engineering QA queue."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from loans.models import LoanRequest

from .engineering_qa import can_review_engineering, engineering_pending_loans, engineering_review_required
from .forms import CollateralEngineeringReviewForm
from .governance import log_collateral_event
from .models import CollateralFieldAuditLog
from .services.notifications import notify_engineering_approved, notify_engineering_returned


@login_required
def engineering_qa_queue(request):
    role = getattr(request.user, 'role', None)
    if role not in ('engineer', 'engineering_head', 'admin', 'superadmin', 'branch_manager'):
        messages.warning(request, 'Access denied.')
        return redirect('collateral:dashboard')
    if not engineering_review_required():
        messages.info(request, 'Engineering QA is not enabled in collateral estimation config.')
        return redirect('collateral:dashboard')
    requests_qs = engineering_pending_loans(request.user)
    can_act = role in ('engineer', 'engineering_head', 'admin', 'superadmin')
    from loans.pagination import page_querystring, paginate
    page_obj = paginate(request, requests_qs)
    return render(request, 'collateral/engineering_qa_queue.html', {
        'pending_loans': page_obj,
        'page_obj': page_obj,
        'can_act_on_queue': can_act,
        'is_branch_manager_view': role == 'branch_manager',
        'querystring': page_querystring(request),
    })


@login_required
def engineering_qa_review(request, loan_request_id):
    loan_request = get_object_or_404(
        LoanRequest.objects.select_related(
            'branch', 'collateral', 'assigned_engineer', 'collateral_submitted_by',
        ),
        pk=loan_request_id,
    )
    if not can_review_engineering(request.user, loan_request):
        messages.error(request, 'You cannot review this collateral submission.')
        return redirect('collateral:engineering_qa_queue')

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        form = CollateralEngineeringReviewForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Invalid form.')
            return redirect('collateral:engineering_qa_review', loan_request_id=loan_request_id)
        note = form.cleaned_data.get('review_note', '')

        if action == 'approve':
            from collateral.engineering_qa import engineering_qa_approve_blockers

            qa_blockers = engineering_qa_approve_blockers(loan_request, form.cleaned_data)
            if qa_blockers:
                messages.error(
                    request,
                    'Cannot approve yet: ' + '; '.join(qa_blockers),
                )
                return redirect('collateral:engineering_qa_review', loan_request_id=loan_request_id)
            loan_request.collateral_engineering_status = LoanRequest.ENG_COLLATERAL_APPROVED
            loan_request.collateral_engineering_reviewed_at = timezone.now()
            loan_request.collateral_engineering_reviewed_by = request.user
            loan_request.collateral_engineering_return_note = ''
            loan_request.save(update_fields=[
                'collateral_engineering_status', 'collateral_engineering_reviewed_at',
                'collateral_engineering_reviewed_by', 'collateral_engineering_return_note',
            ])
            log_collateral_event(
                loan_request,
                CollateralFieldAuditLog.EVT_ENGINEERING_APPROVED,
                user=request.user,
                payload={'note': note[:500]},
            )
            officer = loan_request.collateral_submitted_by or loan_request.assigned_loan_officer
            notify_engineering_approved(loan_request, officer)
            messages.success(request, f'Collateral approved for {loan_request.loan_request_id}.')
            return redirect('collateral:engineering_qa_queue')
        if action == 'return':
            officer = loan_request.assigned_loan_officer or loan_request.collateral_submitted_by
            loan_request.collateral_engineering_status = LoanRequest.ENG_COLLATERAL_RETURNED
            loan_request.collateral_engineering_reviewed_at = timezone.now()
            loan_request.collateral_engineering_reviewed_by = request.user
            loan_request.collateral_engineering_return_note = note
            loan_request.collateral_submitted_at = None
            loan_request.collateral_submitted_by = None
            loan_request.save(update_fields=[
                'collateral_engineering_status', 'collateral_engineering_reviewed_at',
                'collateral_engineering_reviewed_by', 'collateral_engineering_return_note',
                'collateral_submitted_at', 'collateral_submitted_by',
            ])
            log_collateral_event(
                loan_request,
                CollateralFieldAuditLog.EVT_ENGINEERING_RETURNED,
                user=request.user,
                payload={'note': note[:500]},
            )
            notify_engineering_returned(loan_request, officer, note)
            messages.info(request, f'Collateral returned to officer for {loan_request.loan_request_id}.')
            return redirect('collateral:engineering_qa_queue')
        messages.error(request, 'Unknown action.')
        return redirect('collateral:engineering_qa_review', loan_request_id=loan_request_id)

    from collateral.coverage import compute_coverage_adequacy
    from collateral.engineering_qa import engineering_qa_checklist
    from collateral.field_utils import get_loan_collateral_readiness
    from collateral.pipeline import collateral_pipeline_stage, pipeline_stage_label
    from collateral.models import (
        Building, BuildingImage, BuildingValuation, LandValuation, LandValuationImage,
        OtherCollateralItem, OtherCollateralItemImage,
    )
    from loans.services.appraisal_prefill import compute_collateral_totals

    readiness = get_loan_collateral_readiness(loan_request)
    totals = compute_collateral_totals(loan_request)
    photo_previews = []
    for b in Building.objects.filter(loan_request=loan_request):
        for img in BuildingImage.objects.filter(building=b).order_by('-created_at')[:4]:
            if img.image:
                photo_previews.append({
                    'url': img.image.url,
                    'label': f'{b.name} — {img.get_photo_type_display()}',
                    'has_gps': bool(img.gps_lat),
                })
    try:
        land = LandValuation.objects.get(loan_request=loan_request)
        for img in LandValuationImage.objects.filter(land_valuation=land).order_by('-created_at')[:4]:
            if img.image:
                photo_previews.append({
                    'url': img.image.url,
                    'label': f'Land — {img.get_photo_type_display()}',
                    'has_gps': bool(img.gps_lat),
                })
    except LandValuation.DoesNotExist:
        pass
    for item in OtherCollateralItem.objects.filter(loan_request=loan_request):
        for img in OtherCollateralItemImage.objects.filter(item=item).order_by('-created_at')[:4]:
            if img.image:
                photo_previews.append({
                    'url': img.image.url,
                    'label': f'{item.name} — {img.get_photo_type_display()}',
                    'has_gps': bool(img.gps_lat),
                })
    photo_previews = photo_previews[:12]

    building_boq = []
    for b in Building.objects.filter(loan_request=loan_request):
        rows = BuildingValuation.objects.filter(building=b)
        building_boq.append({
            'building': b,
            'line_count': rows.count(),
            'total': sum((r.total or 0) for r in rows),
        })

    return render(request, 'collateral/engineering_qa_review.html', {
        'loan_request': loan_request,
        'form': CollateralEngineeringReviewForm(),
        'coverage': compute_coverage_adequacy(loan_request),
        'pipeline_label': pipeline_stage_label(collateral_pipeline_stage(loan_request)),
        'readiness': readiness,
        'totals': totals,
        'photo_previews': photo_previews,
        'building_boq': building_boq,
        'qa_checklist': engineering_qa_checklist(loan_request),
        'can_review': True,
    })
