"""Fund MIS — envelope, covenant mix, donor export. Not a product wizard."""

import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from loans.forms import FundFileTagForm
from loans.fund_overlay import fund_book, fund_export_rows
from loans.models import FinancingFund, FundFileTag, LoanRequest


def can_view_fund_mis(user) -> bool:
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in (
        'admin', 'superadmin', 'credit_head', 'finance_manager',
        'risk_compliance', 'auditor',
    )


def can_edit_fund_tag(user, loan_request) -> bool:
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in (
        'admin', 'superadmin', 'credit_head', 'branch_manager',
    ):
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    return False


@login_required
def financing_fund_dashboard(request):
    if not can_view_fund_mis(request.user):
        messages.warning(request, 'You cannot open funding-window MIS.')
        return redirect('home')
    funds = []
    for fund in FinancingFund.objects.all().order_by('name'):
        funds.append({'fund': fund, 'book': fund_book(fund)})
    return render(request, 'loans/financing_fund_dashboard.html', {'funds': funds})


@login_required
def financing_fund_export(request, fund_id):
    if not can_view_fund_mis(request.user):
        messages.warning(request, 'You cannot export this funding window.')
        return redirect('home')
    fund = get_object_or_404(FinancingFund, pk=fund_id)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{fund.code}_donor_report.csv"'
    writer = csv.DictWriter(response, fieldnames=[
        'loan_request_id', 'applicant', 'family', 'amount',
        'committee_status', 'disbursement_status',
        'women_owned', 'youth_owned', 'climate', 'region',
        'women_target_pct', 'youth_target_pct',
    ])
    writer.writeheader()
    for row in fund_export_rows(fund):
        writer.writerow(row)
    return response


@login_required
@require_POST
def fund_file_tag(request, loan_request_id):
    loan = get_object_or_404(
        LoanRequest.objects.select_related('financing_fund', 'assigned_loan_officer'),
        pk=loan_request_id,
    )
    if not loan.financing_fund_id or not can_edit_fund_tag(request.user, loan):
        messages.warning(request, 'You cannot tag this file to a funding window.')
        return redirect('loan_request_detail', loan_request_id=loan.id)
    tag, _ = FundFileTag.objects.get_or_create(loan_request=loan)
    form = FundFileTagForm(request.POST, instance=tag)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.updated_by = request.user
        obj.save()
        messages.success(request, 'Funding-window tags saved.')
    else:
        messages.error(request, 'Could not save funding-window tags.')
    nxt = (request.POST.get('next') or '').strip()
    if nxt == 'project':
        return redirect('project_file', loan_request_id=loan.id)
    if nxt == 'wholesale':
        return redirect('wholesale_file', loan_request_id=loan.id)
    return redirect('loan_request_detail', loan_request_id=loan.id)
