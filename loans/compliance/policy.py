"""Compliance policy singleton."""

from __future__ import annotations

from loans.models import CompliancePolicy


def get_compliance_policy() -> CompliancePolicy:
    obj, _ = CompliancePolicy.objects.get_or_create(pk=1)
    return obj
