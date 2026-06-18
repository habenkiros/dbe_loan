# loans/appraisal_policy.py
"""Singleton LoanAnalysisPolicyConfig access with safe defaults."""

from .models import LoanAnalysisPolicyConfig


def get_loan_analysis_policy():
    """
    Return the active policy row, or an unsaved instance with model defaults
    (before migrate / if row missing).
    """
    obj = LoanAnalysisPolicyConfig.objects.first()
    if obj:
        return obj
    return LoanAnalysisPolicyConfig()
