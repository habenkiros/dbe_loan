"""Post-disbursement monitoring and collections desks."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from loans.book_ops import (
    disbursed_loans_qs,
    overdue_covenants,
    set_watchlist,
    user_can_access_book_ops,
    user_can_decide_workout,
)
from loans.disbursement import set_condition_fulfilled
from loans.models import (
    AppraisalCondition,
    LoanCollectionAction,
    LoanMonitoringVisit,
    LoanRequest,
)
from loans.pagination import paginate


def _get_disbursed_loan(user, loan_request_id):
    return get_object_or_404(disbursed_loans_qs(user), pk=loan_request_id)


@login_required
@user_passes_test(user_can_access_book_ops)
def monitoring_desk(request):
    qs = disbursed_loans_qs(request.user)
    watch = (request.GET.get('watch') or '').strip()
    if watch == '1':
        qs = qs.filter(watchlist=True)
    page_obj = paginate(request, qs)
    return render(request, 'loans/monitoring_desk.html', {
        'page_obj': page_obj,
        'watch': watch,
    })


@login_required
@user_passes_test(user_can_access_book_ops)
def monitoring_loan(request, loan_request_id):
    loan = _get_disbursed_loan(request.user, loan_request_id)
    appraisal = getattr(loan, 'appraisal', None)
    covenants = []
    if appraisal:
        covenants = list(
            appraisal.conditions.filter(condition_type=AppraisalCondition.TYPE_COVENANT).order_by('due_date', 'id')
        )
    visits = loan.monitoring_visits.select_related('recorded_by')[:20]
    from loans.rehab import postbook_summary
    from loans.engines import get_engine
    from loans.product_family import (
        FAMILY_IDEA_EQUITY, FAMILY_IFB_IJARAH, FAMILY_IFB_MURABAHA,
        FAMILY_LEASE, FAMILY_PROJECT, FAMILY_WHOLESALE,
    )
    engine = get_engine(loan)
    return render(request, 'loans/monitoring_loan.html', {
        'loan_request': loan,
        'covenants': covenants,
        'overdue': overdue_covenants(loan),
        'visits': visits,
        'is_project': engine.family == FAMILY_PROJECT,
        'is_wholesale': engine.family == FAMILY_WHOLESALE,
        'is_lease': engine.family in (FAMILY_LEASE, FAMILY_IFB_IJARAH),
        'is_ijarah': engine.family == FAMILY_IFB_IJARAH,
        'is_murabaha': engine.family == FAMILY_IFB_MURABAHA,
        'is_idea': engine.family == FAMILY_IDEA_EQUITY,
        'postbook': postbook_summary(loan),
    })


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def monitoring_add_visit(request, loan_request_id):
    loan = _get_disbursed_loan(request.user, loan_request_id)
    notes = (request.POST.get('notes') or '').strip()
    visited = (request.POST.get('visited_at') or '').strip()
    if len(notes) < 5:
        messages.error(request, 'Enter a visit note (at least 5 characters).')
        return redirect('monitoring_loan', loan_request_id=loan.id)
    try:
        from datetime import datetime
        visited_at = datetime.strptime(visited, '%Y-%m-%d').date() if visited else timezone.localdate()
    except ValueError:
        visited_at = timezone.localdate()
    lat = lon = None
    try:
        if request.POST.get('gps_lat'):
            lat = Decimal(request.POST.get('gps_lat'))
        if request.POST.get('gps_lon'):
            lon = Decimal(request.POST.get('gps_lon'))
    except (InvalidOperation, TypeError):
        lat = lon = None
    LoanMonitoringVisit.objects.create(
        loan_request=loan,
        visited_at=visited_at,
        notes=notes,
        gps_lat=lat,
        gps_lon=lon,
        recorded_by=request.user,
    )
    messages.success(request, 'Visit recorded.')
    return redirect('monitoring_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def monitoring_covenant_toggle(request, loan_request_id, condition_id):
    loan = _get_disbursed_loan(request.user, loan_request_id)
    condition = get_object_or_404(
        AppraisalCondition,
        pk=condition_id,
        appraisal__loan_request=loan,
        condition_type=AppraisalCondition.TYPE_COVENANT,
    )
    fulfilled = request.POST.get('fulfilled') == '1'
    evidence = (request.POST.get('evidence_note') or '').strip()
    set_condition_fulfilled(condition, request.user, fulfilled=fulfilled, evidence_note=evidence)
    messages.success(request, 'Covenant updated.')
    return redirect('monitoring_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def monitoring_watchlist(request, loan_request_id):
    loan = _get_disbursed_loan(request.user, loan_request_id)
    flagged = request.POST.get('watchlist') == '1'
    reason = (request.POST.get('watchlist_reason') or '').strip()
    if flagged and len(reason) < 5:
        messages.error(request, 'Give a short reason for the watchlist.')
        return redirect('monitoring_loan', loan_request_id=loan.id)
    set_watchlist(loan, request.user, flagged=flagged, reason=reason)
    messages.success(request, 'Watchlist updated.')
    return redirect('monitoring_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
def collections_desk(request):
    qs = disbursed_loans_qs(request.user).exclude(arrears_status=LoanRequest.ARREARS_CURRENT)
    if request.GET.get('all') == '1':
        qs = disbursed_loans_qs(request.user)
    page_obj = paginate(request, qs.order_by('arrears_status', '-disbursed_at'))
    return render(request, 'loans/collections_desk.html', {
        'page_obj': page_obj,
        'show_all': request.GET.get('all') == '1',
    })


@login_required
@user_passes_test(user_can_access_book_ops)
def collections_loan(request, loan_request_id):
    loan = _get_disbursed_loan(request.user, loan_request_id)
    actions = loan.collection_actions.select_related('recorded_by')[:30]
    from loans.rehab import postbook_summary
    return render(request, 'loans/collections_loan.html', {
        'loan_request': loan,
        'actions': actions,
        'arrears_choices': LoanRequest.ARREARS_CHOICES,
        'can_decide': user_can_decide_workout(request.user),
        'postbook': postbook_summary(loan),
    })


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def collections_add_action(request, loan_request_id):
    loan = _get_disbursed_loan(request.user, loan_request_id)
    kind = (request.POST.get('kind') or '').strip()
    notes = (request.POST.get('notes') or '').strip()
    valid = {c[0] for c in LoanCollectionAction.KIND_CHOICES}
    if kind not in valid or len(notes) < 5:
        messages.error(request, 'Choose an action type and enter a note.')
        return redirect('collections_loan', loan_request_id=loan.id)
    LoanCollectionAction.objects.create(
        loan_request=loan, kind=kind, notes=notes, recorded_by=request.user,
    )
    messages.success(request, 'Collection action recorded.')
    return redirect('collections_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def collections_set_arrears(request, loan_request_id):
    loan = _get_disbursed_loan(request.user, loan_request_id)
    status = (request.POST.get('arrears_status') or '').strip()
    valid = {c[0] for c in LoanRequest.ARREARS_CHOICES}
    if status not in valid:
        messages.error(request, 'Invalid arrears status.')
        return redirect('collections_loan', loan_request_id=loan.id)
    loan.arrears_status = status
    loan.save(update_fields=['arrears_status'])
    messages.success(request, 'Arrears status updated.')
    return redirect('collections_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def collections_workout(request, loan_request_id):
    loan = _get_disbursed_loan(request.user, loan_request_id)
    action = (request.POST.get('action') or '').strip()
    if action == 'request':
        note = (request.POST.get('workout_note') or '').strip()
        if len(note) < 10:
            messages.error(request, 'Describe the proposed reschedule (at least 10 characters).')
            return redirect('collections_loan', loan_request_id=loan.id)
        amount = request.POST.get('workout_proposed_amount') or None
        term = request.POST.get('workout_proposed_term_months') or None
        try:
            loan.workout_proposed_amount = Decimal(amount) if amount else None
        except (InvalidOperation, TypeError):
            loan.workout_proposed_amount = None
        try:
            loan.workout_proposed_term_months = int(term) if term else None
        except (TypeError, ValueError):
            loan.workout_proposed_term_months = None
        loan.workout_note = note
        loan.workout_status = LoanRequest.WORKOUT_REQUESTED
        loan.save(update_fields=[
            'workout_status', 'workout_note', 'workout_proposed_amount', 'workout_proposed_term_months',
        ])
        from loans.models import RehabCase
        from loans.rehab import ensure_rehab_stage
        ensure_rehab_stage(
            loan, RehabCase.STAGE_RESTRUCTURE, request.user,
            note=note,
        )
        messages.success(request, 'Reschedule request submitted.')
        return redirect('collections_loan', loan_request_id=loan.id)
    if action in ('approve', 'reject') and user_can_decide_workout(request.user):
        if loan.workout_status != LoanRequest.WORKOUT_REQUESTED:
            messages.warning(request, 'No pending reschedule request.')
            return redirect('collections_loan', loan_request_id=loan.id)
        loan.workout_status = (
            LoanRequest.WORKOUT_APPROVED if action == 'approve' else LoanRequest.WORKOUT_REJECTED
        )
        loan.workout_decided_at = timezone.now()
        loan.workout_decided_by = request.user
        loan.save(update_fields=['workout_status', 'workout_decided_at', 'workout_decided_by'])
        messages.success(request, 'Workout decision saved. CBS posting is not done from the hub.')
        return redirect('collections_loan', loan_request_id=loan.id)
    messages.warning(request, 'You cannot decide workout on this loan.')
    return redirect('collections_loan', loan_request_id=loan.id)


@login_required
@user_passes_test(user_can_access_book_ops)
@require_POST
def collections_writeoff(request, loan_request_id):
    loan = _get_disbursed_loan(request.user, loan_request_id)
    action = (request.POST.get('action') or '').strip()
    if action == 'request':
        note = (request.POST.get('writeoff_note') or '').strip()
        if len(note) < 10:
            messages.error(request, 'Describe the write-off request.')
            return redirect('collections_loan', loan_request_id=loan.id)
        amount = request.POST.get('writeoff_amount') or None
        try:
            loan.writeoff_amount = Decimal(amount) if amount else None
        except (InvalidOperation, TypeError):
            loan.writeoff_amount = None
        loan.writeoff_note = note
        loan.writeoff_status = LoanRequest.WRITEOFF_REQUESTED
        loan.save(update_fields=['writeoff_status', 'writeoff_note', 'writeoff_amount'])
        messages.success(request, 'Write-off request submitted.')
        return redirect('collections_loan', loan_request_id=loan.id)
    if action in ('approve', 'write_back') and user_can_decide_workout(request.user):
        if action == 'approve':
            if loan.writeoff_status != LoanRequest.WRITEOFF_REQUESTED:
                messages.warning(request, 'No pending write-off request.')
                return redirect('collections_loan', loan_request_id=loan.id)
            loan.writeoff_status = LoanRequest.WRITEOFF_APPROVED
        else:
            loan.writeoff_status = LoanRequest.WRITEOFF_WRITTEN_BACK
        loan.writeoff_decided_at = timezone.now()
        loan.writeoff_decided_by = request.user
        loan.save(update_fields=['writeoff_status', 'writeoff_decided_at', 'writeoff_decided_by'])
        messages.success(request, 'Write-off status updated. CBS posting is not done from the hub.')
        return redirect('collections_loan', loan_request_id=loan.id)
    messages.warning(request, 'You cannot decide write-off on this loan.')
    return redirect('collections_loan', loan_request_id=loan.id)
