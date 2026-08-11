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


def build_applicant_status(application) -> ApplicantStatus:
    """Map OnlineApplication (+ linked LoanRequest) to a public status panel."""
    from loans.models import LoanRequest

    if not application.loan_request_id:
        return _draft_status(application)

    loan = application.loan_request
    if loan is None:
        return _draft_status(application)

    # Rejected early
    if (loan.status or '').lower() == 'rejected':
        return ApplicantStatus(
            headline='Application not approved',
            summary='This loan request was closed without approval. Visit your branch for details.',
            tone='warn',
            queue_id=loan.loan_request_id,
            pipeline_label='Closed',
            stages=[
                Stage('submit', 'Submitted', 'done'),
                Stage('closed', 'Not approved', 'blocked', 'Contact your branch for more information.'),
            ],
            facts=_common_facts(application, loan),
            is_submitted=True,
        )

    # Committee declined
    if loan.committee_status == LoanRequest.COMMITTEE_DECLINED:
        return ApplicantStatus(
            headline='Credit decision: not approved',
            summary='The credit review did not approve this application. Your branch can explain the outcome.',
            tone='warn',
            queue_id=loan.loan_request_id,
            pipeline_label='Declined',
            stages=_pipeline_stages(loan, terminal='declined'),
            facts=_common_facts(application, loan),
            is_submitted=True,
        )

    if loan.disbursement_status == LoanRequest.DISBURSE_DISBURSED or loan.disbursed_at:
        return ApplicantStatus(
            headline='Loan disbursed',
            summary='Funds have been released according to DECSI disbursement records. Contact your branch for statements.',
            tone='done',
            queue_id=loan.loan_request_id,
            pipeline_label='Disbursed',
            stages=_pipeline_stages(loan, terminal='disbursed'),
            facts=_common_facts(application, loan),
            is_submitted=True,
        )

    # Progress through pipeline
    stages = _pipeline_stages(loan)
    current = next((s for s in stages if s.state == 'current'), stages[-1] if stages else None)
    headline = current.label if current else 'In progress'
    summary = current.detail if current and current.detail else (
        'Your application is with DECSI. Keep your queue ID for branch enquiries.'
    )
    return ApplicantStatus(
        headline=headline,
        summary=summary,
        tone='progress' if current and current.key != 'disbursed' else 'ok',
        queue_id=loan.loan_request_id,
        pipeline_label=current.label if current else 'In progress',
        stages=stages,
        facts=_common_facts(application, loan),
        is_submitted=True,
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
            'This application is not yet in the branch queue. Finish the remaining steps to get a queue ID.'
            if application.status != application.STATUS_CANCELLED
            else 'This draft was cancelled.'
        ),
        tone='progress' if application.status != application.STATUS_CANCELLED else 'warn',
        queue_id='',
        pipeline_label=application.get_status_display(),
        stages=[
            Stage('draft', 'Details', _draft_state(application, application.STATUS_DRAFT)),
            Stage('docs', 'Documents', _draft_state(application, application.STATUS_DOCUMENTS)),
            Stage('fee', 'Fee', _draft_state(application, application.STATUS_PAYMENT)),
            Stage('submit', 'Submit', 'upcoming'),
        ],
        facts=[
            {'label': 'Product', 'value': getattr(application.category, 'name', None) or 'Not chosen yet'},
            {'label': 'Amount', 'value': _fmt_amount(application.amount_requested)},
            {'label': 'Branch', 'value': getattr(application.branch, 'name', None) or 'Not chosen yet'},
        ],
        can_continue_draft=application.status != application.STATUS_CANCELLED,
        continue_url_name=url,
        is_submitted=False,
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

    # Keys in order
    defs = [
        ('submitted', 'Submitted', 'Received online and waiting in the branch queue.'),
        ('intake', 'Branch intake', 'Branch cooperative reviews your application.'),
        ('processing', 'Loan processing', 'Officer reviews documents, collateral, and analysis.'),
        ('decision', 'Credit decision', 'Credit approval process is underway.'),
        ('disbursement', 'Disbursement prep', 'Approved loan is prepared for payment.'),
        ('disbursed', 'Disbursed', 'Loan amount has been disbursed.'),
    ]

    # Resolve index of current step
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
        # In processing after intake
        if loan.appraisal_completed_at or loan.collateral_submitted_at:
            current_idx = 2
        else:
            current_idx = 2
        force_state = {}
    else:
        # Pending intake
        current_idx = 1
        force_state = {}
        # Just submitted, intake not done - still can show submitted done, intake current
        if not loan.queue_approved:
            current_idx = 1

    # Refine details
    detail_overrides = {
        'submitted': f'Submitted {loan.date_requested.strftime("%d %b %Y") if loan.date_requested else ""}.'.strip(),
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
        'decision': {
            LoanRequest.COMMITTEE_PENDING: 'Pending credit committee decision.',
            LoanRequest.COMMITTEE_APPROVED: 'Committee approved.',
            LoanRequest.COMMITTEE_RETURNED: 'Returned to officer for corrections — still in progress.',
            LoanRequest.COMMITTEE_DECLINED: 'Not approved by credit committee.',
            '': 'Waiting until appraisal is ready for credit review.',
        }.get(loan.committee_status or '', 'Credit review.'),
        'disbursement': loan.get_disbursement_status_display() if loan.disbursement_status else 'Not started yet.',
        'disbursed': loan.disbursed_at.strftime('Disbursed on %d %b %Y') if loan.disbursed_at else 'Disbursed.',
    }

    if terminal == 'declined':
        detail_overrides['decision'] = 'Application not approved by credit review.'

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
        detail = detail_overrides.get(key, default_detail)
        stages.append(Stage(key=key, label=label, state=state, detail=detail or default_detail))
    return stages


def _common_facts(application, loan) -> List[Dict[str, str]]:
    officer = ''
    if getattr(loan, 'assigned_loan_officer', None):
        u = loan.assigned_loan_officer
        officer = (u.get_full_name() or u.username) if u else ''
    return [
        {'label': 'Queue ID', 'value': loan.loan_request_id},
        {'label': 'Product', 'value': getattr(loan.category, 'name', None) or '—'},
        {'label': 'Branch', 'value': getattr(loan.branch, 'name', None) or '—'},
        {'label': 'Amount requested', 'value': _fmt_amount(loan.amount_requested)},
        {
            'label': 'Submitted',
            'value': (
                application.submitted_at.strftime('%d %b %Y, %H:%M')
                if application.submitted_at
                else (loan.date_requested.strftime('%d %b %Y') if loan.date_requested else '—')
            ),
        },
        {'label': 'Loan officer', 'value': officer or 'Not assigned yet'},
    ]


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
