"""Applicant portal template context."""


def portal_notices(request):
    """Unread notice count for Digital Apply nav (not shown on home dashboard)."""
    account_id = request.session.get('applicant_portal_account_id')
    if not account_id:
        return {}
    try:
        from applicant_portal.models import ApplicantNotification
        count = ApplicantNotification.objects.filter(
            account_id=account_id, is_read=False,
        ).count()
    except Exception:
        count = 0
    return {'applicant_unread_notices': count}
