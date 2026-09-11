from typing import Optional
import re

from django import forms
from django.core.exceptions import ValidationError

from loans.models import Branch, CollateralType, District, LoanCategory
from loans.product_family import FAMILY_GENERAL

from applicant_portal.models import ApplicantAccount, ApplicantPortalSettings, OnlineApplication
from applicant_portal.security import (
    get_portal_settings,
    normalize_customer_number,
    normalize_phone,
    password_policy_hints,
    validate_applicant_password,
    validate_customer_number_format,
    validate_phone_format,
)


class ApplicantPortalSettingsForm(forms.ModelForm):
    """Hub settings form for digital-apply policy (superuser)."""

    class Meta:
        model = ApplicantPortalSettings
        fields = [
            'enabled',
            'processing_fee_etb',
            'min_password_length',
            'require_uppercase',
            'require_lowercase',
            'require_digit',
            'require_special',
            'max_failed_logins',
            'lockout_minutes',
            'register_rate_limit_per_hour',
            'session_idle_minutes',
            'require_terms_acceptance',
            'require_customer_lookup',
        ]
        widgets = {
            'processing_fee_etb': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'min_password_length': forms.NumberInput(attrs={'min': '8', 'max': '64'}),
            'max_failed_logins': forms.NumberInput(attrs={'min': '3', 'max': '20'}),
            'lockout_minutes': forms.NumberInput(attrs={'min': '5', 'max': '1440'}),
            'register_rate_limit_per_hour': forms.NumberInput(attrs={'min': '1', 'max': '100'}),
            'session_idle_minutes': forms.NumberInput(attrs={'min': '5', 'max': '480'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-control')


class ApplicantRegisterForm(forms.Form):
    customer_number = forms.CharField(
        max_length=50,
        label='DECSI customer number',
        widget=forms.TextInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'pattern': r'[0-9\s\-]*',
            'placeholder': 'Your bank customer ID',
            'id': 'id_customer_number',
        }),
        help_text='Required. We load your name and phone from DECSI when the core-banking API is available.',
    )
    full_name = forms.CharField(
        max_length=255,
        label='Full name',
        widget=forms.TextInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'name',
            'autocapitalize': 'words',
            'id': 'id_full_name',
        }),
        help_text='Filled from DECSI when found — edit only if your record is wrong.',
    )
    phone_number = forms.CharField(
        max_length=30,
        label='Mobile number',
        widget=forms.TextInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'tel',
            'inputmode': 'tel',
            'pattern': r'[0-9+\s\-()]*',
            'placeholder': '09… / 07… / +251…',
            'id': 'id_phone_number',
        }),
        help_text='Must match your mobile on file with DECSI when core banking is connected.',
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'new-password',
        }),
    )
    password_confirm = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'new-password',
        }),
    )
    accept_terms = forms.BooleanField(
        required=False,
        label='I accept the terms of digital application and privacy notice.',
    )
    # Honeypot — bots fill this; humans leave empty.
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy = get_portal_settings()
        self.fields['password'].help_text = 'Required: ' + '; '.join(
            password_policy_hints(self.policy),
        )
        self.customer_profile = None
        if self.policy.require_terms_acceptance:
            self.fields['accept_terms'].required = True
        # Enforce field order: customer number first
        self.order_fields([
            'customer_number', 'full_name', 'phone_number',
            'password', 'password_confirm', 'accept_terms', 'website',
        ])

    def clean_phone_number(self):
        phone = normalize_phone(self.cleaned_data.get('phone_number') or '')
        validate_phone_format(phone)
        if ApplicantAccount.objects.filter(phone_number=phone).exists():
            raise ValidationError(
                'An account with this phone already exists. Sign in instead.',
            )
        return phone

    def clean_customer_number(self):
        from loans.services.customer import portal_customer_lookup

        raw = self.data.get(self.add_prefix('customer_number'), self.cleaned_data.get('customer_number'))
        try:
            cn = normalize_customer_number(raw if raw is not None else '')
        except ValidationError:
            raise
        validate_customer_number_format(cn)
        if ApplicantAccount.objects.filter(customer_number__iexact=cn).exists():
            raise ValidationError(
                'An account with this customer number already exists. Sign in instead.',
            )
        profile, msg = portal_customer_lookup(cn)
        if profile is None:
            # portal_customer_lookup already applies require based on live API / settings
            raise ValidationError(msg)
        self.customer_profile = profile
        return cn

    def clean_full_name(self):
        name = (self.cleaned_data.get('full_name') or '').strip()
        if len(name) < 3:
            raise ValidationError('Enter your full name.')
        return name

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get('website') or '').strip():
            raise ValidationError('Registration blocked.')
        password = cleaned.get('password') or ''
        confirm = cleaned.get('password_confirm') or ''
        if password != confirm:
            self.add_error('password_confirm', 'Passwords do not match.')
        if password and not self.errors.get('password'):
            try:
                validate_applicant_password(
                    password,
                    phone=cleaned.get('phone_number') or '',
                    full_name=cleaned.get('full_name') or '',
                    policy=self.policy,
                )
            except ValidationError as exc:
                self.add_error('password', exc)
        if self.policy.require_terms_acceptance and not cleaned.get('accept_terms'):
            self.add_error('accept_terms', 'You must accept the terms to register.')

        # Prefer / enforce bank identity when DECSI returned a profile on LIVE API
        profile = self.customer_profile or {}
        bank_name = (profile.get('name') or '').strip()
        bank_phone = (profile.get('phone_number') or '').strip()
        from loans.services.customer import customer_api_is_live
        if customer_api_is_live() and bank_name and len(bank_name) >= 3:
            cleaned['full_name'] = bank_name[:255]
        if bank_phone:
            try:
                bank_phone_n = normalize_phone(bank_phone)
                validate_phone_format(bank_phone_n)
                entered = cleaned.get('phone_number') or ''
                if customer_api_is_live() and entered and entered != bank_phone_n:
                    self.add_error(
                        'phone_number',
                        'This phone does not match DECSI records for this customer number. '
                        'Use the mobile number on your account or visit a branch to update it.',
                    )
                elif not entered:
                    cleaned['phone_number'] = bank_phone_n
            except ValidationError:
                pass
        return cleaned

    def save(self) -> ApplicantAccount:
        from django.utils import timezone
        from loans.services.customer import apply_profile_to_account_fields, customer_api_is_live

        profile = self.customer_profile or {}
        fields = apply_profile_to_account_fields(profile)
        # Live CBS: bank name is source of truth; phone already validated against bank in clean().
        if customer_api_is_live() and fields.get('full_name'):
            full_name = fields['full_name']
        else:
            full_name = fields.get('full_name') or self.cleaned_data['full_name']
        if customer_api_is_live() and fields.get('phone_number'):
            try:
                phone = normalize_phone(fields['phone_number'])
                validate_phone_format(phone)
            except ValidationError:
                phone = self.cleaned_data['phone_number']
        else:
            phone = self.cleaned_data['phone_number']

        account = ApplicantAccount(
            full_name=full_name,
            phone_number=phone,
            customer_number=self.cleaned_data['customer_number'],
            email=fields.get('email') or '',
            customer_profile_snapshot=profile,
            terms_accepted_at=timezone.now() if self.cleaned_data.get('accept_terms') else None,
        )
        account.set_password(self.cleaned_data['password'])
        account.save()
        return account


