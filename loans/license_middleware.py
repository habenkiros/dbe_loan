"""License enforcement middleware + license status view helpers."""
from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe

from loans.licensing import get_license_status


class LicenseEnforcementMiddleware:
    """
    Block the product when the on-prem license is missing, invalid, or past grace.
    Always allow static/media and the public license status page.
    """

    EXEMPT_PREFIXES = (
        '/static/',
        '/media/',
        '/license/',
        '/favicon.ico',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or '/'
        status = get_license_status()
        request.license_status = status

        if path.startswith(self.EXEMPT_PREFIXES) or any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return self.get_response(request)

        if status.ok_to_run:
            return self.get_response(request)

        # Hard lock — render blocking page (HTML) or JSON-ish plain text for APIs
        accept = (request.headers.get('Accept') or '').lower()
        if 'application/json' in accept or path.startswith('/api/'):
            return HttpResponse(
                '{"detail":"Product license inactive. Contact Seqela for renewal."}',
                status=403,
                content_type='application/json',
            )
        return render(
            request,
            'licensing/blocked.html',
            {
                'license_status': status,
                'license_url': '/license/',
            },
            status=403,
        )


def license_status_view(request):
    status = get_license_status(force_refresh=True)
    return render(request, 'licensing/status.html', {'license_status': status})
