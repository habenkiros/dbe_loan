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
    modality = 'sheets'
    if appraisal:
        from loans.product_family import (
            FAMILY_CONSUMER, FAMILY_IDEA_EQUITY, FAMILY_IFB_IJARAH, FAMILY_IFB_MURABAHA,
            FAMILY_LEASE, FAMILY_PROJECT, FAMILY_WHOLESALE, resolve_product_family,
        )
        family = resolve_product_family(loan_request)
        if family == FAMILY_CONSUMER:
            modality = 'consumer'
            from loans.consumer_appraisal import build_consumer_scorecard
            from loans.consumer_overlay import get_consumer_profile
            detail = appraisal.scorecard_detail or {}
            if detail.get('modality') == 'consumer':
                scorecard = detail
            else:
                scorecard = build_consumer_scorecard(
                    loan_request, get_consumer_profile(loan_request),
                )
        elif family == FAMILY_PROJECT:
            modality = 'project'
            from loans.project_appraisal import build_project_scorecard
            from loans.project_overlay import get_project_profile
            detail = appraisal.scorecard_detail or {}
            if detail.get('modality') == 'project':
                scorecard = detail
            else:
                scorecard = build_project_scorecard(
                    loan_request, get_project_profile(loan_request),
                )
        elif family == FAMILY_WHOLESALE:
            modality = 'wholesale'
            from loans.wholesale_appraisal import build_wholesale_scorecard
            from loans.wholesale_overlay import get_pfi_profile
            detail = appraisal.scorecard_detail or {}
            if detail.get('modality') == 'wholesale':
                scorecard = detail
            else:
                scorecard = build_wholesale_scorecard(
                    loan_request, get_pfi_profile(loan_request),
                )
        elif family in (FAMILY_LEASE, FAMILY_IFB_IJARAH):
            modality = 'lease'
            from loans.lease_appraisal import build_lease_scorecard
            from loans.lease_overlay import get_lease_asset
            detail = appraisal.scorecard_detail or {}
            if detail.get('modality') == 'lease':
                scorecard = detail
            else:
                scorecard = build_lease_scorecard(
                    loan_request, get_lease_asset(loan_request),
                )
        elif family == FAMILY_IFB_MURABAHA:
            modality = 'murabaha'
            from loans.murabaha_appraisal import build_murabaha_scorecard
            from loans.murabaha_overlay import get_murabaha
            detail = appraisal.scorecard_detail or {}
            if detail.get('modality') == 'murabaha':
                scorecard = detail
            else:
                scorecard = build_murabaha_scorecard(
                    loan_request, get_murabaha(loan_request),
                )
        elif family == FAMILY_IDEA_EQUITY:
            modality = 'idea'
            from loans.idea_appraisal import build_idea_scorecard
            from loans.idea_overlay import get_idea_profile
            detail = appraisal.scorecard_detail or {}
            if detail.get('modality') == 'idea':
                scorecard = detail
            else:
                scorecard = build_idea_scorecard(
                    loan_request, get_idea_profile(loan_request),
                )
        else:
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

    risk_brief = None
    try:
        from collateral.intelligence import build_collateral_risk_brief
        risk_brief = build_collateral_risk_brief(loan_request)
    except Exception:
        risk_brief = None

    return {
        'documents': documents,
        'document_count': len(documents),
        'document_verified': verified,
        'document_pending': pending,
        'document_rejected': rejected,
        'doc_readiness': doc_readiness,
        'appraisal': appraisal,
        'scorecard': scorecard,
        'modality': modality,
        'strengths_short': strengths[:280] + ('…' if len(strengths) > 280 else ''),
        'weaknesses_short': weaknesses[:280] + ('…' if len(weaknesses) > 280 else ''),
        'collateral_readiness': collateral_readiness,
        'collateral_totals': collateral_totals,
        'coverage': coverage,
        'pipeline_stage': pipeline_stage,
        'pipeline_label': pipeline_label,
        'risk_brief': risk_brief,
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
