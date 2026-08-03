# loan_system/urls.py

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie


@method_decorator(ensure_csrf_cookie, name='dispatch')
class EnsureCsrfLoginView(auth_views.LoginView):
    """Guarantee csrftoken cookie on GET /login/ (needed for phones / TLS proxy)."""


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('loans.urls')),
    path('collateral/', include('collateral.urls')),
    path('login/', EnsureCsrfLoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='/login/'), name='logout'),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)