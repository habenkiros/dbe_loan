from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone

from applicant_portal.security import session_idle_seconds

SESSION_APPLICANT_KEY = 'applicant_portal_account_id'
SESSION_ACTIVITY_KEY = 'applicant_portal_last_activity'


def get_portal_applicant(request):
    from applicant_portal.models import ApplicantAccount, ApplicantAuthEvent
    from applicant_portal.security import log_auth_event

    pk = request.session.get(SESSION_APPLICANT_KEY)
    if not pk:
        return None

    # Idle timeout
    last = request.session.get(SESSION_ACTIVITY_KEY)
    if last:
        try:
            idle = timezone.now().timestamp() - float(last)
        except (TypeError, ValueError):
            idle = 0
        if idle > session_idle_seconds():
            log_auth_event(
                ApplicantAuthEvent.EVT_SESSION_TIMEOUT,
                request=request,
                phone=str(pk),
                detail={'idle_seconds': int(idle)},
            )
            request.session.pop(SESSION_APPLICANT_KEY, None)
            request.session.pop(SESSION_ACTIVITY_KEY, None)
            return None

    account = ApplicantAccount.objects.filter(pk=pk).first()
    if not account or not account.is_active or not account.password_hash:
        request.session.pop(SESSION_APPLICANT_KEY, None)
        request.session.pop(SESSION_ACTIVITY_KEY, None)
        return None
    if account.is_login_locked():
        request.session.pop(SESSION_APPLICANT_KEY, None)
        request.session.pop(SESSION_ACTIVITY_KEY, None)
        return None

    # Touch activity
    request.session[SESSION_ACTIVITY_KEY] = timezone.now().timestamp()
    return account


def login_applicant(request, account) -> None:
    from applicant_portal.security import register_successful_login

    request.session.cycle_key()
    request.session[SESSION_APPLICANT_KEY] = account.pk
    request.session[SESSION_ACTIVITY_KEY] = timezone.now().timestamp()
    register_successful_login(account, request)


def logout_applicant(request, *, account=None, reason: str = 'logout') -> None:
    from applicant_portal.models import ApplicantAuthEvent
    from applicant_portal.security import log_auth_event

    if account is None:
        pk = request.session.get(SESSION_APPLICANT_KEY)
        if pk:
            from applicant_portal.models import ApplicantAccount
            account = ApplicantAccount.objects.filter(pk=pk).first()
    request.session.pop(SESSION_APPLICANT_KEY, None)
    request.session.pop(SESSION_ACTIVITY_KEY, None)
    request.session.cycle_key()
    if reason == 'logout':
        log_auth_event(
            ApplicantAuthEvent.EVT_LOGOUT,
            request=request,
            account=account,
            phone=getattr(account, 'phone_number', '') if account else '',
        )


def applicant_login_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        account = get_portal_applicant(request)
        if not account:
            messages.info(request, 'Please sign in to continue.')
            return redirect('applicant_portal:login')
        request.portal_applicant = account
        return view(request, *args, **kwargs)

    return _wrapped
