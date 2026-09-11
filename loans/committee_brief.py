"""Committee voter-desk brief: decision card + chips + optional comment draft.

Assistive only — never casts or submits votes.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def build_committee_brief(loan_request, user=None) -> Dict[str, Any]:
    """
    Read-only payload for the manager vote UI and the committee_brief agent tool.

    Includes decision/product cards, evidence chips, SLA age, peer tally, and
    open compliance cases — never a vote action.
    """
    from loans.committee import get_committee_tally, get_levels_for_loan
    from loans.committee_evidence import build_committee_vote_evidence
    from loans.models import LoanAppraisal, LoanRequestBasicInfo

    appraisal = (
        LoanAppraisal.objects.filter(loan_request=loan_request)
        .select_related('created_by')
        .first()
    )
    basic_info = LoanRequestBasicInfo.objects.filter(loan_request=loan_request).first()
    evidence = build_committee_vote_evidence(loan_request)

    decision_card = None
    if appraisal:
        try:
            from loans.ci_decision import build_application_decision
            decision_card = build_application_decision(loan_request, appraisal, basic_info)
        except Exception:
            logger.exception('committee_brief decision_card failed')
            decision_card = None

    desk_intel = None
    try:
        from loans.product_intel import build_product_intel
        desk_intel = build_product_intel(loan_request)
    except Exception:
        desk_intel = None

    levels = get_levels_for_loan(loan_request)
    level = loan_request.current_approval_level
    tally = get_committee_tally(loan_request, current_user=user) if user is not None else get_committee_tally(loan_request)
    current_tally = tally.get('current_tally') or {}

    chips = _build_chips(loan_request, evidence, desk_intel)
    sla = _committee_sla(loan_request)
    open_cases = _open_compliance_cases(loan_request)
    peer_votes = _peer_vote_summary(loan_request, level)

    decision_summary = None
    if decision_card and decision_card.get('decision'):
        decision_summary = {
            'source': 'sheets',
            'code': decision_card['decision'].get('code'),
            'label': decision_card['decision'].get('label'),
            'rationale': decision_card['decision'].get('rationale'),
            'band': decision_card.get('band'),
            'band_label': decision_card.get('band_label'),
            'score_total': decision_card.get('score_total'),
        }
    elif desk_intel and desk_intel.get('decision'):
        decision_summary = {
            'source': 'product_desk',
            'code': desk_intel['decision'].get('code'),
            'label': desk_intel['decision'].get('label'),
            'rationale': desk_intel['decision'].get('rationale'),
            'band': desk_intel['decision'].get('code'),
            'band_label': desk_intel.get('family_label'),
            'score_total': None,
        }

    amount = loan_request.amount_requested
    recommended = getattr(appraisal, 'amount_approved', None) if appraisal else None

    return {
        'loan_request_id': loan_request.loan_request_id,
        'loan_pk': loan_request.pk,
        'applicant_name': loan_request.applicant_name,
        'amount_requested': float(amount) if amount is not None else None,
        'amount_recommended': float(recommended) if recommended is not None else None,
        'committee_status': loan_request.committee_status,
        'current_level': {
            'key': level.key,
            'name': level.name,
        } if level else None,
        'applicable_levels': [{'key': lv.key, 'name': lv.name} for lv in levels],
        'decision_summary': decision_summary,
        'decision_card': decision_card,
        'desk_intel': desk_intel,
        'chips': chips,
        'sla': sla,
        'open_compliance_cases': open_cases,
        'peer_votes': peer_votes,
        'tally': {
            'approve_count': current_tally.get('approve_count') or 0,
            'decline_count': current_tally.get('decline_count') or 0,
            'pend_count': current_tally.get('pend_count') or 0,
            'min_approvals': current_tally.get('min_approvals'),
            'approvals_needed': current_tally.get('approvals_needed'),
            'is_tied': current_tally.get('is_tied'),
        },
        'evidence': {
            'document_verified': evidence.get('document_verified'),
            'document_pending': evidence.get('document_pending'),
            'document_rejected': evidence.get('document_rejected'),
            'modality': evidence.get('modality'),
            'score_band': (evidence.get('scorecard') or {}).get('band_label')
            or (evidence.get('scorecard') or {}).get('band'),
            'strengths_short': evidence.get('strengths_short'),
            'weaknesses_short': evidence.get('weaknesses_short'),
            'pipeline_label': evidence.get('pipeline_label'),
            'coverage_ok': bool((evidence.get('coverage') or {}).get('adequate_for_submit'))
            if evidence.get('coverage') else None,
        },
        'disclaimer': (
            'Assistive only — not an auto-approve. Committee members decide; Assist never votes.'
        ),
    }


def queue_chips_for_loan(loan_request) -> Dict[str, Any]:
    """Compact docs / KYC / CRM / SLA chips for the manager queue list."""
    from loans.committee_evidence import build_committee_vote_evidence

    evidence = build_committee_vote_evidence(loan_request)
    desk_intel = None
    try:
        from loans.product_intel import build_product_intel
        desk_intel = build_product_intel(loan_request)
    except Exception:
        desk_intel = None
    chips = [
        c for c in _build_chips(loan_request, evidence, desk_intel)
        if c.get('key') in ('docs', 'kyc', 'crm')
    ]
    sla = _committee_sla(loan_request)
    return {'chips': chips, 'sla': sla}


def draft_vote_comments(
    loan_request,
    *,
    vote_intent: str = 'approve',
    use_llm: bool = True,
) -> Dict[str, Any]:
    """
    Suggest vote comments for the human to edit. Never submits.

    Tries LLM when use_llm and OPENAI_API_KEY are set; always falls back to
    a deterministic draft from the brief.
    """
    intent = (vote_intent or 'approve').strip().lower()
    if intent not in ('approve', 'decline', 'pend'):
        intent = 'approve'

    brief = build_committee_brief(loan_request)
    rule_draft = _rule_based_draft(brief, intent)
    llm_draft = None
    llm_meta: Dict[str, Any] = {'enabled': False, 'mode': 'off'}

    if use_llm:
        llm_draft, llm_meta = _llm_draft_comments(brief, intent)

    text = (llm_draft or rule_draft or '').strip()
    return {
        'ok': True,
        'vote_intent': intent,
        'comments': text,
        'source': 'llm' if llm_draft else 'rules',
        'llm': llm_meta,
        'disclaimer': brief['disclaimer'],
    }


def brief_for_agent(loan_request, user=None) -> Dict[str, Any]:
    """JSON-friendly slim brief for Agentic Assist (no ORM objects)."""
    brief = build_committee_brief(loan_request, user=user)
    # Drop heavy nested cards; keep decision_summary + chips.
    out = {k: v for k, v in brief.items() if k not in ('decision_card', 'desk_intel')}
    card = brief.get('decision_card') or {}
    desk = brief.get('desk_intel') or {}
    out['positives'] = (card.get('positives') or desk.get('positives') or [])[:6]
    out['risks'] = (card.get('risks') or desk.get('risks') or [])[:8]
    out['required_actions'] = (card.get('required_actions') or desk.get('required_actions') or [])[:6]
    out['blockers'] = (desk.get('blockers') or card.get('blocks') or [])[:8]
    try:
        from django.urls import reverse
        out['links'] = {
            'committee_url': reverse('loan_request_detail_manager', args=[loan_request.pk]),
            'appraisal_pack_url': reverse('committee_appraisal_pack', args=[loan_request.pk]),
        }
    except Exception:
        out['links'] = {}
    out['guidance'] = (
        'READ ONLY committee brief. Summarize for the voter. '
        'Never cast, change, or submit a committee vote. Point humans to the vote UI.'
    )
    return out


def _build_chips(loan_request, evidence, desk_intel) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []

    verified = evidence.get('document_verified') or 0
    pending = evidence.get('document_pending') or 0
    rejected = evidence.get('document_rejected') or 0
    if rejected:
        chips.append({'key': 'docs', 'tone': 'bad', 'label': f'Docs {rejected} rejected'})
    elif pending:
        chips.append({'key': 'docs', 'tone': 'warn', 'label': f'Docs {verified}✓ / {pending} pending'})
    elif verified:
        chips.append({'key': 'docs', 'tone': 'ok', 'label': f'Docs {verified} verified'})
    else:
        chips.append({'key': 'docs', 'tone': 'muted', 'label': 'No documents'})

    if desk_intel:
        kyc = desk_intel.get('kyc') or {}
        if kyc.get('applies'):
            chips.append({
                'key': 'kyc',
                'tone': 'ok' if kyc.get('complete') else 'warn',
                'label': 'KYC clear' if kyc.get('complete') else 'KYC open',
            })
        chips.append({
            'key': 'crm',
            'tone': 'ok' if desk_intel.get('crm_cleared') else 'warn',
            'label': 'CRM clear' if desk_intel.get('crm_cleared') else 'CRM open',
        })
    else:
        try:
            from loans.crm_cycle import crm_is_cleared
            cleared = crm_is_cleared(loan_request)
            chips.append({
                'key': 'crm',
                'tone': 'ok' if cleared else 'warn',
                'label': 'CRM clear' if cleared else 'CRM open',
            })
        except Exception:
            pass
        try:
            from loans.kyc_desk import kyc_applies, kyc_is_complete
            if kyc_applies(loan_request):
                ok = kyc_is_complete(loan_request)
                chips.append({
                    'key': 'kyc',
                    'tone': 'ok' if ok else 'warn',
                    'label': 'KYC clear' if ok else 'KYC open',
                })
        except Exception:
            pass

    coverage = evidence.get('coverage')
    if coverage is not None:
        ok = bool(coverage.get('adequate_for_submit'))
        chips.append({
            'key': 'collateral',
            'tone': 'ok' if ok else 'warn',
            'label': 'Coverage OK' if ok else 'Coverage short',
        })

    band = (evidence.get('scorecard') or {}).get('band_label') or (evidence.get('scorecard') or {}).get('band')
    if band:
        chips.append({'key': 'score', 'tone': 'info', 'label': f'Score {band}'})

    return chips


def _committee_sla(loan_request) -> Dict[str, Any]:
    started = loan_request.submitted_to_committee_at
    if not started:
        return {'days': None, 'label': 'Not submitted', 'tone': 'muted'}
    delta = timezone.now() - started
    days = max(delta.total_seconds() / 86400.0, 0)
    target = float(
        getattr(settings, 'CI_COMMITTEE_SLA_DAYS', None)
        or getattr(settings, 'COMMITTEE_SLA_DAYS', 5)
        or 5
    )
    if days >= target * 2:
        tone = 'bad'
        label = f'{days:.0f}d at committee (SLA breached)'
    elif days >= target:
        tone = 'warn'
        label = f'{days:.0f}d at committee (SLA due)'
    else:
        tone = 'ok'
        label = f'{days:.1f}d at committee'
    return {
        'days': round(days, 2),
        'target_days': target,
        'label': label,
        'tone': tone,
        'submitted_at': started.isoformat(),
    }


def _open_compliance_cases(loan_request) -> List[Dict[str, Any]]:
    try:
        from loans.compliance.case_engine import open_cases_for_loan
        cases = list(open_cases_for_loan(loan_request, open_only=True)[:5])
    except Exception:
        return []
    rows = []
    for c in cases:
        rows.append({
            'id': c.pk,
            'kind': getattr(c, 'kind', None) or getattr(c, 'case_type', '') or '',
            'status': getattr(c, 'status', ''),
            'title': getattr(c, 'title', None) or str(c),
        })
    return rows


def _peer_vote_summary(loan_request, level) -> Dict[str, Any]:
    from loans.models import LoanCommitteeVote

    if not level:
        return {'votes': [], 'approve': 0, 'decline': 0, 'pend': 0}
    votes = list(
        LoanCommitteeVote.objects.filter(
            loan_request=loan_request, approval_level=level,
        ).select_related('member').order_by('voted_at')
    )
    rows = []
    approve = decline = pend = 0
    for v in votes:
        if v.vote == LoanCommitteeVote.VOTE_APPROVE:
            approve += 1
        elif v.vote == LoanCommitteeVote.VOTE_DECLINE:
            decline += 1
        else:
            pend += 1
        rows.append({
            'member': v.member.get_full_name() or v.member.username,
            'vote': v.vote,
            'voted_at': v.voted_at.isoformat() if v.voted_at else None,
            'has_comments': bool((v.comments or '').strip()),
        })
    return {
        'votes': rows,
        'approve': approve,
        'decline': decline,
        'pend': pend,
    }


def _rule_based_draft(brief: Dict[str, Any], intent: str) -> str:
    summary = brief.get('decision_summary') or {}
    evidence = brief.get('evidence') or {}
    amount = brief.get('amount_recommended') or brief.get('amount_requested')
    amount_txt = f'{amount:,.2f} ETB' if amount is not None else 'the recommended amount'

    lines: List[str] = []
    if intent == 'approve':
        lines.append(f'I support approval of {amount_txt}.')
    elif intent == 'decline':
        lines.append(f'I recommend decline for this file (ask {amount_txt}).')
    else:
        lines.append('I recommend pending this file until the gaps below are resolved.')

    if summary.get('label'):
        lines.append(
            f'AI assist cue: {summary.get("label")} — {summary.get("rationale") or ""}'.strip()
        )
    if evidence.get('strengths_short'):
        lines.append(f'Strengths: {evidence["strengths_short"]}')
    if evidence.get('weaknesses_short'):
        lines.append(f'Watch-outs: {evidence["weaknesses_short"]}')

    risks = []
    card = brief.get('decision_card') or {}
    desk = brief.get('desk_intel') or {}
    risks.extend(card.get('risks') or [])
    risks.extend(desk.get('risks') or [])
    if risks and intent != 'approve':
        lines.append('Key risks: ' + '; '.join(risks[:3]))
    elif risks and intent == 'approve':
        lines.append('Conditions / residual risks: ' + '; '.join(risks[:2]))

    chips = brief.get('chips') or []
    warn_chips = [c['label'] for c in chips if c.get('tone') in ('warn', 'bad')]
    if warn_chips:
        lines.append('Open items: ' + '; '.join(warn_chips[:4]))

    cases = brief.get('open_compliance_cases') or []
    if cases:
        lines.append(f'Open compliance cases: {len(cases)} — resolve or document before final.')

    lines.append('(Draft for edit — committee decision remains yours.)')
    return '\n'.join(lines)


def _llm_draft_comments(brief: Dict[str, Any], intent: str) -> tuple:
    openai_key = getattr(settings, 'OPENAI_API_KEY', '') or os.getenv('OPENAI_API_KEY', '')
    if not openai_key:
        return None, {'enabled': False, 'mode': 'off', 'error': 'OPENAI_API_KEY not configured.'}

    payload = {
        'loan': brief.get('loan_request_id'),
        'applicant': brief.get('applicant_name'),
        'amount_requested': brief.get('amount_requested'),
        'amount_recommended': brief.get('amount_recommended'),
        'decision': brief.get('decision_summary'),
        'chips': brief.get('chips'),
        'evidence': brief.get('evidence'),
        'peer_votes': brief.get('peer_votes'),
        'sla': brief.get('sla'),
        'open_cases': brief.get('open_compliance_cases'),
        'vote_intent': intent,
    }
    prompt = (
        'You draft short committee vote comments for a human voter to edit.\n'
        'Return JSON only: {"comments": "..."}.\n'
        'Rules: 3–6 sentences, ETB amounts, no invented facts, never claim the AI approved.\n'
        f'Vote intent: {intent}.\n'
        f'Brief JSON:\n{json.dumps(payload, default=str)[:6000]}'
    )
    try:
        import requests

        model = getattr(settings, 'OPENAI_MODEL', None) or getattr(
            settings, 'OPENAI_DOCUMENT_MODEL', 'gpt-4o-mini',
        )
        base = (getattr(settings, 'OPENAI_BASE_URL', '') or 'https://api.openai.com/v1').rstrip('/')
        resp = requests.post(
            f'{base}/chat/completions',
            headers={'Authorization': f'Bearer {openai_key}', 'Content-Type': 'application/json'},
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': 'You respond with valid JSON only.'},
                    {'role': 'user', 'content': prompt},
                ],
                'temperature': 0.2,
            },
            timeout=45,
        )
        if resp.status_code != 200:
            return None, {
                'enabled': True,
                'mode': 'error',
                'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
            }
        text = resp.json()['choices'][0]['message']['content']
        content = (text or '').strip()
        if content.startswith('```'):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
        parsed = json.loads(content)
        comments = (parsed.get('comments') or '').strip()
        if not comments:
            return None, {'enabled': True, 'mode': 'empty', 'error': 'Empty LLM comments.'}
        return comments, {'enabled': True, 'mode': 'live', 'provider': 'openai', 'model': model}
    except Exception as exc:
        logger.warning('committee draft LLM failed: %s', exc)
        return None, {'enabled': True, 'mode': 'error', 'error': str(exc)[:200]}
