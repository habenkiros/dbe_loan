# loans/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, LoanRequest, Zone, Branch

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'password1', 'password2', 'role', 'phone_number', 'zone', 'branch']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = Branch.objects.none()

        if 'zone' in self.data:
            try:
                zone_id = int(self.data.get('zone'))
                self.fields['branch'].queryset = Branch.objects.filter(zone_id=zone_id).order_by('name')
            except (ValueError, TypeError):
                pass  # Invalid input from the client; ignore and fallback to empty Branch queryset
        elif self.instance.pk and self.instance.zone:
            self.fields['branch'].queryset = self.instance.zone.branch_set.order_by('name')

class LoanRequestForm(forms.ModelForm):
    class Meta:
        model = LoanRequest
        fields = ['applicant_name', 'phone_number', 'email', 'category', 'collateral', 'amount_requested', 'reason']
