"""Appraisal pack ↔ CRM comment rounds (DBE prototyping spine).

DECSI general files skip this. Product desks send a pack; CRM clears or returns
it. Committee submit waits for a cleared round.
"""

from __future__ import annotations

from typing import Optional

from django.utils import timezone

from loans.kyc_desk import kyc_applies, kyc_is_complete, user_can_work_desk
from loans.dbe_desks import DESK_CRM


def crm_cycle_applies(loan_request) -> bool:
    return kyc_applies(loan_request)


def latest_round(loan_request):
    from loans.models import AppraisalCrmRound

    if loan_request is None or not getattr(loan_request, 'pk', None):
        return None
    return (
        AppraisalCrmRound.objects.filter(loan_request=loan_request)
        .order_by('-version', '-id')
        .first()
    )


def crm_is_cleared(loan_request) -> bool:
    if not crm_cycle_applies(loan_request):
        return True
    row = latest_round(loan_request)
    return bool(row and row.status == row.STATUS_CLEARED)


def crm_committee_blockers(loan_request) -> list:
    if not crm_cycle_applies(loan_request):
        return []
    row = latest_round(loan_request)
    if row is None:
        return ['Send the appraisal pack to CRM for comment before committee.']
    if row.status == row.STATUS_WITH_CRM:
        return ['Waiting for CRM comments on the appraisal pack.']
    if row.status == row.STATUS_RETURNED:
        return ['CRM returned the pack — revise it and send it again.']
    if row.status == row.STATUS_DRAFT:
        return ['The appraisal pack is still a draft — send it to CRM.']
    if row.status != row.STATUS_CLEARED:
        return ['CRM must clear the appraisal pack before committee.']
    return []


def can_send_to_crm(user, loan_request) -> bool:
    if not crm_cycle_applies(loan_request):
        return False
    if not kyc_is_complete(loan_request):
        return False
    role = getattr(user, 'role', None)
    if not (
        getattr(user, 'is_superuser', False)
        or role in ('admin', 'superadmin', 'credit_head', 'loan_officer', 'credit_loan_officer')
    ):
        return False
    row = latest_round(loan_request)
    if row is None:
        return True
    return row.status in (row.STATUS_DRAFT, row.STATUS_RETURNED, row.STATUS_CLEARED)


def can_crm_comment(user, loan_request) -> bool:
    if not crm_cycle_applies(loan_request):
        return False
    row = latest_round(loan_request)
    if row is None or row.status != row.STATUS_WITH_CRM:
        return False
    return user_can_work_desk(user, DESK_CRM)


def send_pack_to_crm(loan_request, user, note: str = ''):
    from loans.models import AppraisalCrmRound

    note = (note or '').strip()
    row = latest_round(loan_request)
    now = timezone.now()
    if row is None or row.status in (AppraisalCrmRound.STATUS_RETURNED, AppraisalCrmRound.STATUS_CLEARED):
        version = (row.version + 1) if row else 1
        row = AppraisalCrmRound.objects.create(
            loan_request=loan_request,
            version=version,
            status=AppraisalCrmRound.STATUS_WITH_CRM,
            appraisal_note=note,
            sent_by=user,
            sent_at=now,
        )
        return row
    row.status = AppraisalCrmRound.STATUS_WITH_CRM
    row.appraisal_note = note or row.appraisal_note
    row.sent_by = user
    row.sent_at = now
    row.save(update_fields=['status', 'appraisal_note', 'sent_by', 'sent_at', 'updated_at'])
    return row


def crm_respond(loan_request, user, action: str, note: str = ''):
    from loans.models import AppraisalCrmRound

    row = latest_round(loan_request)
    if row is None or row.status != AppraisalCrmRound.STATUS_WITH_CRM:
        return None
    note = (note or '').strip()
    now = timezone.now()
    if action == 'return':
        row.status = AppraisalCrmRound.STATUS_RETURNED
    else:
        row.status = AppraisalCrmRound.STATUS_CLEARED
        row.cleared_at = now
    row.crm_note = note
    row.crm_by = user
    row.crm_at = now
    row.save(update_fields=['status', 'crm_note', 'crm_by', 'crm_at', 'cleared_at', 'updated_at'])
    return row


def cycle_payload(loan_request) -> Optional[dict]:
    if not crm_cycle_applies(loan_request):
        return None
    row = latest_round(loan_request)
    history = []
    if getattr(loan_request, 'pk', None):
        from loans.models import AppraisalCrmRound
        history = list(
            AppraisalCrmRound.objects.filter(loan_request=loan_request).order_by('-version')[:8]
        )
    return {
        'applies': True,
        'latest': row,
        'history': history,
        'cleared': crm_is_cleared(loan_request),
        'blockers': crm_committee_blockers(loan_request),
    }
