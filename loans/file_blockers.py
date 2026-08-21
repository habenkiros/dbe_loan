"""Per-file blocker summary for Agentic Assist / branch reality."""

from __future__ import annotations

from typing import Any, Dict, List


def build_file_blockers(loan_request) -> Dict[str, Any]:
    """
    Read-only: what is blocking this file right now.

    Does not create agreements, send notifications, or change status.
    """
    from django.urls import reverse

    from loans.models import LoanRequest

    blockers: List[Dict[str, Any]] = []
    stage = 'intake'

    # Documents
    missing_names: List[str] = []
    try:
        from loans.services.document_auth import loan_documents_collateral_readiness
        doc = loan_documents_collateral_readiness(loan_request)
        for name in doc.get('missing_required') or []:
            missing_names.append(name)
            blockers.append({
                'area': 'documents',
                'severity': 'high',
                'message': f'Missing required document: {name}',
                'action_label': 'Upload / request docs',
                'action_url_name': 'upload_loan_request_documents',
                'action_url_args': [loan_request.id],
            })
        for name in doc.get('not_authenticated') or []:
            blockers.append({
                'area': 'documents',
                'severity': 'medium',
                'message': f'Document not verified: {name}',
                'action_label': 'Review documents',
                'action_url_name': 'loan_request_detail',
                'action_url_args': [loan_request.id],
            })
        for name in (doc.get('rejected') or [])[:3]:
            blockers.append({
                'area': 'documents',
                'severity': 'high',
                'message': f'Rejected document: {name}',
                'action_label': 'Fix documents',
                'action_url_name': 'upload_loan_request_documents',
                'action_url_args': [loan_request.id],
            })
        if not doc.get('ready'):
            stage = 'documents'
    except Exception:
        pass

    # Appraisal sheets
    try:
        from loans.models import LoanAppraisal, LoanRequestBasicInfo
        from loans.sheet_requirements import get_appraisal_sheet_status, sheets_blocking_completion

        appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
        basic = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
        if appraisal and not loan_request.appraisal_completed_at:
            sheet_status = get_appraisal_sheet_status(loan_request, appraisal, basic)
            gaps = sheets_blocking_completion(sheet_status) or []
            for gap in gaps[:6]:
                msg = gap if isinstance(gap, str) else str(gap)
                blockers.append({
                    'area': 'appraisal',
                    'severity': 'medium',
                    'message': msg,
                    'action_label': 'Open appraisal',
                    'action_url_name': 'loan_request_detail',
                    'action_url_args': [loan_request.id],
                })
            if gaps:
                stage = 'appraisal'
        elif not appraisal and loan_request.assigned_loan_officer_id:
            blockers.append({
                'area': 'appraisal',
                'severity': 'medium',
                'message': 'Appraisal not started yet.',
                'action_label': 'Open loan',
                'action_url_name': 'loan_request_detail',
                'action_url_args': [loan_request.id],
            })
            stage = 'appraisal'
    except Exception:
        pass

    # Collateral field work (when past docs)
    try:
        from collateral.field_utils import collateral_submit_blockers, get_loan_collateral_readiness
        readiness = get_loan_collateral_readiness(loan_request)
        if readiness and not readiness.get('locked'):
            for b in (collateral_submit_blockers(loan_request) or [])[:4]:
                blockers.append({
                    'area': 'collateral',
                    'severity': 'medium',
                    'message': b,
                    'action_label': 'Collateral summary',
                    'action_url_name': 'collateral:summary',
                    'action_url_args': [loan_request.id],
                })
                stage = 'collateral'
    except Exception:
        pass

    # Committee
    if loan_request.committee_status == LoanRequest.COMMITTEE_PENDING:
        stage = 'committee'
        level = ''
        if loan_request.current_approval_level_id:
            level = loan_request.current_approval_level.name
        blockers.append({
            'area': 'committee',
            'severity': 'info',
            'message': f'Awaiting committee votes{" at " + level if level else ""}.',
            'action_label': 'Committee review',
            'action_url_name': 'loan_request_detail_manager',
            'action_url_args': [loan_request.id],
        })
    elif loan_request.committee_status == LoanRequest.COMMITTEE_RETURNED:
        stage = 'appraisal'
        blockers.append({
            'area': 'committee',
            'severity': 'high',
            'message': 'Returned to officer — fix feedback and resubmit.',
            'action_label': 'Open loan',
            'action_url_name': 'loan_request_detail',
            'action_url_args': [loan_request.id],
        })

    # Post-approval / disbursement
    try:
        from loans.disbursement import disbursement_readiness, is_post_approval
        if is_post_approval(loan_request):
            stage = 'disbursement'
            ready = disbursement_readiness(loan_request)
            for msg in ready.get('blockers') or []:
                blockers.append({
                    'area': 'disbursement',
                    'severity': 'high',
                    'message': msg,
                    'action_label': 'Post-approval',
                    'action_url_name': 'post_approval_detail',
                    'action_url_args': [loan_request.id],
                })
            if ready.get('ok'):
                blockers.append({
                    'area': 'disbursement',
                    'severity': 'info',
                    'message': 'Ready for Finance booking / disbursement.',
                    'action_label': 'Post-approval',
                    'action_url_name': 'post_approval_detail',
                    'action_url_args': [loan_request.id],
                })
    except Exception:
        pass

    # Resolve URLs
    resolved = []
    for b in blockers:
        row = dict(b)
        name = row.pop('action_url_name', None)
        args = row.pop('action_url_args', None) or []
        href = ''
        if name:
            try:
                href = reverse(name, args=args) if args else reverse(name)
            except Exception:
                href = ''
        row['action_url'] = href
        resolved.append(row)

    draft_request = ''
    if missing_names:
        listed = ', '.join(missing_names[:6])
        draft_request = (
            f'Please upload the following required documents for '
            f'{loan_request.loan_request_id} ({loan_request.applicant_name}): {listed}. '
            f'Use the loan Documents page when ready.'
        )

    agreement_hint = ''
    try:
        from loans.agreement_signing import agreement_blockers
        from loans.disbursement import is_post_approval
        if is_post_approval(loan_request):
            ab = agreement_blockers(loan_request)
            if ab:
                agreement_hint = (
                    'Agreement not ready: ' + '; '.join(ab[:3])
                    + '. Generate and collect signatures on Post-approval (Assist will not create agreements).'
                )
            else:
                agreement_hint = (
                    'Agreement signing looks clear — open Post-approval to generate/print if needed. '
                    'Assist does not create or sign agreements.'
                )
    except Exception:
        pass

    high = sum(1 for b in resolved if b.get('severity') == 'high')
    return {
        'loan_request_id': loan_request.loan_request_id,
        'loan_id': loan_request.id,
        'applicant_name': loan_request.applicant_name,
        'stage': stage,
        'blocker_count': len(resolved),
        'high_severity_count': high,
        'blockers': resolved,
        'draft_missing_doc_request': draft_request,
        'agreement_guidance': agreement_hint,
        'guidance': (
            'Read-only diagnosis. Use the action links for real work. '
            'Assist will not send document requests, generate agreements, approve, or disburse.'
        ),
    }