class ExternalActorRegisterForm(forms.Form):
    """PFI / promoter door — no DECSI customer-number lookup."""

    actor_kind = forms.ChoiceField(
        choices=[
            (ApplicantAccount.ACTOR_INSTITUTION, 'Institution (bank / MFI / PFI)'),
            (ApplicantAccount.ACTOR_PROMOTER, 'Project / idea promoter'),
        ],
        widget=forms.HiddenInput(),
    )
    institution_name = forms.CharField(
        max_length=255,
        label='Institution or venture name',
        widget=forms.TextInput(attrs={'class': 'ap-input', 'autocomplete': 'organization'}),
    )
    license_number = forms.CharField(
        max_length=80,
        required=False,
        label='License / registration number',
        widget=forms.TextInput(attrs={'class': 'ap-input'}),
    )
    full_name = forms.CharField(
        max_length=255,
        label='Contact person',
        widget=forms.TextInput(attrs={'class': 'ap-input', 'autocomplete': 'name'}),
    )
    phone_number = forms.CharField(
        max_length=30,
        label='Mobile number',
        widget=forms.TextInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'tel',
            'inputmode': 'tel',
            'placeholder': '09… / 07… / +251…',
        }),
    )
    email = forms.EmailField(
        required=False,
        label='Email',
        widget=forms.EmailInput(attrs={'class': 'ap-input', 'autocomplete': 'email'}),
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'ap-input', 'autocomplete': 'new-password'}),
    )
    password_confirm = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(attrs={'class': 'ap-input', 'autocomplete': 'new-password'}),
    )
    accept_terms = forms.BooleanField(
        required=False,
        label='I accept the terms of digital application and privacy notice.',
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy = get_portal_settings()
        self.fields['password'].help_text = 'Required: ' + '; '.join(
            password_policy_hints(self.policy),
        )
        if self.policy.require_terms_acceptance:
            self.fields['accept_terms'].required = True

    def clean_phone_number(self):
        phone = normalize_phone(self.cleaned_data.get('phone_number') or '')
        validate_phone_format(phone)
        if ApplicantAccount.objects.filter(phone_number=phone).exists():
            raise ValidationError('An account with this phone already exists. Sign in instead.')
        return phone

    def clean_full_name(self):
        name = (self.cleaned_data.get('full_name') or '').strip()
        if len(name) < 3:
            raise ValidationError('Enter the contact person’s name.')
        return name

    def clean_institution_name(self):
        name = (self.cleaned_data.get('institution_name') or '').strip()
        if len(name) < 2:
            raise ValidationError('Enter the institution or venture name.')
        return name

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get('website') or '').strip():
            raise ValidationError('Registration blocked.')
        password = cleaned.get('password') or ''
        confirm = cleaned.get('password_confirm') or ''
        if password != confirm:
            self.add_error('password_confirm', 'Passwords do not match.')
        if password and not self.errors.get('password'):
            try:
                validate_applicant_password(
                    password,
                    phone=cleaned.get('phone_number') or '',
                    full_name=cleaned.get('full_name') or '',
                    policy=self.policy,
                )
            except ValidationError as exc:
                self.add_error('password', exc)
        if self.policy.require_terms_acceptance and not cleaned.get('accept_terms'):
            self.add_error('accept_terms', 'You must accept the terms to register.')
        return cleaned

    def save(self) -> ApplicantAccount:
        from django.utils import timezone
        from applicant_portal.access import portal_customer_number

        account = ApplicantAccount(
            actor_kind=self.cleaned_data['actor_kind'],
            full_name=self.cleaned_data['full_name'],
            institution_name=self.cleaned_data['institution_name'],
            license_number=(self.cleaned_data.get('license_number') or '').strip(),
            phone_number=self.cleaned_data['phone_number'],
            email=(self.cleaned_data.get('email') or '').strip(),
            customer_number=portal_customer_number(),
            terms_accepted_at=timezone.now() if self.cleaned_data.get('accept_terms') else None,
        )
        account.set_password(self.cleaned_data['password'])
        account.save()
        return account


