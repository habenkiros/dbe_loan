"""Collateral pipeline stages for dashboard and reporting."""

from __future__ import annotations

from typing import Any, Dict, List

from collateral.field_utils import get_loan_collateral_readiness
from loans.collateral_config import allows_engineering_team
from loans.models import LoanRequest


STAGE_ASSIGNED = 'assigned'
STAGE_IN_PROGRESS = 'in_progress'
STAGE_READY = 'ready_to_submit'
STAGE_SUBMITTED = 'submitted'
STAGE_ENG_PENDING = 'engineering_pending'
STAGE_ENG_APPROVED = 'engineering_approved'
STAGE_RETURNED = 'returned'

STAGE_LABELS = {
    STAGE_ASSIGNED: 'Assigned',
    STAGE_IN_PROGRESS: 'In progress',
    STAGE_READY: 'Ready to submit',
    STAGE_SUBMITTED: 'Submitted',
    STAGE_ENG_PENDING: 'Pending engineering QA',
    STAGE_ENG_APPROVED: 'Engineering approved',
    STAGE_RETURNED: 'Returned for correction',
}


def collateral_pipeline_stage(loan_request) -> str:
    if loan_request.collateral_engineering_status == LoanRequest.ENG_COLLATERAL_RETURNED:
        return STAGE_RETURNED
    if loan_request.collateral_submitted_at:
        if (
            allows_engineering_team()
            and loan_request.collateral_engineering_status == LoanRequest.ENG_COLLATERAL_PENDING
        ):
            return STAGE_ENG_PENDING
        if loan_request.collateral_engineering_status == LoanRequest.ENG_COLLATERAL_APPROVED:
            return STAGE_ENG_APPROVED
        return STAGE_SUBMITTED
    readiness = get_loan_collateral_readiness(loan_request)
    if not readiness.get('applies'):
        return STAGE_ASSIGNED
    if readiness.get('all_ready'):
        return STAGE_READY
    if readiness.get('buildings') or readiness.get('land') or readiness.get('other_items'):
        return STAGE_IN_PROGRESS
    return STAGE_ASSIGNED


def pipeline_stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage.replace('_', ' ').title())


def annotate_loans_pipeline(loan_requests) -> List[Dict[str, Any]]:
    rows = []
    for lr in loan_requests:
        stage = collateral_pipeline_stage(lr)
        rows.append({
            'loan_request': lr,
            'pipeline_stage': stage,
            'pipeline_label': pipeline_stage_label(stage),
        })
    return rows


def pipeline_counts(loan_requests) -> Dict[str, int]:
    counts = {k: 0 for k in STAGE_LABELS}
    for lr in loan_requests:
        stage = collateral_pipeline_stage(lr)
        counts[stage] = counts.get(stage, 0) + 1
    return counts
