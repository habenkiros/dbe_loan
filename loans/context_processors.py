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
