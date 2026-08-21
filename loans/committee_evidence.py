"""Evidence bundle for the committee vote screen (docs + appraisal + collateral)."""

from __future__ import annotations

from typing import Any, Dict, List


def build_committee_vote_evidence(loan_request) -> Dict[str, Any]:
    """
    Compact, read-only evidence for voters before they cast a vote.

    Intentionally lighter than the full appraisal pack / collateral evidence pack —
    enough to decide, with deep-links for full review.
    """
    from loans.models import LoanAppraisal, LoanRequestDocument
    from loans.services.document_auth import loan_documents_collateral_readiness

    appraisal = (
        LoanAppraisal.objects.filter(loan_request=loan_request)
        .select_related('created_by')
        .first()
    )
    documents = list(
        loan_request.application_documents.select_related('document_type', 'uploaded_by')
        .order_by('document_type__order', 'document_type__name', 'uploaded_at')
    )
    doc_readiness = loan_documents_collateral_readiness(loan_request)

    verified = 0
    pending = 0
    rejected = 0
    for d in documents:
        if d.auth_status == LoanRequestDocument.AUTH_VERIFIED:
            verified += 1
        elif d.auth_status == LoanRequestDocument.AUTH_REJECTED:
            rejected += 1
        else:
            pending += 1

    scorecard = None
    if appraisal:
        scorecard = appraisal.scorecard_detail
        if not scorecard:
            from loans.appraisal_scorecard import build_credit_scorecard
            scorecard = build_credit_scorecard(appraisal)

    collateral_readiness = None
    collateral_totals = None
    coverage = None
    pipeline_stage = None
    pipeline_label = None
    try:
        from collateral.coverage import compute_coverage_adequacy
        from collateral.field_utils import get_loan_collateral_readiness
        from collateral.pipeline import collateral_pipeline_stage, pipeline_stage_label
        from loans.services.appraisal_prefill import compute_collateral_totals

        collateral_readiness = get_loan_collateral_readiness(loan_request)
        collateral_totals = compute_collateral_totals(loan_request)
        coverage = compute_coverage_adequacy(loan_request)
        pipeline_stage = collateral_pipeline_stage(loan_request)
        pipeline_label = pipeline_stage_label(pipeline_stage)
    except Exception:
        # Collateral app optional / incomplete on some installs — still show docs + appraisal.
        pass

    strengths = (appraisal.strengths or '').strip() if appraisal else ''
    weaknesses = (appraisal.weaknesses or '').strip() if appraisal else ''

    return {
        'documents': documents,
        'document_count': len(documents),
        'document_verified': verified,
        'document_pending': pending,
        'document_rejected': rejected,
        'doc_readiness': doc_readiness,
        'appraisal': appraisal,
        'scorecard': scorecard,
        'strengths_short': strengths[:280] + ('…' if len(strengths) > 280 else ''),
        'weaknesses_short': weaknesses[:280] + ('…' if len(weaknesses) > 280 else ''),
        'collateral_readiness': collateral_readiness,
        'collateral_totals': collateral_totals,
        'coverage': coverage,
        'pipeline_stage': pipeline_stage,
        'pipeline_label': pipeline_label,
        'has_documents': bool(documents),
        'has_appraisal': appraisal is not None,
        'has_collateral': bool(
            collateral_readiness
            and (
                collateral_readiness.get('buildings')
                or collateral_readiness.get('land')
                or collateral_readiness.get('other_items')
                or (collateral_totals and collateral_totals.get('grand_total'))
            )
        ),
    }
