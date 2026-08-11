"""Applicant-facing loan pipeline status (friendly labels from core LoanRequest)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Stage:
    key: str
    label: str
    state: str  # done | current | upcoming | blocked
    detail: str = ''


@dataclass
class ApplicantStatus:
    headline: str
    summary: str
    tone: str  # progress | ok | warn | done
    queue_id: str = ''
    pipeline_label: str = ''
    stages: List[Stage] = field(default_factory=list)
    facts: List[Dict[str, str]] = field(default_factory=list)
    # Critical decision milestones (requested vs credit-approved)
    amount_requested: str = ''
    amount_approved: str = ''
    is_loan_requested: bool = False
    is_loan_approved: bool = False
    is_credit_declined: bool = False
    approval_date: str = ''
    has_repayment_schedule: bool = False
    schedule_ready: bool = False
    can_continue_draft: bool = False
    continue_url_name: str = ''
    is_submitted: bool = False


def _fmt_amount(value) -> str:
    if value is None:
        return '—'
    try:
        return f'{value:,.2f} ETB'
    except Exception:
        return f'{value} ETB'


def _approved_amount(loan):
    from loans.disbursement import final_loan_amount

    if not loan:
        return None
    from loans.models import LoanRequest
    if loan.committee_status != LoanRequest.COMMITTEE_APPROVED and not loan.disbursed_at:
        return None
    try:
        amt = final_loan_amount(loan)
        return amt if amt and amt > 0 else None
    except Exception:
        return loan.committee_final_amount


def _approval_date_str(loan) -> str:
    dt = getattr(loan, 'committee_decided_at', None) or getattr(loan, 'date_reviewed', None)
    if not dt:
        return ''
    try:
        return dt.strftime('%d %b %Y')
    except Exception:
        return str(dt)


def _schedule_flags(loan) -> tuple:
    """(has_link_eligible, entries_ready)."""
    from applicant_portal.schedule import can_show_schedule
    from loans.committee import get_appraisal_for_loan

    if not can_show_schedule(loan):
        return False, False
    appraisal = get_appraisal_for_loan(loan)
    if not appraisal:
        return True, False
    return True, appraisal.amortization_entries.exists()


def build_applicant_status(application) -> ApplicantStatus:
    """Map OnlineApplication (+ linked LoanRequest) to a public status panel."""
    from loans.models import LoanRequest

    if not application.loan_request_id:
        return _draft_status(application)

    loan = application.loan_request
    if loan is None:
        return _draft_status(application)

    requested = _fmt_amount(loan.amount_requested)
    approved_amt = _approved_amount(loan)
    approved_str = _fmt_amount(approved_amt) if approved_amt is not None else ''
    has_sched, sched_ready = _schedule_flags(loan)
    base_kw = dict(
        queue_id=loan.loan_request_id or '',
        amount_requested=requested,
        amount_approved=approved_str,
        is_loan_requested=True,
        is_loan_approved=bool(
            loan.committee_status == LoanRequest.COMMITTEE_APPROVED or loan.disbursed_at
        ),
        is_credit_declined=loan.committee_status == LoanRequest.COMMITTEE_DECLINED,
        approval_date=_approval_date_str(loan) if loan.committee_status == LoanRequest.COMMITTEE_APPROVED else '',
        has_repayment_schedule=has_sched,
        schedule_ready=sched_ready,
        is_submitted=True,
        facts=_common_facts(application, loan, approved_str=approved_str),
    )

    # Rejected early
    if (loan.status or '').lower() == 'rejected':
        return ApplicantStatus(
            headline='Application not approved',
            summary='This loan request was closed without approval. Visit your branch for details.',
            tone='warn',
            pipeline_label='Closed',
            stages=[
                Stage('submit', 'Loan requested', 'done'),
                Stage('closed', 'Not approved', 'blocked', 'Contact your branch for more information.'),
            ],
            **base_kw,
        )

    # Committee declined
    if loan.committee_status == LoanRequest.COMMITTEE_DECLINED:
        return ApplicantStatus(
            headline='Credit decision: not approved',
            summary=(
                f'You requested {requested}. Credit review did not approve this loan. '
                'Your branch can explain the outcome.'
            ),
            tone='warn',
            pipeline_label='Declined',
            stages=_pipeline_stages(loan, terminal='declined'),
            **base_kw,
        )

    # Credit approved — critical milestone
    if loan.committee_status == LoanRequest.COMMITTEE_APPROVED or loan.disbursed_at:
        if loan.disbursement_status == LoanRequest.DISBURSE_DISBURSED or loan.disbursed_at:
            headline = 'Loan disbursed'
            summary = (
                f'LOAN APPROVED for {approved_str or requested}. '
                'Funds have been released according to DECSI records. Use your repayment schedule for installments.'
            )
            tone = 'done'
            label = 'Disbursed'
            terminal = 'disbursed'
        else:
            headline = 'Loan approved'
            summary = (
                f'LOAN APPROVED — credit decision confirmed for {approved_str or requested}. '
                + (
                    'Your repayment schedule is ready to view.'
                    if sched_ready
                    else 'Your branch is preparing the repayment schedule and disbursement steps.'
                )
            )
            tone = 'ok'
            label = 'Loan approved'
            terminal = None
        return ApplicantStatus(
            headline=headline,
            summary=summary,
            tone=tone,
            pipeline_label=label,
            stages=_pipeline_stages(loan, terminal=terminal),
            **base_kw,
        )

    # Progress through pipeline (still loan requested, not yet credit approved)
    stages = _pipeline_stages(loan)
    current = next((s for s in stages if s.state == 'current'), stages[-1] if stages else None)
    headline = current.label if current else 'In progress'
    if current and current.key == 'submitted':
        headline = 'Loan requested'
    summary = current.detail if current and current.detail else (
        f'Your loan request of {requested} is with DECSI. Keep your queue ID for branch enquiries.'
    )
    if loan.committee_status != LoanRequest.COMMITTEE_APPROVED:
        summary = (
            f'LOAN REQUESTED: {requested}. '
            + (summary or 'In branch processing until credit approval.')
        )
    return ApplicantStatus(
        headline=headline,
        summary=summary,
        tone='progress' if current and current.key != 'disbursed' else 'ok',
        pipeline_label=current.label if current else 'In progress',
        stages=stages,
        **base_kw,
    )


def _draft_status(application) -> ApplicantStatus:
    stage_map = {
        application.STATUS_DRAFT: ('Complete loan details', 'details'),
        application.STATUS_DOCUMENTS: ('Upload documents', 'documents'),
        application.STATUS_PAYMENT: ('Pay processing fee', 'payment'),
        application.STATUS_CANCELLED: ('Application cancelled', ''),
    }
    label, url = stage_map.get(
        application.status,
        ('Continue your application', 'details'),
    )
    return ApplicantStatus(
        headline=label if application.status != application.STATUS_CANCELLED else 'Cancelled',
        summary=(
            'This application is not yet a formal loan request. Finish the steps to submit and get a queue ID.'
            if application.status != application.STATUS_CANCELLED
            else 'This draft was cancelled.'
        ),
        tone='progress' if application.status != application.STATUS_CANCELLED else 'warn',
        queue_id='',
        pipeline_label=application.get_status_display(),
        amount_requested=_fmt_amount(application.amount_requested),
        stages=[
            Stage('draft', 'Details', _draft_state(application, application.STATUS_DRAFT)),
            Stage('docs', 'Documents', _draft_state(application, application.STATUS_DOCUMENTS)),
            Stage('fee', 'Fee', _draft_state(application, application.STATUS_PAYMENT)),
            Stage('submit', 'Loan request', 'upcoming'),
        ],
        facts=[
            {'label': 'Product', 'value': getattr(application.category, 'name', None) or 'Not chosen yet'},
            {'label': 'Amount requested', 'value': _fmt_amount(application.amount_requested)},
            {'label': 'Branch', 'value': getattr(application.branch, 'name', None) or 'Not chosen yet'},
        ],
        can_continue_draft=application.status != application.STATUS_CANCELLED,
        continue_url_name=url,
        is_submitted=False,
        is_loan_requested=False,
        is_loan_approved=False,
    )


def _draft_state(application, target: str) -> str:
    order = [
        application.STATUS_DRAFT,
        application.STATUS_DOCUMENTS,
        application.STATUS_PAYMENT,
        application.STATUS_SUBMITTED,
    ]
    try:
        cur = order.index(application.status)
        tgt = order.index(target)
    except ValueError:
        return 'upcoming'
    if cur > tgt:
        return 'done'
    if cur == tgt:
        return 'current'
    return 'upcoming'


def _pipeline_stages(loan, terminal: Optional[str] = None) -> List[Stage]:
    from loans.models import LoanRequest

    defs = [
        ('submitted', 'Loan requested', 'Online request received and waiting in the branch queue.'),
        ('intake', 'Branch intake', 'Branch cooperative reviews your application.'),
        ('processing', 'Loan processing', 'Officer reviews documents, collateral, and analysis.'),
        ('decision', 'Credit decision', 'Credit approval process is underway.'),
        ('disbursement', 'Disbursement prep', 'Approved loan is prepared for payment.'),
        ('disbursed', 'Disbursed', 'Loan amount has been disbursed.'),
    ]

    if terminal == 'declined':
        current_idx = 3
        force_state = {3: 'blocked'}
    elif terminal == 'disbursed' or loan.disbursement_status == LoanRequest.DISBURSE_DISBURSED:
        current_idx = 5
        force_state = {}
    elif loan.disbursement_status in (
        LoanRequest.DISBURSE_READY,
        LoanRequest.DISBURSE_SCHEDULE_CONFIRMED,
        LoanRequest.DISBURSE_AWAITING_CONDITIONS,
    ) or loan.committee_status == LoanRequest.COMMITTEE_APPROVED:
        current_idx = 4
        force_state = {}
        if loan.committee_status != LoanRequest.COMMITTEE_APPROVED and not loan.disbursement_status:
            current_idx = 3
    elif loan.committee_status == LoanRequest.COMMITTEE_PENDING:
        current_idx = 3
        force_state = {}
    elif loan.queue_approved or (loan.status or '') == 'Approved':
        if loan.appraisal_completed_at or loan.collateral_submitted_at:
            current_idx = 2
        else:
            current_idx = 2
        force_state = {}
    else:
        current_idx = 1
        force_state = {}
        if not loan.queue_approved:
            current_idx = 1

    decision_detail = {
        LoanRequest.COMMITTEE_PENDING: 'Pending credit committee decision.',
        LoanRequest.COMMITTEE_APPROVED: 'LOAN APPROVED by credit committee.',
        LoanRequest.COMMITTEE_RETURNED: 'Returned to officer for corrections — still in progress.',
        LoanRequest.COMMITTEE_DECLINED: 'Not approved by credit committee.',
        '': 'Waiting until appraisal is ready for credit review.',
    }.get(loan.committee_status or '', 'Credit review.')

    detail_overrides = {
        'submitted': (
            f'LOAN REQUESTED on {loan.date_requested.strftime("%d %b %Y")}.'
            if loan.date_requested
            else 'LOAN REQUESTED — online application submitted.'
        ),
        'intake': (
            'Branch has accepted your request into the loan queue.'
            if loan.queue_approved
            else 'Waiting for branch cooperative intake approval.'
        ),
        'processing': (
            'Appraisal completed; advancing to credit decision.'
            if loan.appraisal_completed_at
            else (
                'Collateral / field work recorded.'
                if loan.collateral_submitted_at
                else 'Branch team is reviewing documents and preparing appraisal.'
            )
        ),
        'decision': decision_detail,
        'disbursement': loan.get_disbursement_status_display() if loan.disbursement_status else 'Not started yet.',
        'disbursed': loan.disbursed_at.strftime('Disbursed on %d %b %Y') if loan.disbursed_at else 'Disbursed.',
    }

    if terminal == 'declined':
        detail_overrides['decision'] = 'Application not approved by credit review.'

    # After credit approval, mark decision stage done with LOAN APPROVED label
    decision_label_override = None
    if loan.committee_status == LoanRequest.COMMITTEE_APPROVED:
        decision_label_override = 'Loan approved'

    stages: List[Stage] = []
    for i, (key, label, default_detail) in enumerate(defs):
        if terminal == 'declined' and i > 3:
            break
        if i < current_idx:
            state = 'done'
        elif i == current_idx:
            state = force_state.get(i, 'current')
        else:
            state = 'upcoming'
        if terminal == 'disbursed' and i <= 5:
            state = 'done' if i < 5 else 'current'
            if i == 5:
                state = 'done'
        if loan.committee_status == LoanRequest.COMMITTEE_APPROVED and key == 'decision':
            state = 'done'
            label = decision_label_override or label
        detail = detail_overrides.get(key, default_detail)
        stages.append(Stage(key=key, label=label, state=state, detail=detail or default_detail))
    return stages


def _common_facts(application, loan, *, approved_str: str = '') -> List[Dict[str, str]]:
    from loans.models import LoanRequest

    officer = ''
    if getattr(loan, 'assigned_loan_officer', None):
        u = loan.assigned_loan_officer
        officer = (u.get_full_name() or u.username) if u else ''

    facts = [
        {'label': 'Queue ID', 'value': loan.loan_request_id},
        {'label': 'Product', 'value': getattr(loan.category, 'name', None) or '—'},
        {'label': 'Branch', 'value': getattr(loan.branch, 'name', None) or '—'},
        {'label': 'Loan requested', 'value': _fmt_amount(loan.amount_requested)},
    ]
    if loan.committee_status == LoanRequest.COMMITTEE_APPROVED or approved_str:
        facts.append({
            'label': 'Loan approved',
            'value': approved_str or _fmt_amount(loan.committee_final_amount),
        })
        if loan.committee_decided_at:
            facts.append({
                'label': 'Approved on',
                'value': loan.committee_decided_at.strftime('%d %b %Y'),
            })
    facts.extend([
        {
            'label': 'Submitted',
            'value': (
                application.submitted_at.strftime('%d %b %Y, %H:%M')
                if application.submitted_at
                else (loan.date_requested.strftime('%d %b %Y') if loan.date_requested else '—')
            ),
        },
        {'label': 'Loan officer', 'value': officer or 'Not assigned yet'},
    ])
    return facts


def enrich_applications(applications) -> List[Dict[str, Any]]:
    """Attach compact status chips for list views."""
    rows = []
    for app in applications:
        status = build_applicant_status(app)
        rows.append({
            'application': app,
            'status': status,
        })
    return rows
