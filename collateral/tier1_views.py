"""Tier 1 collateral views: policy config, evidence pack, unlock workflow."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .evidence_pack import build_collateral_evidence_pack
from .forms import CollateralPolicyConfigForm, CollateralUnlockRequestForm, CollateralUnlockReviewForm
from .governance import log_collateral_event
from .models import CollateralFieldAuditLog, CollateralPolicyConfig, CollateralUnlockRequest
from .views import (
    _can_access_collateral,
    _can_request_collateral_unlock,
    _can_review_collateral_unlock,
    _collateral_eligible_loans,
)


@login_required
@user_passes_test(lambda u: u.role == 'superadmin')
def collateral_policy_config(request):
    config, _ = CollateralPolicyConfig.objects.get_or_create()
    if request.method == 'POST':
        form = CollateralPolicyConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, 'Collateral policy saved.')
            return redirect('collateral:collateral_policy_config')
    else:
        form = CollateralPolicyConfigForm(instance=config)
    blocks = sum(
        1
        for flag in (
            config.block_submit_on_far_photos,
            config.block_submit_on_missing_photo_gps,
            config.block_submit_on_declared_address_mismatch,
            config.block_submit_on_exif_gps_mismatch,
        )
        if flag
    )
    return render(
        request,
        'collateral/collateral_policy_config.html',
        {
            'form': form,
            'config': config,
            'block_rules_on': blocks,
        },
    )


@login_required
@user_passes_test(_can_access_collateral)
def collateral_evidence_pack(request, loan_request_id):
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    pack = build_collateral_evidence_pack(loan_request)
    return render(request, 'collateral/collateral_evidence_pack.html', pack)


@login_required
@user_passes_test(_can_access_collateral)
def collateral_unlock_request(request, loan_request_id):
    if request.method != 'POST':
        return redirect('collateral:summary', loan_request_id=loan_request_id)
    loan_request = get_object_or_404(_collateral_eligible_loans(request.user), pk=loan_request_id)
    if not _can_request_collateral_unlock(request.user, loan_request):
        messages.error(request, 'Cannot request unlock for this loan.')
        return redirect('collateral:summary', loan_request_id=loan_request_id)
    form = CollateralUnlockRequestForm(request.POST)
    if form.is_valid():
        CollateralUnlockRequest.objects.create(
            loan_request=loan_request,
            requested_by=request.user,
            reason=form.cleaned_data['reason'],
            previous_submitted_at=loan_request.collateral_submitted_at,
            previous_submitted_by=loan_request.collateral_submitted_by,
        )
        log_collateral_event(
            loan_request,
            CollateralFieldAuditLog.EVT_UNLOCK_REQUESTED,
            user=request.user,
            payload={'reason': form.cleaned_data['reason'][:500]},
        )
        messages.success(request, 'Unlock request sent for engineering review.')
    else:
        messages.error(request, 'Please provide a detailed reason (min 20 characters).')
    return redirect('collateral:summary', loan_request_id=loan_request_id)


@login_required
def collateral_unlock_queue(request):
    role = getattr(request.user, 'role', None)
    if role not in ('branch_manager', 'engineering_head', 'superadmin', 'admin'):
        messages.warning(request, 'Access denied.')
        return redirect('collateral:dashboard')
    qs = CollateralUnlockRequest.objects.filter(
        status=CollateralUnlockRequest.STATUS_PENDING,
    ).select_related('loan_request', 'loan_request__branch', 'requested_by')
    if role == 'branch_manager' and getattr(request.user, 'branch_id', None):
        qs = qs.filter(loan_request__branch_id=request.user.branch_id)
    from loans.pagination import page_querystring, paginate
    page_obj = paginate(request, qs.order_by('requested_at'))
    return render(request, 'collateral/unlock_queue.html', {
        'requests': page_obj,
        'page_obj': page_obj,
        'querystring': page_querystring(request),
    })


@login_required
def collateral_unlock_review(request, request_id):
    unlock_req = get_object_or_404(
        CollateralUnlockRequest.objects.select_related('loan_request'),
        pk=request_id,
    )
    loan_request = unlock_req.loan_request
    if not _can_review_collateral_unlock(request.user, loan_request):
        messages.error(request, 'You cannot review this unlock request.')
        return redirect('collateral:unlock_queue')
    if unlock_req.status != CollateralUnlockRequest.STATUS_PENDING:
        messages.info(request, 'This request was already processed.')
        return redirect('collateral:unlock_queue')
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        form = CollateralUnlockReviewForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Invalid form.')
            return redirect('collateral:unlock_queue')
        note = form.cleaned_data.get('review_note', '')
        if action == 'approve':
            unlock_req.status = CollateralUnlockRequest.STATUS_APPROVED
            unlock_req.reviewed_by = request.user
            unlock_req.reviewed_at = timezone.now()
            unlock_req.review_note = note
            unlock_req.save()
            loan_request.collateral_submitted_at = None
            loan_request.collateral_submitted_by = None
            update_fields = ['collateral_submitted_at', 'collateral_submitted_by']
            from .engineering_qa import engineering_review_required
            from loans.models import LoanRequest
            from .services.notifications import notify_engineering_returned

            # Keep LO visibility consistent with engineering return.
            if engineering_review_required():
                loan_request.collateral_engineering_status = LoanRequest.ENG_COLLATERAL_RETURNED
                loan_request.collateral_engineering_return_note = (
                    note or 'Reopened by engineering for correction.'
                )[:2000]
                loan_request.collateral_engineering_reviewed_at = timezone.now()
                loan_request.collateral_engineering_reviewed_by = request.user
                update_fields.extend([
                    'collateral_engineering_status',
                    'collateral_engineering_return_note',
                    'collateral_engineering_reviewed_at',
                    'collateral_engineering_reviewed_by',
                ])
            loan_request.save(update_fields=update_fields)
            log_collateral_event(
                loan_request,
                CollateralFieldAuditLog.EVT_UNLOCK_APPROVED,
                user=request.user,
                subject_type='CollateralUnlockRequest',
                subject_id=unlock_req.pk,
                payload={
                    'previous_submitted_at': (
                        unlock_req.previous_submitted_at.isoformat()
                        if unlock_req.previous_submitted_at else None
                    ),
                    'note': note[:500],
                },
            )
            if engineering_review_required():
                officer = loan_request.assigned_loan_officer
                notify_engineering_returned(
                    loan_request,
                    officer,
                    loan_request.collateral_engineering_return_note,
                )
            messages.success(
                request,
                f'Collateral unlocked for {loan_request.loan_request_id}. Officer may edit and re-submit.',
            )
        elif action == 'reject':
            unlock_req.status = CollateralUnlockRequest.STATUS_REJECTED
            unlock_req.reviewed_by = request.user
            unlock_req.reviewed_at = timezone.now()
            unlock_req.review_note = note
            unlock_req.save()
            log_collateral_event(
                loan_request,
                CollateralFieldAuditLog.EVT_UNLOCK_REJECTED,
                user=request.user,
                subject_id=unlock_req.pk,
                payload={'note': note[:500]},
            )
            messages.info(request, 'Unlock request rejected.')
        return redirect('collateral:unlock_queue')
    return render(request, 'collateral/unlock_review.html', {
        'unlock_req': unlock_req,
        'loan_request': loan_request,
        'form': CollateralUnlockReviewForm(),
    })
