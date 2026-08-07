"""Agentic Assist — who may use which tools (server-enforced)."""

from __future__ import annotations

from typing import Any, Dict, Optional

# Who sees the floating chatbot + call /agent/chat/
AGENT_ROLES = (
    'branch_manager',
    'loan_officer',
    'credit_loan_officer',
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
    'admin',
    'superadmin',
)

# Read / coach appraisal sheets (LO primary).
APPRAISAL_ROLES = (
    'loan_officer',
    'credit_loan_officer',
    'branch_manager',
    'admin',
    'superadmin',
)


def user_can_use_agent(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in AGENT_ROLES


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
    return getattr(user, 'role', None) in APPRAISAL_ROLES


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
            'Documents + appraisal sheets (read completeness, coach fields).'
            if role in ('loan_officer', 'credit_loan_officer')
            else ''
        ),
        'branch_manager_focus': (
            'Create loan requests in your branch; hold/edit story; reports.'
            if role == 'branch_manager'
            else ''
        ),
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
