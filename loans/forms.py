# loans/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import CustomUser, LoanRequest, Zone, Branch, LoanCategory, CollateralType

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

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'role', 'phone_number', 'zone', 'branch']

class LoanRequestForm(forms.ModelForm):
    class Meta:
        model = LoanRequest
        fields = ['applicant_name', 'phone_number', 'email', 'category', 'collateral', 'amount_requested', 'reason', 'customer_history']

class ZoneForm(forms.ModelForm):
    class Meta:
        model = Zone
        fields = ['name']

class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['zone', 'name']

class LoanCategoryForm(forms.ModelForm):
    class Meta:
        model = LoanCategory
        fields = ['name']

class CollateralTypeForm(forms.ModelForm):
    class Meta:
        model = CollateralType
        fields = ['name']

from django import forms
from .models import Zone, Branch, LoanRequest

class LoanRequestFilterForm(forms.Form):
    zone = forms.ModelChoiceField(queryset=Zone.objects.all(), required=False, label="Zone")
    branch = forms.ModelChoiceField(queryset=Branch.objects.none(), required=False, label="Branch")
    status = forms.ChoiceField(choices=LoanRequest.STATUS_CHOICES, required=False, label="Status")
    
    def __init__(self, *args, **kwargs):
        zone_id = kwargs.pop('zone_id', None)
        super().__init__(*args, **kwargs)
        if zone_id:
            self.fields['branch'].queryset = Branch.objects.filter(zone_id=zone_id)
        else:
            self.fields['branch'].queryset = Branch.objects.none()
