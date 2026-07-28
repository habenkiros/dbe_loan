"""Appraisal edit lock — finalize Sheets 1–7 + scorecard once done."""

from __future__ import annotations

from typing import Any, Dict, Optional


def get_appraisal_lock_state(loan_request) -> Dict[str, Any]:
    """
    Returns whether the assigned officer may edit appraisal / refresh score inputs.

    Locked when:
      - committee approved or declined (final), or
      - pending committee review, or
      - appraisal marked finished (unless returned for corrections).

    Unlocked when:
      - appraisal not finished yet, or
      - committee returned the file to the loan officer.
    """
    status = (getattr(loan_request, 'committee_status', None) or '').strip()
    completed = bool(getattr(loan_request, 'appraisal_completed_at', None))

    from loans.models import LoanRequest

    if status == LoanRequest.COMMITTEE_APPROVED:
        return {
            'locked': True,
            'reason': 'Committee approved — appraisal and credit score are final (read-only).',
            'code': 'committee_approved',
        }
    if status == LoanRequest.COMMITTEE_DECLINED:
        return {
            'locked': True,
            'reason': 'Committee declined — appraisal is locked (read-only).',
            'code': 'committee_declined',
        }
    if status == LoanRequest.COMMITTEE_PENDING:
        return {
            'locked': True,
            'reason': 'Submitted to the approval committee — editing is locked until returned.',
            'code': 'pending_committee',
        }
    if status == LoanRequest.COMMITTEE_RETURNED:
        return {
            'locked': False,
            'reason': 'Returned for corrections — you may edit and re-finish the appraisal.',
            'code': 'returned',
        }
    if completed:
        return {
            'locked': True,
            'reason': 'Appraisal finished — locked. Submit to committee, or ask committee to return for edits.',
            'code': 'appraisal_finished',
        }
    return {
        'locked': False,
        'reason': '',
        'code': 'open',
    }


def appraisal_is_locked(loan_request) -> bool:
    return bool(get_appraisal_lock_state(loan_request).get('locked'))


def appraisal_lock_reason(loan_request) -> str:
    return get_appraisal_lock_state(loan_request).get('reason') or ''
