"""Request middleware for MFA enrollment + idle session timeout."""
from __future__ import annotations

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from .models import SecurityAuditLog
from .security import log_security_event, mfa_required

SESSION_LAST_ACTIVITY = 'security_last_activity'


def idle_timeout_seconds() -> int:
    return int(getattr(settings, 'SESSION_IDLE_TIMEOUT', 1800) or 1800)


def idle_warning_seconds() -> int:
    return int(getattr(settings, 'SESSION_IDLE_WARNING_SECONDS', 120) or 120)


class EnforceMfaMiddleware:
    """
    When MFA_REQUIRED=True, authenticated users without MFA must enroll.
    Skips login/logout/MFA/password-reset and static/media/admin paths.
    """

    EXEMPT_PREFIXES = (
        '/hub/login/',
        '/hub/logout/',
        '/hub/mfa/',
        '/hub/password-reset/',
        '/hub/password-change/',
        '/hub/session/',
        '/login/',
        '/logout/',
        '/security/mfa/',
        '/password-reset/',
        '/reset/',
        '/static/',
        '/media/',
        '/admin/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if mfa_required() and getattr(request, 'user', None) and request.user.is_authenticated:
            path = request.path or '/'
            if not any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
                if not getattr(request.user, 'mfa_enabled', False):
                    return redirect(reverse('mfa_setup'))
        return self.get_response(request)


class DelegationPrincipalLockoutMiddleware:
    """
    Principals with an active approved outgoing delegation cannot use the hub
    until the cover window ends (or an admin revokes).
    """

    EXEMPT_PREFIXES = (
        '/hub/login/',
        '/hub/logout/',
        '/hub/password-reset/',
        '/hub/mfa/',
        '/login/',
        '/logout/',
        '/password-reset/',
        '/reset/',
        '/static/',
        '/media/',
        '/admin/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        path = request.path or '/'
        if user and user.is_authenticated and not any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            from loans.delegation import (
                principal_locked_out_by_delegation,
                principal_lockout_message,
            )
            locked, ends_at, _ = principal_locked_out_by_delegation(user)
            if locked:
                logout(request)
                messages.warning(request, principal_lockout_message(ends_at))
                return redirect(reverse('login'))
        return self.get_response(request)


class IdleSessionMiddleware:
    """End authenticated sessions after SESSION_IDLE_TIMEOUT seconds idle."""

    EXEMPT_PREFIXES = (
        '/static/',
        '/media/',
        '/hub/password-reset/',
        '/hub/login/',
        '/hub/logout/',
        '/password-reset/',
        '/reset/',
        '/login/',
        '/logout/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or '/'
        user = getattr(request, 'user', None)
        authenticated = bool(user and user.is_authenticated)
        timeout = idle_timeout_seconds()
        exempt = any(path.startswith(p) for p in self.EXEMPT_PREFIXES)

        if authenticated and timeout > 0 and not exempt:
            now = int(time.time())
            last = request.session.get(SESSION_LAST_ACTIVITY)
            if last is not None:
                try:
                    idle_for = now - int(last)
                except (TypeError, ValueError):
                    idle_for = 0
                if idle_for >= timeout:
                    log_security_event(
                        SecurityAuditLog.EVT_SESSION_TIMEOUT,
                        request=request,
                        user=user,
                        username=getattr(user, 'username', ''),
                        detail={'idle_seconds': idle_for, 'timeout': timeout},
                    )
                    logout(request)
                    messages.warning(
                        request,
                        'Your session ended due to inactivity. Please sign in again.',
                    )
                    return redirect(reverse('login'))
            request.session[SESSION_LAST_ACTIVITY] = now
            request.session.modified = True

        return self.get_response(request)
