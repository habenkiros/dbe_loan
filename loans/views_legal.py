"""Legal Administration desk views."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from loans.collateral_legal import (
    collateral_legal_blockers,
    collateral_legal_summary,
    legal_clearance_required,
    legal_papers_required,
)
from loans.legal_desk import (
    QUEUE_CHOICES,
    clear_for_disbursement,
    legal_desk_counts,
    legal_queue_queryset,
    return_to_branch,
    user_can_access_legal_desk,
    user_can_manage_legal,
)
from loans.models import LoanRequest


@login_required
@user_passes_test(user_can_access_legal_desk)
def legal_desk(request):
    queue = (request.GET.get('queue') or 'awaiting').strip()
    if queue not in dict(QUEUE_CHOICES):
        queue = 'awaiting'
    qs, label = legal_queue_queryset(request.user, queue)
    page_obj = Paginator(qs, 15).get_page(request.GET.get('page'))
    return render(request, 'loans/legal_desk.html', {
        'queue': queue,
        'queue_choices': QUEUE_CHOICES,
        'counts': legal_desk_counts(request.user),
        'page_obj': page_obj,
        'scope_label': label,
    })


@login_required
@user_passes_test(user_can_access_legal_desk)
def legal_loan_detail(request, loan_request_id):
    loan = get_object_or_404(
        LoanRequest.objects.select_related('branch', 'assigned_loan_officer', 'legal_cleared_by'),
        pk=loan_request_id,
    )
    legal = collateral_legal_summary(loan)
    return render(request, 'loans/legal_loan_detail.html', {
        'loan_request': loan,
        'legal': legal,
        'papers_required': legal_papers_required(loan),
        'clearance_required': legal_clearance_required(loan),
        'paper_blockers': collateral_legal_blockers(loan),
        'can_manage': user_can_manage_legal(request.user),
    })


@login_required
@user_passes_test(user_can_manage_legal)
@require_POST
def legal_loan_action(request, loan_request_id):
    loan = get_object_or_404(LoanRequest, pk=loan_request_id)
    action = (request.POST.get('action') or '').strip()
    note = (request.POST.get('note') or '').strip()
    try:
        if action == 'clear':
            clear_for_disbursement(loan, request.user, note=note)
            messages.success(request, 'Legal cleared for disbursement.')
        elif action == 'return':
            return_to_branch(loan, request.user, note=note)
            messages.warning(request, 'Returned to branch — Legal clearance removed.')
        else:
            messages.warning(request, 'Unknown action.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('legal_loan_detail', loan_request_id=loan.pk)
