"""Agentic Assist chatbot: LLM plans, Django tools execute (guarded).

Production flow:
  1. Hold a multi-turn *story* (draft loan file) the user can correct.
  2. Commit only on explicit confirmation.
  3. Generate scoped pipeline reporting with Excel links.

Provider: OpenAI Chat Completions + tool calling (Azure via OPENAI_BASE_URL).
Without API key: offline stub with story + reports + commit.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.utils import timezone

from loans.agent import user_can_use_agent
from loans.agent_story import (
    conversation_story,
    story_for_api,
    story_summary_lines,
)
from loans.agent_tools import TOOL_SPECS, dispatch_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6
MAX_HISTORY_MESSAGES = 48


def resolve_llm_provider() -> str:
    raw = (getattr(settings, 'AGENT_LLM_PROVIDER', None) or 'auto').strip().lower()
    key = (getattr(settings, 'OPENAI_API_KEY', None) or '').strip()
    if raw == 'auto':
        return 'openai' if key else 'stub'
    if raw == 'openai' and not key:
        return 'stub'
    return raw if raw in ('openai', 'stub') else 'stub'


def build_system_prompt(user, conversation=None) -> str:
    from loans.agent_permissions import capabilities_for_user

    role = getattr(user, 'role', None) or 'staff'
    branch = getattr(user, 'branch', None)
    branch_name = branch.name if branch else 'not assigned'
    story = conversation_story(conversation) if conversation else {}
    story_block = story_summary_lines(story) if story else '(empty draft)'
    caps = capabilities_for_user(user)
    role_block = ''
    if caps.get('can_create_loan'):
        role_block = (
            'You are helping a BRANCH MANAGER:\n'
            '- Create ONLY a loan application (update_story → confirm). '
            'Never documents, appraisal, estimation, queue flags, or approvals.\n'
            '- LO can later register collateral shells; estimation is UI/field only.\n'
            '- Pipeline report is allowed in scope.\n'
        )
    elif role in ('loan_officer', 'credit_loan_officer'):
        role_block = (
            'You are helping a LOAN OFFICER:\n'
            '- NEVER create loans, attach documents, estimate collateral, fill appraisal, or approve.\n'
            '- May register_collateral shells (building/land/other with no values).\n'
            '- document_checklist and read_appraisal are read-only coaching; point to UI for writes.\n'
            '- find_loans on assigned/branch scope.\n'
        )
    else:
        role_block = (
            'Admin/staff Assist (no create-loan):\n'
            '- NEVER create loans, documents, estimation, appraisal writes, or approvals.\n'
            '- Reports / read tools only as returned by tools.\n'
        )

    return (
        'You are DECSI Assist — a production banking ops copilot with role-aware tools.\n'
        f'Officer: {user.get_username()} · role: {role} · branch: {branch_name}.\n'
        f'Capabilities: create_loan={caps.get("can_create_loan")} · '
        f'documents={caps.get("can_manage_documents")} · appraisal={caps.get("can_work_appraisal")}.\n\n'
        f'{role_block}\n'
        '## Hard rules\n'
        '- Tools enforce permissions; never invent success if a tool returns error.\n'
        '- NEVER: attach/verify documents, seed appraisal, estimate/value collateral, '
        'queue-approve, committee submit, vote, or disburse — illegal via Assist in production.\n'
        '- Never invent loan IDs or KPI/numbers outside tool payloads.\n'
        '- Currency is ETB.\n\n'
        f'## Current held story (BM create draft)\n{story_block}\n'
    )


def _parse_tool_args(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _openai_chat(messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    api_key = (getattr(settings, 'OPENAI_API_KEY', None) or '').strip()
    base = (getattr(settings, 'OPENAI_BASE_URL', None) or 'https://api.openai.com/v1').rstrip('/')
    model = getattr(settings, 'OPENAI_MODEL', None) or 'gpt-4o-mini'
    timeout = int(getattr(settings, 'AGENT_LLM_TIMEOUT', 90) or 90)
    url = f'{base}/chat/completions'
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    api_version = (getattr(settings, 'OPENAI_API_VERSION', None) or '').strip()
    if api_version:
        url = f'{url}?api-version={api_version}'
        headers['api-key'] = api_key

    payload = {
        'model': model,
        'messages': messages,
        'tools': tools,
        'tool_choice': 'auto',
        'temperature': 0.15,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f'LLM HTTP {resp.status_code}: {resp.text[:500]}')
    return resp.json()


def _trim_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(messages) <= MAX_HISTORY_MESSAGES:
        return messages
    return messages[-MAX_HISTORY_MESSAGES:]


def _ui_append(conversation, role: str, content: str, tools: Optional[List[Dict[str, Any]]] = None):
    ui = list(conversation.ui_messages or [])
    entry = {
        'role': role,
        'content': content or '',
        'at': timezone.now().isoformat(),
    }
    if tools:
        entry['tools'] = tools
    ui.append(entry)
    # Cap UI timeline
    conversation.ui_messages = ui[-80:]


def _tool_audit_entry(name: str, out: Dict[str, Any]) -> Dict[str, Any]:
    detail = (
        out.get('error')
        or out.get('loan_request_code')
        or out.get('narrative')
        or out.get('detail')
        or (out.get('story') or {}).get('status')
        or ''
    )
    data = {}
    for k in (
        'loan_request_id', 'loan_request_code', 'run_id', 'links', 'partial',
        'ready_to_commit', 'missing', 'stats', 'scope',
    ):
        if k in out:
            data[k] = out[k]
    if out.get('story'):
        data['story'] = out['story']
    if out.get('links'):
        data['links'] = out['links']
    return {
        'tool': name,
        'ok': bool(out.get('ok')),
        'detail': str(detail)[:240],
        'data': data,
    }


def _result_payload(user, conversation, provider: str, reply: str, tools_audit: List, **extra) -> Dict[str, Any]:
    story = story_for_api(conversation_story(conversation))
    code = None
    if conversation.last_loan_request_id:
        try:
            code = conversation.last_loan_request.loan_request_id
        except Exception:
            code = story.get('committed_loan_code')
    return {
        'ok': True,
        'provider': provider,
        'reply': reply or 'Done.',
        'conversation_id': conversation.pk,
        'tools': tools_audit,
        'story': story,
        'loan_request_id': conversation.last_loan_request_id,
        'loan_request_code': code or story.get('committed_loan_code') or None,
        **extra,
    }


def run_chat_turn(user, conversation, user_text: str) -> Dict[str, Any]:
    """Process one user message; mutates and saves conversation."""
    text = (user_text or '').strip()
    if not text:
        return {
            'ok': False,
            'error': 'Empty message',
            'reply': 'Please type a message.',
            'conversation_id': conversation.pk,
            'story': story_for_api(conversation_story(conversation)),
        }
    if not user_can_use_agent(user):
        return {
            'ok': False,
            'error': 'Permission denied',
            'reply': 'You are not allowed to use DECSI Assist.',
            'conversation_id': conversation.pk,
            'story': story_for_api(conversation_story(conversation)),
        }

    provider = resolve_llm_provider()
    conversation.llm_provider = provider
    _ui_append(conversation, 'user', text)

    if provider == 'stub':
        result = _stub_turn(user, conversation, text)
    else:
        try:
            result = _openai_turn(user, conversation, text)
        except Exception as exc:
            logger.exception('Agent chat LLM failure')
            result = _stub_turn(user, conversation, text)
            result['reply'] = (
                f'(LLM unavailable: {exc}. Using offline assistant.)\n\n'
                + (result.get('reply') or '')
            )
            result['llm_error'] = str(exc)
            result['provider'] = 'stub_fallback'

    # Ensure story latest on result
    if 'story' not in result:
        result['story'] = story_for_api(conversation_story(conversation))

    try:
        conversation.save()
    except Exception:
        logger.exception('Failed saving conversation')
        conversation.save(update_fields=['messages', 'ui_messages', 'story', 'llm_provider', 'title', 'last_loan_request', 'updated_at'])
    return result


def _openai_turn(user, conversation, text: str) -> Dict[str, Any]:
    hist = list(conversation.messages or [])
    hist.append({'role': 'user', 'content': text})
    hist = _trim_history(hist)

    api_messages: List[Dict[str, Any]] = [
        {'role': 'system', 'content': build_system_prompt(user, conversation)},
        *hist,
    ]
    tools_audit: List[Dict[str, Any]] = []
    final_text = ''

    for _ in range(MAX_TOOL_ROUNDS):
        data = _openai_chat(api_messages, TOOL_SPECS)
        choice = (data.get('choices') or [{}])[0]
        msg = choice.get('message') or {}
        tool_calls = msg.get('tool_calls') or []

        if tool_calls:
            api_messages.append({
                'role': 'assistant',
                'content': msg.get('content') or None,
                'tool_calls': tool_calls,
            })
            for tc in tool_calls:
                fn = (tc.get('function') or {})
                name = fn.get('name') or ''
                args = _parse_tool_args(fn.get('arguments'))
                out = dispatch_tool(user, name, args, conversation)
                tools_audit.append(_tool_audit_entry(name, out))
                api_messages.append({
                    'role': 'tool',
                    'tool_call_id': tc.get('id') or name,
                    'content': json.dumps(out, default=str)[:14000],
                })
            continue

        final_text = (msg.get('content') or '').strip()
        api_messages.append({'role': 'assistant', 'content': final_text})
        break
    else:
        final_text = final_text or (
            'I hit the tool-loop limit. Check the actions below or try a shorter request.'
        )

    conversation.messages = [m for m in api_messages if m.get('role') != 'system']
    _ui_append(conversation, 'assistant', final_text, tools_audit or None)
    return _result_payload(user, conversation, 'openai', final_text, tools_audit)


# ---------------------------------------------------------------------------
# Offline stub
# ---------------------------------------------------------------------------

# Comma-grouped first; never allow [1-3 digits] + optional commas empty — that
# matched "900" inside "900000" and left amount = None forever on bare ETB amounts.
_AMOUNT_RE = re.compile(
    r'(?:etb|birr)?\s*'
    r'('
    r'[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?'  # 1,500,000
    r'|[0-9]+(?:\.[0-9]+)?'                   # 900000 / 1.5
    r')'
    r'\s*(?:etb|birr)?',
    re.I,
)
_NAME_RE = re.compile(
    r'(?:for|applicant|client|borrower)\s+([A-Za-z][A-Za-z0-9 .,&\'-]{1,80})',
    re.I,
)
_PHONE_RE = re.compile(r'(0?9\d{8}|\+?2519\d{8})')
_NAME_STOP_WORDS = frozenset({
    'loan', 'request', 'application', 'file', 'story', 'draft', 'msme',
    'corporate', 'category', 'collateral', 'building', 'amount', 'phone',
    'confirm', 'create', 'the', 'a', 'an',
})


def _looks_like_phone_digits(raw: str) -> bool:
    d = re.sub(r'\D', '', raw or '')
    return bool(re.fullmatch(r'0?9\d{8}|2519\d{8}', d))


def _extract_amount(text: str) -> Optional[Decimal]:
    t = text.lower()
    # "1.5m" has no word boundary between digit and m — do not use \bm
    mil = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(?:million|m)\b', t)
    if mil:
        return Decimal(mil.group(1)) * Decimal('1000000')
    candidates: List[Decimal] = []
    for m in _AMOUNT_RE.finditer(text):
        raw = m.group(1).replace(',', '')
        if _looks_like_phone_digits(raw):
            continue
        # Skip digits glued to labeled phone lines
        start = m.start()
        prefix = text[max(0, start - 12):start].lower()
        if re.search(r'(phone|mobile|tel)\s*[:=]?\s*$', prefix):
            continue
        try:
            val = Decimal(raw)
        except InvalidOperation:
            continue
        if val >= 1000:
            candidates.append(val)
    if not candidates:
        return None
    # Prefer loan-scale amounts near amount/etb/birr labels when multiple hits
    labeled = re.search(
        r'(?:amount|etb|birr)\s*[:=]?\s*(?:of\s+|to\s+|is\s+)?([0-9][0-9,.]*)',
        t,
        re.I,
    )
    if labeled:
        try:
            lab = Decimal(labeled.group(1).replace(',', ''))
            if lab >= 1000:
                return lab
        except InvalidOperation:
            pass
    return candidates[0]


def _name_clean(name: str) -> str:
    name = (name or '').strip(' .,;:\n\t')
    # Drop trailing amount fragments: "zemeo, 900000" / "zemeo 900000 birr"
    name = re.sub(
        r'[,;\s]+[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?(?:\s*(?:etb|birr|m|million))?.*$',
        '',
        name,
        flags=re.I,
    )
    name = re.sub(
        r'\s+[0-9]+(?:\.[0-9]+)?(?:\s*(?:etb|birr|m|million))?.*$',
        '',
        name,
        flags=re.I,
    )
    low = name.lower()
    for stop in (
        ' amount', ' for', ' with', ' phone', ' etb', ' birr', ' category',
        ' collateral', ' corporate', ' msme', ' —', ' - ', '\namount', '\nphone',
        '\ncategory', '\ncollateral',
    ):
        if stop in low:
            name = name[: low.index(stop)].strip(' .,;:')
            low = name.lower()
    name = name.strip(' .,;:')
    if name.lower() in _NAME_STOP_WORDS:
        return ''
    return name


def _extract_name(text: str) -> str:
    # Labeled multi-line forms first: "applicant name: zemeo"
    labeled = re.search(
        r'(?:applicant\s*name|customer\s*name|borrower\s*name|client\s*name'
        r'|(?<![A-Za-z])name)\s*[:=]\s*([A-Za-z][^\n,;]{1,80})',
        text,
        re.I,
    )
    if labeled:
        cleaned = _name_clean(labeled.group(1))
        if cleaned:
            return cleaned

    # "loan for X" / "for X," — stop at punctuation that starts amount clauses
    m_for = re.search(
        r'(?:loan|application|request|file|story|draft)\s+for\s+([A-Za-z][A-Za-z0-9 .&\'-]{1,60})',
        text,
        re.I,
    )
    if m_for:
        cleaned = _name_clean(m_for.group(1))
        if cleaned:
            return cleaned

    m = _NAME_RE.search(text)
    if m:
        cleaned = _name_clean(m.group(1))
        if cleaned and cleaned.lower() not in ('the', 'a', 'an'):
            return cleaned

    m2 = re.search(
        r'(?:create|open|start|bootstrap|draft|hold)\s+(?:a\s+)?'
        r'(?:loan|file|application|story|request)?\s*(?:request\s+)?'
        r'(?:for\s+)([A-Za-z][A-Za-z0-9 .&\'-]{1,60})',
        text,
        re.I,
    )
    if m2:
        cleaned = _name_clean(m2.group(1))
        if cleaned:
            return cleaned
    return ''


def _wants_create_phrase(tlow: str) -> bool:
    if re.search(r'\b(create|open|start|bootstrap)\b.{0,40}\bloan\b', tlow):
        return True
    return any(k in tlow for k in ('new loan', 'bootstrap', 'register applicant'))


def _wants_confirm(tlow: str) -> bool:
    return any(
        k in tlow
        for k in (
            'confirm', 'create it', 'create the loan', 'create the file',
            'go ahead', 'yes create', 'commit', 'finalize',
        )
    )


def _wants_report(tlow: str) -> bool:
    return any(
        k in tlow
        for k in (
            'report', 'pipeline', 'how many loan', 'kpi', 'dashboard',
            'export excel', 'excel export', 'portfolio summary',
            'branch summary', 'disbursed count', 'pending loans',
        )
    )


def _wants_story_show(tlow: str) -> bool:
    return any(
        k in tlow
        for k in (
            'show story', 'my draft', 'current draft', 'what do you have',
            'show draft', 'held story', 'what is the story',
        )
    )


def _correction_patch(text: str, tlow: str) -> Dict[str, Any]:
    """Parse simple correction phrases into a story patch."""
    patch: Dict[str, Any] = {}
    # amount — support "amount: 900000", "amount of 900000", "amount to 1.2m"
    m_amt = re.search(
        r'(?:change|set|update|correct|said)?\s*(?:the\s+)?'
        r'(?:loan\s+)?amount\s*(?:to|is|=|:|of)?\s*([0-9][0-9,.]*)\s*(m|million|etb|birr)?',
        tlow,
        re.I,
    )
    if m_amt:
        raw = m_amt.group(1).replace(',', '')
        try:
            val = Decimal(raw)
            unit = (m_amt.group(2) or '').lower()
            if unit in ('m', 'million'):
                val *= Decimal('1000000')
            if val >= 1000:
                patch['amount'] = float(val)
        except InvalidOperation:
            pass
    if 'amount' not in patch:
        # "to 2 million" / "i said 900000 birr" after user mentions amount
        if 'amount' in tlow or 'etb' in tlow or 'birr' in tlow or re.search(r'\bto\b', tlow):
            amt = _extract_amount(text)
            if amt and (
                'amount' in tlow
                or re.search(r'(change|correct|set|update|make it|to |said)\s', tlow)
            ):
                patch['amount'] = float(amt)

    m_name = re.search(
        r'(?:applicant\s*name|customer\s*name|(?<![A-Za-z])name|applicant)\s*'
        r'(?:to|is|=|:)\s*([A-Za-z][^\n,;]{1,60})',
        text,
        re.I,
    )
    if m_name:
        cleaned = _name_clean(m_name.group(1))
        if cleaned:
            patch['applicant_name'] = cleaned

    m_phone = re.search(
        r'(?:phone|mobile)\s*(?:to|is|=|:)?\s*(0?9\d{8}|\+?2519\d{8})',
        tlow,
    )
    if m_phone:
        patch['phone_number'] = m_phone.group(1)

    m_reason = re.search(r'(?:purpose|reason)\s*(?:to|is|=|:)\s*(.+)$', text, re.I)
    if m_reason:
        patch['reason'] = m_reason.group(1).strip()[:500]

    if 'corporate' in tlow and any(w in tlow for w in ('make', 'set', 'mark', 'is ', 'type')):
        patch['corporate'] = 'not corporate' not in tlow and 'msme' not in tlow
    if re.search(r'\bmsme\b', tlow) and any(w in tlow for w in ('make', 'set', 'mark', 'category', 'type')):
        patch['corporate'] = False

    m_addr = re.search(r'(?:address)\s*(?:to|is|=|:)\s*(.+)$', text, re.I)
    if m_addr:
        patch['declared_address'] = m_addr.group(1).strip()[:2000]

    return patch


def _stub_finish(conversation, text, reply, tools_audit, user, **extra):
    conversation.messages = list(conversation.messages or []) + [
        {'role': 'user', 'content': text},
        {'role': 'assistant', 'content': reply},
    ]
    _ui_append(conversation, 'assistant', reply, tools_audit or None)
    base = _result_payload(user, conversation, 'stub', reply, tools_audit)
    base.update(extra)
    return base


def _stub_turn(user, conversation, text: str) -> Dict[str, Any]:
    tools_audit: List[Dict[str, Any]] = []
    tlow = text.lower().strip()

    if any(k in tlow for k in ('what can you', 'help', 'capabilities', 'who are you')):
        from loans.agent_permissions import capabilities_for_user
        caps = capabilities_for_user(user)
        if caps.get('can_create_loan'):
            reply = (
                'I’m DECSI Assist for branch managers.\n'
                '• Create a bare loan application only (no docs/appraisal/approvals).\n'
                '• Pipeline reports / Excel.\n'
                'LO can register collateral shells later (no estimation).'
            )
        else:
            reply = (
                'I’m DECSI Assist for loan officers.\n'
                '• Cannot create loans, attach documents, estimate, appraisal write, or approve.\n'
                '• Register collateral shells: building / land / other (no values).\n'
                '• Document checklist + appraisal coach are read-only.\n'
            )
        return _stub_finish(conversation, text, reply, [], user)

    if _wants_story_show(tlow) or tlow in ('story', 'draft'):
        out = dispatch_tool(user, 'get_story', {}, conversation)
        tools_audit.append(_tool_audit_entry('get_story', out))
        reply = 'Current draft:\n' + (out.get('summary') or story_summary_lines(conversation_story(conversation)))
        return _stub_finish(conversation, text, reply, tools_audit, user)

    if any(k in tlow for k in ('clear story', 'reset draft', 'new story', 'forget draft')):
        out = dispatch_tool(user, 'clear_story', {}, conversation)
        tools_audit.append(_tool_audit_entry('clear_story', out))
        return _stub_finish(conversation, text, 'Draft cleared. Describe the next applicant when ready.', tools_audit, user)

    if _wants_report(tlow):
        args: Dict[str, Any] = {}
        if 'pending' in tlow:
            args['status'] = 'Pending'
        if 'approved' in tlow and 'committee' not in tlow:
            args['status'] = 'Approved'
        out = dispatch_tool(user, 'pipeline_report', args, conversation)
        tools_audit.append(_tool_audit_entry('pipeline_report', out))
        if not out.get('ok'):
            reply = out.get('error') or 'Report failed.'
        else:
            stats = out.get('stats') or {}
            links = out.get('links') or {}
            reply = (
                f"{out.get('narrative')}\n"
                f"Approval rate: {stats.get('approval_rate')}% · "
                f"Avg credit score: {stats.get('avg_credit_score') or 'n/a'}.\n"
            )
            sample = out.get('sample') or []
            if sample:
                reply += 'Sample:\n'
                for row in sample[:5]:
                    reply += (
                        f"· {row.get('loan_request_id')} — {row.get('applicant_name')} — "
                        f"ETB {row.get('amount_requested', 0):,.0f} — {row.get('status')}\n"
                    )
            if links.get('excel_export_url'):
                reply += f"\nExcel export: {links['excel_export_url']}"
            if links.get('pipeline_view_url'):
                reply += f"\nPipeline view: {links['pipeline_view_url']}"
        return _stub_finish(conversation, text, reply, tools_audit, user)

    if any(k in tlow for k in ('find loan', 'search loan', 'look up', 'lookup')):
        q = re.sub(r'^(find|search|look up|lookup)\s+(loan|loans)?\s*', '', text, flags=re.I).strip()
        out = dispatch_tool(user, 'find_loans', {'query': q or text}, conversation)
        tools_audit.append(_tool_audit_entry('find_loans', out))
        loans = out.get('loans') or []
        if not loans:
            reply = f"No loans matched “{out.get('query') or q}” in your scope."
        else:
            reply = f"Found {len(loans)}:\n"
            for row in loans:
                reply += f"· {row.get('loan_request_id')} — {row.get('applicant_name')} — ETB {row.get('amount', 0):,.0f}\n"
        return _stub_finish(conversation, text, reply, tools_audit, user)

    if any(k in tlow for k in ('my branch', 'workspace', 'what branch', 'categories')):
        out = dispatch_tool(user, 'lookup_workspace', {}, conversation)
        tools_audit.append(_tool_audit_entry('lookup_workspace', out))
        reply = (
            f"Branch: {out.get('branch_name') or '—'} · role: {out.get('role')} · "
            f"report scope: {out.get('report_scope') or 'n/a'}."
        )
        return _stub_finish(conversation, text, reply, tools_audit, user)

    if any(k in tlow for k in ('document', 'checklist', 'upload doc', 'docs for')):
        code_m = re.search(r'([A-Z]{1,4}-?\d{3,}|[A-Z]{2,}-\d+)', text, re.I)
        args = {}
        if code_m:
            args['loan_code'] = code_m.group(1)
        out = dispatch_tool(user, 'document_checklist', args, conversation)
        tools_audit.append(_tool_audit_entry('document_checklist', out))
        if not out.get('ok'):
            reply = out.get('error') or 'Document checklist failed.'
        else:
            missing = out.get('missing_or_unverified') or []
            reply = (
                f"Documents for {out.get('loan_request_code')} — "
                f"{len(missing)} missing/unverified.\n"
            )
            for d in (out.get('documents') or [])[:12]:
                reply += f"· {d.get('document_type')}: {d.get('status')}\n"
            if out.get('links', {}).get('upload_url'):
                reply += f"\nUpload real files: {out['links']['upload_url']}"
            if 'demo' in tlow or 'placeholder' in tlow:
                reply += (
                    '\nAssist will not attach demo documents (production policy). '
                    'Upload real files via the Documents page.'
                )
        return _stub_finish(conversation, text, reply, tools_audit, user)

    if any(k in tlow for k in (
        'register collateral', 'register building', 'register land',
        'add building', 'add collateral', 'register vehicle', 'register machinery',
    )):
        kind = 'other'
        if 'building' in tlow or 'house' in tlow:
            kind = 'building'
        elif 'land' in tlow or 'plot' in tlow:
            kind = 'land'
        elif any(x in tlow for x in ('vehicle', 'machinery', 'equipment', 'other')):
            kind = 'other'
        code_m = re.search(r'([A-Z]{1,4}-?\d{3,}|[A-Z]{2,}-\d+)', text, re.I)
        args = {'kind': kind, 'label': 'Shell from chat'}
        # extract "called X" or "named X"
        nm = re.search(
            r'(?:called|named|label)\s+([A-Za-z0-9 .,&\'-]{2,60}?)(?:\s+for\b|\s*$)',
            text,
            re.I,
        )
        if nm:
            args['label'] = nm.group(1).strip(' .,')
        if code_m:
            args['loan_code'] = code_m.group(1)
        out = dispatch_tool(user, 'register_collateral', args, conversation)
        tools_audit.append(_tool_audit_entry('register_collateral', out))
        reply = out.get('detail') or out.get('error') or str(out)
        return _stub_finish(conversation, text, reply, tools_audit, user)

    if any(k in tlow for k in ('appraisal', 'read sheet', 'dscr', 'scorecard', 'missing field', 'coach')):
        code_m = re.search(r'([A-Z]{1,4}-?\d{3,}|[A-Z]{2,}-\d+)', text, re.I)
        args = {}
        if code_m:
            args['loan_code'] = code_m.group(1)
        if 'sheet 1' in tlow or 'sheet1' in tlow:
            args['focus_sheet'] = 1
        elif 'sheet 2' in tlow:
            args['focus_sheet'] = 2
        elif 'sheet 3' in tlow or 'cashflow' in tlow or 'dscr' in tlow:
            args['focus_sheet'] = 3
        elif 'sheet 5' in tlow or 'collateral' in tlow:
            args['focus_sheet'] = 5
        elif 'sheet 6' in tlow:
            args['focus_sheet'] = 6
        out = dispatch_tool(user, 'read_appraisal', args, conversation)
        tools_audit.append(_tool_audit_entry('read_appraisal', out))
        if not out.get('ok'):
            reply = out.get('error') or 'Could not read appraisal.'
        else:
            gaps = out.get('blocking_gaps') or []
            assist = out.get('analysis_assist') or {}
            reply = (
                f"Appraisal coach for {out.get('loan_request_code')} "
                f"({out.get('mode_label') or out.get('appraisal_mode')}).\n"
                f"Score: {assist.get('score_total')} · band: {assist.get('score_band')}\n"
            )
            if gaps:
                reply += 'Gaps:\n' + '\n'.join(f'· {g}' for g in gaps[:6]) + '\n'
            for ins in (assist.get('insights') or [])[:4]:
                reply += f"· [{ins.get('severity')}] {ins.get('title')}: {ins.get('detail')}\n"
            if out.get('links', {}).get('appraisal_url'):
                reply += f"\nOpen sheets: {out['links']['appraisal_url']}"
        return _stub_finish(conversation, text, reply, tools_audit, user)

    if _wants_confirm(tlow):
        from loans.agent_permissions import user_can_create_loan_via_agent
        if not user_can_create_loan_via_agent(user):
            reply = (
                'Only branch managers can create loan requests. '
                'I can help you with documents and appraisal coaching on assigned files.'
            )
            return _stub_finish(conversation, text, reply, [], user)
        out = dispatch_tool(user, 'commit_story', {}, conversation)
        tools_audit.append(_tool_audit_entry('commit_story', out))
        if out.get('ok'):
            code = out.get('loan_request_code')
            reply = (
                f"Created {code}. Bare application only — no documents, appraisal, estimation, or approvals.\n"
                'LO may register collateral shells next; real work continues in the UI.'
            )
            if out.get('links', {}).get('detail_url'):
                reply += f"\nOpen: {out['links']['detail_url']}"
        else:
            reply = out.get('error') or 'Could not commit story.'
            if out.get('summary') or out.get('story'):
                reply += '\n\n' + story_summary_lines(conversation_story(conversation))
        return _stub_finish(conversation, text, reply, tools_audit, user, ok=bool(out.get('ok')), error=out.get('error'))

    # Corrections → story
    patch = _correction_patch(text, tlow)
    name = _extract_name(text)
    amount = _extract_amount(text)
    phone_m = _PHONE_RE.search(text)
    wants_loanish = any(
        k in tlow
        for k in (
            'create loan', 'new loan', 'open loan', 'start loan', 'bootstrap',
            'loan for', 'application for', 'draft for', 'file for', 'hold story',
            'applicant is', 'borrower is',
        )
    ) or _wants_create_phrase(tlow) or bool(name and amount) or bool(patch)


    if wants_loanish or patch:
        from loans.agent_permissions import user_can_create_loan_via_agent
        if not user_can_create_loan_via_agent(user):
            reply = (
                'Loan officers cannot create new loan requests. Ask your branch manager to open the file, '
                'then say e.g. “document checklist for LOAN-CODE” or “read appraisal for LOAN-CODE”.'
            )
            return _stub_finish(conversation, text, reply, [], user)
        if name and 'applicant_name' not in patch:
            patch['applicant_name'] = name
        if amount is not None and 'amount' not in patch:
            # For pure amount extract without correction verbs only if loanish/create
            if wants_loanish or 'amount' in tlow:
                patch['amount'] = float(amount)
        if phone_m and 'phone_number' not in patch:
            patch['phone_number'] = phone_m.group(0)
        if 'corporate' not in patch and any(x in tlow for x in ('corporate', 'plc', 'ltd')):
            patch['corporate'] = True
        if 'working capital' in tlow or ' wc' in tlow:
            patch.setdefault('reason', 'Working capital')

        if not patch:
            reply = 'Tell me what to change (e.g. “amount to 2,000,000” or “name is Acme PLC”).'
            return _stub_finish(conversation, text, reply, [], user)

        # One-shot create: only if user said create AND we have full fields and "now" etc.
        force_create = any(k in tlow for k in ('create now', 'create immediately', 'bootstrap', 'one shot'))
        out = dispatch_tool(user, 'update_story', {**patch, 'change_note': 'user message'}, conversation)
        tools_audit.append(_tool_audit_entry('update_story', out))
        if not out.get('ok'):
            reply = out.get('error') or 'Could not update story.'
            return _stub_finish(conversation, text, reply, tools_audit, user)
        story = conversation_story(conversation)

        if force_create and out.get('ready_to_commit'):
            cout = dispatch_tool(user, 'commit_story', {}, conversation)
            tools_audit.append(_tool_audit_entry('commit_story', cout))
            if cout.get('ok'):
                reply = f"Created {cout.get('loan_request_code')}. (Immediate create.)"
                return _stub_finish(
                    conversation, text, reply, tools_audit, user,
                    loan_request_id=cout.get('loan_request_id'),
                    loan_request_code=cout.get('loan_request_code'),
                )

        # Production path: hold story, invite confirm
        reply = (
            'Held in draft (edit anytime):\n'
            + story_summary_lines(story)
            + '\n\nSay **confirm** to create the loan file, or correct any field.'
        )
        # Special: "create loan for X" auto-commits for speed unless hold/draft-only
        skip_auto = any(
            k in tlow
            for k in (
                'hold', 'do not create', "don't create", 'draft only',
                'without creating', 'story only', 'not yet',
            )
        )
        if (
            _wants_create_phrase(tlow)
            and out.get('ready_to_commit')
            and not skip_auto
        ):
            # Auto-commit on classic "create loan for" phrasing for speed while story stays auditable
            cout = dispatch_tool(user, 'commit_story', {}, conversation)
            tools_audit.append(_tool_audit_entry('commit_story', cout))
            if cout.get('ok'):
                reply = (
                    f"Story locked and loan created: {cout.get('loan_request_code')}.\n"
                    'Documents and appraisal can proceed; LO owns appraisal sheets unless you seeded a draft.'
                )
                return _stub_finish(
                    conversation, text, reply, tools_audit, user,
                    loan_request_id=cout.get('loan_request_id'),
                    loan_request_code=cout.get('loan_request_code'),
                )
            reply = (cout.get('error') or 'Commit failed.') + '\n' + story_summary_lines(conversation_story(conversation))

        return _stub_finish(conversation, text, reply, tools_audit, user)

    reply = (
        'Try:\n'
        '• BM: “Loan for Acme PLC, 1.5m ETB” then “confirm”\n'
        '• LO: “Document checklist for LOAN-CODE” / “Read appraisal for LOAN-CODE”\n'
        '• “Pipeline report” · “Find loan Acme”\n'
        'Or set OPENAI_API_KEY for full ChatGPT tool-calling.'
    )
    return _stub_finish(conversation, text, reply, [], user)
