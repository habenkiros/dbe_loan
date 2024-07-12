# loans/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('create_user/', views.create_user, name='create_user'),
    path('edit_user/<int:user_id>/', views.edit_user, name='edit_user'),
    path('create_loan_request/', views.create_loan_request, name='create_loan_request'),
    path('view_loan_requests/', views.view_loan_requests, name='view_loan_requests'),
    path('view_loan_requests_operation_manager/', views.view_loan_requests_operation_manager, name='view_loan_requests_operation_manager'),
    path('view_loan_requests_finance_manager/', views.view_loan_requests_finance_manager, name='view_loan_requests_finance_manager'),
    path('loan_request_detail/<int:loan_request_id>/', views.loan_request_detail, name='loan_request_detail'),
    path('loan_request_detail_operation_manager/<int:loan_request_id>/', views.loan_request_detail_operation_manager, name='loan_request_detail_operation_manager'),
    path('loan_request_detail_finance/<int:loan_request_id>/', views.loan_request_detail_finance, name='loan_request_detail_finance'),
    path('update_operation_manager_approval/<int:loan_request_id>/', views.update_operation_manager_approval, name='update_operation_manager_approval'),
    path('update_finance_manager_approval/<int:loan_request_id>/', views.update_finance_manager_approval, name='update_finance_manager_approval'),
    path('filter_loan_requests/', views.filter_loan_requests, name='filter_loan_requests'),
    path('manage_zones/', views.manage_zones, name='manage_zones'),
    path('edit_zone/<int:zone_id>/', views.edit_zone, name='edit_zone'),
    path('manage_branches/', views.manage_branches, name='manage_branches'),
    path('edit_branch/<int:branch_id>/', views.edit_branch, name='edit_branch'),
    path('manage_loan_categories/', views.manage_loan_categories, name='manage_loan_categories'),
    path('edit_loan_category/<int:category_id>/', views.edit_loan_category, name='edit_loan_category'),
    path('manage_collateral_types/', views.manage_collateral_types, name='manage_collateral_types'),
    path('edit_collateral_type/<int:collateral_type_id>/', views.edit_collateral_type, name='edit_collateral_type'),
    path('manage_users/', views.manage_users, name='manage_users'),
    path('ajax/load-branches/', views.load_branches, name='ajax_load_branches'),
]
