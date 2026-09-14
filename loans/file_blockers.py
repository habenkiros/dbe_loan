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

    # KYC packs (DBE product files)
    try:
        from loans.kyc_desk import kyc_applies, kyc_committee_blockers
        if kyc_applies(loan_request):
            for msg in kyc_committee_blockers(loan_request):
                blockers.append({
                    'area': 'kyc',
                    'severity': 'high',
                    'message': msg,
                    'action_label': 'Open KYC packs',
                    'action_url_name': 'loan_request_detail',
                    'action_url_args': [loan_request.id],
                })
                stage = 'kyc'
    except Exception:
        pass

    # Fraud / AML compliance cases
    try:
        from loans.compliance.case_engine import open_cases_for_loan
        for case in open_cases_for_loan(loan_request)[:5]:
            blockers.append({
                'area': 'compliance',
                'severity': 'high' if case.priority in ('critical', 'high') else 'medium',
                'message': f'{case.get_case_type_display()} case {case.case_number}: {case.summary[:100]}',
                'action_label': 'Investigate case',
                'action_url_name': 'compliance_case_detail',
                'action_url_args': [case.id],
            })
        if open_cases_for_loan(loan_request).exists():
            stage = 'compliance'
    except Exception:
        pass

    # Appraisal sheets
    try:
        from loans.engines import get_engine
        from loans.models import LoanAppraisal, LoanRequestBasicInfo
        from loans.sheet_requirements import get_appraisal_sheet_status, sheets_blocking_completion

        engine = get_engine(loan_request)
        appraisal = LoanAppraisal.objects.filter(loan_request=loan_request).first()
        basic = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
        if engine.requires_appraisal_sheets():
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
        else:
            for msg in (engine.committee_blockers() or [])[:6]:
                blockers.append({
                    'area': 'appraisal',
                    'severity': 'medium',
                    'message': msg,
                    'action_label': 'Open product desk',
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
    next_plan = rank_next_actions(resolved)
    return {
        'loan_request_id': loan_request.loan_request_id,
        'loan_id': loan_request.id,
        'applicant_name': loan_request.applicant_name,
        'stage': stage,
        'blocker_count': len(resolved),
        'high_severity_count': high,
        'blockers': resolved,
        'next_action': next_plan.get('next_action'),
        'next_steps': next_plan.get('next_steps') or [],
        'remaining_step_count': next_plan.get('remaining_step_count') or 0,
        'draft_missing_doc_request': draft_request,
        'agreement_guidance': agreement_hint,
        'guidance': (
            'Lead with next_action. At most three next_steps. '
            'Use action links for real work. Assist does not attach files, write appraisal, '
            'vote, or disburse. Document requests send only after an explicit confirm.'
        ),
    }


_SEV_RANK = {'high': 0, 'medium': 1, 'info': 2, 'low': 3}
_AREA_RANK = {
    'documents': 0,
    'kyc': 1,
    'appraisal': 2,
    'collateral': 3,
    'compliance': 4,
    'committee': 5,
    'legal': 6,
    'disbursement': 7,
    'post_approval': 7,
}


def rank_next_actions(blockers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Collapse same-area blockers into at most three ranked steps."""
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    order: List[tuple] = []
    for item in blockers or []:
        area = (item.get('area') or 'other').strip() or 'other'
        url = item.get('action_url') or ''
        key = (area, url)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    steps: List[Dict[str, Any]] = []
    for key in order:
        items = groups[key]
        first = items[0]
        area = key[0]
        sev = first.get('severity') or 'medium'
        for row in items:
            if _SEV_RANK.get(row.get('severity'), 9) < _SEV_RANK.get(sev, 9):
                sev = row.get('severity') or sev
        if area == 'documents' and len(items) > 1:
            details = []
            for row in items:
                msg = row.get('message') or ''
                if ':' in msg:
                    details.append(msg.split(':', 1)[1].strip())
                else:
                    details.append(msg)
            title = f'Upload {len(items)} required documents'
            detail = ', '.join(details[:5])
            if len(details) > 5:
                detail += f' (+{len(details) - 5} more)'
        elif len(items) > 1:
            title = first.get('message') or first.get('action_label') or area
            extra = len(items) - 1
            detail = f'{extra} more in {area}' if extra else ''
        else:
            title = first.get('message') or first.get('action_label') or area
            detail = ''
        steps.append({
            'area': area,
            'severity': sev,
            'title': title,
            'detail': detail,
            'action_label': first.get('action_label') or 'Open',
            'action_url': first.get('action_url') or '',
            'item_count': len(items),
        })

    steps.sort(key=lambda s: (_AREA_RANK.get(s['area'], 9), _SEV_RANK.get(s['severity'], 9)))
    top = steps[:3]
    return {
        'next_action': top[0] if top else None,
        'next_steps': top,
        'remaining_step_count': max(0, len(steps) - 3),
    }
