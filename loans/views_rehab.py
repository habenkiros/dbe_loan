"""Rehab / recovery desk — named stages, SLA, insurance, appeals."""

from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from loans.book_ops import user_can_access_book_ops, user_can_decide_workout
from loans.credit_intelligence import scoped_loans
from loans.models import (
    InsurancePolicy,
    LoanAppeal,
    LoanRequest,
    RehabCase,
    RevaluationDiary,
)
from loans.pagination import paginate
from loans.rehab import (
    can_move_rehab,
    get_rehab_case,
    postbook_summary,
    set_rehab_stage,
    sla_breach_q,
)


def _scoped_loan(user, loan_request_id):
    qs, _label = scoped_loans(user)
    return get_object_or_404(qs, pk=loan_request_id)


@login_required
@user_passes_test(user_can_access_book_ops)
def rehab_desk(request):
    qs, _label = scoped_loans(request.user)
    qs = qs.select_related('branch', 'category', 'rehab')
    stage = (request.GET.get('stage') or '').strip()
    view = (request.GET.get('view') or '').strip()
    if view == 'sla':
        qs = qs.filter(sla_breach_q())
    elif view == 'appeals':
        qs = qs.filter(appeals__status=LoanAppeal.STATUS_OPEN).distinct()
    elif view == 'insurance':
        qs = qs.filter(
            insurance_policies__expires_on__lt=timezone.localdate(),
        ).distinct()
    elif stage and stage in {k for k, _ in RehabCase.STAGE_CHOICES}:
        qs = qs.filter(rehab__stage=stage)
    else:
        qs = qs.filter(rehab__isnull=False)
    page_obj = paginate(request, qs.order_by('-date_requested'))
    rows = []
    for loan in page_obj:
        rows.append((loan, postbook_summary(loan)))
    return render(request, 'loans/rehab_desk.html', {
        'page_obj': page_obj,
        'rows': rows,
        'stage': stage,
        'view': view,
        'stage_choices': RehabCase.STAGE_CHOICES,
    })


