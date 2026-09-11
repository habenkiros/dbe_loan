"""Wholesale / PFI institution file. Hidden for DECSI general files."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from loans.forms import PfiInstitutionForm
from loans.models import LoanAppraisal, LoanRequest, PfiInstitutionProfile, PfiUtilizationReport
from loans.wholesale_appraisal import sync_wholesale_decision_to_appraisal
from loans.wholesale_overlay import (
    can_edit_wholesale_file,
    can_view_wholesale_file,
    is_wholesale_file,
    wholesale_file_summary,
)
from loans.product_intel import intel_context


def _get_wholesale_loan(user, loan_request_id):
    loan = get_object_or_404(
        LoanRequest.objects.select_related(
            'category', 'branch', 'assigned_loan_officer', 'financing_fund',
        ),
        pk=loan_request_id,
    )
    if not is_wholesale_file(loan) or not can_view_wholesale_file(user, loan):
        return None
    return loan


@login_required
def wholesale_file(request, loan_request_id):
    loan = _get_wholesale_loan(request.user, loan_request_id)
    if loan is None:
        messages.warning(request, 'This file has no PFI overlay, or you cannot open it.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)

    profile, _ = PfiInstitutionProfile.objects.get_or_create(loan_request=loan)
    appraisal = LoanAppraisal.objects.filter(loan_request=loan).first()
    can_edit = can_edit_wholesale_file(request.user, loan)
    if request.method == 'POST' and can_edit:
        form = PfiInstitutionForm(
            request.POST, instance=profile, appraisal=appraisal, loan_request=loan,
        )
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            sync_wholesale_decision_to_appraisal(
                loan, obj, request.user,
                recommendation=form.cleaned_data.get('recommendation') or '',
                amount_approved=form.cleaned_data.get('amount_approved'),
                rate_approved=form.cleaned_data.get('rate_approved'),
                term_approved_months=form.cleaned_data.get('term_approved_months'),
                recommendation_comment=form.cleaned_data.get('recommendation_comment') or '',
                strengths=form.cleaned_data.get('strengths') or '',
                weaknesses=form.cleaned_data.get('weaknesses') or '',
            )
            messages.success(request, 'PFI appraisal saved — scorecard and recommendation updated.')
            return redirect('wholesale_file', loan_request_id=loan.id)
    else:
        form = PfiInstitutionForm(instance=profile, appraisal=appraisal, loan_request=loan)

    reports = list(profile.utilization_reports.select_related('recorded_by')[:12])
    return render(request, 'loans/wholesale_file.html', {
        'loan_request': loan,
        'form': form,
        'profile': profile,
        'reports': reports,
        'can_edit': can_edit,
        'overlay': wholesale_file_summary(loan),
        **intel_context(loan),
    })


@login_required
@require_POST
def wholesale_add_utilization(request, loan_request_id):
    loan = _get_wholesale_loan(request.user, loan_request_id)
    if loan is None or not can_edit_wholesale_file(request.user, loan):
        messages.warning(request, 'You cannot record PFI utilization on this file.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile, _ = PfiInstitutionProfile.objects.get_or_create(loan_request=loan)
    raw_date = (request.POST.get('as_of') or '').strip()
    try:
        as_of = datetime.strptime(raw_date, '%Y-%m-%d').date() if raw_date else timezone.localdate()
    except ValueError:
        as_of = timezone.localdate()

    def _dec(name):
        raw = (request.POST.get(name) or '').strip()
        if raw == '':
            return None
        try:
            return Decimal(raw)
        except (InvalidOperation, TypeError, ValueError):
            return None

    PfiUtilizationReport.objects.create(
        profile=profile,
        as_of=as_of,
        amount_onlent=_dec('amount_onlent') or Decimal('0'),
        pfi_repaid_to_dbe=_dec('pfi_repaid_to_dbe') or Decimal('0'),
        sub_par30_pct=_dec('sub_par30_pct'),
        sub_par90_pct=_dec('sub_par90_pct'),
        women_onlent_pct=_dec('women_onlent_pct'),
        youth_onlent_pct=_dec('youth_onlent_pct'),
        note=(request.POST.get('note') or '').strip(),
        recorded_by=request.user,
    )
    messages.success(request, 'PFI utilization report recorded.')
    nxt = (request.POST.get('next') or '').strip()
    if nxt == 'post_approval':
        return redirect('post_approval_detail', loan_request_id=loan.id)
    return redirect('wholesale_file', loan_request_id=loan.id)
