"""Agentic Assist console + chatbot API views."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from loans.agent import AgentRequest, run_bootstrap_pipeline, user_can_use_agent
from loans.agent_chat import resolve_llm_provider, run_chat_turn
from loans.models import (
    AgentConversation,
    AgentRun,
    Branch,
    CollateralType,
    LoanCategory,
)


User = get_user_model()


def _agent_access(user):
    return user_can_use_agent(user)


def _llm_status():
    provider = resolve_llm_provider()
    key_set = bool((getattr(settings, 'OPENAI_API_KEY', None) or '').strip())
    return {
        'provider': provider,
        'model': getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini'),
        'api_key_configured': key_set,
        'using_live_llm': provider == 'openai' and key_set,
    }


@login_required
@user_passes_test(_agent_access)
@require_http_methods(['GET', 'POST'])
def agent_assist_console(request):
    """Chat-first Agentic Assist (+ optional structured bootstrap form)."""
    role = getattr(request.user, 'role', None)
    branches = Branch.objects.select_related('district').order_by('district__name', 'name')
    if role == 'branch_manager' and request.user.branch_id:
        branches = branches.filter(pk=request.user.branch_id)
    elif role == 'loan_officer' and request.user.branch_id:
        branches = branches.filter(pk=request.user.branch_id)

    officers = User.objects.filter(role__in=('loan_officer', 'credit_loan_officer')).order_by('username')
    if role == 'branch_manager' and request.user.branch_id:
        officers = officers.filter(branch_id=request.user.branch_id)
    elif role == 'loan_officer':
        officers = officers.filter(pk=request.user.pk)

    categories = LoanCategory.objects.order_by('name')
    collaterals = CollateralType.objects.order_by('name')
    recent = AgentRun.objects.filter(user=request.user).select_related('loan_request')[:12]
    recent_chats = AgentConversation.objects.filter(user=request.user)[:8]

    form_data = {
        'applicant_name': '',
        'phone_number': '0911',
        'amount': '1000000',
        'reason': 'Working capital',
        'category_id': '',
        'collateral_type_id': '',
        'branch_id': str(request.user.branch_id or ''),
        'assign_officer_id': str(request.user.pk) if role == 'loan_officer' else '',
        'corporate': False,
        'complete_documents': True,
        'draft_appraisal': True,
        'queue_approved': True,
        'customer_number': '',
        'declared_address': '',
        'intent_text': '',
    }

    result = None
    if request.method == 'POST' and request.POST.get('form_mode') == 'structured':
        form_data['applicant_name'] = (request.POST.get('applicant_name') or '').strip()
        form_data['phone_number'] = (request.POST.get('phone_number') or '').strip()
        form_data['amount'] = (request.POST.get('amount') or '0').strip()
        form_data['reason'] = (request.POST.get('reason') or '').strip()
        form_data['category_id'] = request.POST.get('category_id') or ''
        form_data['collateral_type_id'] = request.POST.get('collateral_type_id') or ''
        form_data['branch_id'] = request.POST.get('branch_id') or ''
        form_data['assign_officer_id'] = request.POST.get('assign_officer_id') or ''
        form_data['corporate'] = request.POST.get('corporate') == 'on'
        form_data['complete_documents'] = request.POST.get('complete_documents') == 'on'
        form_data['draft_appraisal'] = request.POST.get('draft_appraisal') == 'on'
        form_data['queue_approved'] = request.POST.get('queue_approved') == 'on'
        form_data['customer_number'] = (request.POST.get('customer_number') or '').strip()
        form_data['declared_address'] = (request.POST.get('declared_address') or '').strip()
        form_data['intent_text'] = (request.POST.get('intent_text') or '').strip()

        try:
            amount = Decimal(form_data['amount'].replace(',', ''))
        except (InvalidOperation, ValueError):
            messages.error(request, 'Invalid amount.')
            amount = None

        if amount is not None and form_data['applicant_name']:
            req = AgentRequest(
                applicant_name=form_data['applicant_name'],
                phone_number=form_data['phone_number'] or '0911000000',
                amount=amount,
                reason=form_data['reason'] or 'Working capital',
                category_id=int(form_data['category_id']) if form_data['category_id'] else None,
                collateral_type_id=int(form_data['collateral_type_id']) if form_data['collateral_type_id'] else None,
                branch_id=int(form_data['branch_id']) if form_data['branch_id'] else None,
                assign_officer_id=int(form_data['assign_officer_id']) if form_data['assign_officer_id'] else None,
                corporate=form_data['corporate'],
                complete_documents=form_data['complete_documents'],
                draft_appraisal=form_data['draft_appraisal'],
                queue_approved=form_data['queue_approved'],
                customer_number=form_data['customer_number'],
                declared_address=form_data['declared_address'],
                intent_text=form_data['intent_text'] or form_data['applicant_name'],
            )
            result = run_bootstrap_pipeline(request.user, req)
            if result.get('ok'):
                messages.success(
                    request,
                    f"Agent created {result.get('loan_request_code')}. Collateral left for field work.",
                )
            elif result.get('partial'):
                messages.warning(request, f"Partial: {result.get('error')}")
            else:
                messages.error(request, result.get('error') or 'Agent run failed.')
            recent = AgentRun.objects.filter(user=request.user).select_related('loan_request')[:12]
        elif not form_data['applicant_name']:
            messages.error(request, 'Applicant name is required.')

    convo_id = request.GET.get('c') or ''
    conversation = None
    if convo_id.isdigit():
        conversation = AgentConversation.objects.filter(
            pk=int(convo_id), user=request.user,
        ).first()

    return render(request, 'loans/agent_assist.html', {
        'branches': branches,
        'officers': officers,
        'categories': categories,
        'collaterals': collaterals,
        'form_data': form_data,
        'result': result,
        'recent_runs': recent,
        'recent_chats': recent_chats,
        'role': role,
        'llm': _llm_status(),
        'conversation': conversation,
        'chat_api_url': '/agent/chat/',
        'agent_chat_auto_open': True,
    })


@login_required
@user_passes_test(_agent_access)
@require_http_methods(['POST'])
def agent_chat_api(request):
    """JSON chatbot endpoint: {message, conversation_id?}."""
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        body = {}
    if not body and request.POST:
        body = {
            'message': request.POST.get('message', ''),
            'conversation_id': request.POST.get('conversation_id'),
        }

    message = (body.get('message') or '').strip()
    if not message:
        return JsonResponse({'ok': False, 'error': 'Empty message', 'reply': 'Please type a message.'}, status=400)

    convo_id = body.get('conversation_id')
    conversation = None
    if convo_id:
        conversation = AgentConversation.objects.filter(
            pk=convo_id, user=request.user,
        ).first()
    if not conversation:
        conversation = AgentConversation.objects.create(
            user=request.user,
            title=(message[:80] + ('…' if len(message) > 80 else '')),
            llm_provider=resolve_llm_provider(),
        )

    result = run_chat_turn(request.user, conversation, message)
    status = 200 if result.get('ok') or result.get('reply') else 400
    conversation.refresh_from_db()
    payload = {
        'ok': result.get('ok', False),
        'reply': result.get('reply') or result.get('error') or '',
        'conversation_id': conversation.pk,
        'provider': result.get('provider') or conversation.llm_provider,
        'tools': result.get('tools') or [],
        'story': result.get('story') or story_for_api_safe(conversation),
        'loan_request_id': result.get('loan_request_id') or conversation.last_loan_request_id,
        'loan_request_code': result.get('loan_request_code'),
        'llm_error': result.get('llm_error'),
        'error': result.get('error'),
    }
    if payload.get('loan_request_id') and not payload.get('loan_request_code'):
        lr = conversation.last_loan_request
        if lr:
            payload['loan_request_code'] = lr.loan_request_id
    return JsonResponse(payload, status=status)


def story_for_api_safe(conversation):
    from loans.agent_story import conversation_story, story_for_api
    return story_for_api(conversation_story(conversation))


@login_required
@user_passes_test(_agent_access)
@require_http_methods(['GET'])
def agent_conversation_api(request, conversation_id):
    conversation = get_object_or_404(AgentConversation, pk=conversation_id)
    if conversation.user_id != request.user.id and not (
        getattr(request.user, 'is_superuser', False)
        or request.user.role in ('admin', 'superadmin')
    ):
        return JsonResponse({'ok': False, 'error': 'Forbidden'}, status=403)
    from loans.agent_story import conversation_story, story_for_api
    return JsonResponse({
        'ok': True,
        'conversation_id': conversation.pk,
        'title': conversation.title,
        'provider': conversation.llm_provider,
        'messages': conversation.ui_messages or [],
        'story': story_for_api(conversation_story(conversation)),
        'loan_request_id': conversation.last_loan_request_id,
        'loan_request_code': (
            conversation.last_loan_request.loan_request_id
            if conversation.last_loan_request_id
            else None
        ),
    })


@login_required
@user_passes_test(_agent_access)
def agent_run_detail(request, run_id):
    run = get_object_or_404(AgentRun.objects.select_related('loan_request', 'user'), pk=run_id)
    if run.user_id != request.user.id and not (
        getattr(request.user, 'is_superuser', False)
        or request.user.role in ('admin', 'superadmin')
    ):
        messages.warning(request, 'You can only view your own agent runs.')
        return redirect('agent_assist')
    return render(request, 'loans/agent_run_detail.html', {'run': run})
