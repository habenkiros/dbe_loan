"""Project-finance overlay pages. Hidden for DECSI general files."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from loans.forms import ProjectProfileForm
from loans.models import (
    LoanDisbursementTranche,
    LoanRequest,
    ProjectCashflowYear,
    ProjectProfile,
    ProjectSourceUseLine,
    ProjectTechnicalReview,
)
from loans.rehab import postbook_summary
from loans.product_intel import intel_context
from loans.project_overlay import (
    PURPOSE_LABELS,
    can_edit_project_file,
    can_view_project_file,
    compute_project_metrics,
    compute_sensitivity,
    ensure_plant_desks,
    equity_structure,
    is_project_file,
    journey_steps,
    parse_decimal,
    project_file_summary,
    record_implementation_visit,
    seed_lines_from_profile,
    sources_uses_totals,
    year_snapshots,
)


def _get_project_loan(user, loan_request_id):
    loan = get_object_or_404(
        LoanRequest.objects.select_related('category', 'branch', 'assigned_loan_officer'),
        pk=loan_request_id,
    )
    if not is_project_file(loan) or not can_view_project_file(user, loan):
        return None
    return loan


@login_required
def project_file(request, loan_request_id):
    loan = _get_project_loan(request.user, loan_request_id)
    if loan is None:
        messages.warning(request, 'This file has no project overlay, or you cannot open it.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)

    profile, _ = ProjectProfile.objects.get_or_create(loan_request=loan)
    ensure_plant_desks(profile)
    can_edit = can_edit_project_file(request.user, loan)
    if request.method == 'POST' and can_edit:
        form = ProjectProfileForm(request.POST, instance=profile)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, 'Project profile saved.')
            return redirect('project_file', loan_request_id=loan.id)
    else:
        form = ProjectProfileForm(instance=profile)

    lines = list(profile.lines.order_by('side', 'sequence', 'id'))
    cashflows = list(profile.cashflows.order_by('year_number'))
    cashflow_rows = year_snapshots(profile)
    desks = list(profile.technical_reviews.order_by('desk'))
    totals = sources_uses_totals(profile)
    metrics = compute_project_metrics(profile)
    sensitivity = compute_sensitivity(profile)
    visits = list(
        loan.monitoring_visits.filter(visit_kind='implementation').order_by('-visited_at', '-id')[:8]
    )
    ctx = {
        'loan_request': loan,
        'form': form,
        'profile': profile,
        'lines': lines,
        'source_lines': [ln for ln in lines if ln.side == ln.SIDE_SOURCE],
        'use_lines': [ln for ln in lines if ln.side == ln.SIDE_USE],
        'cashflows': cashflows,
        'cashflow_rows': cashflow_rows,
        'sensitivity': sensitivity,
        'desks': desks,
        'metrics': metrics,
        'structure': equity_structure(profile),
        'journey': journey_steps(loan, profile, totals, metrics, desks),
        'totals': totals,
        'can_edit': can_edit,
        'overlay': project_file_summary(loan),
        'postbook': postbook_summary(loan),
        'visits': visits,
        'source_purposes': [
            (ProjectSourceUseLine.PURPOSE_PROMOTER, PURPOSE_LABELS['promoter_cash']),
            (ProjectSourceUseLine.PURPOSE_DBE, PURPOSE_LABELS['dbe_loan']),
            (ProjectSourceUseLine.PURPOSE_OTHER_BANK, PURPOSE_LABELS['other_bank']),
            (ProjectSourceUseLine.PURPOSE_GRANT, PURPOSE_LABELS['grant']),
            (ProjectSourceUseLine.PURPOSE_OTHER, PURPOSE_LABELS['other']),
        ],
        'use_purposes': [
            (ProjectSourceUseLine.PURPOSE_CIVIL, PURPOSE_LABELS['civil']),
            (ProjectSourceUseLine.PURPOSE_MACHINERY, PURPOSE_LABELS['machinery']),
            (ProjectSourceUseLine.PURPOSE_WC, PURPOSE_LABELS['working_capital']),
            (ProjectSourceUseLine.PURPOSE_INSURANCE, PURPOSE_LABELS['insurance']),
            (ProjectSourceUseLine.PURPOSE_OTHER, PURPOSE_LABELS['other']),
        ],
    }
    ctx.update(intel_context(loan))
    return render(request, 'loans/project_file.html', ctx)


@login_required
@require_POST
def project_add_line(request, loan_request_id):
    loan = _get_project_loan(request.user, loan_request_id)
    if loan is None or not can_edit_project_file(request.user, loan):
        messages.warning(request, 'You cannot edit this project file.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile, _ = ProjectProfile.objects.get_or_create(loan_request=loan)
    side = (request.POST.get('side') or '').strip()
    if side not in (ProjectSourceUseLine.SIDE_SOURCE, ProjectSourceUseLine.SIDE_USE):
        messages.error(request, 'Choose source or use.')
        return redirect('project_file', loan_request_id=loan.id)
    amount = parse_decimal(request.POST.get('amount'))
    if amount is None or amount <= 0:
        messages.error(request, 'Enter a positive amount.')
        return redirect('project_file', loan_request_id=loan.id)
    purpose = (request.POST.get('purpose') or ProjectSourceUseLine.PURPOSE_OTHER).strip()
    valid = {k for k, _ in ProjectSourceUseLine.PURPOSE_CHOICES}
    if purpose not in valid:
        purpose = ProjectSourceUseLine.PURPOSE_OTHER
    last = profile.lines.filter(side=side).order_by('-sequence').first()
    ProjectSourceUseLine.objects.create(
        profile=profile,
        side=side,
        purpose=purpose,
        label=(request.POST.get('label') or '').strip(),
        amount=amount,
        sequence=(last.sequence + 1) if last else 1,
    )
    messages.success(request, 'Line added.')
    return redirect(reverse('project_file', args=[loan.id]) + '#su')


@login_required
@require_POST
def project_delete_line(request, loan_request_id, line_id):
    loan = _get_project_loan(request.user, loan_request_id)
    if loan is None or not can_edit_project_file(request.user, loan):
        messages.warning(request, 'You cannot edit this project file.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile = get_project_profile_or_none(loan)
    if profile is None:
        return redirect('project_file', loan_request_id=loan.id)
    ProjectSourceUseLine.objects.filter(pk=line_id, profile=profile).delete()
    messages.success(request, 'Line removed.')
    return redirect(reverse('project_file', args=[loan.id]) + '#su')


@login_required
@require_POST
def project_seed_lines(request, loan_request_id):
    loan = _get_project_loan(request.user, loan_request_id)
    if loan is None or not can_edit_project_file(request.user, loan):
        messages.warning(request, 'You cannot edit this project file.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile, _ = ProjectProfile.objects.get_or_create(loan_request=loan)
    created = seed_lines_from_profile(profile)
    if created:
        messages.success(request, f'Drafted {created} sources & uses lines from cost and equity.')
    else:
        messages.info(request, 'Save cost, equity, and debt first — or clear existing lines.')
    return redirect(reverse('project_file', args=[loan.id]) + '#su')


def get_project_profile_or_none(loan):
    from loans.project_overlay import get_project_profile
    return get_project_profile(loan)


def _sync_computed_metrics(profile):
    metrics = compute_project_metrics(profile)
    profile.npv = metrics['npv']
    profile.irr_pct = metrics['irr_pct']
    profile.project_dscr = metrics['dscr']
    profile.save(update_fields=['npv', 'irr_pct', 'project_dscr'])


@login_required
@require_POST
def project_implementation_visit(request, loan_request_id):
    loan = get_object_or_404(LoanRequest.objects.select_related('category'), pk=loan_request_id)
    if not is_project_file(loan) or not can_edit_project_file(request.user, loan):
        messages.warning(request, 'You cannot record an implementation visit on this file.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    notes = (request.POST.get('notes') or '').strip()
    if len(notes) < 5:
        messages.error(request, 'Enter a visit note (at least 5 characters).')
        return _visit_redirect(request, loan)
    visited = (request.POST.get('visited_at') or '').strip()
    try:
        visited_at = datetime.strptime(visited, '%Y-%m-%d').date() if visited else timezone.localdate()
    except ValueError:
        visited_at = timezone.localdate()
    pct = parse_decimal(request.POST.get('percent_complete'))
    if pct is not None and (pct < 0 or pct > 100):
        messages.error(request, 'Percent complete must be between 0 and 100.')
        return _visit_redirect(request, loan)
    lat = lon = None
    try:
        if request.POST.get('gps_lat'):
            lat = Decimal(request.POST.get('gps_lat'))
        if request.POST.get('gps_lon'):
            lon = Decimal(request.POST.get('gps_lon'))
    except (InvalidOperation, TypeError):
        lat = lon = None
    record_implementation_visit(
        loan,
        request.user,
        notes=notes,
        visited_at=visited_at,
        percent_complete=pct,
        purpose_code=request.POST.get('purpose_code') or '',
        unlocks_next_tranche=request.POST.get('unlocks_next_tranche') == '1',
        gps_lat=lat,
        gps_lon=lon,
    )
    messages.success(request, 'Implementation visit recorded.')
    return _visit_redirect(request, loan)


@login_required
@require_POST
def project_add_cashflow(request, loan_request_id):
    loan = _get_project_loan(request.user, loan_request_id)
    if loan is None or not can_edit_project_file(request.user, loan):
        messages.warning(request, 'You cannot edit this project file.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile, _ = ProjectProfile.objects.get_or_create(loan_request=loan)
    try:
        year = int(request.POST.get('year_number') or '0')
    except (TypeError, ValueError):
        year = 0
    revenue = parse_decimal(request.POST.get('revenue'))
    opex = parse_decimal(request.POST.get('operating_cost'))
    ocf = parse_decimal(request.POST.get('operating_cf'))
    ds = parse_decimal(request.POST.get('debt_service')) or Decimal('0')
    capacity = parse_decimal(request.POST.get('capacity_pct'))
    if revenue is not None and opex is not None:
        ocf = revenue - opex
    if year < 1 or ocf is None:
        messages.error(request, 'Enter a year number and either sales + operating cost, or net operating cashflow.')
        return redirect('project_file', loan_request_id=loan.id)
    if capacity is not None and (capacity < 0 or capacity > 200):
        messages.error(request, 'Capacity utilization must be between 0 and 200%.')
        return redirect('project_file', loan_request_id=loan.id)
    ProjectCashflowYear.objects.update_or_create(
        profile=profile, year_number=year,
        defaults={
            'operating_cf': ocf,
            'debt_service': ds,
            'revenue': revenue,
            'operating_cost': opex,
            'capacity_pct': capacity,
        },
    )
    _sync_computed_metrics(profile)
    messages.success(request, 'Cashflow year saved.')
    return redirect(reverse('project_file', args=[loan.id]) + '#viability')


@login_required
@require_POST
def project_delete_cashflow(request, loan_request_id, year_id):
    loan = _get_project_loan(request.user, loan_request_id)
    if loan is None or not can_edit_project_file(request.user, loan):
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile = get_project_profile_or_none(loan)
    if profile:
        ProjectCashflowYear.objects.filter(pk=year_id, profile=profile).delete()
        _sync_computed_metrics(profile)
        messages.success(request, 'Cashflow year removed.')
    return redirect(reverse('project_file', args=[loan.id]) + '#viability')


@login_required
@require_POST
def project_desk_review(request, loan_request_id, desk):
    loan = _get_project_loan(request.user, loan_request_id)
    if loan is None or not can_edit_project_file(request.user, loan):
        messages.warning(request, 'You cannot update plant desks on this file.')
        return redirect('loan_request_detail', loan_request_id=loan_request_id)
    profile, _ = ProjectProfile.objects.get_or_create(loan_request=loan)
    ensure_plant_desks(profile)
    valid = {k for k, _ in ProjectTechnicalReview.DESK_CHOICES}
    if desk not in valid:
        messages.error(request, 'Unknown plant desk.')
        return redirect('project_file', loan_request_id=loan.id)
    review = profile.technical_reviews.get(desk=desk)
    action = (request.POST.get('action') or '').strip()
    note = (request.POST.get('note') or '').strip()
    if action == 'clear':
        review.status = ProjectTechnicalReview.STATUS_CLEARED
    elif action == 'return':
        review.status = ProjectTechnicalReview.STATUS_RETURNED
    else:
        review.status = ProjectTechnicalReview.STATUS_PENDING
    review.note = note
    review.reviewed_at = timezone.now()
    review.reviewed_by = request.user
    review.save(update_fields=['status', 'note', 'reviewed_at', 'reviewed_by'])
    messages.success(request, f'{review.get_desk_display()} desk updated.')
    return redirect(reverse('project_file', args=[loan.id]) + '#desks')


@login_required
@require_POST
def project_record_utilization(request, loan_request_id, tranche_id):
    loan = get_object_or_404(LoanRequest.objects.select_related('category'), pk=loan_request_id)
    if not is_project_file(loan) or not can_edit_project_file(request.user, loan):
        messages.warning(request, 'You cannot record utilization on this file.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    tranche = get_object_or_404(
        LoanDisbursementTranche, pk=tranche_id, loan_request=loan,
    )
    note = (request.POST.get('utilization_note') or '').strip()
    if len(note) < 5:
        messages.error(request, 'Enter utilization evidence (at least 5 characters).')
        return redirect('post_approval_detail', loan_request_id=loan.id)
    tranche.utilization_note = note
    tranche.utilization_recorded_at = timezone.now()
    tranche.save(update_fields=['utilization_note', 'utilization_recorded_at'])
    messages.success(request, f'Tranche {tranche.sequence} utilization recorded.')
    return redirect('post_approval_detail', loan_request_id=loan.id)


@login_required
@require_POST
def project_set_equity_stage(request, loan_request_id):
    loan = get_object_or_404(LoanRequest.objects.select_related('category'), pk=loan_request_id)
    if not is_project_file(loan) or not can_edit_project_file(request.user, loan):
        messages.warning(request, 'You cannot update equity stage on this file.')
        return redirect('post_approval_detail', loan_request_id=loan_request_id)
    profile, _ = ProjectProfile.objects.get_or_create(loan_request=loan)
    try:
        stage = int(request.POST.get('equity_stage') or '0')
    except (TypeError, ValueError):
        stage = 0
    profile.equity_stage = max(0, min(3, stage))
    profile.save(update_fields=['equity_stage'])
    messages.success(request, 'Equity stage updated.')
    return redirect('post_approval_detail', loan_request_id=loan.id)


def _visit_redirect(request, loan):
    nxt = (request.POST.get('next') or '').strip()
    if nxt == 'monitoring':
        return redirect('monitoring_loan', loan_request_id=loan.id)
    if nxt == 'project':
        return redirect(reverse('project_file', args=[loan.id]) + '#implementation')
    return redirect('post_approval_detail', loan_request_id=loan.id)