@login_required
@user_passes_test(user_can_access_book_ops)
def rehab_loan(request, loan_request_id):
    loan = _scoped_loan(request.user, loan_request_id)
    case = get_rehab_case(loan)
    summary = postbook_summary(loan)
    events = list(case.events.select_related('recorded_by')[:30]) if case else []
    return render(request, 'loans/rehab_loan.html', {
        'loan_request': loan,
        'case': case,
        'postbook': summary,
        'events': events,
        'stage_choices': RehabCase.STAGE_CHOICES,
        'policies': list(loan.insurance_policies.all()),
        'revaluations': list(loan.revaluations.all()),
        'appeals': list(loan.appeals.select_related('filed_by', 'decided_by')[:20]),
        'can_decide_appeal': user_can_decide_workout(request.user),
        'kind_choices': InsurancePolicy.KIND_CHOICES,
        'appeal_levels': LoanAppeal.LEVEL_CHOICES,
    })


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def rehab_set_stage(request, loan_request_id):
    loan = _scoped_loan(request.user, loan_request_id)
    stage = (request.POST.get('stage') or '').strip()
    note = (request.POST.get('note') or '').strip()
    current = getattr(get_rehab_case(loan), 'stage', None)
    ok, err = can_move_rehab(current, stage)
    if not ok:
        messages.error(request, err)
        return redirect('rehab_loan', loan_request_id=loan.id)
    case, err = set_rehab_stage(loan, stage, request.user, note)
    if err:
        messages.error(request, err)
    else:
        messages.success(request, f'Rehabilitation stage: {case.get_stage_display()}.')
    return redirect('rehab_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def rehab_add_insurance(request, loan_request_id):
    loan = _scoped_loan(request.user, loan_request_id)
    insurer = (request.POST.get('insurer') or '').strip()
    if not insurer:
        messages.error(request, 'Enter the insurer.')
        return redirect('rehab_loan', loan_request_id=loan.id)
    kind = (request.POST.get('kind') or InsurancePolicy.KIND_ASSET).strip()
    valid = {k for k, _ in InsurancePolicy.KIND_CHOICES}
    if kind not in valid:
        kind = InsurancePolicy.KIND_ASSET
    InsurancePolicy.objects.create(
        loan_request=loan,
        kind=kind,
        insurer=insurer,
        policy_number=(request.POST.get('policy_number') or '').strip(),
        dbe_co_beneficiary=request.POST.get('dbe_co_beneficiary') == '1',
        starts_on=_parse_date(request.POST.get('starts_on')),
        expires_on=_parse_date(request.POST.get('expires_on')),
        note=(request.POST.get('note') or '').strip(),
        recorded_by=request.user,
    )
    messages.success(request, 'Insurance policy recorded. DBE should be co-beneficiary.')
    return redirect('rehab_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def rehab_add_revaluation(request, loan_request_id):
    loan = _scoped_loan(request.user, loan_request_id)
    due = _parse_date(request.POST.get('due_on'))
    if due is None:
        messages.error(request, 'Enter a revaluation due date.')
        return redirect('rehab_loan', loan_request_id=loan.id)
    RevaluationDiary.objects.create(
        loan_request=loan,
        due_on=due,
        note=(request.POST.get('note') or '').strip(),
        recorded_by=request.user,
    )
    messages.success(request, 'Revaluation diary entry added.')
    return redirect('rehab_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def rehab_complete_revaluation(request, loan_request_id, row_id):
    loan = _scoped_loan(request.user, loan_request_id)
    row = get_object_or_404(RevaluationDiary, pk=row_id, loan_request=loan)
    row.completed_on = _parse_date(request.POST.get('completed_on')) or timezone.localdate()
    row.save(update_fields=['completed_on'])
    messages.success(request, 'Revaluation marked complete.')
    return redirect('rehab_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def rehab_file_appeal(request, loan_request_id):
    loan = _scoped_loan(request.user, loan_request_id)
    grounds = (request.POST.get('grounds') or '').strip()
    if len(grounds) < 10:
        messages.error(request, 'State the grounds (at least 10 characters).')
        return redirect('rehab_loan', loan_request_id=loan.id)
    level = (request.POST.get('level') or LoanAppeal.LEVEL_PRESIDENT).strip()
    valid = {k for k, _ in LoanAppeal.LEVEL_CHOICES}
    if level not in valid:
        level = LoanAppeal.LEVEL_PRESIDENT
    LoanAppeal.objects.create(
        loan_request=loan,
        level=level,
        grounds=grounds,
        filed_by=request.user,
    )
    messages.success(request, f'Appeal to the {level} filed.')
    return redirect('rehab_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def rehab_decide_appeal(request, loan_request_id, appeal_id):
    loan = _scoped_loan(request.user, loan_request_id)
    if not user_can_decide_workout(request.user):
        messages.warning(request, 'You cannot decide this appeal.')
        return redirect('rehab_loan', loan_request_id=loan.id)
    appeal = get_object_or_404(LoanAppeal, pk=appeal_id, loan_request=loan)
    if appeal.status != LoanAppeal.STATUS_OPEN:
        messages.warning(request, 'This appeal is already decided.')
        return redirect('rehab_loan', loan_request_id=loan.id)
    action = (request.POST.get('action') or '').strip()
    if action not in (LoanAppeal.STATUS_UPHELD, LoanAppeal.STATUS_DISMISSED):
        messages.error(request, 'Choose uphold or dismiss.')
        return redirect('rehab_loan', loan_request_id=loan.id)
    appeal.status = action
    appeal.decision_note = (request.POST.get('decision_note') or '').strip()
    appeal.decided_by = request.user
    appeal.decided_at = timezone.now()
    appeal.save(update_fields=['status', 'decision_note', 'decided_by', 'decided_at'])
    messages.success(request, f'Appeal {appeal.get_status_display().lower()}.')
    return redirect('rehab_loan', loan_request_id=loan.id)


def _parse_date(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None
