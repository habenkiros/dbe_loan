"""Agentic Assist — who may use which tools (server-enforced)."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Who always sees the floating chatbot (plus committee voters via user_can_use_agent).
AGENT_ROLES = (
    'branch_manager',
    'loan_officer',
    'credit_loan_officer',
    'engineer',
    'engineering_head',
    'admin',
    'superadmin',
)

# Only branch managers may create / bootstrap loan requests via the agent.
# Admin / LO / superuser cannot create loans here (mirrors operational BM ownership).
CREATE_LOAN_ROLES = (
    'branch_manager',
)

# Application document checklist + placeholder attach (not committee).
DOCUMENT_ROLES = (
    'branch_manager',
    'loan_officer',
    'credit_loan_officer',
    'engineer',
    'engineering_head',
    'admin',
    'superadmin',
)

# Read / coach appraisal sheets (LO primary; committee/engineer read-only via access checks).
APPRAISAL_ROLES = (
    'loan_officer',
    'credit_loan_officer',
    'branch_manager',
    'engineer',
    'engineering_head',
    'admin',
    'superadmin',
)


def user_can_use_agent(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    role = getattr(user, 'role', None)
    if role in AGENT_ROLES:
        return True
    try:
        from loans.nav import user_can_access_committee_queues
        return user_can_access_committee_queues(user)
    except Exception:
        return False


def user_can_create_loan_via_agent(user) -> bool:
    """Strict: branch managers only — not admin, not LO, not superuser shortcut."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return getattr(user, 'role', None) in CREATE_LOAN_ROLES


def user_can_manage_documents_via_agent(user) -> bool:
    if not user_can_use_agent(user):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in DOCUMENT_ROLES


def user_can_work_appraisal_via_agent(user) -> bool:
    if not user_can_use_agent(user):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'role', None) in APPRAISAL_ROLES:
        return True
    try:
        from loans.nav import user_can_access_committee_queues
        return user_can_access_committee_queues(user)
    except Exception:
        return False


def capabilities_for_user(user) -> Dict[str, Any]:
    role = getattr(user, 'role', None)
    return {
        'role': role,
        'can_open_chat': user_can_use_agent(user),
        'can_create_loan': user_can_create_loan_via_agent(user),
        'can_manage_documents': user_can_manage_documents_via_agent(user),
        'can_work_appraisal': user_can_work_appraisal_via_agent(user),
        'create_loan_note': (
            'Only branch managers create loan requests via Assist. '
            'Admin cannot create loans; use reports / checkup instead. '
            'Loan officers prepare documents and appraisal.'
        ),
        'loan_officer_focus': (
            'Documents + appraisal sheets (read completeness, coach fields). '
            'May send a document request after explicit confirm.'
            if role in ('loan_officer', 'credit_loan_officer')
            else ''
        ),
        'branch_manager_focus': (
            'Create loan requests in your branch; hold/edit story; reports.'
            if role == 'branch_manager'
            else ''
        ),
        'engineer_focus': (
            'Assigned collateral files: blockers, KYC, docs, appraisal coach. Never estimate in chat.'
            if role in ('engineer', 'engineering_head')
            else ''
        ),
        'committee_focus': (
            'Read-only committee brief, KYC, docs, appraisal coach. Never vote in chat.'
            if role not in AGENT_ROLES
            else ''
        ),
        'can_request_docs_chip': role in ('loan_officer', 'credit_loan_officer', 'engineer'),
    }


def user_may_access_loan(user, loan) -> bool:
    """Whether agent tools may read/act on this loan for the user."""
    if not user or not loan:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    role = getattr(user, 'role', None)
    if role in ('admin', 'superadmin'):
        return True
    if role == 'branch_manager':
        return bool(user.branch_id and loan.branch_id == user.branch_id)
    if role == 'loan_officer':
        if loan.assigned_loan_officer_id == user.id:
            return True
        if user.branch_id and loan.branch_id == user.branch_id:
            return True
        return False
    if role == 'credit_loan_officer':
        return True
    if role == 'engineer':
        return getattr(loan, 'assigned_engineer_id', None) == user.id
    if role == 'engineering_head':
        return bool(getattr(loan, 'sent_to_engineering_at', None))
    try:
        from loans.committee import user_can_view_committee_loan
        if user_can_view_committee_loan(user, loan):
            return True
    except Exception:
        pass
    return False


