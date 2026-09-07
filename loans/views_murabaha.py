"""Murabaha cost-plus file. Hidden for DECSI general files."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from loans.forms import MurabahaContractForm
from loans.models import LoanRequest, MurabahaContract, ShariaReview
from loans.murabaha_overlay import (
    can_edit_murabaha_file,
    can_view_murabaha_file,
    compute_selling_price,
    is_murabaha_file,
    murabaha_file_summary,
)
from loans.product_intel import intel_context


def _get_murabaha_loan(user, loan_request_id):
    loan = get_object_or_404(
        LoanRequest.objects.select_related(
            'category', 'branch', 'assigned_loan_officer', 'financing_fund',
        ),
        pk=loan_request_id,
    )
    if not is_murabaha_file(loan) or not can_view_murabaha_file(user, loan):
        return None
    return loan


@login_required
def murabaha_file(request, loan_request_id):
    loan = _get_murabaha_loan(request.user, loan_request_id)
    if loan is None:
        messages.warning(request, 'This file has no Murabaha overlay, or you cannot open it.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)

    contract, _ = MurabahaContract.objects.get_or_create(loan_request=loan)
    can_edit = can_edit_murabaha_file(request.user, loan)
    if request.method == 'POST' and can_edit:
        form = MurabahaContractForm(request.POST, instance=contract)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.selling_price = compute_selling_price(obj.cost_price, obj.markup_pct)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, 'Murabaha contract saved.')
            return redirect('murabaha_file', loan_request_id=loan.id)
    else:
        form = MurabahaContractForm(instance=contract)

    return render(request, 'loans/murabaha_file.html', {
        'loan_request': loan,
        'form': form,
        'contract': contract,
        'can_edit': can_edit,
        'overlay': murabaha_file_summary(loan),
        'sharia_reviews': list(
            loan.sharia_reviews.filter(kind=ShariaReview.KIND_MURABAHA).order_by('-created_at')[:12]
        ),
        **intel_context(loan),
    })


@login_required
@require_POST
def murabaha_sharia_review(request, loan_request_id):
    loan = _get_murabaha_loan(request.user, loan_request_id)
    if loan is None or not can_edit_murabaha_file(request.user, loan):
        messages.warning(request, 'You cannot record a Sharia review on this file.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    action = (request.POST.get('action') or '').strip()
    if action == 'clear':
        status = ShariaReview.STATUS_CLEARED
    elif action == 'return':
        status = ShariaReview.STATUS_RETURNED
    else:
        status = ShariaReview.STATUS_PENDING
    ShariaReview.objects.create(
        loan_request=loan,
        kind=ShariaReview.KIND_MURABAHA,
        status=status,
        note=(request.POST.get('note') or '').strip(),
        reviewed_at=timezone.now(),
        reviewed_by=request.user,
    )
    messages.success(request, 'Sharia review recorded.')
    nxt = (request.POST.get('next') or '').strip()
    if nxt == 'post_approval':
        return redirect('post_approval_detail', loan_request_id=loan.id)
    return redirect('murabaha_file', loan_request_id=loan.id)
