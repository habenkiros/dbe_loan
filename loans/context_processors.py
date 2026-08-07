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


def agent_assistant(request):
    """Floating Agentic Assist chatbot widget (lower-right) for allowed roles."""
    if not request.user.is_authenticated:
        return {'agent_chat_enabled': False}
    from django.urls import reverse
    from loans.agent import user_can_use_agent
    from loans.agent_chat import resolve_llm_provider

    if not user_can_use_agent(request.user):
        return {'agent_chat_enabled': False}
    return {
        'agent_chat_enabled': True,
        'agent_chat_api_url': reverse('agent_chat_api'),
        'agent_chat_history_url_tpl': reverse(
            'agent_conversation_api', args=[999999999]
        ).replace('999999999', '{id}'),
        'agent_chat_provider': resolve_llm_provider(),
    }
