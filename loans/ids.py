"""Loan request ID generation (kept out of views so importers can use it)."""

from __future__ import annotations

import re

from django.db import transaction

from loans.models import LatestLoanRequestID, LoanRequest

_HK_ID = re.compile(r'^HK-(\d+)$')


def generate_incremental_loan_request_id() -> str:
    with transaction.atomic():
        latest, _ = LatestLoanRequestID.objects.select_for_update().get_or_create(
            pk=1, defaults={'latest_id': 0},
        )
        latest.latest_id += 1
        latest.save(update_fields=['latest_id'])
        return f'HK-{latest.latest_id:09d}'


def bump_latest_id_from_existing() -> None:
    """Keep HK-######### imports from colliding with later generated IDs."""
    max_n = 0
    for loan_id in LoanRequest.objects.filter(
        loan_request_id__startswith='HK-',
    ).values_list('loan_request_id', flat=True):
        match = _HK_ID.match(loan_id or '')
        if match:
            max_n = max(max_n, int(match.group(1)))
    if not max_n:
        return
    with transaction.atomic():
        obj, _ = LatestLoanRequestID.objects.select_for_update().get_or_create(
            pk=1, defaults={'latest_id': max_n},
        )
        if obj.latest_id < max_n:
            obj.latest_id = max_n
            obj.save(update_fields=['latest_id'])
