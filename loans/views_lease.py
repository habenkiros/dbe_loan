"""Lease / Ijarah asset register. Hidden for DECSI general files."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from loans.forms import LeaseAssetForm
from loans.lease_overlay import (
    can_edit_lease_file,
    can_view_lease_file,
    is_ijarah_file,
    is_lease_file,
    lease_file_summary,
)
from loans.models import IjarahRentLine, LeaseAssetProfile, LoanRequest, ShariaReview
from loans.product_intel import intel_context


def _get_lease_loan(user, loan_request_id):
    loan = get_object_or_404(
        LoanRequest.objects.select_related(
            'category', 'branch', 'assigned_loan_officer', 'financing_fund',
        ),
        pk=loan_request_id,
    )
    if not is_lease_file(loan) or not can_view_lease_file(user, loan):
        return None
    return loan


@login_required
def lease_file(request, loan_request_id):
    loan = _get_lease_loan(request.user, loan_request_id)
    if loan is None:
        messages.warning(request, 'This file has no lease overlay, or you cannot open it.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)

    profile, _ = LeaseAssetProfile.objects.get_or_create(loan_request=loan)
    can_edit = can_edit_lease_file(request.user, loan)
    if request.method == 'POST' and can_edit:
        form = LeaseAssetForm(request.POST, instance=profile)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, 'Lease asset register saved.')
            return redirect('lease_file', loan_request_id=loan.id)
    else:
        form = LeaseAssetForm(instance=profile)

    return render(request, 'loans/lease_file.html', {
        'loan_request': loan,
        'form': form,
        'profile': profile,
        'can_edit': can_edit,
        'is_ijarah': is_ijarah_file(loan),
        'overlay': lease_file_summary(loan),
        'rent_lines': list(profile.rent_lines.order_by('period_number')),
        'sharia_reviews': list(loan.sharia_reviews.order_by('-created_at')[:12]),
        **intel_context(loan),
    })


@login_required
@require_POST
def lease_add_rent(request, loan_request_id):
    loan = _get_lease_loan(request.user, loan_request_id)
    if loan is None or not can_edit_lease_file(request.user, loan) or not is_ijarah_file(loan):
        messages.warning(request, 'You cannot add rent lines on this file.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile, _ = LeaseAssetProfile.objects.get_or_create(loan_request=loan)
    try:
        period = int(request.POST.get('period_number') or '0')
    except (TypeError, ValueError):
        period = 0
    raw = (request.POST.get('rent_amount') or '').strip()
    try:
        amount = Decimal(raw) if raw else None
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    if period < 1 or amount is None or amount <= 0:
        messages.error(request, 'Enter a period number and a positive rent amount.')
        return redirect('lease_file', loan_request_id=loan.id)
    due = (request.POST.get('due_date') or '').strip()
    due_date = None
    if due:
        try:
            due_date = datetime.strptime(due, '%Y-%m-%d').date()
        except ValueError:
            due_date = None
    IjarahRentLine.objects.update_or_create(
        profile=profile, period_number=period,
        defaults={'rent_amount': amount, 'due_date': due_date},
    )
    messages.success(request, 'Rent line saved.')
    return redirect('lease_file', loan_request_id=loan.id)


@login_required
@require_POST
def lease_delete_rent(request, loan_request_id, line_id):
    loan = _get_lease_loan(request.user, loan_request_id)
    if loan is None or not can_edit_lease_file(request.user, loan):
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile = getattr(loan, 'lease_asset', None)
    if profile:
        IjarahRentLine.objects.filter(pk=line_id, profile=profile).delete()
        messages.success(request, 'Rent line removed.')
    return redirect('lease_file', loan_request_id=loan.id)


@login_required
@require_POST
def lease_sharia_review(request, loan_request_id):
    loan = _get_lease_loan(request.user, loan_request_id)
    if loan is None or not can_edit_lease_file(request.user, loan) or not is_ijarah_file(loan):
        messages.warning(request, 'You cannot record a Sharia review on this file.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    action = (request.POST.get('action') or '').strip()
    note = (request.POST.get('note') or '').strip()
    if action == 'clear':
        status = ShariaReview.STATUS_CLEARED
    elif action == 'return':
        status = ShariaReview.STATUS_RETURNED
    else:
        status = ShariaReview.STATUS_PENDING
    ShariaReview.objects.create(
        loan_request=loan,
        kind=ShariaReview.KIND_IJARAH,
        status=status,
        note=note,
        reviewed_at=timezone.now(),
        reviewed_by=request.user,
    )
    messages.success(request, 'Sharia review recorded.')
    nxt = (request.POST.get('next') or '').strip()
    if nxt == 'post_approval':
        return redirect('post_approval_detail', loan_request_id=loan.id)
    return redirect('lease_file', loan_request_id=loan.id)