class ApplicantLoginForm(forms.Form):
    login_id = forms.CharField(
        max_length=50,
        label='Phone or customer number',
        widget=forms.TextInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'username',
            'placeholder': '09… or customer number',
        }),
        help_text='Mobile number or core-banking customer number.',
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'current-password',
        }),
    )

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        self.account: Optional[ApplicantAccount] = None

    def clean(self):
        from applicant_portal.security import (
            is_ip_locked,
            lockout_message,
            register_failed_login,
        )

        cleaned = super().clean()
        raw_id = (cleaned.get('login_id') or '').strip()
        password = cleaned.get('password') or ''

        if self.request is not None and is_ip_locked(self.request):
            raise ValidationError(lockout_message())

        account = None
        phone = ''
        # Prefer phone if it looks like a mobile number
        try:
            phone = normalize_phone(raw_id)
            validate_phone_format(phone)
            account = ApplicantAccount.objects.filter(phone_number=phone).first()
        except ValidationError:
            phone = ''
            try:
                cn = normalize_customer_number(raw_id)
                validate_customer_number_format(cn)
                account = ApplicantAccount.objects.filter(customer_number__iexact=cn).first()
                phone = account.phone_number if account else cn
            except ValidationError:
                raise ValidationError('Enter a valid phone or customer number.')

        if account and account.is_login_locked():
            raise ValidationError(lockout_message())

        if not account or not account.is_active or not account.check_password(password):
            register_failed_login(account, self.request, phone or raw_id)
            raise ValidationError('Invalid credentials.')

        if account.is_login_locked() or not account.can_use_portal():
            raise ValidationError(lockout_message())

        self.account = account
        return cleaned


