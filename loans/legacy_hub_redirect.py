"""Redirect bookmarked staff URLs from /path to /hub/path after public root was given to applicants."""

from __future__ import annotations

from django.http import HttpResponsePermanentRedirect
from django.urls import Resolver404, resolve


class StaffHubLegacyRedirectMiddleware:
    """
    Root domain is the applicant portal. Staff app lives under /hub/.

    Bookmarks / old links like /view_loan_requests/ or /manage_users/ would 404.
    If the path has no root match but exists under /hub/, redirect there (302).
    """

    # Never rewrite these public / field / system prefixes
    SKIP_PREFIXES = (
        '/hub/',
        '/admin/',
        '/static/',
        '/media/',
        '/collateral/',
        '/market-portal/',
        '/applicant-portal/',
        '/staff/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or '/'
        if path == '/' or any(path.startswith(p) for p in self.SKIP_PREFIXES):
            return self.get_response(request)

        # Already a known root route (applicant login, register, etc.) — leave alone
        try:
            resolve(path)
            return self.get_response(request)
        except Resolver404:
            pass

        hub_path = '/hub' + path if path.startswith('/') else '/hub/' + path
        try:
            resolve(hub_path)
        except Resolver404:
            return self.get_response(request)

        qs = request.META.get('QUERY_STRING') or ''
        target = hub_path + (f'?{qs}' if qs else '')
        # Temporary redirect so bookmarks update without hard-coding permanent forever
        return HttpResponsePermanentRedirect(target)
