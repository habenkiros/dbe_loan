"""Idea / quasi-equity file. Hidden for DECSI general files."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from loans.forms import IdeaProfileForm
from loans.idea_overlay import (
    can_edit_idea_file,
    can_view_idea_file,
    idea_file_summary,
    is_idea_file,
)
from loans.models import CapTableEntry, IdeaProfile, LoanRequest
from loans.product_intel import intel_context


def _get_idea_loan(user, loan_request_id):
    loan = get_object_or_404(
        LoanRequest.objects.select_related(
            'category', 'branch', 'assigned_loan_officer', 'financing_fund',
        ),
        pk=loan_request_id,
    )
    if not is_idea_file(loan) or not can_view_idea_file(user, loan):
        return None
    return loan


@login_required
def idea_file(request, loan_request_id):
    loan = _get_idea_loan(request.user, loan_request_id)
    if loan is None:
        messages.warning(request, 'This file has no idea overlay, or you cannot open it.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)

    profile, _ = IdeaProfile.objects.get_or_create(loan_request=loan)
    can_edit = can_edit_idea_file(request.user, loan)
    if request.method == 'POST' and can_edit:
        form = IdeaProfileForm(request.POST, instance=profile)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, 'Idea file saved.')
            return redirect('idea_file', loan_request_id=loan.id)
    else:
        form = IdeaProfileForm(instance=profile)

    overlay = idea_file_summary(loan)
    return render(request, 'loans/idea_file.html', {
        'loan_request': loan,
        'form': form,
        'profile': profile,
        'can_edit': can_edit,
        'overlay': overlay,
        'cap_rows': list(profile.cap_table.all()),
        'cap_totals': (overlay or {}).get('cap_totals'),
        **intel_context(loan),
    })


@login_required
@require_POST
def idea_add_cap_row(request, loan_request_id):
    loan = _get_idea_loan(request.user, loan_request_id)
    if loan is None or not can_edit_idea_file(request.user, loan):
        messages.warning(request, 'You cannot edit this cap table.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile, _ = IdeaProfile.objects.get_or_create(loan_request=loan)
    name = (request.POST.get('holder_name') or '').strip()
    role = (request.POST.get('role') or CapTableEntry.ROLE_FOUNDER).strip()
    valid = {k for k, _ in CapTableEntry.ROLE_CHOICES}
    if role not in valid:
        role = CapTableEntry.ROLE_OTHER
    raw = (request.POST.get('share_pct') or '').strip()
    try:
        pct = Decimal(raw) if raw else None
    except (InvalidOperation, TypeError, ValueError):
        pct = None
    if not name or pct is None or pct <= 0:
        messages.error(request, 'Enter a holder and a positive share %.')
        return _cap_redirect(request, loan)
    CapTableEntry.objects.create(
        profile=profile,
        holder_name=name,
        role=role,
        share_pct=pct,
        note=(request.POST.get('note') or '').strip(),
    )
    messages.success(request, 'Cap-table row added.')
    return _cap_redirect(request, loan)


@login_required
@require_POST
def idea_delete_cap_row(request, loan_request_id, row_id):
    loan = _get_idea_loan(request.user, loan_request_id)
    if loan is None or not can_edit_idea_file(request.user, loan):
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile = getattr(loan, 'idea_profile', None)
    if profile:
        CapTableEntry.objects.filter(pk=row_id, profile=profile).delete()
        messages.success(request, 'Cap-table row removed.')
    return _cap_redirect(request, loan)


def _cap_redirect(request, loan):
    nxt = (request.POST.get('next') or '').strip()
    if nxt == 'post_approval':
        return redirect('post_approval_detail', loan_request_id=loan.id)
    return redirect('idea_file', loan_request_id=loan.id)
