# loans/context_processors.py

def loan_notifications(request):
    if not request.user.is_authenticated:
        return {}
    from .models import LoanNotification

    return {
        'unread_notification_count': LoanNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).count(),
    }


def staff_delegations(request):
    """Banner + nav flags for staff authority delegation."""
    empty = {
        'active_delegations_received': [],
        'pending_delegation_count': 0,
        'can_manage_delegations': False,
        'can_assign_loan_officer': False,
        'can_delegated_appraisal': False,
        'can_cooperative_intake': False,
        'can_finance_disbursement': False,
        'show_delegated_loans_nav': False,
    }
    if not request.user.is_authenticated:
        return empty
    try:
        from loans.delegation import (
            SCOPE_APPRAISAL,
            pending_delegation_qs,
            principals_for,
            received_delegations,
            user_can_approve_delegations,
            user_can_manage_delegations,
            user_has_assign_officer_authority,
            user_has_cooperative_authority,
            user_has_finance_authority,
        )
        user = request.user
        can_manage = user_can_manage_delegations(user)
        rows = received_delegations(user) if can_manage else []
        pending_count = (
            pending_delegation_qs().count()
            if user_can_approve_delegations(user)
            else 0
        )
        can_assign = user_has_assign_officer_authority(user)
        can_appraisal_del = bool(principals_for(user, SCOPE_APPRAISAL))
        role = getattr(user, 'role', None)
        # Roles that already have Loan requests in the main nav
        has_native_loan_nav = role in (
            'branch_manager', 'loan_officer', 'credit_loan_officer', 'credit_head',
            'district_manager', 'engineer', 'engineering_head', 'admin', 'superadmin',
        ) or getattr(user, 'is_superuser', False)
        return {
            'active_delegations_received': rows,
            'pending_delegation_count': pending_count,
            'can_manage_delegations': can_manage,
            'can_assign_loan_officer': can_assign,
            'can_delegated_appraisal': can_appraisal_del,
            'can_cooperative_intake': user_has_cooperative_authority(user),
            'can_finance_disbursement': user_has_finance_authority(user),
            'show_delegated_loans_nav': (can_assign or can_appraisal_del) and not has_native_loan_nav,
        }
    except Exception:
        return empty


def agent_assistant(request):
    """Floating Agentic Assist chatbot widget (lower-right) for allowed roles."""
    if not request.user.is_authenticated:
        return {'agent_chat_enabled': False}
    from django.urls import reverse
    from loans.agent import user_can_use_agent
    from loans.agent_chat import resolve_llm_provider
    from loans.agent_permissions import page_loan_for_user

    if not user_can_use_agent(request.user):
        return {'agent_chat_enabled': False}
    page_loan = None
    try:
        page_loan = page_loan_for_user(request.user, request.path)
    except Exception:
        page_loan = None
    return {
        'agent_chat_enabled': True,
        'agent_chat_api_url': reverse('agent_chat_api'),
        'agent_chat_inbox_url': reverse('agent_conversations_list_api'),
        'agent_chat_history_url_tpl': reverse(
            'agent_conversation_api', args=[999999999]
        ).replace('999999999', '{id}'),
        'agent_chat_provider': resolve_llm_provider(),
        'agent_page_loan_id': page_loan.pk if page_loan else '',
        'agent_page_loan_code': page_loan.loan_request_id if page_loan else '',
        'agent_show_request_docs': getattr(request.user, 'role', None) in (
            'loan_officer', 'credit_loan_officer', 'engineer',
        ),
    }


def staff_nav(request):
    """Role-based nav visibility (avoid duplicate dashboards / committee links)."""
    from loans.nav import nav_flags_for

    if not request.user.is_authenticated:
        return nav_flags_for(None)
    return nav_flags_for(request.user)


def institution_branding(request):
    """Bank name on the hub / portal. This instance is DBE."""
    from loans.branding import institution_name, institution_short, product_name

    return {
        'institution_name': institution_name(),
        'institution_short': institution_short(),
        'product_name': product_name(),
    }


def product_license(request):
    """Expose license status for hub banners (days remaining / grace)."""
    status = getattr(request, 'license_status', None)
    if status is None:
        try:
            from loans.licensing import get_license_status
            status = get_license_status()
        except Exception:
            return {}
    warn = False
    if status.present and status.valid and status.days_remaining is not None:
        warn = status.days_remaining <= 30
    if status.grace:
        warn = True
    return {
        'product_license': status,
        'product_license_warn': warn,
    }

