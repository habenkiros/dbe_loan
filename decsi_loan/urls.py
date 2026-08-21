# loan_system/urls.py

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from loans import auth_views as staff_auth
from loans import help_views as hub_help
from loans import views as loan_views
from loans.license_middleware import license_status_view


# Staff (branch / credit / ops) hub — not on the public root
_staff_auth_urlpatterns = [
    path('login/', staff_auth.StaffLoginView.as_view(), name='login'),
    path('logout/', staff_auth.StaffLogoutView.as_view(), name='logout'),
    path('mfa/verify/', staff_auth.mfa_verify, name='mfa_verify'),
    path('mfa/setup/', staff_auth.mfa_setup, name='mfa_setup'),
    path('mfa/disable/', staff_auth.mfa_disable, name='mfa_disable'),
    path(
        'password-reset/',
        staff_auth.StaffPasswordResetView.as_view(),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        staff_auth.StaffPasswordResetDoneView.as_view(),
        name='password_reset_done',
    ),
    path(
        'password-reset/<uidb64>/<token>/',
        staff_auth.StaffPasswordResetConfirmView.as_view(),
        name='password_reset_confirm',
    ),
    path(
        'password-reset/complete/',
        staff_auth.StaffPasswordResetCompleteView.as_view(),
        name='password_reset_complete',
    ),
    path(
        'password-change/',
        staff_auth.StaffPasswordChangeView.as_view(),
        name='password_change',
    ),
    path(
        'password-change/done/',
        staff_auth.password_change_done,
        name='password_change_done',
    ),
    path('session/keepalive/', staff_auth.session_keepalive, name='session_keepalive'),
    path('help/', hub_help.help_index, name='help_index'),
    path('help/manual/', hub_help.help_combined_html, name='help_manual_html'),
    path('help/manual.pdf', hub_help.help_combined_pdf, name='help_manual_pdf'),
    path('help/screenshots/<str:name>', hub_help.help_screenshot, name='help_screenshot'),
    path('help/<slug:slug>/', hub_help.help_chapter, name='help_chapter'),
    path('security/audit/', staff_auth.security_audit_list, name='security_audit_list'),
    path(
        'security/audit/export/',
        staff_auth.security_audit_export,
        name='security_audit_export',
    ),
    path(
        'security/users/<int:user_id>/unlock/',
        staff_auth.unlock_user,
        name='unlock_user',
    ),
    path('', include('loans.urls')),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('license/', license_status_view, name='product_license_status'),
    # Browsers request /favicon.ico by default (outside static/)
    path(
        'favicon.ico',
        RedirectView.as_view(url=settings.STATIC_URL + 'favicon.ico', permanent=False),
        name='favicon',
    ),
    # Public digital apply at domain root
    path('', include('applicant_portal.urls')),
    # Public remote OTP agreement signing (no staff login)
    path(
        'sign/agreement/<str:token>/',
        loan_views.remote_agreement_sign,
        name='remote_agreement_sign',
    ),
    # Staff loan hub
    path('hub/', include(_staff_auth_urlpatterns)),
    # Legacy shortcuts
    path(
        'applicant-portal/',
        RedirectView.as_view(url='/', permanent=False),
        name='legacy_applicant_portal',
    ),
    path(
        'applicant-portal/<path:rest>',
        RedirectView.as_view(url='/%(rest)s', permanent=False),
    ),
    path('staff/', RedirectView.as_view(url='/hub/', permanent=False)),
    path('staff/<path:rest>', RedirectView.as_view(url='/hub/%(rest)s', permanent=False)),
    # Field / ops tools (staff auth required by views)
    path('collateral/', include('collateral.urls')),
    # External market reporters
    path('market-portal/', include('partners.portal_urls')),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
