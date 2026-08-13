"""Staff delegation create / list forms."""

from django import forms
from django.utils import timezone
from datetime import timedelta

from loans.delegation import (
    eligible_delegates_queryset,
    native_scopes_for,
    scope_choices_for,
)
from loans.models import StaffDelegation


class StaffDelegationForm(forms.ModelForm):
    scopes = forms.MultipleChoiceField(
        choices=[],
        widget=forms.CheckboxSelectMultiple,
        required=True,
        help_text='Only permissions you hold yourself can be delegated.',
    )

    class Meta:
        model = StaffDelegation
        fields = ['delegate', 'scopes', 'starts_at', 'ends_at', 'reason']
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'reason': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Annual leave / field mission',
            }),
            'delegate': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, principal=None, **kwargs):
        self.principal = principal
        super().__init__(*args, **kwargs)
        qs = eligible_delegates_queryset(principal)
        self.fields['delegate'].queryset = qs
        self.fields['delegate'].label = 'Proposed delegate (who will be signed)'
        role = getattr(principal, 'role', None) if principal else None
        if role == 'branch_manager' or (principal and getattr(principal, 'branch_id', None)):
            sphere = 'your branch'
        elif role == 'district_manager' or (
            principal and getattr(principal, 'district_id', None) and not getattr(principal, 'branch_id', None)
        ):
            sphere = 'your district'
        else:
            sphere = 'your organization'
        self.fields['delegate'].help_text = (
            f'Colleagues in {sphere} only. An admin must approve before they can act.'
        )
        if not qs.exists():
            self.fields['delegate'].help_text += (
                ' No eligible colleagues found — check that your branch/district is set on your profile.'
            )

        held_choices = scope_choices_for(principal)
        self.fields['scopes'].choices = held_choices
        self._held_scopes = [c[0] for c in held_choices]
        if held_choices:
            self.fields['scopes'].help_text = (
                'Only permissions you currently hold. You cannot grant access you do not have.'
            )
        else:
            self.fields['scopes'].required = False
            self.fields['scopes'].help_text = (
                'You have no delegable permissions for your role right now '
                '(e.g. not on a committee, and no appraisal/finance/intake/assign rights).'
            )

        if not self.is_bound:
            now = timezone.now()
            self.fields['starts_at'].initial = now.strftime('%Y-%m-%dT%H:%M')
            self.fields['ends_at'].initial = (now + timedelta(days=7)).strftime('%Y-%m-%dT%H:%M')

    def clean_scopes(self):
        scopes = self.cleaned_data.get('scopes') or []
        held = set(native_scopes_for(self.principal))
        bad = [s for s in scopes if s not in held]
        if bad:
            raise forms.ValidationError(
                'You cannot delegate permissions outside your access: '
                + ', '.join(bad)
            )
        if not scopes:
            raise forms.ValidationError(
                'Select at least one permission you currently hold.'
            )
        return list(scopes)

    def clean_delegate(self):
        delegate = self.cleaned_data.get('delegate')
        if not delegate:
            return delegate
        allowed = eligible_delegates_queryset(self.principal)
        if not allowed.filter(pk=delegate.pk).exists():
            raise forms.ValidationError(
                'That user is outside your branch/district sphere. Pick a colleague in your scope.'
            )
        return delegate

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('starts_at')
        end = cleaned.get('ends_at')
        if start and end and end <= start:
            self.add_error('ends_at', 'End must be after start.')
        delegate = cleaned.get('delegate')
        if self.principal and delegate and delegate.id == self.principal.id:
            self.add_error('delegate', 'You cannot delegate to yourself.')
        if not native_scopes_for(self.principal):
            raise forms.ValidationError(
                'You have no permissions that can be delegated. Ask an admin if your role should hold committee or other scopes.'
            )
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.principal = self.principal
        obj.scopes = self.cleaned_data['scopes']
        # Approach A: staff name the proposed delegate; admin must approve before live.
        obj.status = StaffDelegation.STATUS_PENDING
        obj.is_active = False
        obj.revoked_at = None
        obj.revoked_by = None
        obj.reviewed_by = None
        obj.reviewed_at = None
        obj.review_note = ''
        if commit:
            obj.save()
        return obj
