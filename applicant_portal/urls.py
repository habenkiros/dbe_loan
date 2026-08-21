from django.urls import path

from applicant_portal import help_views as applicant_help
from applicant_portal import views

app_name = 'applicant_portal'

urlpatterns = [
    path('', views.landing, name='landing'),
    path('help/', applicant_help.help_index, name='help_index'),
    path('help/screenshots/<str:name>', applicant_help.help_screenshot, name='help_screenshot'),
    path('help/<slug:slug>/', applicant_help.help_chapter, name='help_chapter'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('password/forgot/', views.password_reset_request, name='password_reset_request'),
    path('password/reset/', views.password_reset_confirm, name='password_reset_confirm'),
    path('account/password/', views.change_password, name='change_password'),
    path('account/notices/read/', views.mark_notices_read, name='mark_notices_read'),
    path('account/notices/', views.notices, name='notices'),
    path('home/', views.home, name='home'),
    path('apply/new/', views.apply_start, name='apply_start'),
    path('apply/<uuid:public_id>/', views.apply_status, name='apply_status'),
    path('apply/<uuid:public_id>/schedule/', views.apply_schedule, name='apply_schedule'),
    path('apply/<uuid:public_id>/details/', views.apply_details, name='apply_details'),
    path('apply/<uuid:public_id>/documents/', views.apply_documents, name='apply_documents'),
    path('apply/<uuid:public_id>/payment/', views.apply_payment, name='apply_payment'),
    path('apply/<uuid:public_id>/payment/return/', views.apply_payment_return, name='apply_payment_return'),
    path('apply/<uuid:public_id>/submit/', views.apply_submit, name='apply_submit'),
    path('apply/<uuid:public_id>/withdraw/', views.apply_withdraw, name='apply_withdraw'),
    path('payments/chapa/webhook/', views.chapa_webhook, name='chapa_webhook'),
    path('ajax/branches/', views.ajax_branches, name='ajax_branches'),
    path('ajax/customer/', views.ajax_lookup_customer, name='ajax_lookup_customer'),
]
