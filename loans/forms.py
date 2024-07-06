# loans/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, LoanRequest

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'password1', 'password2', 'role', 'phone_number', 'zone', 'branch']

class LoanRequestForm(forms.ModelForm):
    class Meta:
        model = LoanRequest
        fields = ['applicant_name', 'phone_number', 'email', 'category', 'collateral', 'amount_requested', 'reason']
