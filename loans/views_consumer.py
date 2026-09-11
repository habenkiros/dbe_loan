"""HRM consumer (housing / vehicle) appraisal desk."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from loans.consumer_appraisal import sync_consumer_decision_to_appraisal
from loans.consumer_overlay import (
    can_edit_consumer_file,
    can_view_consumer_file,
    consumer_file_summary,
    is_consumer_file,
)
from loans.forms import ConsumerProfileForm
from loans.models import ConsumerProfile, LoanAppraisal, LoanRequest
from loans.product_intel import intel_context


def _get_consumer_loan(user, loan_request_id):
    loan = get_object_or_404(
        LoanRequest.objects.select_related(
            'category', 'branch', 'assigned_loan_officer', 'financing_fund',
        ),
        pk=loan_request_id,
    )
    if not is_consumer_file(loan) or not can_view_consumer_file(user, loan):
        return None
    return loan


@login_required
def consumer_file(request, loan_request_id):
    loan = _get_consumer_loan(request.user, loan_request_id)
    if loan is None:
        messages.warning(request, 'This file has no consumer overlay, or you cannot open it.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)

    profile, _ = ConsumerProfile.objects.get_or_create(loan_request=loan)
    appraisal = LoanAppraisal.objects.filter(loan_request=loan).first()
    can_edit = can_edit_consumer_file(request.user, loan)
    if request.method == 'POST' and can_edit:
        form = ConsumerProfileForm(
            request.POST, instance=profile, appraisal=appraisal, loan_request=loan,
        )
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            sync_consumer_decision_to_appraisal(
                loan, obj, request.user,
                recommendation=form.cleaned_data.get('recommendation') or '',
                amount_approved=form.cleaned_data.get('amount_approved'),
                rate_approved=form.cleaned_data.get('rate_approved'),
                recommendation_comment=form.cleaned_data.get('recommendation_comment') or '',
                strengths=form.cleaned_data.get('strengths') or '',
                weaknesses=form.cleaned_data.get('weaknesses') or '',
            )
            messages.success(request, 'Consumer appraisal saved — scorecard and recommendation updated.')
            return redirect('consumer_file', loan_request_id=loan.id)
    else:
        form = ConsumerProfileForm(instance=profile, appraisal=appraisal, loan_request=loan)

    overlay = consumer_file_summary(loan)
    return render(request, 'loans/consumer_file.html', {
        'loan_request': loan,
        'form': form,
        'profile': profile,
        'can_edit': can_edit,
        'overlay': overlay,
        **intel_context(loan),
    })