class PasswordResetRequestForm(forms.Form):
    login_id = forms.CharField(
        max_length=50,
        label='Phone or customer number',
        widget=forms.TextInput(attrs={'class': 'ap-input', 'autocomplete': 'username'}),
    )

    def clean_login_id(self):
        raw = (self.cleaned_data.get('login_id') or '').strip()
        account = None
        try:
            phone = normalize_phone(raw)
            validate_phone_format(phone)
            account = ApplicantAccount.objects.filter(phone_number=phone).first()
        except ValidationError:
            try:
                cn = normalize_customer_number(raw)
                account = ApplicantAccount.objects.filter(customer_number__iexact=cn).first()
            except ValidationError:
                pass
        # Always succeed wording to avoid account enumeration — but store account for view.
        self.account = account
        return raw


class PasswordResetConfirmForm(forms.Form):
    login_id = forms.CharField(
        max_length=50,
        label='Phone or customer number',
        widget=forms.TextInput(attrs={'class': 'ap-input'}),
    )
    code = forms.CharField(
        max_length=12,
        label='6-digit code',
        widget=forms.TextInput(attrs={
            'class': 'ap-input', 'inputmode': 'numeric', 'autocomplete': 'one-time-code',
        }),
    )
    new_password = forms.CharField(
        label='New password',
        widget=forms.PasswordInput(attrs={'class': 'ap-input', 'autocomplete': 'new-password'}),
    )
    new_password_confirm = forms.CharField(
        label='Confirm new password',
        widget=forms.PasswordInput(attrs={'class': 'ap-input', 'autocomplete': 'new-password'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy = get_portal_settings()
        self.fields['new_password'].help_text = 'Required: ' + '; '.join(
            password_policy_hints(self.policy),
        )
        self.account: Optional[ApplicantAccount] = None

    def clean(self):
        cleaned = super().clean()
        raw = (cleaned.get('login_id') or '').strip()
        account = None
        try:
            phone = normalize_phone(raw)
            validate_phone_format(phone)
            account = ApplicantAccount.objects.filter(phone_number=phone).first()
        except ValidationError:
            try:
                cn = normalize_customer_number(raw)
                account = ApplicantAccount.objects.filter(customer_number__iexact=cn).first()
            except ValidationError:
                account = None
        if not account:
            raise ValidationError('Account not found.')
        self.account = account
        new = cleaned.get('new_password') or ''
        confirm = cleaned.get('new_password_confirm') or ''
        if new != confirm:
            self.add_error('new_password_confirm', 'Passwords do not match.')
        if new:
            try:
                validate_applicant_password(
                    new, phone=account.phone_number, full_name=account.full_name, policy=self.policy,
                )
            except ValidationError as exc:
                self.add_error('new_password', exc)
        return cleaned


class ApplicantChangePasswordForm(forms.Form):
    current_password = forms.CharField(
        label='Current password',
        widget=forms.PasswordInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'current-password',
        }),
    )
    new_password = forms.CharField(
        label='New password',
        widget=forms.PasswordInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'new-password',
        }),
    )
    new_password_confirm = forms.CharField(
        label='Confirm new password',
        widget=forms.PasswordInput(attrs={
            'class': 'ap-input',
            'autocomplete': 'new-password',
        }),
    )

    def __init__(self, *args, account=None, **kwargs):
        self.account = account
        super().__init__(*args, **kwargs)
        self.policy = get_portal_settings()
        self.fields['new_password'].help_text = 'Required: ' + '; '.join(
            password_policy_hints(self.policy),
        )

    def clean_current_password(self):
        pwd = self.cleaned_data.get('current_password') or ''
        if not self.account or not self.account.check_password(pwd):
            raise ValidationError('Current password is incorrect.')
        return pwd

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get('new_password') or ''
        confirm = cleaned.get('new_password_confirm') or ''
        if new != confirm:
            self.add_error('new_password_confirm', 'Passwords do not match.')
        if new and not self.errors.get('new_password'):
            try:
                validate_applicant_password(
                    new,
                    phone=getattr(self.account, 'phone_number', ''),
                    full_name=getattr(self.account, 'full_name', ''),
                    policy=self.policy,
                )
            except ValidationError as exc:
                self.add_error('new_password', exc)
        if (
            new
            and self.account
            and self.account.check_password(new)
            and not self.errors.get('new_password')
        ):
            self.add_error('new_password', 'New password must be different from the current one.')
        return cleaned

    def save(self) -> None:
        self.account.set_password(self.cleaned_data['new_password'])
        self.account.save(update_fields=['password_hash', 'password_changed_at', 'updated_at'])


