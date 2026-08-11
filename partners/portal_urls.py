from django.urls import path

from partners import portal_views

app_name = 'market_portal'

urlpatterns = [
    path('', portal_views.portal_landing, name='landing'),
    path('submit/', portal_views.portal_landing, name='submit'),
    path('submit/product/', portal_views.portal_submit_product, name='submit_product'),
    path('register/', portal_views.portal_register, name='register'),
    path('login/', portal_views.portal_login, name='login'),
    path('logout/', portal_views.portal_logout, name='logout'),
    path('home/', portal_views.portal_home, name='home'),
    path('profile/', portal_views.portal_profile, name='profile'),
    path('ajax/zones/', portal_views.ajax_zones, name='ajax_zones'),
    path('ajax/cities/', portal_views.ajax_cities, name='ajax_cities'),
    path('ajax/sub-works/', portal_views.ajax_sub_works, name='ajax_sub_works'),
    path('ajax/sub-sub-works/', portal_views.ajax_sub_sub_works, name='ajax_sub_sub_works'),
]
