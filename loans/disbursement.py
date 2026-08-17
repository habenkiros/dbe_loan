# loans/disbursement.py
"""Post-committee disbursement track: conditions → schedule → ready → disbursed."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Q
from django.utils import timezone


def is_post_approval(loan_request) -> bool:
    return loan_request.committee_status == loan_request.COMMITTEE_APPROVED


def final_loan_amount(loan_request, appraisal=None) -> Decimal:
    from loans.committee import get_appraisal_for_loan

    if loan_request.committee_final_amount and loan_request.committee_final_amount > 0:
        return loan_request.committee_final_amount
    appraisal = appraisal or get_appraisal_for_loan(loan_request)
    if appraisal and appraisal.amount_approved and appraisal.amount_approved > 0:
        return appraisal.amount_approved
    return loan_request.amount_requested or Decimal('0')


def final_term_months(loan_request, appraisal=None, basic_info=None) -> int:
    from loans.committee import get_appraisal_for_loan
    from loans.models import LoanRequestBasicInfo

    appraisal = appraisal or get_appraisal_for_loan(loan_request)
    if appraisal and appraisal.term_approved_months:
        return int(appraisal.term_approved_months)
    if basic_info is None:
        basic_info = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    if basic_info and basic_info.term_months:
        return int(basic_info.term_months)
    return 12


def final_annual_rate_pct(loan_request, appraisal=None, basic_info=None) -> Decimal:
    from loans.committee import get_appraisal_for_loan
    from loans.models import LoanRequestBasicInfo

    appraisal = appraisal or get_appraisal_for_loan(loan_request)
    if appraisal and appraisal.rate_approved is not None:
        return Decimal(str(appraisal.rate_approved))
    if basic_info is None:
        basic_info = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    if basic_info and basic_info.interest_rate is not None:
        return Decimal(str(basic_info.interest_rate))
    return Decimal('0')


def required_cp_queryset(loan_request):
    from loans.models import AppraisalCondition

    appraisal = getattr(loan_request, 'appraisal', None)
    if appraisal is None:
        from loans.committee import get_appraisal_for_loan
        appraisal = get_appraisal_for_loan(loan_request)
    if not appraisal:
        return AppraisalCondition.objects.none()
    return appraisal.conditions.filter(
        Q(condition_type=AppraisalCondition.TYPE_CP) | Q(condition_type__isnull=True) | Q(condition_type=''),
        required_before_disbursement=True,
    )


def open_required_cps(loan_request) -> List:
    return [
        c for c in required_cp_queryset(loan_request)
        if not c.fulfilled
    ]


def conditions_cleared(loan_request) -> bool:
    return len(open_required_cps(loan_request)) == 0


def schedule_summary(loan_request, appraisal=None) -> Dict[str, Any]:
    from loans.committee import get_appraisal_for_loan
    from loans.models import AppraisalAmortizationEntry, LoanRequestBasicInfo

    appraisal = appraisal or get_appraisal_for_loan(loan_request)
    basic_info = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    amount = final_loan_amount(loan_request, appraisal)
    term = final_term_months(loan_request, appraisal, basic_info)
    rate = final_annual_rate_pct(loan_request, appraisal, basic_info)
    rows = []
    principal_sum = Decimal('0')
    if appraisal:
        rows = list(appraisal.amortization_entries.order_by('period_number'))
        principal_sum = sum((r.principal or Decimal('0')) for r in rows)
    amount_ok = False
    if rows and amount > 0:
        amount_ok = abs(principal_sum - amount) <= Decimal('1.00')
    return {
        'amount': amount,
        'term_months': term,
        'rate_pct': rate,
        'row_count': len(rows),
        'principal_sum': principal_sum,
        'amount_matches': amount_ok,
        'confirmed': bool(loan_request.schedule_confirmed_at),
        'entries': rows[:6],
        'has_full_schedule': len(rows) > 0,
    }


def disbursement_readiness(loan_request) -> Dict[str, Any]:
    blockers = []
    # Repair stuck committee routing (e.g. advanced to District after amount bands changed).
    if not is_post_approval(loan_request) and loan_request.committee_status == loan_request.COMMITTEE_PENDING:
        from loans.committee import reconcile_approval_routing
        reconcile_approval_routing(loan_request)
        loan_request.refresh_from_db()
    if not is_post_approval(loan_request):
        blockers.append('Loan must be committee-approved first.')
    open_cps = open_required_cps(loan_request)
    if open_cps:
        blockers.append(f'{len(open_cps)} condition(s) precedent still open.')
    sched = schedule_summary(loan_request)
    if not sched['has_full_schedule']:
        blockers.append('Repayment schedule is empty — regenerate from final terms.')
    elif not sched['amount_matches']:
        blockers.append('Schedule principal does not match final approved amount — regenerate.')
    if not loan_request.schedule_confirmed_at:
        blockers.append('Confirm the repayment schedule.')
    from loans.collateral_legal import collateral_legal_blockers
    blockers.extend(collateral_legal_blockers(loan_request))
    from loans.agreement_signing import agreement_blockers
    blockers.extend(agreement_blockers(loan_request))
    return {
        'ok': not blockers and is_post_approval(loan_request),
        'blockers': blockers,
        'open_cps': open_cps,
        'schedule': sched,
        'status': loan_request.disbursement_status,
        'status_label': loan_request.get_disbursement_status_display() if loan_request.disbursement_status else 'Not started',
    }


def start_disbursement_track(loan_request) -> None:
    """Called when committee fully approves the loan."""
    from loans.models import LoanRequest

    if loan_request.disbursement_status in (
        LoanRequest.DISBURSE_READY,
        LoanRequest.DISBURSE_DISBURSED,
        LoanRequest.DISBURSE_SCHEDULE_CONFIRMED,
    ):
        return
    loan_request.disbursement_status = LoanRequest.DISBURSE_AWAITING_CONDITIONS
    loan_request.save(update_fields=['disbursement_status'])


def can_manage_conditions(user, loan_request) -> bool:
    if not is_post_approval(loan_request):
        return False
    if loan_request.disbursement_status == loan_request.DISBURSE_DISBURSED:
        return False
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in ('admin', 'superadmin', 'branch_manager', 'credit_head'):
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    return False


def can_confirm_schedule(user, loan_request) -> bool:
    return can_manage_conditions(user, loan_request)


def can_mark_ready(user, loan_request) -> bool:
    if not is_post_approval(loan_request):
        return False
    if loan_request.disbursement_status == loan_request.DISBURSE_DISBURSED:
        return False
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in ('admin', 'superadmin', 'branch_manager', 'accountant', 'credit_head'):
        return True
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    return False


def can_approve_finance_disbursement(user, loan_request) -> bool:
    """Finance manager (or delegate) approves release after ready-for-disbursement."""
    if not is_post_approval(loan_request):
        return False
    if loan_request.disbursement_status != loan_request.DISBURSE_READY:
        return False
    if loan_request.finance_disbursement_approval:
        return False
    from loans.delegation import user_has_finance_authority
    return user_has_finance_authority(user)


def set_finance_disbursement_approval(loan_request, user, *, approved: bool = True) -> None:
    loan_request.finance_disbursement_approval = bool(approved)
    loan_request.save(update_fields=['finance_disbursement_approval'])


def can_mark_disbursed(user, loan_request) -> bool:
    """Assigned loan officer / BM confirms disbursement after Finance approval."""
    if not is_post_approval(loan_request):
        return False
    if loan_request.disbursement_status != loan_request.DISBURSE_READY:
        return False
    if not loan_request.finance_disbursement_approval:
        return False
    role = getattr(user, 'role', None)
    if role in ('loan_officer', 'credit_loan_officer') and loan_request.assigned_loan_officer_id == user.id:
        return True
    if role == 'branch_manager' and getattr(user, 'branch_id', None):
        return loan_request.branch_id == user.branch_id
    if role == 'credit_head' and loan_request.origin_level == loan_request.ORIGIN_HEAD_OFFICE:
        return True
    return False


def set_condition_fulfilled(condition, user, *, fulfilled: bool, evidence_note: str = '') -> None:
    condition.fulfilled = fulfilled
    if fulfilled:
        condition.fulfilled_at = timezone.now()
        condition.fulfilled_by = user
        if evidence_note:
            condition.evidence_note = evidence_note.strip()
    else:
        condition.fulfilled_at = None
        condition.fulfilled_by = None
    condition.save(update_fields=[
        'fulfilled', 'fulfilled_at', 'fulfilled_by', 'evidence_note',
    ])
    loan = condition.appraisal.loan_request
    if (
        loan.disbursement_status == loan.DISBURSE_AWAITING_CONDITIONS
        and conditions_cleared(loan)
        and not loan.schedule_confirmed_at
    ):
        # Stay on awaiting_conditions until schedule confirmed; status label still accurate.
        loan.save(update_fields=[])  # no-op; readiness recomputed in UI
    elif (
        loan.disbursement_status in (loan.DISBURSE_SCHEDULE_CONFIRMED, loan.DISBURSE_READY)
        and not conditions_cleared(loan)
    ):
        loan.disbursement_status = loan.DISBURSE_AWAITING_CONDITIONS
        loan.schedule_confirmed_at = None
        loan.schedule_confirmed_by = None
        loan.ready_for_disbursement_at = None
        loan.ready_for_disbursement_by = None
        loan.save(update_fields=[
            'disbursement_status', 'schedule_confirmed_at', 'schedule_confirmed_by',
            'ready_for_disbursement_at', 'ready_for_disbursement_by',
        ])


def confirm_schedule(loan_request, user) -> Tuple[bool, List[str]]:
    readiness = disbursement_readiness(loan_request)
    # Confirm only needs CPs + matching schedule; ignore "confirm schedule" blocker itself
    blockers = [
        b for b in readiness['blockers']
        if b != 'Confirm the repayment schedule.'
    ]
    if blockers:
        return False, blockers
    loan_request.schedule_confirmed_at = timezone.now()
    loan_request.schedule_confirmed_by = user
    loan_request.disbursement_status = loan_request.DISBURSE_SCHEDULE_CONFIRMED
    loan_request.save(update_fields=[
        'schedule_confirmed_at', 'schedule_confirmed_by', 'disbursement_status',
    ])
    return True, []


def mark_ready_for_disbursement(loan_request, user, *, notes: str = '') -> Tuple[bool, List[str]]:
    readiness = disbursement_readiness(loan_request)
    if not readiness['ok']:
        return False, readiness['blockers']
    loan_request.disbursement_status = loan_request.DISBURSE_READY
    loan_request.ready_for_disbursement_at = timezone.now()
    loan_request.ready_for_disbursement_by = user
    if notes:
        loan_request.disbursement_notes = notes.strip()
    loan_request.save(update_fields=[
        'disbursement_status', 'ready_for_disbursement_at', 'ready_for_disbursement_by',
        'disbursement_notes',
    ])
    from loans.models import LoanNotification
    from loans.services.notifications import notify_users

    from loans.models import CustomUser

    recipients = list(
        CustomUser.objects.filter(role='finance_manager', is_active=True)[:5]
    )
    if loan_request.assigned_loan_officer_id and loan_request.assigned_loan_officer.is_active:
        recipients.append(loan_request.assigned_loan_officer)
    if loan_request.branch_id:
        recipients.extend(list(
            CustomUser.objects.filter(
                role='branch_manager',
                branch_id=loan_request.branch_id,
                is_active=True,
            )[:3]
        ))
    # Deduplicate
    seen = set()
    unique = []
    for u in recipients:
        if u.id not in seen:
            seen.add(u.id)
            unique.append(u)
    if unique:
        from django.urls import reverse

        notify_users(
            unique,
            loan_request=loan_request,
            kind=LoanNotification.KIND_DISBURSEMENT_READY,
            title=f'Ready for disbursement: {loan_request.loan_request_id}',
            message=(
                f'{loan_request.applicant_name} — amount '
                f'{final_loan_amount(loan_request)}. '
                'Finance must approve disbursement, then the assigned officer confirms funds released.'
            ),
            url=reverse('post_approval_detail', args=[loan_request.pk]),
        )
    return True, []


def mark_disbursed(loan_request, user, *, notes: str = '') -> Tuple[bool, List[str]]:
    """
    Confirm disbursement. When DECSI_CBS_BOOK_ON_DISBURSE is on, books in CBS first
    (live or mock ledger) and stores the booking reference.
    """
    from django.conf import settings

    if loan_request.disbursement_status != loan_request.DISBURSE_READY:
        return False, ['Loan must be marked ready for disbursement first.']
    if not loan_request.finance_disbursement_approval:
        return False, ['Finance department must approve disbursement before confirmation.']

    booking_note = ''
    if getattr(settings, 'DECSI_CBS_BOOK_ON_DISBURSE', True):
        from loans.portfolio_ledger import get_ledger_adapter
        from loans.services.cbs_client import fetch_customer_outstanding

        adapter = get_ledger_adapter()
        if not adapter.is_connected():
            return False, [
                'CBS ledger is not connected. Set DECSI_CBS_USE_MOCK_LEDGER=True for demo '
                'or configure DECSI_BASE_URL / DECSI_LEDGER_ADAPTER=cbs.'
            ]
        result = adapter.book_disbursement(loan_request, user, notes=notes)
        if not result.ok:
            loan_request.cbs_booking_status = loan_request.CBS_BOOK_FAILED
            loan_request.save(update_fields=['cbs_booking_status'])
            return False, [result.message or 'CBS disbursement booking failed.']

        loan_request.cbs_booking_status = (
            loan_request.CBS_BOOK_MOCK if result.status == 'mock' else loan_request.CBS_BOOK_BOOKED
        )
        loan_request.cbs_booking_ref = result.booking_ref or ''
        loan_request.cbs_loan_account = result.loan_account or ''
        loan_request.cbs_booked_at = timezone.now()
        cid = (loan_request.customer_number or '').strip()
        if cid:
            snap = fetch_customer_outstanding(cid)
            if snap:
                loan_request.cbs_outstanding_at_booking = snap.total_outstanding
        booking_note = (
            f'CBS {result.status}: ref={result.booking_ref or "—"} '
            f'account={result.loan_account or "—"} ({result.provider})'
        )

    loan_request.disbursement_status = loan_request.DISBURSE_DISBURSED
    loan_request.disbursed_at = timezone.now()
    loan_request.disbursed_by = user
    note_parts = [p for p in (notes.strip() if notes else '', booking_note) if p]
    if note_parts:
        loan_request.disbursement_notes = (
            (loan_request.disbursement_notes + '\n' if loan_request.disbursement_notes else '')
            + '\n'.join(note_parts)
        )
    loan_request.save(update_fields=[
        'disbursement_status', 'disbursed_at', 'disbursed_by', 'disbursement_notes',
        'cbs_booking_status', 'cbs_booking_ref', 'cbs_loan_account', 'cbs_booked_at',
        'cbs_outstanding_at_booking',
    ])

    from loans.models import CustomUser, LoanNotification
    from loans.services.notifications import notify_users

    recipients = []
    if loan_request.branch_id:
        recipients.extend(list(
            CustomUser.objects.filter(
                role='branch_manager',
                branch_id=loan_request.branch_id,
                is_active=True,
            ).exclude(pk=user.pk)[:3]
        ))
    if recipients:
        from django.urls import reverse

        notify_users(
            recipients,
            loan_request=loan_request,
            kind=LoanNotification.KIND_DISBURSED,
            title=f'Disbursed: {loan_request.loan_request_id}',
            message=(
                f'Loan marked disbursed by {user.get_full_name() or user.username}'
                + (f' · CBS ref {loan_request.cbs_booking_ref}' if loan_request.cbs_booking_ref else '')
                + '.'
            ),
            url=reverse('post_approval_detail', args=[loan_request.pk]),
        )
    return True, []


def _scope_queryset_by_org(qs, user):
    """Filter queryset by branch/district attachment for accountant/auditor/DM."""
    role = getattr(user, 'role', None)
    if role == 'accountant' or role == 'auditor':
        if getattr(user, 'branch_id', None):
            return qs.filter(branch_id=user.branch_id)
        if getattr(user, 'district_id', None):
            return qs.filter(branch__district_id=user.district_id)
        return qs  # HO-attached accountant/auditor without branch/district
    if role == 'district_manager' and getattr(user, 'district_id', None):
        return qs.filter(branch__district_id=user.district_id)
    return qs


def post_approval_queue_queryset(user):
    from loans.models import LoanRequest

    qs = LoanRequest.objects.filter(
        committee_status=LoanRequest.COMMITTEE_APPROVED,
    ).exclude(
        disbursement_status=LoanRequest.DISBURSE_DISBURSED,
    ).select_related(
        'branch', 'assigned_loan_officer', 'appraisal',
    ).order_by('-committee_decided_at')
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in (
        'admin', 'superadmin', 'cooperative_manager', 'operation_manager',
        'finance_manager', 'credit_head',
    ):
        return qs
    if role in ('loan_officer', 'credit_loan_officer'):
        return qs.filter(assigned_loan_officer=user)
    if role == 'branch_manager' and user.branch_id:
        return qs.filter(branch_id=user.branch_id)
    if role == 'accountant':
        scoped = _scope_queryset_by_org(qs, user)
        return scoped.filter(
            disbursement_status__in=(
                LoanRequest.DISBURSE_SCHEDULE_CONFIRMED,
                LoanRequest.DISBURSE_READY,
            )
        )
    if role == 'district_manager':
        return _scope_queryset_by_org(qs, user)
    return qs.none()


def finance_disbursement_queue_queryset(user):
    """Loans ready for disbursement awaiting Finance approval."""
    from loans.models import LoanRequest

    qs = LoanRequest.objects.filter(
        committee_status=LoanRequest.COMMITTEE_APPROVED,
        disbursement_status=LoanRequest.DISBURSE_READY,
        finance_disbursement_approval=False,
    ).select_related('branch', 'assigned_loan_officer').order_by('-ready_for_disbursement_at')
    role = getattr(user, 'role', None)
    if getattr(user, 'is_superuser', False) or role in ('admin', 'superadmin', 'finance_manager'):
        return qs
    return qs.none()