def user_may_write_loan_docs(user, loan) -> bool:
    if not user_can_manage_documents_via_agent(user):
        return False
    if not user_may_access_loan(user, loan):
        return False
    role = getattr(user, 'role', None)
    if role in ('admin', 'superadmin') or getattr(user, 'is_superuser', False):
        return True
    if role == 'branch_manager' and loan.branch_id == user.branch_id:
        return True
    if role == 'loan_officer' and (
        loan.assigned_loan_officer_id == user.id
        or (loan.assigned_loan_officer_id is None and loan.branch_id == user.branch_id)
    ):
        return True
    if role == 'credit_loan_officer':
        return True
    return False


def user_may_read_appraisal(user, loan) -> bool:
    if not user_can_work_appraisal_via_agent(user):
        return False
    return user_may_access_loan(user, loan)


def user_may_request_docs_via_agent(user, loan) -> bool:
    """Same coverage as the loan-detail document request button (assigned LO / delegate)."""
    if not user or not loan:
        return False
    if not user_may_access_loan(user, loan):
        return False
    role = getattr(user, 'role', None)
    if role in ('loan_officer', 'credit_loan_officer') and loan.assigned_loan_officer_id == user.id:
        return True
    if role == 'engineer' and getattr(loan, 'assigned_engineer_id', None) == user.id:
        return True
    try:
        from loans.delegation import can_access_loan_as_officer
        ok, _principal = can_access_loan_as_officer(user, loan)
        return bool(ok)
    except Exception:
        return False


_PAGE_LOAN_PATH_RE = re.compile(
    r'(?:'
    r'/loan_request_detail(?:_manager|_operation_manager|_finance)?/(\d+)'
    r'|/loan_request/(\d+)'
    r'|/collateral/loan/(\d+)'
    r'|/legal/loans/(\d+)'
    r')(?:/|$)',
    re.I,
)


def loan_pk_from_path(path: str) -> Optional[int]:
    """Parse a loan pk from a staff loan-file URL, or None."""
    if not path:
        return None
    match = _PAGE_LOAN_PATH_RE.search(path)
    if not match:
        return None
    for group in match.groups():
        if group:
            try:
                return int(group)
            except (TypeError, ValueError):
                return None
    return None


def page_loan_for_user(user, path: str):
    """Loan on this URL if the officer may access it; otherwise None."""
    pk = loan_pk_from_path(path)
    if not pk:
        return None
    from loans.models import LoanRequest

    loan = LoanRequest.objects.filter(pk=pk).only(
        'id', 'loan_request_id', 'branch_id', 'assigned_loan_officer_id',
        'assigned_engineer_id', 'sent_to_engineering_at', 'committee_status',
        'current_approval_level_id', 'district_id',
    ).first()
    if not loan or not user_may_access_loan(user, loan):
        return None
    return loan


def bind_page_loan(user, conversation, page_loan_id) -> bool:
    """Attach in-scope page_loan_id to the conversation. Out-of-scope IDs are ignored."""
    if conversation is None or page_loan_id in (None, ''):
        return False
    try:
        pk = int(page_loan_id)
    except (TypeError, ValueError):
        return False
    loan, err = resolve_loan_for_agent(user, loan_pk=pk, conversation=None)
    if err or not loan:
        return False
    if conversation.last_loan_request_id != loan.pk:
        conversation.last_loan_request_id = loan.pk
    return True


def resolve_loan_for_agent(user, *, loan_code: str = '', loan_pk: Optional[int] = None, conversation=None):
    """Load LoanRequest in scope by code/pk/conversation last loan."""
    from loans.models import LoanRequest

    loan = None
    if loan_pk:
        loan = LoanRequest.objects.filter(pk=loan_pk).select_related(
            'branch', 'category', 'assigned_loan_officer', 'appraisal',
        ).first()
    code = (loan_code or '').strip()
    if not loan and code:
        loan = LoanRequest.objects.filter(loan_request_id__iexact=code).select_related(
            'branch', 'category', 'assigned_loan_officer', 'appraisal',
        ).first()
        if not loan:
            loan = LoanRequest.objects.filter(loan_request_id__icontains=code).select_related(
                'branch', 'category', 'assigned_loan_officer', 'appraisal',
            ).first()
    if not loan and conversation and getattr(conversation, 'last_loan_request_id', None):
        loan = LoanRequest.objects.filter(pk=conversation.last_loan_request_id).select_related(
            'branch', 'category', 'assigned_loan_officer', 'appraisal',
        ).first()
    if not loan:
        return None, 'Loan not found. Provide loan_code or open a linked file first.'
    if not user_may_access_loan(user, loan):
        return None, 'You do not have access to that loan under your role/scope.'
    return loan, None