class ApplicationDetailsForm(forms.ModelForm):
    district = forms.ModelChoiceField(
        queryset=District.objects.none(),
        required=True,
        label='District',
        empty_label='— Select district —',
        widget=forms.Select(attrs={'class': 'ap-input', 'id': 'id_district'}),
    )

    class Meta:
        model = OnlineApplication
        fields = [
            'applicant_name',
            'phone_number',
            'customer_number',
            'customer_history',
            'category',
            'collateral',
            'branch',
            'amount_requested',
            'reason',
        ]
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 3}),
            'branch': forms.Select(attrs={'class': 'ap-input', 'id': 'id_branch'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from applicant_portal.access import (
            ACTOR_INSTITUTION, ACTOR_PERSON, ACTOR_PROMOTER, actor_kind_of, categories_for_account,
        )
        from loans.forms import ProductFamilySelect

        self.fields['district'].queryset = District.objects.order_by('name')
        acct = getattr(self.instance, 'applicant', None) if self.instance else None
        if acct is not None:
            self.fields['category'].queryset = categories_for_account(acct)
        else:
            self.fields['category'].queryset = LoanCategory.objects.order_by('product_family', 'name')
        cat_qs = self.fields['category'].queryset
        # Replacing the widget after queryset assignment drops choices — re-sync.
        cat_widget = ProductFamilySelect(attrs={'class': 'ap-input', 'id': 'id_category'})
        cat_widget.family_by_pk = {c.id: c.product_family for c in cat_qs}
        self.fields['category'].widget = cat_widget
        self.fields['category'].widget.choices = self.fields['category'].choices
        self.fields['category'].label_from_instance = (
            lambda obj: obj.name if obj.product_family == FAMILY_GENERAL
            else f'{obj.name} — {obj.get_product_family_display()}'
        )
        # label_from_instance changed — refresh widget choices again
        self.fields['category'].widget.choices = self.fields['category'].choices
        posted_cat = None
        if self.data.get('category'):
            posted_cat = LoanCategory.objects.filter(pk=self.data.get('category')).first()
        elif self.instance and self.instance.category_id:
            posted_cat = self.instance.category
        # Same as staff registration: full collateral list; JS filters by product family.
        self.fields['collateral'].queryset = CollateralType.objects.exclude(
            name__icontains='to be determined',
        ).order_by('name')
        self.fields['collateral'].widget.attrs['id'] = 'id_collateral'
        kind = actor_kind_of(acct) if acct is not None else ACTOR_PERSON
        wholesale_door = kind == ACTOR_INSTITUTION
        # Requiredness enforced in clean() via family policy (matches hub LoanRequestForm).
        self.fields['collateral'].required = False
        self.fields['collateral'].empty_label = '— Select collateral type —'
        self.fields['collateral'].help_text = (
            'Optional for a PFI facility — staff may add security later.'
            if wholesale_door else
            'Options update when you pick a product (same rules as branch registration).'
        )
        self.fields['customer_number'].required = kind == ACTOR_PERSON
        self.fields['customer_number'].help_text = (
            'DBE / core-banking customer number from your account.'
            if kind == ACTOR_PERSON else
            'Not required for a PFI or promoter. A portal reference is generated.'
        )
        self.fields['applicant_name'].label = (
            'Institution name' if wholesale_door else
            'Promoter / project name' if kind == ACTOR_PROMOTER else
            'Applicant name'
        )
        self.fields['applicant_name'].help_text = (
            'Legal name of the PFI.' if wholesale_door else
            'Promoter or venture as it should appear on the file.'
            if kind == ACTOR_PROMOTER else
            'From your customer account when available.'
        )
        self.fields['phone_number'].help_text = 'Reachable contact for this application.'
        self.fields['category'].help_text = (
            'The product decides the next page: project file, PFI file, lease / Ijarah, Murabaha, or idea.'
        )
        self.fields['reason'].label = 'Purpose of financing'
        self.fields['amount_requested'].label = 'Amount requested (ETB)'

        # Prefill locked identity from snapshot when drafting
        if self.instance and self.instance.pk:
            acct = getattr(self.instance, 'applicant', None)
            snap = (getattr(acct, 'customer_profile_snapshot', None) or {}) if acct else {}
            if snap.get('name') and not self.initial.get('applicant_name'):
                self.fields['applicant_name'].initial = snap.get('name')
            if snap.get('home_address'):
                self.fields['applicant_name'].help_text = (
                    (self.fields['applicant_name'].help_text or '')
                    + f' Address on file: {snap.get("home_address")[:80]}'
                )

        district_id = None
        if self.data.get('district'):
            try:
                district_id = int(self.data.get('district'))
            except (TypeError, ValueError):
                district_id = None
        elif self.instance and self.instance.branch_id:
            district_id = self.instance.branch.district_id
            self.fields['district'].initial = district_id

        if district_id:
            self.fields['branch'].queryset = Branch.objects.filter(
                district_id=district_id,
            ).order_by('name')
        else:
            self.fields['branch'].queryset = Branch.objects.none()
        self.fields['branch'].empty_label = '— Select branch —'
        self.fields['branch'].required = True

        self.fields['phone_number'].widget.attrs.update({
            'inputmode': 'tel',
            'pattern': r'[0-9+\s\-()]*',
            'placeholder': '09… / 07… / +251…',
        })
        self.fields['customer_number'].widget.attrs.update({
            'inputmode': 'numeric',
            'pattern': r'[0-9\s\-]*',
            'placeholder': 'Digits only',
        })
        if kind == ACTOR_PERSON:
            self.fields['customer_number'].help_text = 'DBE / core-banking customer number (from your account).'
        self.fields['amount_requested'].widget = forms.NumberInput(attrs={
            'class': 'ap-input',
            'min': '1',
            'step': '0.01',
            'inputmode': 'decimal',
        })
        self.fields['amount_requested'].help_text = 'Numbers only (ETB).'

        desired = [
            'category',
            'applicant_name', 'phone_number', 'customer_number', 'customer_history',
            'collateral', 'district', 'branch', 'amount_requested', 'reason',
        ]
        self.order_fields(desired)

        for name, field in self.fields.items():
            field.widget.attrs.setdefault('class', 'ap-input')
            if name == 'district':
                field.widget.attrs['id'] = 'id_district'
            if name == 'branch':
                field.widget.attrs['id'] = 'id_branch'

    def clean_phone_number(self):
        phone = normalize_phone(self.cleaned_data.get('phone_number') or '')
        validate_phone_format(phone)
        # When live, prefer bank phone; do not force mismatch errors on apply so staff can adjust later
        return phone

    def clean_customer_number(self):
        from applicant_portal.access import ACTOR_PERSON, actor_kind_of

        raw = self.cleaned_data.get('customer_number') or ''
        acct = getattr(self.instance, 'applicant', None) if self.instance else None
        if actor_kind_of(acct) != ACTOR_PERSON:
            if not str(raw).strip() and acct is not None:
                return acct.customer_number
            return (str(raw).strip() or '')[:50]
        if not str(raw).strip():
            raise ValidationError('Customer number is required.')
        cn = normalize_customer_number(raw)
        validate_customer_number_format(cn)
        return cn

    def clean_amount_requested(self):
        raw = (self.data.get(self.add_prefix('amount_requested')) if self.data else None)
        if raw is None:
            raw = ''
        raw = str(raw).strip()
        if raw and re.search(r'[A-Za-z]', raw):
            raise ValidationError('Amount must be a number — letters are not allowed.')
        if raw and re.search(r'[^\d.,\s]', raw):
            raise ValidationError('Amount may only contain digits and a decimal point.')
        amount = self.cleaned_data.get('amount_requested')
        if amount is None or amount <= 0:
            raise ValidationError('Enter a positive loan amount.')
        return amount

    def clean(self):
        from applicant_portal.access import ACTOR_INSTITUTION, actor_kind_of
        from loans.registration import collateral_for_category, collateral_required

        cleaned = super().clean()
        district = cleaned.get('district')
        branch = cleaned.get('branch')
        if district and branch and branch.district_id != district.pk:
            self.add_error('branch', 'Select a branch that belongs to the chosen district.')

        category = cleaned.get('category')
        collateral = cleaned.get('collateral')
        acct = getattr(self.instance, 'applicant', None) if self.instance else None
        wholesale_door = actor_kind_of(acct) == ACTOR_INSTITUTION if acct is not None else False
        if collateral_required(category) and not collateral and not wholesale_door:
            self.add_error('collateral', 'Select a security type for this product.')
        if collateral and category and not collateral_for_category(category).filter(pk=collateral.pk).exists():
            self.add_error(
                'collateral',
                'This security type is not used for the selected product.',
            )
        return cleaned

    def save(self, commit=True):
        return super().save(commit=commit)
