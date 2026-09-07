"""Superadmin Settings → Process policy."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect, render

from loans.forms import ProcessPolicyForm
from loans.process_policy import get_or_create_analysis_policy, get_or_create_process_policy


@login_required
@user_passes_test(lambda u: getattr(u, 'is_superuser', False) or getattr(u, 'role', None) in ('admin', 'superadmin'))
def manage_process_policy(request):
    analysis = get_or_create_analysis_policy()
    process = get_or_create_process_policy()
    if request.method == 'POST':
        form = ProcessPolicyForm(request.POST)
        if form.is_valid():
            analysis.require_risk_review_before_committee = form.cleaned_data[
                'require_risk_review_before_committee'
            ]
            analysis.save(update_fields=['require_risk_review_before_committee'])
            process.book_ops_roles = form.cleaned_data['book_ops_roles']
            process.workout_decide_roles = form.cleaned_data['workout_decide_roles']
            process.require_collateral_restriction = form.cleaned_data['require_collateral_restriction']
            process.require_agreement_signatures = form.cleaned_data['require_agreement_signatures']
            process.require_title_search = form.cleaned_data['require_title_search']
            process.require_mortgage_registration = form.cleaned_data['require_mortgage_registration']
            process.require_notary_stamp = form.cleaned_data['require_notary_stamp']
            process.require_own_contribution = form.cleaned_data['require_own_contribution']
            process.require_legal_clearance = form.cleaned_data['require_legal_clearance']
            process.enable_disbursement_tranches = form.cleaned_data['enable_disbursement_tranches']
            process.save(update_fields=[
                'book_ops_roles', 'workout_decide_roles',
                'require_collateral_restriction', 'require_agreement_signatures',
                'require_title_search', 'require_mortgage_registration',
                'require_notary_stamp', 'require_own_contribution',
                'require_legal_clearance', 'enable_disbursement_tranches',
            ])
            messages.success(request, 'Process policy saved.')
            return redirect('manage_process_policy')
    else:
        form = ProcessPolicyForm(initial={
            'require_risk_review_before_committee': analysis.require_risk_review_before_committee,
            'book_ops_roles': process.book_ops_roles or [],
            'workout_decide_roles': process.workout_decide_roles or [],
            'require_collateral_restriction': process.require_collateral_restriction,
            'require_agreement_signatures': process.require_agreement_signatures,
            'require_title_search': process.require_title_search,
            'require_mortgage_registration': process.require_mortgage_registration,
            'require_notary_stamp': process.require_notary_stamp,
            'require_own_contribution': process.require_own_contribution,
            'require_legal_clearance': process.require_legal_clearance,
            'enable_disbursement_tranches': process.enable_disbursement_tranches,
        })
    return render(request, 'loans/manage_process_policy.html', {
        'form': form,
        'analysis': analysis,
        'process': process,
    })
