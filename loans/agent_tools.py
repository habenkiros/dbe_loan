"""Guarded Agentic Assist tools: story, bootstrap, pipeline reporting."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from loans.agent import (
    FORBIDDEN_TOOLS,
    AgentRequest,
    run_bootstrap_pipeline,
    tool_register_collateral,
    user_can_use_agent,
)
from loans.agent_permissions import (
    capabilities_for_user,
    resolve_loan_for_agent,
    user_can_create_loan_via_agent,
    user_can_manage_documents_via_agent,
    user_can_work_appraisal_via_agent,
    user_may_read_appraisal,
    user_may_request_docs_via_agent,
    user_may_write_loan_docs,
)
from loans.agent_story import (
    conversation_story,
    empty_story,
    mark_committed,
    merge_story,
    save_story,
    story_for_api,
    story_is_ready,
    story_missing_required,
    story_summary_lines,
)

TOOL_SPECS: List[Dict[str, Any]] = [
    {
        'type': 'function',
        'function': {
            'name': 'lookup_workspace',
            'description': 'Officer role, branch, category/collateral options, and reporting scope.',
            'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_story',
            'description': (
                'Return the held loan-file draft (story) for this chat. '
                'Always call after updates, or when user asks what is drafted / to correct fields.'
            ),
            'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'update_story',
            'description': (
                'Create or correct the held loan draft WITHOUT creating a loan yet. '
                'Use for partial info and every correction (name, amount, phone, purpose, corporate, address). '
                'Only merge provided fields; leave others unchanged.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'applicant_name': {'type': 'string'},
                    'amount': {'type': 'number', 'description': 'ETB'},
                    'phone_number': {'type': 'string'},
                    'reason': {'type': 'string'},
                    'corporate': {'type': 'boolean'},
                    'customer_number': {'type': 'string'},
                    'declared_address': {'type': 'string'},
                    'category_hint': {'type': 'string'},
                    'notes': {'type': 'string'},
                    'change_note': {
                        'type': 'string',
                        'description': 'Short note about this correction, e.g. user fixed amount',
                    },
                },
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'clear_story',
            'description': 'Reset the held draft story (does not delete existing loans).',
            'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'commit_story',
            'description': (
                'Create ONLY the loan request application from the held story. '
                'Branch managers only. Never documents, appraisal, estimation, queue, or approval. '
                'Does NOT submit committee or disburse.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'force': {
                        'type': 'boolean',
                        'description': 'Allow commit even if status is draft when required fields present',
                    },
                },
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'bootstrap_loan',
            'description': (
                'Create a loan immediately (branch manager only). Prefer update_story + commit_story. '
                'Loan officers and admin must not call this.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'applicant_name': {'type': 'string'},
                    'amount': {'type': 'number'},
                    'phone_number': {'type': 'string'},
                    'reason': {'type': 'string'},
                    'corporate': {'type': 'boolean'},
                    'customer_number': {'type': 'string'},
                    'declared_address': {'type': 'string'},
                    'category_hint': {'type': 'string'},
                },
                'required': ['applicant_name', 'amount'],
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'pipeline_report',
            'description': (
                'Generate a scoped pipeline report summary (counts, amounts, committee/disbursement) '
                'within the officer permission scope. Optionally filter by status/dates. '
                'Returns KPIs, sample loans, and Excel export URL.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'status': {
                        'type': 'string',
                        'description': 'Pending | Approved | Rejected or empty for all',
                    },
                    'committee_status': {'type': 'string'},
                    'disbursement_status': {'type': 'string'},
                    'date_from': {'type': 'string', 'description': 'YYYY-MM-DD'},
                    'date_to': {'type': 'string', 'description': 'YYYY-MM-DD'},
                    'limit_sample': {'type': 'integer', 'description': 'Sample rows (default 8, max 15)'},
                },
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'find_loans',
            'description': 'Search loans in reporting scope by applicant name or loan code.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'limit': {'type': 'integer'},
                },
                'required': ['query'],
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'document_checklist',
            'description': (
                'List required application document types for a loan and their upload/verification status. '
                'Use for BM/LO when preparing or reviewing docs. Provide loan_code or use the linked file.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'loan_code': {'type': 'string'},
                    'loan_id': {'type': 'integer'},
                },
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'file_blockers',
            'description': (
                'Diagnose what is blocking a loan file right now: missing/unverified docs, incomplete appraisal, '
                'collateral field work, committee wait, or post-approval/disbursement gaps. '
                'Also returns a draft missing-document request message (does not send it) and agreement guidance '
                '(does not generate or sign agreements). Use when the user asks "what\'s blocking this file?".'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'loan_code': {'type': 'string'},
                    'loan_id': {'type': 'integer'},
                },
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'register_collateral',
            'description': (
                'Register a collateral SHELL for a loan (building, land, or other/vehicle). '
                'No estimation, BOQ, unit prices, or valuation values. Loan officer / BM only. '
                'Forbidden: valuing, approving, or estimating.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'loan_code': {'type': 'string'},
                    'loan_id': {'type': 'integer'},
                    'kind': {
                        'type': 'string',
                        'description': 'building | land | other (or vehicle/machinery/equipment)',
                    },
                    'label': {
                        'type': 'string',
                        'description': 'Name/label e.g. Main house, or Toyota Hilux',
                    },
                    'notes': {'type': 'string'},
                },
                'required': ['kind'],
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'read_appraisal',
            'description': (
                'Deep-read appraisal for a loan: all 7 sheet completeness, field snapshot, '
                'scorecard-style analysis assist, blocks/warnings, field coaching tips. '
                'Primary tool for loan officers. Explains how sheets relate (capacity vs ask, '
                'character, DSCR, ES, collateral, decision). Does not auto-approve or submit.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'loan_code': {'type': 'string'},
                    'loan_id': {'type': 'integer'},
                    'focus_sheet': {
                        'type': 'integer',
                        'description': 'Optional 1-7 to emphasize that sheet in the coaching reply',
                    },
                },
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'committee_brief',
            'description': (
                'Read-only committee voter brief for a loan: amount band / current level, '
                'decision-card summary, docs/KYC/CRM/SLA chips, peer vote counts, open compliance cases. '
                'Use when a branch manager or officer asks what voters should know before voting. '
                'Never casts, changes, or submits committee votes — humans vote only in the UI.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'loan_code': {'type': 'string'},
                    'loan_id': {'type': 'integer'},
                },
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'read_kyc',
            'description': (
                'Read-only KYC / identity case for a loan: band, score, parties, Fayda/TIN verify, '
                'face/liveness, UBO gap. Use when the officer asks if the customer is verified. '
                'Does not call Fayda, store biometrics, or freeze the file.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'loan_code': {'type': 'string'},
                    'loan_id': {'type': 'integer'},
                },
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'request_documents',
            'description': (
                'Request missing checklist documents for a loan (same as the loan-detail Request button). '
                'Does NOT attach or verify files. First call with confirm=false to preview names. '
                'Send only when the officer explicitly confirms (confirm=true).'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'loan_code': {'type': 'string'},
                    'loan_id': {'type': 'integer'},
                    'confirm': {
                        'type': 'boolean',
                        'description': 'false = preview only; true = record requests and notify branch',
                    },
                    'document_type_ids': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'Optional type ids. Empty = all missing required types.',
                    },
                },
                'additionalProperties': False,
            },
        },
    },
]


def _resolve_category_id(hint: Optional[str], corporate: bool) -> Optional[int]:
    from loans.models import LoanCategory

    if hint:
        hit = LoanCategory.objects.filter(name__icontains=hint.strip()).order_by('id').first()
        if hit:
            return hit.pk
    if corporate:
        hit = LoanCategory.objects.filter(name__icontains='Corporate').order_by('id').first()
        return hit.pk if hit else None
    return None


def _tool_lookup_workspace(user) -> Dict[str, Any]:
    from loans.models import CollateralType, LoanCategory
    from loans.reporting import report_scope_label, user_can_access_reports

    branch = getattr(user, 'branch', None)
    cats = list(LoanCategory.objects.order_by('name').values_list('id', 'name')[:25])
    colls = list(CollateralType.objects.order_by('name').values_list('id', 'name')[:25])
    caps = capabilities_for_user(user)
    return {
        'ok': True,
        'username': user.get_username(),
        'role': getattr(user, 'role', None),
        'branch_id': branch.pk if branch else None,
        'branch_name': branch.name if branch else None,
        'categories': [{'id': i, 'name': n} for i, n in cats],
        'collateral_types': [{'id': i, 'name': n} for i, n in colls],
        'report_scope': report_scope_label(user) if user_can_access_reports(user) else 'n/a',
        'can_report': user_can_access_reports(user),
        'capabilities': caps,
        'limits': {
            'may_create_loan': user_can_create_loan_via_agent(user),
            'may_manage_documents': user_can_manage_documents_via_agent(user),
            'may_work_appraisal': user_can_work_appraisal_via_agent(user),
            'forbidden_actions': sorted(FORBIDDEN_TOOLS),
            'role_policy': {
                'create_loan': 'branch_manager only (not admin, not LO)',
                'documents': 'branch_manager, loan_officer (assigned), credit_loan_officer',
                'appraisal_read': 'loan_officer (assigned), BM branch, credit_loan_officer',
            },
        },
    }


def _tool_get_story(conversation) -> Dict[str, Any]:
    story = conversation_story(conversation)
    return {'ok': True, 'story': story_for_api(story), 'summary': story_summary_lines(story)}


def _tool_update_story(user, conversation, args: Dict[str, Any]) -> Dict[str, Any]:
    if not user_can_create_loan_via_agent(user):
        return {
            'ok': False,
            'error': (
                'Loan officers cannot create or hold a create-loan story. '
                'Ask your branch manager to open the request, then use document_checklist / read_appraisal.'
            ),
            'capabilities': capabilities_for_user(user),
        }
    args = dict(args or {})
    change_note = (args.pop('change_note', None) or '')[:300]
    # Only allow known fields
    patch = {k: args[k] for k in args if k in (
        'applicant_name', 'amount', 'phone_number', 'reason', 'corporate',
        'complete_documents', 'draft_appraisal', 'customer_number',
        'declared_address', 'category_hint', 'notes',
    )}
    if not patch:
        return {'ok': False, 'error': 'No story fields provided to update.'}
    # Production: never create docs/appraisal via story
    patch['complete_documents'] = False
    patch['draft_appraisal'] = False
    story, changes = merge_story(conversation_story(conversation), patch, change_note=change_note)
    save_story(conversation, story)
    return {
        'ok': True,
        'changed_fields': [c['field'] for c in changes],
        'story': story_for_api(story),
        'summary': story_summary_lines(story),
        'ready_to_commit': story_is_ready(story),
        'missing': story_missing_required(story),
        'hint': (
            'Story updated. Restate the summary. Confirm creates the loan (BM only). '
            'LO will then own documents + appraisal unless you seeded a draft appraisal.'
            if story_is_ready(story)
            else 'Story incomplete — ask for: ' + ', '.join(story_missing_required(story))
        ),
    }


def _tool_clear_story(user, conversation) -> Dict[str, Any]:
    if not user_can_create_loan_via_agent(user):
        return {'ok': False, 'error': 'Only branch managers manage the create-loan story.'}
    save_story(conversation, empty_story())
    return {'ok': True, 'story': story_for_api(empty_story()), 'detail': 'Story cleared.'}


def _bootstrap_from_fields(user, fields: Dict[str, Any], conversation) -> Dict[str, Any]:
    if not user_can_create_loan_via_agent(user):
        return {
            'ok': False,
            'error': (
                'Only branch managers can create loan requests. '
                'As a loan officer or admin, use register_collateral (shell only), document_checklist (read-only), read_appraisal (coach only) '
                'on loans in your scope (or ask a BM to open a new file).'
            ),
            'capabilities': capabilities_for_user(user),
        }
    name = (fields.get('applicant_name') or '').strip()
    try:
        amount = Decimal(str(fields.get('amount')).replace(',', ''))
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        return {'ok': False, 'error': 'Invalid amount'}
    if len(name) < 2:
        return {'ok': False, 'error': 'Applicant name required'}
    if amount <= 0:
        return {'ok': False, 'error': 'Amount must be positive'}

    corporate = bool(fields.get('corporate', False))
    # PRODUCTION hard block: bare application only
    complete_documents = False
    draft_appraisal = False
    reason = (fields.get('reason') or 'Working capital').strip() or 'Working capital'
    phone = (fields.get('phone_number') or '0911000000').strip()
    cat_id = _resolve_category_id(fields.get('category_hint'), corporate)

    # BM assigns a branch LO if provided via story notes only; officer optional
    assign_officer_id = None
    if fields.get('assign_officer_id'):
        try:
            assign_officer_id = int(fields['assign_officer_id'])
        except (TypeError, ValueError):
            assign_officer_id = None

    req = AgentRequest(
        applicant_name=name,
        phone_number=phone,
        amount=amount,
        reason=reason,
        category_id=cat_id,
        branch_id=getattr(user, 'branch_id', None),
        assign_officer_id=assign_officer_id,
        corporate=corporate,
        complete_documents=complete_documents,
        draft_appraisal=draft_appraisal,
        queue_approved=False,
        customer_number=(fields.get('customer_number') or '')[:50],
        declared_address=(fields.get('declared_address') or '')[:2000],
        intent_text=f'agent story commit: {name}',
    )
    out = run_bootstrap_pipeline(user, req)
    if out.get('run_id') and conversation and conversation.pk:
        from loans.models import AgentRun
        AgentRun.objects.filter(pk=out['run_id']).update(conversation_id=conversation.pk)

    loan_id = out.get('loan_request_id')
    code = out.get('loan_request_code')
    links = {}
    if loan_id:
        try:
            links = {
                'detail_url': reverse('loan_request_detail', args=[loan_id]),
                'documents_url': reverse('upload_loan_request_documents', args=[loan_id]),
                'appraisal_url': reverse('loan_appraisal_edit', args=[loan_id]),
            }
        except Exception:
            links = {}
        if conversation:
            try:
                conversation.last_loan_request_id = loan_id
                conversation.title = (code or name)[:200]
            except Exception:
                pass
            story = mark_committed(conversation_story(conversation), code or '')
            for k in (
                'applicant_name', 'amount', 'phone_number', 'reason', 'corporate',
                'complete_documents', 'draft_appraisal', 'customer_number',
                'declared_address', 'category_hint',
            ):
                if fields.get(k) is not None and k not in ('amount',):
                    story[k] = fields.get(k)
            if fields.get('amount') is not None:
                try:
                    story['amount'] = float(amount)
                except Exception:
                    pass
            story['draft_appraisal'] = draft_appraisal
            story['complete_documents'] = complete_documents
            save_story(conversation, story)
    out = {
        **out,
        'links': links,
        'loan_request_code': code,
        'story': story_for_api(conversation_story(conversation)),
        'next_for_loan_officer': [
            'Upload documents only in the UI (not Assist).',
            'Register collateral shells via register_collateral (no estimation).',
            'Appraisal, estimation, approvals only in the product UI — illegal via Assist.',
        ],
    }
    return out


def _tool_commit_story(user, conversation, args: Dict[str, Any]) -> Dict[str, Any]:
    if not user_can_create_loan_via_agent(user):
        return {
            'ok': False,
            'error': 'Only branch managers can confirm/create loan requests (not admin).',
            'capabilities': capabilities_for_user(user),
        }
    story = conversation_story(conversation)
    miss = story_missing_required(story)
    if miss:
        return {
            'ok': False,
            'error': f'Story incomplete: {", ".join(miss)}',
            'story': story_for_api(story),
            'missing': miss,
        }
    if story.get('status') == 'committed' and story.get('committed_loan_code') and not args.get('force'):
        return {
            'ok': False,
            'error': (
                f"Story already committed as {story.get('committed_loan_code')}. "
                'Clear story or start a new draft for another loan.'
            ),
            'story': story_for_api(story),
        }
    return _bootstrap_from_fields(user, story, conversation)


def _tool_bootstrap_loan(user, args: Dict[str, Any], conversation) -> Dict[str, Any]:
    if not user_can_create_loan_via_agent(user):
        return {
            'ok': False,
            'error': 'Only branch managers can create loans via Assist (not admin).',
            'capabilities': capabilities_for_user(user),
        }
    if conversation is not None:
        merge_patch = {k: args[k] for k in (args or {}) if k in (
            'applicant_name', 'amount', 'phone_number', 'reason', 'corporate',
            'complete_documents', 'draft_appraisal', 'customer_number',
            'declared_address', 'category_hint',
        )}
        story, _ = merge_story(conversation_story(conversation), merge_patch, change_note='bootstrap')
        save_story(conversation, story)
    return _bootstrap_from_fields(user, args or {}, conversation)


def _tool_document_checklist(user, args: Dict[str, Any], conversation) -> Dict[str, Any]:
    if not user_can_use_agent(user):
        return {'ok': False, 'error': 'Not allowed to read documents.'}
    loan, err = resolve_loan_for_agent(
        user,
        loan_code=args.get('loan_code') or '',
        loan_pk=args.get('loan_id'),
        conversation=conversation,
    )
    if err:
        return {'ok': False, 'error': err}
    from loans.document_checklist import checklist_for_loan, required_items
    from loans.models import LoanApplicationDocumentType, LoanRequestDocument

    checklist = checklist_for_loan(loan)
    types = list(required_items(checklist))
    audit = LoanApplicationDocumentType.objects.filter(name__icontains='audit').first()
    if audit and all(i.id != audit.id for i in types):
        for item in checklist:
            if item.id == audit.id:
                types.append(item)
                break
    items = []
    missing_real = []
    for item in types:
        dt = item.document_type
        doc = loan.application_documents.filter(document_type=dt).order_by('-id').first()
        status = 'missing'
        note = ''
        if doc:
            status = doc.auth_status or 'uploaded'
            note = (doc.auth_notes or '')[:120]
            if doc.auth_status != LoanRequestDocument.AUTH_VERIFIED:
                missing_real.append(dt.name)
        else:
            missing_real.append(dt.name)
        items.append({
            'document_type_id': dt.id,
            'document_type': dt.name,
            'required': bool(item.is_required),
            'status': status,
            'filename': doc.get_display_filename() if doc else '',
            'notes': note,
        })
    try:
        upload_url = reverse('upload_loan_request_documents', args=[loan.pk])
        detail_url = reverse('loan_request_detail', args=[loan.pk])
    except Exception:
        upload_url = detail_url = ''
    return {
        'ok': True,
        'loan_request_code': loan.loan_request_id,
        'loan_request_id': loan.pk,
        'applicant_name': loan.applicant_name,
        'documents': items,
        'missing_or_unverified': missing_real,
        'can_write': user_may_write_loan_docs(user, loan),
        'links': {
            'upload_url': upload_url,
            'detail_url': detail_url,
        },
        'guidance': (
            'Read-only checklist. Direct officer to upload_url for real PDFs. '
            'Never attach documents via Assist. No approvals.'
        ),
    }


def _tool_file_blockers(user, args: Dict[str, Any], conversation) -> Dict[str, Any]:
    loan, err = resolve_loan_for_agent(
        user,
        loan_code=args.get('loan_code') or '',
        loan_pk=args.get('loan_id'),
        conversation=conversation,
    )
    if err:
        return {'ok': False, 'error': err}
    from loans.file_blockers import build_file_blockers

    out = build_file_blockers(loan)
    out['ok'] = True
    if conversation:
        conversation.last_loan_request_id = loan.pk
    return out


def _tool_attach_demo_documents(user, args: Dict[str, Any], conversation) -> Dict[str, Any]:
    return {
        'ok': False,
        'error': (
            'Illegal for Assist in production: cannot attach or verify documents. '
            'Use the Documents upload page. Officers may only register collateral shells (no estimation).'
        ),
    }


def _tool_register_collateral(user, args: Dict[str, Any], conversation) -> Dict[str, Any]:
    loan, err = resolve_loan_for_agent(
        user,
        loan_code=args.get('loan_code') or '',
        loan_pk=args.get('loan_id'),
        conversation=conversation,
    )
    if err:
        return {'ok': False, 'error': err}
    res = tool_register_collateral(
        user,
        loan,
        kind=args.get('kind') or '',
        label=args.get('label') or '',
        notes=args.get('notes') or '',
    )
    out = res.as_dict()
    out['ok'] = res.ok
    if res.ok and conversation:
        conversation.last_loan_request_id = loan.pk
    try:
        out['links'] = {
            'detail_url': reverse('loan_request_detail', args=[loan.pk]),
            'collateral_url': reverse('collateral:dashboard'),
        }
    except Exception:
        out['links'] = {}
    return out


def _project_overlay_brief(loan) -> Optional[Dict[str, Any]]:
    from loans.engines import get_engine
    return get_engine(loan).assist_brief()


def _tool_read_appraisal(user, args: Dict[str, Any], conversation) -> Dict[str, Any]:
    if not user_can_work_appraisal_via_agent(user):
        return {'ok': False, 'error': 'Not allowed to work appraisal via Assist.'}
    loan, err = resolve_loan_for_agent(
        user,
        loan_code=args.get('loan_code') or '',
        loan_pk=args.get('loan_id'),
        conversation=conversation,
    )
    if err:
        return {'ok': False, 'error': err}
    if not user_may_read_appraisal(user, loan):
        return {'ok': False, 'error': 'No appraisal access for this loan.'}

    from loans.analysis_assist import build_analysis_assist, officer_checklist_for_mode
    from loans.appraisal_mode import mode_label, resolve_appraisal_mode
    from loans.models import LoanAppraisal, LoanRequestBasicInfo
    from loans.sheet_requirements import (
        build_appraisal_ai_snapshot,
        get_appraisal_sheet_status,
        sheets_blocking_completion,
    )

    appraisal, _ = LoanAppraisal.objects.get_or_create(loan_request=loan)
    basic, _ = LoanRequestBasicInfo.objects.get_or_create(loan_request=loan)

    # Snapshot (fix purpose key if model uses reason)
    try:
        snapshot = build_appraisal_ai_snapshot(loan, appraisal, basic)
    except Exception as exc:
        sheet_status = get_appraisal_sheet_status(loan, appraisal, basic)
        snapshot = {
            'loan_request_id': loan.loan_request_id,
            'sheets': sheet_status,
            'blocking_gaps': sheets_blocking_completion(sheet_status),
            'snapshot_error': str(exc),
            'sheet_1_basic': {
                'applicant_name': loan.applicant_name,
                'amount_requested': str(loan.amount_requested),
                'purpose': getattr(loan, 'reason', None),
                'business_name': basic.business_name,
                'economic_sector': basic.economic_sector,
                'term_months': basic.term_months,
                'repayment_frequency': basic.repayment_frequency,
                'interest_rate': str(basic.interest_rate) if basic.interest_rate else None,
            },
        }
    # Ensure purpose from reason if blank
    s1 = snapshot.get('sheet_1_basic') or {}
    if not s1.get('purpose'):
        s1['purpose'] = loan.reason
        snapshot['sheet_1_basic'] = s1

    assist = build_analysis_assist(appraisal, basic)
    mode = resolve_appraisal_mode(loan, appraisal)
    focus = args.get('focus_sheet')
    focus_detail = None
    sheets = snapshot.get('sheets') or {}
    if focus is not None:
        try:
            focus = int(focus)
            focus_detail = sheets.get(focus) or sheets.get(str(focus))
        except (TypeError, ValueError):
            focus = None

    coaching = []
    for gap in (snapshot.get('blocking_gaps') or [])[:8]:
        coaching.append({'type': 'gap', 'detail': gap})
    for ins in (assist.get('insights') or [])[:6]:
        coaching.append({
            'type': 'insight',
            'severity': ins.get('severity'),
            'title': ins.get('title'),
            'detail': ins.get('detail'),
            'sheet': ins.get('sheet'),
        })

    try:
        appraisal_url = reverse('loan_appraisal_edit', args=[loan.pk])
        step_url = reverse('loan_appraisal_step', args=[loan.pk, focus or 1])
    except Exception:
        appraisal_url = step_url = ''

    if conversation:
        conversation.last_loan_request_id = loan.pk

    # Truncate snapshot sizes for LLM
    sheets_brief = {}
    for k, v in (sheets or {}).items():
        if isinstance(v, dict):
            sheets_brief[str(k)] = {
                'title': v.get('title'),
                'complete': v.get('complete'),
                'missing': (v.get('missing') or [])[:12],
            }
        else:
            sheets_brief[str(k)] = v

    _engine_brief = _project_overlay_brief(loan)
    from loans.rehab import postbook_brief
    desk_compact = {}
    try:
        from loans.product_intel import compact_product_desk
        desk_compact = compact_product_desk(loan) or {}
    except Exception:
        desk_compact = {}

    return {
        'ok': True,
        'loan_request_code': loan.loan_request_id,
        'loan_request_id': loan.pk,
        'applicant_name': loan.applicant_name,
        'amount_requested': float(loan.amount_requested or 0),
        'appraisal_mode': mode,
        'mode_label': mode_label(mode),
        'product_family': getattr(getattr(loan, 'category', None), 'product_family', 'general'),
        'product_family_label': (
            loan.category.get_product_family_display() if getattr(loan, 'category_id', None) else ''
        ),
        'engine': _engine_brief,
        'project_overlay': _engine_brief,
        'product_desk': desk_compact,
        'postbook': postbook_brief(loan),
        'officer_checklist': officer_checklist_for_mode(mode),
        'analysis_assist': {
            'score_total': assist.get('score_total'),
            'score_band': assist.get('score_band'),
            'blocks': assist.get('blocks'),
            'warnings': assist.get('warnings'),
            'insights': assist.get('insights'),
        },
        'sheets_completeness': sheets_brief,
        'blocking_gaps': snapshot.get('blocking_gaps') or [],
        'field_snapshot': {
            'sheet_1_basic': snapshot.get('sheet_1_basic'),
            'sheet_2_credit_character': snapshot.get('sheet_2_credit_character'),
            'sheet_3_cashflow': snapshot.get('sheet_3_cashflow'),
            'sheet_4_es': snapshot.get('sheet_4_es'),
            'sheet_5_collateral': snapshot.get('sheet_5_collateral'),
            'sheet_6_decision': snapshot.get('sheet_6_decision'),
            'sheet_7_amortization': snapshot.get('sheet_7_amortization'),
        },
        'focus_sheet': focus,
        'focus_sheet_detail': focus_detail,
        'coaching': coaching,
        'links': {
            'appraisal_url': appraisal_url,
            'appraisal_step_url': step_url,
            'detail_url': reverse('loan_request_detail', args=[loan.pk]),
            'documents_url': reverse('upload_loan_request_documents', args=[loan.pk]),
        },
        'guidance': (
            'READ ONLY coach: explain gaps and field meaning. Never write appraisal values, '
            'never estimate collateral, never approve. Officer edits sheets only in the UI.'
        ),
    }


def _tool_read_kyc(user, args: Dict[str, Any], conversation) -> Dict[str, Any]:
    loan, err = resolve_loan_for_agent(
        user,
        loan_code=args.get('loan_code') or '',
        loan_pk=args.get('loan_id'),
        conversation=conversation,
    )
    if err:
        return {'ok': False, 'error': err}
    from loans.kyc_identity import case_payload, get_identity_case, identity_committee_blockers

    if conversation:
        conversation.last_loan_request_id = loan.pk
    try:
        detail_url = reverse('loan_request_detail', args=[loan.pk])
    except Exception:
        detail_url = ''
    case = get_identity_case(loan_request=loan)
    if case is None:
        return {
            'ok': True,
            'present': False,
            'loan_request_code': loan.loan_request_id,
            'loan_request_id': loan.pk,
            'applicant_name': loan.applicant_name,
            'message': 'No identity case on this file yet. Open the loan and complete the KYC band.',
            'links': {'detail_url': detail_url},
            'guidance': 'READ ONLY. Assist does not call Fayda or capture biometrics.',
        }
    payload = case_payload(loan) or {}
    blockers = []
    try:
        blockers = identity_committee_blockers(loan) or []
    except Exception:
        blockers = payload.get('blockers') or []
    applicant = next(
        (p for p in (payload.get('parties') or []) if p.get('role_key') == 'applicant'),
        None,
    )
    return {
        'ok': True,
        'present': True,
        'loan_request_code': loan.loan_request_id,
        'loan_request_id': loan.pk,
        'applicant_name': loan.applicant_name,
        'band': payload.get('band'),
        'band_label': payload.get('band_label'),
        'score': payload.get('score'),
        'needs_ubo': payload.get('needs_ubo'),
        'applicant': applicant,
        'parties': payload.get('parties') or [],
        'blockers': blockers,
        'biometric': payload.get('biometric') or {},
        'links': {'detail_url': detail_url},
        'guidance': (
            'READ ONLY identity snapshot. Do not invent Fayda/TIN results. '
            'Officer verifies in the KYC band on the loan page.'
        ),
    }


def _tool_request_documents(user, args: Dict[str, Any], conversation) -> Dict[str, Any]:
    loan, err = resolve_loan_for_agent(
        user,
        loan_code=args.get('loan_code') or '',
        loan_pk=args.get('loan_id'),
        conversation=conversation,
    )
    if err:
        return {'ok': False, 'error': err}
    if not user_may_request_docs_via_agent(user, loan):
        return {
            'ok': False,
            'error': (
                'Only the assigned loan officer (or covering delegate) can send a document request. '
                'Assist will not attach or verify files.'
            ),
        }
    from django.utils import timezone
    from loans.document_checklist import checklist_for_loan, checklist_type_ids
    from loans.models import LoanApplicationDocumentType, LoanDocumentRequest, LoanRequestDocument
    from loans.services.document_notifications import notify_document_requested

    checklist = checklist_for_loan(loan)
    allowed_ids = set(checklist_type_ids(checklist))
    wanted_ids = args.get('document_type_ids') or []
    parsed_ids: List[int] = []
    for raw in wanted_ids:
        try:
            parsed_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not parsed_ids:
        for item in checklist:
            if not item.is_required:
                continue
            dt = item.document_type
            doc = loan.application_documents.filter(document_type=dt).order_by('-id').first()
            if doc is None or doc.auth_status != LoanRequestDocument.AUTH_VERIFIED:
                parsed_ids.append(dt.id)
    parsed_ids = [i for i in parsed_ids if i in allowed_ids]
    types = list(LoanApplicationDocumentType.objects.filter(pk__in=parsed_ids))
    names = [dt.name for dt in types]
    try:
        upload_url = reverse('upload_loan_request_documents', args=[loan.pk])
        detail_url = reverse('loan_request_detail', args=[loan.pk])
    except Exception:
        upload_url = detail_url = ''
    preview = {
        'ok': True,
        'sent': False,
        'needs_confirm': True,
        'loan_request_code': loan.loan_request_id,
        'loan_request_id': loan.pk,
        'applicant_name': loan.applicant_name,
        'document_type_ids': [dt.id for dt in types],
        'document_names': names,
        'links': {'upload_url': upload_url, 'detail_url': detail_url},
        'guidance': (
            'Preview only. Call again with confirm=true after the officer says to send. '
            'Does not attach files.'
        ),
    }
    if not types:
        preview['ok'] = False
        preview['error'] = 'No missing checklist documents to request.'
        preview['needs_confirm'] = False
        return preview
    if not args.get('confirm'):
        return preview

    recorded = []
    for dt in types:
        LoanDocumentRequest.objects.update_or_create(
            loan_request=loan,
            document_type=dt,
            defaults={'requested_by': user, 'requested_at': timezone.now()},
        )
        recorded.append(dt)
    notify_document_requested(loan, recorded, user)
    if conversation:
        conversation.last_loan_request_id = loan.pk
    return {
        'ok': True,
        'sent': True,
        'needs_confirm': False,
        'loan_request_code': loan.loan_request_id,
        'loan_request_id': loan.pk,
        'applicant_name': loan.applicant_name,
        'document_names': [dt.name for dt in recorded],
        'notified': True,
        'links': {'upload_url': upload_url, 'detail_url': detail_url},
        'guidance': (
            'Request recorded and branch notified. Officers still upload real files on the Documents page. '
            'Assist did not attach or verify anything.'
        ),
    }


def _tool_committee_brief(user, args: Dict[str, Any], conversation) -> Dict[str, Any]:
    from loans.agent_permissions import user_may_read_appraisal
    from loans.committee import user_can_view_committee_loan
    from loans.committee_brief import brief_for_agent

    loan, err = resolve_loan_for_agent(
        user,
        loan_code=args.get('loan_code') or '',
        loan_pk=args.get('loan_id'),
        conversation=conversation,
    )
    if err:
        return {'ok': False, 'error': err}

    allowed = (
        getattr(user, 'is_superuser', False)
        or getattr(user, 'role', None) in ('superadmin', 'admin')
        or user_can_view_committee_loan(user, loan)
        or user_may_read_appraisal(user, loan)
    )
    if not allowed:
        return {'ok': False, 'error': 'No committee brief access for this loan.'}

    if conversation:
        conversation.last_loan_request_id = loan.pk

    payload = brief_for_agent(loan, user=user)
    payload['ok'] = True
    return payload


def _report_params(args: Dict[str, Any]) -> Dict[str, str]:
    params: Dict[str, str] = {}
    for key in ('status', 'committee_status', 'disbursement_status', 'date_from', 'date_to', 'branch_id', 'district_id'):
        val = (args or {}).get(key)
        if val is not None and str(val).strip():
            params[key] = str(val).strip()
    return params


def _tool_pipeline_report(user, args: Dict[str, Any]) -> Dict[str, Any]:
    from loans.reporting import (
        branch_dashboard_stats,
        filtered_reporting_queryset,
        report_scope_label,
        user_can_access_reports,
    )

    if not user_can_access_reports(user):
        return {'ok': False, 'error': 'You do not have report access.'}

    params = _report_params(args or {})
    qs = filtered_reporting_queryset(user, params)
    stats = branch_dashboard_stats(qs)
    # JSON-safe stats
    safe_stats = {
        'total': stats.get('total'),
        'pending': stats.get('pending'),
        'approved': stats.get('approved'),
        'rejected': stats.get('rejected'),
        'committee_pending': stats.get('committee_pending'),
        'committee_approved': stats.get('committee_approved'),
        'awaiting_disbursement': stats.get('awaiting_disbursement'),
        'disbursed': stats.get('disbursed'),
        'amount_requested': float(stats.get('amount_requested') or 0),
        'final_approved_amount': float(stats.get('final_approved_amount') or 0),
        'approval_rate': stats.get('approval_rate'),
        'avg_credit_score': stats.get('avg_credit_score'),
        'weak_band_count': stats.get('weak_band_count'),
        'weak_band_share': stats.get('weak_band_share'),
    }
    limit = max(1, min(int((args or {}).get('limit_sample') or 8), 15))
    sample = []
    for lr in qs[:limit]:
        sample.append({
            'loan_request_id': lr.loan_request_id,
            'applicant_name': lr.applicant_name,
            'amount_requested': float(lr.amount_requested or 0),
            'status': lr.status,
            'committee_status': lr.committee_status or '',
            'disbursement_status': lr.disbursement_status or '',
            'branch': lr.branch.name if lr.branch_id else '',
            'date_requested': lr.date_requested.isoformat() if lr.date_requested else '',
        })
    q = urlencode(params)
    try:
        export_url = reverse('generate_report') + (f'?{q}' if q else '')
        view_url = reverse('view_report') + (f'?{q}' if q else '')
        dash_url = reverse('branch_report_dashboard')
        options_url = reverse('view_report_options')
    except Exception:
        export_url = view_url = dash_url = options_url = ''

    narrative = (
        f"Scope: {report_scope_label(user)}. "
        f"{safe_stats['total']} loans · requested ETB {safe_stats['amount_requested']:,.0f} · "
        f"pending {safe_stats['pending']} · committee-pending {safe_stats['committee_pending']} · "
        f"disbursed {safe_stats['disbursed']}."
    )
    return {
        'ok': True,
        'narrative': narrative,
        'scope': report_scope_label(user),
        'filters': params,
        'stats': safe_stats,
        'sample': sample,
        'generated_at': timezone.now().isoformat(),
        'links': {
            'excel_export_url': export_url,
            'pipeline_view_url': view_url,
            'dashboard_url': dash_url,
            'report_hub_url': options_url,
        },
        'guidance': (
            'Summarise stats in plain language. Offer the Excel export link. '
            'Do not invent loans outside sample/stats.'
        ),
    }


def _tool_find_loans(user, args: Dict[str, Any]) -> Dict[str, Any]:
    from loans.reporting import filtered_reporting_queryset, user_can_access_reports

    if not user_can_access_reports(user) and not user_can_use_agent(user):
        return {'ok': False, 'error': 'Not allowed.'}
    query = (args.get('query') or '').strip()
    if len(query) < 2:
        return {'ok': False, 'error': 'Query too short'}
    limit = max(1, min(int(args.get('limit') or 10), 20))
    qs = filtered_reporting_queryset(user, {}) if user_can_access_reports(user) else (
        __import__('loans.models', fromlist=['LoanRequest']).LoanRequest.objects.none()
    )
    # LO without full report may still see assigned via reporting_base
    if not user_can_access_reports(user):
        from loans.reporting import reporting_base_queryset
        qs = reporting_base_queryset(user)

    qs = qs.filter(
        Q(applicant_name__icontains=query) | Q(loan_request_id__icontains=query)
    )[:limit]
    rows = []
    for lr in qs:
        rows.append({
            'loan_request_id': lr.loan_request_id,
            'pk': lr.pk,
            'applicant_name': lr.applicant_name,
            'amount': float(lr.amount_requested or 0),
            'status': lr.status,
            'detail_url': reverse('loan_request_detail', args=[lr.pk]),
        })
    return {'ok': True, 'count': len(rows), 'loans': rows, 'query': query}


def dispatch_tool(user, name: str, arguments: Dict[str, Any], conversation=None) -> Dict[str, Any]:
    if name in FORBIDDEN_TOOLS:
        return {'ok': False, 'error': f'Tool {name} is forbidden.'}
    if not user_can_use_agent(user):
        return {'ok': False, 'error': 'Permission denied'}
    args = arguments or {}
    if name == 'lookup_workspace':
        return _tool_lookup_workspace(user)
    if name == 'get_story':
        return _tool_get_story(conversation)
    if name == 'update_story':
        return _tool_update_story(user, conversation, args)
    if name == 'clear_story':
        return _tool_clear_story(user, conversation)
    if name == 'commit_story':
        return _tool_commit_story(user, conversation, args)
    if name == 'bootstrap_loan':
        return _tool_bootstrap_loan(user, args, conversation)
    if name == 'document_checklist':
        return _tool_document_checklist(user, args, conversation)
    if name == 'file_blockers':
        return _tool_file_blockers(user, args, conversation)
    if name == 'attach_demo_documents':
        return _tool_attach_demo_documents(user, args, conversation)
    if name == 'register_collateral':
        return _tool_register_collateral(user, args, conversation)
    if name == 'complete_documents' or name == 'draft_appraisal':
        return {'ok': False, 'error': f'Tool {name} is illegal for Assist in production.'}
    if name == 'read_appraisal':
        return _tool_read_appraisal(user, args, conversation)
    if name == 'read_kyc':
        return _tool_read_kyc(user, args, conversation)
    if name == 'request_documents':
        return _tool_request_documents(user, args, conversation)
    if name == 'committee_brief':
        return _tool_committee_brief(user, args, conversation)
    if name == 'pipeline_report':
        return _tool_pipeline_report(user, args)
    if name == 'find_loans':
        return _tool_find_loans(user, args)
    return {'ok': False, 'error': f'Unknown tool: {name}'}
