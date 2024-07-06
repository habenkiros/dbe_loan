# loans/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('create_user/', views.create_user, name='create_user'),
    path('create_loan_request/', views.create_loan_request, name='create_loan_request'),
    path('manage_zones/', views.manage_zones, name='manage_zones'),
    path('manage_branches/', views.manage_branches, name='manage_branches'),
    path('manage_loan_categories/', views.manage_loan_categories, name='manage_loan_categories'),
    path('manage_collateral_types/', views.manage_collateral_types, name='manage_collateral_types'),
    path('ajax/load-branches/', views.load_branches, name='ajax_load_branches'),
]
