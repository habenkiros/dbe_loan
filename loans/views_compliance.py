"""Fraud / AML compliance desk views."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from loans.compliance.case_engine import (
    add_case_note,
    assign_case,
    open_case,
    transition_case,
    user_can_access_compliance_desk,
    user_can_manage_compliance_cases,
)
from loans.compliance_desk import QUEUE_CHOICES, compliance_desk_counts, compliance_queue_queryset
from loans.models import ComplianceCase, CustomUser, LoanRequest


@login_required
@user_passes_test(user_can_access_compliance_desk)
def compliance_desk(request):
    queue = (request.GET.get('queue') or 'open').strip()
    if queue not in dict(QUEUE_CHOICES):
        queue = 'open'
    qs, label = compliance_queue_queryset(request.user, queue)
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'loans/compliance_desk.html', {
        'queue': queue,
        'queue_choices': QUEUE_CHOICES,
        'counts': compliance_desk_counts(request.user),
        'page_obj': page_obj,
        'scope_label': label,
    })


@login_required
@user_passes_test(user_can_access_compliance_desk)
def compliance_case_detail(request, case_id):
    case = get_object_or_404(
        ComplianceCase.objects.select_related(
            'loan_request', 'loan_request__branch', 'document', 'assigned_to', 'opened_by', 'closed_by',
        ),
        pk=case_id,
    )
    events = case.events.select_related('recorded_by').order_by('created_at')
    assignees = CustomUser.objects.filter(
        role='risk_compliance', is_active=True,
    ).order_by('username')
    can_manage = user_can_manage_compliance_cases(request.user)
    return render(request, 'loans/compliance_case_detail.html', {
        'case': case,
        'events': events,
        'assignees': assignees,
        'can_manage': can_manage,
        'status_choices': ComplianceCase.STATUS_CHOICES,
    })


@login_required
@user_passes_test(user_can_manage_compliance_cases)
@require_POST
def compliance_case_action(request, case_id):
    case = get_object_or_404(ComplianceCase, pk=case_id)
    action = (request.POST.get('action') or '').strip()
    note = (request.POST.get('note') or '').strip()

    try:
        if action == 'investigate':
            transition_case(case, request.user, ComplianceCase.STATUS_INVESTIGATING, note=note)
            messages.success(request, 'Case marked investigating.')
        elif action == 'escalate':
            transition_case(case, request.user, ComplianceCase.STATUS_ESCALATED, note=note)
            messages.success(request, 'Case escalated.')
        elif action == 'close':
            if len(note) < 10:
                raise ValueError('Resolution note required (min 10 characters).')
            transition_case(case, request.user, ComplianceCase.STATUS_CLOSED, note=note)
            messages.success(request, 'Case closed.')
        elif action == 'false_positive':
            if len(note) < 10:
                raise ValueError('Explain why this is a false positive (min 10 characters).')
            transition_case(case, request.user, ComplianceCase.STATUS_FALSE_POSITIVE, note=note)
            messages.success(request, 'Case closed as false positive.')
        elif action == 'note':
            add_case_note(case, request.user, note)
            messages.success(request, 'Note added.')
        elif action == 'assign':
            uid = request.POST.get('assignee_id')
            assignee = get_object_or_404(CustomUser, pk=uid, role='risk_compliance')
            assign_case(case, request.user, assignee)
            messages.success(request, f'Assigned to {assignee.username}.')
        else:
            messages.warning(request, 'Unknown action.')
    except ValueError as exc:
        messages.error(request, str(exc))

    return redirect('compliance_case_detail', case_id=case.pk)


@login_required
@user_passes_test(user_can_manage_compliance_cases)
@require_POST
def compliance_open_manual_case(request):
    loan_id = request.POST.get('loan_request_id')
    loan = get_object_or_404(LoanRequest, pk=loan_id) if loan_id else None
    summary = (request.POST.get('summary') or '').strip()
    case_type = (request.POST.get('case_type') or ComplianceCase.TYPE_FRAUD).strip()
    valid_types = {c[0] for c in ComplianceCase.TYPE_CHOICES}
    if case_type not in valid_types:
        case_type = ComplianceCase.TYPE_FRAUD
    if len(summary) < 10:
        messages.error(request, 'Enter a case summary (min 10 characters).')
        if loan:
            return redirect('loan_request_detail', loan_request_id=loan.pk)
        return redirect('compliance_desk')
    case = open_case(
        case_type=case_type,
        source=ComplianceCase.SOURCE_MANUAL,
        summary=summary,
        loan_request=loan,
        opened_by=request.user,
        priority=(request.POST.get('priority') or 'medium').strip(),
        metadata={'fingerprint': f'manual:{loan.pk if loan else "none"}:{summary[:40]}'},
        fingerprint=f'manual:{loan.pk if loan else "none"}',
    )
    if case:
        messages.success(request, f'Case {case.case_number} opened.')
        return redirect('compliance_case_detail', case_id=case.pk)
    messages.warning(request, 'Case engine disabled or duplicate.')
    return redirect('compliance_desk')


@login_required
@user_passes_test(user_can_manage_compliance_cases)
@require_POST
def compliance_rescreen_loan(request, loan_request_id):
    loan = get_object_or_404(LoanRequest, pk=loan_request_id)
    from loans.compliance.case_engine import screen_loan_and_open_case

    case = screen_loan_and_open_case(
        loan,
        opened_by=request.user,
        source=ComplianceCase.SOURCE_NAME_SCREEN,
    )
    if case:
        messages.warning(request, f'Sanctions/PEP hit — case {case.case_number} opened.')
        return redirect('compliance_case_detail', case_id=case.pk)
    messages.success(request, 'Sanctions/PEP screen clear (or provider off).')
    return redirect('loan_request_detail', loan_request_id=loan.pk)
