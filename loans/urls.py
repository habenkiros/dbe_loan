# loans/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('create_user/', views.create_user, name='create_user'),
    path('create_loan_request/', views.create_loan_request, name='create_loan_request'),
]
