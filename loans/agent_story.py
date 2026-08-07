"""Editable loan-file 'story' held on AgentConversation for multi-turn corrections."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone


STORY_FIELDS = (
    'applicant_name',
    'phone_number',
    'amount',
    'reason',
    'corporate',
    'complete_documents',
    'draft_appraisal',
    'customer_number',
    'declared_address',
    'category_hint',
    'notes',
)

STORY_STATUS_DRAFT = 'draft'
STORY_STATUS_READY = 'ready'
STORY_STATUS_COMMITTED = 'committed'


def empty_story() -> Dict[str, Any]:
    return {
        'applicant_name': '',
        'phone_number': '',
        'amount': None,
        'reason': 'Working capital',
        'corporate': False,
        'complete_documents': False,
        'draft_appraisal': False,
        'customer_number': '',
        'declared_address': '',
        'category_hint': '',
        'notes': '',
        'status': STORY_STATUS_DRAFT,
        'revision': 0,
        'history': [],
        'committed_loan_code': '',
        'updated_at': '',
    }


def normalize_story(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = empty_story()
    if not isinstance(raw, dict):
        return base
    for key in STORY_FIELDS:
        if key in raw and raw[key] is not None:
            base[key] = raw[key]
    if raw.get('status') in (STORY_STATUS_DRAFT, STORY_STATUS_READY, STORY_STATUS_COMMITTED):
        base['status'] = raw['status']
    base['revision'] = int(raw.get('revision') or 0)
    hist = raw.get('history')
    base['history'] = list(hist) if isinstance(hist, list) else []
    base['committed_loan_code'] = (raw.get('committed_loan_code') or '')[:64]
    base['updated_at'] = raw.get('updated_at') or ''
    # Coerce amount
    if base.get('amount') is not None and base.get('amount') != '':
        try:
            base['amount'] = float(Decimal(str(base['amount']).replace(',', '')))
        except (InvalidOperation, TypeError, ValueError):
            base['amount'] = None
    base['corporate'] = bool(base.get('corporate'))
    base['complete_documents'] = False  # production agent never manages docs via story
    base['draft_appraisal'] = False
    base['applicant_name'] = str(base.get('applicant_name') or '').strip()
    base['phone_number'] = str(base.get('phone_number') or '').strip()
    base['reason'] = str(base.get('reason') or 'Working capital').strip() or 'Working capital'
    return base


def story_missing_required(story: Dict[str, Any]) -> List[str]:
    miss = []
    if len((story.get('applicant_name') or '').strip()) < 2:
        miss.append('applicant_name')
    amt = story.get('amount')
    try:
        if amt is None or Decimal(str(amt)) <= 0:
            miss.append('amount')
    except (InvalidOperation, TypeError, ValueError):
        miss.append('amount')
    return miss


def story_is_ready(story: Dict[str, Any]) -> bool:
    return not story_missing_required(story)


def story_summary_lines(story: Dict[str, Any]) -> str:
    s = normalize_story(story)
    amt = s.get('amount')
    amt_s = f"{amt:,.0f} ETB" if isinstance(amt, (int, float)) and amt else '—'
    lines = [
        f"Applicant: {s.get('applicant_name') or '—'}",
        f"Amount: {amt_s}",
        f"Phone: {s.get('phone_number') or '—'}",
        f"Purpose: {s.get('reason') or '—'}",
        f"Mode: {'corporate' if s.get('corporate') else 'MSME'}",
        f"Docs via agent: never · Appraisal via agent: never",
    ]
    if s.get('declared_address'):
        lines.append(f"Address: {s['declared_address']}")
    if s.get('customer_number'):
        lines.append(f"Customer #: {s['customer_number']}")
    if s.get('notes'):
        lines.append(f"Notes: {s['notes']}")
    miss = story_missing_required(s)
    status = s.get('status') or STORY_STATUS_DRAFT
    if s.get('committed_loan_code'):
        lines.append(f"Committed loan: {s['committed_loan_code']}")
    elif miss:
        lines.append(f"Still needed: {', '.join(miss)}")
        lines.append('Status: draft (not created yet)')
    else:
        lines.append(f"Status: {status} — say “confirm” to create the loan file")
    return '\n'.join(lines)


def merge_story(
    current: Optional[Dict[str, Any]],
    patch: Dict[str, Any],
    *,
    change_note: str = '',
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Apply patch; return (new_story, list of field changes for history)."""
    story = normalize_story(current)
    changes: List[Dict[str, Any]] = []
    patch = patch or {}

    for key in STORY_FIELDS:
        if key not in patch:
            continue
        new_val = patch[key]
        if key == 'amount' and new_val is not None and new_val != '':
            try:
                new_val = float(Decimal(str(new_val).replace(',', '')))
            except (InvalidOperation, TypeError, ValueError):
                continue
        if key in ('corporate', 'complete_documents', 'draft_appraisal'):
            new_val = bool(new_val)
        if key in ('applicant_name', 'phone_number', 'reason', 'customer_number', 'declared_address', 'category_hint', 'notes'):
            new_val = str(new_val if new_val is not None else '').strip()
        old_val = story.get(key)
        if old_val == new_val:
            continue
        changes.append({'field': key, 'from': old_val, 'to': new_val})
        story[key] = new_val

    now = timezone.now().isoformat()
    if changes:
        story['revision'] = int(story.get('revision') or 0) + 1
        story['updated_at'] = now
        entry = {
            'at': now,
            'note': (change_note or '')[:300],
            'changes': changes,
        }
        hist = list(story.get('history') or [])
        hist.append(entry)
        story['history'] = hist[-30:]  # cap

    if story.get('status') != STORY_STATUS_COMMITTED:
        story['status'] = STORY_STATUS_READY if story_is_ready(story) else STORY_STATUS_DRAFT

    return story, changes


def conversation_story(conversation) -> Dict[str, Any]:
    return normalize_story(getattr(conversation, 'story', None) or {})


def save_story(conversation, story: Dict[str, Any]) -> Dict[str, Any]:
    story = normalize_story(story)
    conversation.story = story
    return story


def mark_committed(story: Dict[str, Any], loan_code: str) -> Dict[str, Any]:
    s = normalize_story(story)
    s['status'] = STORY_STATUS_COMMITTED
    s['committed_loan_code'] = (loan_code or '')[:64]
    s['updated_at'] = timezone.now().isoformat()
    return s


def story_for_api(story: Dict[str, Any]) -> Dict[str, Any]:
    """Compact story for UI/API (no full history dump unless recent)."""
    s = normalize_story(story)
    return {
        'applicant_name': s.get('applicant_name') or '',
        'phone_number': s.get('phone_number') or '',
        'amount': s.get('amount'),
        'reason': s.get('reason') or '',
        'corporate': bool(s.get('corporate')),
        'complete_documents': bool(s.get('complete_documents')),
        'draft_appraisal': bool(s.get('draft_appraisal')),
        'customer_number': s.get('customer_number') or '',
        'declared_address': s.get('declared_address') or '',
        'category_hint': s.get('category_hint') or '',
        'notes': s.get('notes') or '',
        'status': s.get('status'),
        'revision': s.get('revision'),
        'committed_loan_code': s.get('committed_loan_code') or '',
        'missing': story_missing_required(s),
        'summary': story_summary_lines(s),
        'history_tail': (s.get('history') or [])[-5:],
    }
