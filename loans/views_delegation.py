"""Manage staff authority delegations (request → admin approve / revoke)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from loans.delegation import (
    SCOPE_CHOICES,
    given_delegations,
    pending_delegation_qs,
    received_delegations,
    user_can_approve_delegations,
    user_can_manage_delegations,
)
from loans.forms_delegation import StaffDelegationForm
from loans.models import StaffDelegation


@login_required
@user_passes_test(user_can_manage_delegations)
def manage_delegations(request):
    """Staff request cover (proposed delegate); admins approve / revoke."""
    principal = request.user
    form = StaffDelegationForm(principal=principal)
    if request.method == 'POST':
        form = StaffDelegationForm(request.POST, principal=principal)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            messages.success(
                request,
                f'Delegation requested: {obj.delegate.get_full_name() or obj.delegate.username} '
                f'is proposed to act for you until '
                f'{timezone.localtime(obj.ends_at).strftime("%d %b %Y %H:%M")}. '
                f'An admin must approve before it takes effect. '
                f'It ends automatically on the end date (or when an admin revokes).',
            )
            return redirect('manage_delegations')

    can_approve = user_can_approve_delegations(request.user)
    given = list(
        StaffDelegation.objects.filter(principal=principal)
        .select_related('delegate', 'reviewed_by', 'revoked_by')
        .order_by('-created_at')[:40]
    )
    admin_active = []
    if can_approve:
        admin_active = list(
            StaffDelegation.objects.filter(
                status=StaffDelegation.STATUS_APPROVED,
                is_active=True,
            )
            .select_related('principal', 'delegate', 'reviewed_by')
            .order_by('-starts_at')[:100]
        )
    return render(request, 'loans/manage_delegations.html', {
        'form': form,
        'given': given,
        'received': received_delegations(principal),
        'pending': list(pending_delegation_qs()) if can_approve else [],
        'admin_active': admin_active,
        'can_approve': can_approve,
        'scope_choices': SCOPE_CHOICES,
        'active_given': given_delegations(principal),
    })


@login_required
@user_passes_test(user_can_approve_delegations)
@require_http_methods(['POST'])
def approve_delegation(request, delegation_id):
    d = get_object_or_404(StaffDelegation, pk=delegation_id)
    if d.status != StaffDelegation.STATUS_PENDING:
        messages.warning(request, 'Only pending requests can be approved.')
        return redirect('manage_delegations')
    now = timezone.now()
    d.status = StaffDelegation.STATUS_APPROVED
    d.is_active = True
    d.reviewed_by = request.user
    d.reviewed_at = now
    d.review_note = (request.POST.get('review_note') or '').strip()[:255]
    d.save(update_fields=[
        'status', 'is_active', 'reviewed_by', 'reviewed_at', 'review_note',
    ])
    messages.success(
        request,
        f'Approved: {d.delegate.get_full_name() or d.delegate.username} '
        f'is signed to act for {d.principal.get_full_name() or d.principal.username}.',
    )
    return redirect('manage_delegations')


@login_required
@user_passes_test(user_can_approve_delegations)
@require_http_methods(['POST'])
def reject_delegation(request, delegation_id):
    d = get_object_or_404(StaffDelegation, pk=delegation_id)
    if d.status != StaffDelegation.STATUS_PENDING:
        messages.warning(request, 'Only pending requests can be rejected.')
        return redirect('manage_delegations')
    d.status = StaffDelegation.STATUS_REJECTED
    d.is_active = False
    d.reviewed_by = request.user
    d.reviewed_at = timezone.now()
    d.review_note = (request.POST.get('review_note') or '').strip()[:255]
    d.save(update_fields=[
        'status', 'is_active', 'reviewed_by', 'reviewed_at', 'review_note',
    ])
    messages.info(request, 'Delegation request rejected.')
    return redirect('manage_delegations')


@login_required
@user_passes_test(user_can_approve_delegations)
@require_http_methods(['POST'])
def revoke_delegation(request, delegation_id):
    """Only admin/superadmin may revoke. Cover otherwise ends at ends_at."""
    d = get_object_or_404(StaffDelegation, pk=delegation_id)
    if d.status not in (StaffDelegation.STATUS_APPROVED, StaffDelegation.STATUS_PENDING):
        messages.warning(request, 'This delegation cannot be revoked in its current state.')
        return redirect('manage_delegations')
    d.status = StaffDelegation.STATUS_REVOKED
    d.is_active = False
    d.revoked_at = timezone.now()
    d.revoked_by = request.user
    d.save(update_fields=['status', 'is_active', 'revoked_at', 'revoked_by'])
    messages.info(request, 'Delegation revoked by admin.')
    return redirect('manage_delegations')
