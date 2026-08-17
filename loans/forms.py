# loans/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.db.models import Q
from .models import (
    CustomUser, LoanRequest, District, Branch, Department, Region, Zone, City,
    LoanCategory, CollateralType, LoanApplicationDocumentType, LoanAppraisal, CollateralEstimationConfig,
    LoanRequestBasicInfo, AppraisalPurposeLine, AppraisalCreditHistoryEntry, AppraisalQualitativeFactor,
    AppraisalRiskMitigation, AppraisalCondition,
    AppraisalESChecklistItem,
    ApprovalCommitteeLevel, ApprovalCommitteeMemberRule,
    QUALITATIVE_FACTOR_KEYS, qualitative_rating_field_choices,
    es_checklist_item_count,
)

# Roles shown in user admin forms (exclude legacy aliases).
ACTIVE_USER_ROLE_CHOICES = [
    c for c in CustomUser.ROLE_CHOICES
    if c[0] not in ('operation_manager', 'credit_committee')
]


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['key', 'name', 'is_active', 'sort_order']


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'password1', 'password2', 'role', 'phone_number', 'department', 'district', 'branch']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = ACTIVE_USER_ROLE_CHOICES
        self.fields['department'].queryset = Department.objects.filter(is_active=True).order_by('sort_order', 'name')
        self.fields['department'].required = False
        self.fields['branch'].queryset = Branch.objects.none()

        if 'district' in self.data:
            try:
                district_id = int(self.data.get('district'))
                self.fields['branch'].queryset = Branch.objects.filter(district_id=district_id).order_by('name')
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and self.instance.district:
            self.fields['branch'].queryset = self.instance.district.branch_set.order_by('name')

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'role', 'phone_number', 'department', 'district', 'branch']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = ACTIVE_USER_ROLE_CHOICES
        self.fields['department'].queryset = Department.objects.filter(is_active=True).order_by('sort_order', 'name')
        self.fields['department'].required = False
        self.fields['branch'].queryset = Branch.objects.none()
        if 'district' in self.data:
            try:
                district_id = int(self.data.get('district'))
                self.fields['branch'].queryset = Branch.objects.filter(district_id=district_id).order_by('name')
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and self.instance.district_id:
            self.fields['branch'].queryset = Branch.objects.filter(
                district_id=self.instance.district_id,
            ).order_by('name')


class DistrictForm(forms.ModelForm):
    class Meta:
        model = District
        fields = ['name']


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['district', 'name']


class RegionForm(forms.ModelForm):
    class Meta:
        model = Region
        fields = ['name']


class ZoneForm(forms.ModelForm):
    class Meta:
        model = Zone
        fields = ['region', 'name']


class CityForm(forms.ModelForm):
    class Meta:
        model = City
        fields = ['zone', 'name']

class LoanCategoryForm(forms.ModelForm):
    class Meta:
        model = LoanCategory
        fields = ['name', 'appraisal_mode']

class CollateralTypeForm(forms.ModelForm):
    class Meta:
        model = CollateralType
        fields = ['name']


class LoanApplicationDocumentTypeForm(forms.ModelForm):
    """Superadmin: document type + per-type authentication rules."""
    class Meta:
        model = LoanApplicationDocumentType
        fields = [
            'name', 'order', 'is_required',
            'allowed_extensions', 'max_file_size_mb', 'auth_notes',
            'content_validation_sample', 'content_validation_min_matches',
            'content_validation_strict', 'content_extraction_mappings',
            'require_officer_verification', 'enable_ocr_match',
            'identity_match_fields', 'identity_match_strict',
            'enable_llm_check', 'enable_external_id', 'for_appraisal_mode',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'is_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allowed_extensions': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'pdf,jpg,jpeg,png (blank = bank default)'},
            ),
            'max_file_size_mb': forms.NumberInput(
                attrs={'class': 'form-control', 'min': 1, 'placeholder': 'Bank default'},
            ),
            'auth_notes': forms.TextInput(attrs={'class': 'form-control'}),
            'content_validation_sample': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 6,
                    'placeholder': 'One expected phrase per line, e.g.\nFEDERAL DEMOCRATIC REPUBLIC OF ETHIOPIA\nIDENTITY CARD\nTrade License',
                },
            ),
            'content_validation_min_matches': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'content_validation_strict': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'content_extraction_mappings': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 5,
                    'placeholder': 'tin_number=TIN\nbusiness_name=Business Name\nfather_name=Father Name\ntin_number=regex:\\b(\\d{10})\\b',
                },
            ),
            'require_officer_verification': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_ocr_match': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'identity_match_fields': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'applicant_name,phone_number,tin_number,business_name',
                },
            ),
            'identity_match_strict': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_llm_check': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_external_id': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'allowed_extensions': 'Only these extensions accepted for this document type.',
            'max_file_size_mb': 'Leave empty to use the bank-wide default below.',
            'content_validation_sample': (
                'Paste phrases that must appear in a valid upload (one per line). '
                'The system reads PDF/image/DOCX text and rejects wrong documents.'
            ),
            'content_validation_min_matches': 'How many of the phrases above must be found in the file.',
            'content_validation_strict': 'Reject upload immediately when content validation fails.',
            'content_extraction_mappings': (
                'Map document labels to appraisal fields for auto-fill (Sheet 1 / 2). '
                'One per line: field_name=Label in document.'
            ),
            'identity_match_fields': (
                'Comma-separated loan fields to find in the document via OCR: '
                'applicant_name, phone_number, tin_number, business_name.'
            ),
            'identity_match_strict': (
                'Reject upload when configured identity fields do not match loan data. '
                'Leave unchecked to accept upload but flag for officer review.'
            ),
        }

    def clean(self):
        cleaned = super().clean()
        phrases = []
        sample = cleaned.get('content_validation_sample') or ''
        for line in sample.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                phrases.append(line)
        min_matches = cleaned.get('content_validation_min_matches') or 1
        if phrases and min_matches > len(phrases):
            raise forms.ValidationError(
                f'Minimum matches ({min_matches}) cannot exceed number of phrases ({len(phrases)}).'
            )
        return cleaned


class LoanApplicationDocumentTypeEditForm(LoanApplicationDocumentTypeForm):
    """Edit form includes official reference sample file upload."""

    class Meta(LoanApplicationDocumentTypeForm.Meta):
        fields = LoanApplicationDocumentTypeForm.Meta.fields + [
            'reference_sample',
            'use_reference_sample_validation',
            'reference_min_similarity',
        ]
        widgets = {
            **LoanApplicationDocumentTypeForm.Meta.widgets,
            'reference_sample': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'}),
            'use_reference_sample_validation': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'reference_min_similarity': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '1'},
            ),
        }
        help_texts = {
            **LoanApplicationDocumentTypeForm.Meta.help_texts,
            'reference_sample': 'Upload the official blank/sample document (PDF or image). Save to analyze and seed validation rules.',
            'use_reference_sample_validation': 'Reject uploads that do not match the reference sample text/layout.',
            'reference_min_similarity': '0.08 is lenient for phone scans; increase to 0.15+ for stricter matching.',
        }


class DocumentAuthenticationDefaultsForm(forms.Form):
    """Bank-wide defaults when a document type leaves size/extensions blank."""

    def __init__(self, *args, **kwargs):
        from .models import DocumentAuthenticationPolicy
        self.policy = DocumentAuthenticationPolicy.objects.first()
        if not self.policy:
            self.policy = DocumentAuthenticationPolicy()
        super().__init__(*args, **kwargs)
        self.fields['allowed_extensions'] = forms.CharField(
            required=True,
            initial=self.policy.allowed_extensions,
            widget=forms.TextInput(attrs={'class': 'form-control'}),
            help_text='Used when a document type does not set its own allowed extensions.',
        )
        self.fields['max_file_size_mb'] = forms.IntegerField(
            min_value=1,
            initial=self.policy.max_file_size_mb,
            widget=forms.NumberInput(attrs={'class': 'form-control'}),
            help_text='Used when a document type does not set its own max size.',
        )
        self.fields['require_verified_documents_for_collateral'] = forms.BooleanField(
            required=False,
            initial=self.policy.require_verified_documents_for_collateral,
            widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            help_text='Required document types must pass authentication before collateral.',
        )

    def save(self):
        from .models import DocumentAuthenticationPolicy
        if not self.policy.pk:
            self.policy = DocumentAuthenticationPolicy.objects.create(
                allowed_extensions=self.cleaned_data['allowed_extensions'],
                max_file_size_mb=self.cleaned_data['max_file_size_mb'],
                require_verified_documents_for_collateral=self.cleaned_data['require_verified_documents_for_collateral'],
            )
        else:
            self.policy.allowed_extensions = self.cleaned_data['allowed_extensions']
            self.policy.max_file_size_mb = self.cleaned_data['max_file_size_mb']
            self.policy.require_verified_documents_for_collateral = self.cleaned_data['require_verified_documents_for_collateral']
            self.policy.save()
        return self.policy


class CollateralEstimationConfigForm(forms.ModelForm):
    """Superadmin: who does collateral estimation – loan officer or engineering team."""
    class Meta:
        model = CollateralEstimationConfig
        fields = ['mode']
        widgets = {
            'mode': forms.Select(attrs={'class': 'form-control'}),
        }

class LoanRequestForm(forms.ModelForm):
    class Meta:
        model = LoanRequest
        fields = [
            'customer_number',
            'applicant_name',
            'phone_number',
            'category',
            'collateral',
            'amount_requested',
            'reason',
            'customer_history',
        ]
        widgets = {
            'date_requested': forms.DateInput(attrs={'type': 'date'}),
            'customer_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 2000050042 Samrawit',
                'autocomplete': 'off',
                'inputmode': 'numeric',
            }),
            'applicant_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '09…'}),
            'amount_requested': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'collateral': forms.Select(attrs={'class': 'form-control'}),
            'customer_history': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'customer_number': 'Customer number',
            'applicant_name': 'Applicant name',
            'phone_number': 'Phone number',
            'amount_requested': 'Amount requested (ETB)',
            'customer_history': 'New or existing customer',
        }
        help_texts = {
            'customer_number': 'Look up DECSI core banking first — name and phone fill in when found.',
            'applicant_name': 'Filled from party API when available; correct if needed.',
            'phone_number': 'Filled from party API when available; must be reachable.',
        }

    def __init__(self, *args, credit_origin=False, **kwargs):
        super(LoanRequestForm, self).__init__(*args, **kwargs)
        self.fields['customer_number'].required = True
        self.fields['customer_number'].error_messages = {
            'required': 'Enter the DECSI customer number.',
        }
        # Filled from Look up / clean(); required only after party resolve.
        self.fields['applicant_name'].required = False
        self.fields['phone_number'].required = False
        if credit_origin:
            self.fields['branch'] = forms.ModelChoiceField(
                queryset=Branch.objects.select_related('district').order_by('district__name', 'name'),
                required=True,
                widget=forms.Select(attrs={'class': 'form-control'}),
                help_text='Servicing branch for this head-office Credit loan.',
            )

    def clean_customer_number(self):
        raw = (self.cleaned_data.get('customer_number') or '').strip()
        if not raw:
            raise forms.ValidationError('Customer number is required.')
        # Digits preferred; allow alphanumeric codes used by bank
        cn = ''.join(ch for ch in raw if ch.isalnum())
        if len(cn) < 4:
            raise forms.ValidationError('Customer number looks too short.')
        return cn

    def clean(self):
        cleaned = super().clean()
        cn = cleaned.get('customer_number')
        self._lookup_profile = None
        if not cn:
            return cleaned
        from loans.services.customer import fetch_customer_by_number
        profile = fetch_customer_by_number(cn)
        self._lookup_profile = profile
        if profile:
            if not (cleaned.get('applicant_name') or '').strip() and profile.get('name'):
                cleaned['applicant_name'] = str(profile['name'])[:255]
            if not (cleaned.get('phone_number') or '').strip() and profile.get('phone_number'):
                cleaned['phone_number'] = str(profile['phone_number'])[:15]
        if not (cleaned.get('applicant_name') or '').strip():
            self.add_error(
                'applicant_name',
                'Name is required. Look up the customer number or type the name.',
            )
        if not (cleaned.get('phone_number') or '').strip():
            self.add_error(
                'phone_number',
                'Phone is required. Look up the customer number or enter a phone.',
            )
        return cleaned


class LoanRequestBasicInfoForm(forms.ModelForm):
    """Sheet (1) Basic Info and loan request – client, business, loan details."""
    class Meta:
        model = LoanRequestBasicInfo
        fields = [
            'tin_number', 'gender', 'age', 'marital_status', 'education_level', 'home_address',
            'spouse_name', 'spouse_occupation', 'father_name', 'grandfather_name',
            'business_name', 'business_description', 'business_address', 'date_business_started',
            'form_of_ownership', 'economic_sector', 'subsector_activity',
            'legal_registration_number', 'directors_summary', 'ubo_summary',
            'employees_full_time', 'employees_part_time', 'employees_seasonal',
            'employees_ft_equivalent', 'family_members_employed',
            'peak_sales_months', 'lowest_sales_months',
            'peak_sales_percent', 'lowest_sales_percent',
            'number_business_owners',
            'term_months', 'repayment_frequency', 'interest_rate', 'interest_basis',
            'grace_period_months', 'interest_only_months', 'instalments_per_year', 'cash_contribution',
        ]
        widgets = {
            'date_business_started': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'home_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'business_description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'business_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'directors_summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'ubo_summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            if self.fields[name].widget.attrs.get('class') != 'form-control':
                self.fields[name].widget.attrs.setdefault('class', 'form-control')

    def changed_data_for_sources(self):
        """Fields the officer changed (or newly filled) for provenance badges."""
        return list(self.changed_data)

    def save(self, commit=True):
        instance = super().save(commit=False)
        changed = self.changed_data_for_sources()
        if changed:
            sources = dict(instance.field_sources or {})
            for name in changed:
                sources[name] = {'source': 'manual', 'label': 'Officer'}
            instance.field_sources = sources
        if commit:
            instance.save()
        return instance


class AppraisalPurposeLineForm(forms.ModelForm):
    class Meta:
        model = AppraisalPurposeLine
        fields = ['description', 'quantity', 'unit_price', 'value', 'display_order']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'display_order': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hidden field must not block Save when omitted from the template/POST
        self.fields['display_order'].required = False
        if self.fields['display_order'].initial is None and not self.instance.pk:
            self.fields['display_order'].initial = 0

    def clean(self):
        from decimal import Decimal
        data = super().clean()
        if data.get('display_order') in (None, ''):
            data['display_order'] = self.instance.display_order or 0
        qty = data.get('quantity')
        price = data.get('unit_price')
        if qty is not None and price is not None and data.get('value') is None:
            data['value'] = (Decimal(str(qty)) * Decimal(str(price))).quantize(Decimal('0.01'))
        return data


def get_purpose_line_formset():
    from django.forms import inlineformset_factory
    return inlineformset_factory(
        LoanRequestBasicInfo,
        AppraisalPurposeLine,
        form=AppraisalPurposeLineForm,
        extra=2,
        can_delete=True,
    )


class AppraisalCreditHistoryEntryForm(forms.ModelForm):
    """One row of credit history (Sheet 2). Dropdowns per Excel: Status, Purpose, Repayment, Letter from lender."""
    class Meta:
        model = AppraisalCreditHistoryEntry
        fields = [
            'lender', 'loan_amount', 'current_balance', 'maturity_date', 'purpose',
            'status', 'repayment', 'letter_from_lender', 'score',
        ]
        widgets = {
            'maturity_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'purpose': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'repayment': forms.Select(attrs={'class': 'form-control'}),
            'letter_from_lender': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')
        for name in ('purpose', 'status', 'repayment', 'letter_from_lender'):
            self.fields[name].required = False
            self.fields[name].empty_label = '—'


class AppraisalQualitativeFactorForm(forms.ModelForm):
    """One qualitative factor (Sheet 2) – rating dropdown per Excel (options vary by factor_key)."""
    class Meta:
        model = AppraisalQualitativeFactor
        # weight / earned_score are computed server-side (+ live JS); not posted.
        fields = [
            'factor_key', 'factor_name',
            'rating',
            'notes', 'display_order',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['factor_key'].widget = forms.HiddenInput()
        self.fields['factor_name'].widget = forms.HiddenInput()
        self.fields['display_order'].widget = forms.HiddenInput()
        self.fields['display_order'].required = False

        factor_key = ''
        if getattr(self.instance, 'pk', None) and self.instance.factor_key:
            factor_key = self.instance.factor_key
        elif self.data is not None and self.prefix:
            # Bound formset POST: factor_key comes as hidden input
            factor_key = self.data.get(f'{self.prefix}-factor_key') or ''
        elif self.initial.get('factor_key'):
            factor_key = self.initial['factor_key']

        choices = qualitative_rating_field_choices(factor_key)
        current = ''
        if self.data is not None and self.prefix:
            current = self.data.get(f'{self.prefix}-rating') or ''
        if not current:
            current = getattr(self.instance, 'rating', None) or self.initial.get('rating') or ''
        if current and not any(current == c[0] for c in choices):
            # Tolerate Excel trailing-space / drift vs stored value
            stripped = current.strip()
            matched = next((c[0] for c in choices if c[0] and c[0].strip() == stripped), None)
            if matched:
                current = matched
            else:
                choices = list(choices) + [(current, current)]

        # Must use ChoiceField — CharField + Select does not render options from .choices
        self.fields['rating'] = forms.ChoiceField(
            choices=choices,
            required=False,
            widget=forms.Select(attrs={
                'class': 'form-control rating-select',
                'data-factor-key': factor_key,
            }),
            label='Rating',
        )
        if current:
            self.fields['rating'].initial = current


def get_credit_history_formset():
    from django.forms import inlineformset_factory
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalCreditHistoryEntry,
        form=AppraisalCreditHistoryEntryForm,
        extra=1,
        can_delete=True,
    )


def get_qualitative_factors_formset():
    from django.forms import inlineformset_factory
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalQualitativeFactor,
        form=AppraisalQualitativeFactorForm,
        extra=0,
        can_delete=False,
        max_num=10,
    )


class AppraisalESChecklistItemForm(forms.ModelForm):
    """One E&S checklist row (Sheet 4) – Yes/No/N/A, description, mitigation."""

    class Meta:
        model = AppraisalESChecklistItem
        fields = [
            'section_key', 'section_label', 'item_key', 'question_text',
            'response_yes_no', 'description', 'mitigation', 'display_order',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'mitigation': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('section_key', 'section_label', 'item_key', 'question_text', 'display_order'):
            self.fields[name].widget = forms.HiddenInput()
        self.fields['response_yes_no'].required = False
        self.fields['response_yes_no'].widget.attrs.setdefault('class', 'form-control')


def get_es_checklist_formset():
    from django.forms import inlineformset_factory
    n = es_checklist_item_count()
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalESChecklistItem,
        form=AppraisalESChecklistItemForm,
        extra=0,
        can_delete=False,
        max_num=n,
    )


class AppraisalRiskMitigationForm(forms.ModelForm):
    class Meta:
        model = AppraisalRiskMitigation
        fields = [
            'risk', 'severity', 'mitigation', 'owner', 'due_date', 'status',
        ]
        widgets = {
            'mitigation': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')

    def save(self, commit=True):
        obj = super().save(commit=False)
        if obj.display_order is None:
            obj.display_order = 0
        if commit:
            obj.save()
        return obj


def get_risk_mitigation_formset():
    from django.forms import inlineformset_factory
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalRiskMitigation,
        form=AppraisalRiskMitigationForm,
        extra=1,
        can_delete=True,
    )


class AppraisalConditionForm(forms.ModelForm):
    class Meta:
        model = AppraisalCondition
        fields = [
            'condition_type', 'description', 'responsible_party', 'due_date',
            'required_before_disbursement', 'fulfilled',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            if name not in ('fulfilled', 'required_before_disbursement'):
                self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['fulfilled'].widget.attrs.setdefault('class', 'form-check-input')
        self.fields['required_before_disbursement'].widget.attrs.setdefault('class', 'form-check-input')
        self.fields['required_before_disbursement'].label = 'Before disbursement'

    def save(self, commit=True):
        obj = super().save(commit=False)
        if obj.display_order is None:
            obj.display_order = 0
        if commit:
            obj.save()
        return obj


def get_conditions_formset():
    from django.forms import inlineformset_factory
    return inlineformset_factory(
        LoanAppraisal,
        AppraisalCondition,
        form=AppraisalConditionForm,
        extra=1,
        can_delete=True,
    )


# Step-based appraisal: one form per sheet so saving a step doesn't overwrite others.
class AppraisalSheet2Form(forms.ModelForm):
    """Sheet (2) Business & character – NBE, credit history summary, qualitative score, assessments."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'nbe_credit_report_obtained', 'nbe_report_date_received', 'total_number_repaid_loans',
            'credit_history_max_score', 'qualitative_total_score', 'qualitative_passed',
            'bureau_score', 'bureau_score_band', 'bureau_report_date',
            'bureau_active_loans_count', 'bureau_total_outstanding', 'bureau_total_monthly_debt_service',
            'bureau_inquiries_6m', 'bureau_defaults_ever', 'bureau_restructured_ever', 'bureau_thin_file',
            'business_assessment', 'character_assessment',
        ]
        widgets = {
            'nbe_report_date_received': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'bureau_report_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'business_assessment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'character_assessment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            if name not in ('nbe_credit_report_obtained', 'qualitative_passed'):
                self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['nbe_credit_report_obtained'].widget.attrs['class'] = 'form-check-input'
        self.fields['qualitative_passed'].widget.attrs['class'] = 'form-check-input'
        # Computed from qualitative factors earned scores.
        self.fields['qualitative_total_score'].disabled = True
        self.fields['qualitative_passed'].disabled = True


class AppraisalSheet3Form(forms.ModelForm):
    """
    Sheet (3) Cashflow analysis.
    Phase 0: aggregate income/expense + installment → net cashflow, DSCR (computed).
    Phase 1: optional P&L lines roll into business income (from sales) / expenses when filled.
    Phase 2: annual net cashflow, annual debt service, annual DSCR (computed from Sheet 1 frequency).
    """
    class Meta:
        model = LoanAppraisal
        fields = [
            # Phase 1 – structured monthly P&L
            'cf_monthly_sales', 'cf_monthly_cogs', 'cf_monthly_salaries', 'cf_monthly_rent',
            'cf_monthly_utilities', 'cf_monthly_transport', 'cf_monthly_other_operating', 'cf_monthly_taxes',
            # Phase 0 – aggregates (optional if Phase 1 breakdown used)
            'monthly_business_income', 'monthly_business_expenses', 'other_monthly_income', 'other_monthly_expenses',
            'proposed_monthly_installment',
            # Stress test (sensitivity)
            'stress_sales_drop_pct', 'stress_cost_increase_pct',
            # Balance sheet / ratios
            'bs_current_assets', 'bs_current_liabilities', 'bs_inventory',
            'bs_total_assets', 'bs_total_liabilities', 'bs_equity',
            'corp_annual_revenue', 'corp_operating_profit',
        ]
        widgets = {
            'cf_monthly_sales': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_cogs': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_salaries': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_rent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_utilities': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_transport': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_other_operating': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cf_monthly_taxes': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monthly_business_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monthly_business_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'proposed_monthly_installment': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stress_sales_drop_pct': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'stress_cost_increase_pct': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'bs_current_assets': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'bs_current_liabilities': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'bs_inventory': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'bs_total_assets': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'bs_total_liabilities': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'bs_equity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'corp_annual_revenue': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'corp_operating_profit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, basic_info=None, **kwargs):
        self.basic_info = basic_info
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['monthly_business_income'].help_text = (
            'Leave blank to use Monthly sales (Phase 1) as business income when sales is filled.'
        )
        self.fields['monthly_business_expenses'].help_text = (
            'When P&L expense lines sum to more than 0, that sum replaces monthly business expenses.'
        )

    def clean(self):
        from decimal import Decimal, InvalidOperation
        from .cashflow_utils import payments_per_year_from_repayment_frequency, annual_debt_service

        data = super().clean()

        def d(v):
            return v if v is not None else Decimal('0')

        pl_exp = (
            d(data.get('cf_monthly_cogs'))
            + d(data.get('cf_monthly_salaries'))
            + d(data.get('cf_monthly_rent'))
            + d(data.get('cf_monthly_utilities'))
            + d(data.get('cf_monthly_transport'))
            + d(data.get('cf_monthly_other_operating'))
            + d(data.get('cf_monthly_taxes'))
        )
        if pl_exp > 0:
            data['monthly_business_expenses'] = pl_exp

        sales = data.get('cf_monthly_sales')
        if data.get('monthly_business_income') is None and sales is not None:
            data['monthly_business_income'] = sales

        inc1 = d(data.get('monthly_business_income'))
        inc2 = d(data.get('other_monthly_income'))
        exp1 = d(data.get('monthly_business_expenses'))
        exp2 = d(data.get('other_monthly_expenses'))
        net = inc1 + inc2 - exp1 - exp2
        self._computed_net_monthly = net

        installment = data.get('proposed_monthly_installment')
        self._computed_dscr_monthly = None
        if installment and installment > 0:
            try:
                self._computed_dscr_monthly = (net / installment).quantize(Decimal('0.01'))
            except (InvalidOperation, ZeroDivisionError):
                pass

        freq = getattr(self.basic_info, 'repayment_frequency', None) if self.basic_info else None
        ppy = payments_per_year_from_repayment_frequency(freq)
        self._payments_per_year = ppy
        self._computed_annual_debt = annual_debt_service(installment, ppy)
        self._computed_annual_net = (net * Decimal('12')).quantize(Decimal('0.01')) if net is not None else None
        self._computed_dscr_annual = None
        if self._computed_annual_net is not None and self._computed_annual_debt and self._computed_annual_debt > 0:
            try:
                self._computed_dscr_annual = (
                    self._computed_annual_net / self._computed_annual_debt
                ).quantize(Decimal('0.01'))
            except (InvalidOperation, ZeroDivisionError):
                pass

        # Stress test: apply % shock to income and expenses, then recompute net + DSCR.
        drop_pct = data.get('stress_sales_drop_pct')
        cost_pct = data.get('stress_cost_increase_pct')
        self._computed_stressed_net = None
        self._computed_stressed_dscr = None
        if (drop_pct is not None) or (cost_pct is not None):
            try:
                drop = d(drop_pct) / Decimal('100')
                cost = d(cost_pct) / Decimal('100')
                stressed_inc = (inc1 + inc2) * (Decimal('1') - drop)
                stressed_exp = (exp1 + exp2) * (Decimal('1') + cost)
                self._computed_stressed_net = (stressed_inc - stressed_exp).quantize(Decimal('0.01'))
                if installment and installment > 0:
                    self._computed_stressed_dscr = (self._computed_stressed_net / installment).quantize(Decimal('0.01'))
            except (InvalidOperation, ZeroDivisionError):
                pass

        return data

    def save(self, commit=True):
        from decimal import Decimal
        from .cashflow_utils import (
            max_loan_capacity_from_cashflow,
            suggested_installment_declining,
            compute_balance_sheet_ratios,
        )
        from .appraisal_policy import get_loan_analysis_policy

        obj = super().save(commit=False)
        obj.net_monthly_cashflow = self._computed_net_monthly
        obj.dscr = self._computed_dscr_monthly
        obj.cf_annual_net_cashflow = self._computed_annual_net
        obj.cf_annual_debt_service = self._computed_annual_debt
        obj.dscr_annual = self._computed_dscr_annual
        obj.stressed_net_monthly_cashflow = getattr(self, '_computed_stressed_net', None)
        obj.stressed_dscr = getattr(self, '_computed_stressed_dscr', None)

        ratios = compute_balance_sheet_ratios(
            current_assets=obj.bs_current_assets,
            current_liabilities=obj.bs_current_liabilities,
            inventory=obj.bs_inventory,
            total_liabilities=obj.bs_total_liabilities,
            equity=obj.bs_equity,
        )
        obj.ratio_current = ratios['ratio_current']
        obj.ratio_acid_test = ratios['ratio_acid_test']
        obj.ratio_debt_equity = ratios['ratio_debt_equity']

        bi = self.basic_info
        loan = obj.loan_request
        ppy = getattr(self, '_payments_per_year', 12) or 12
        term = getattr(bi, 'term_months', None) if bi else None
        rate = getattr(bi, 'interest_rate', None) if bi else None
        principal = getattr(loan, 'amount_requested', None) if loan else None
        obj.suggested_monthly_installment = suggested_installment_declining(
            principal, rate, term, payments_per_year=ppy,
        )
        policy = get_loan_analysis_policy()
        target = getattr(policy, 'warn_annual_dscr_min', None) or Decimal('1.2')
        obj.max_loan_capacity = max_loan_capacity_from_cashflow(
            self._computed_annual_net, rate, term, target_dscr=target, payments_per_year=ppy,
        )
        if commit:
            obj.save()
        return obj


class AppraisalESForm(forms.ModelForm):
    """Sheet (4) E&S Assessment — loan officer screening; committee signs later."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'es_risk_category', 'es_eligibility_decision',
            'es_screened_by', 'es_checked_by', 'es_approved_by',
            'es_assessment_date', 'es_notes',
        ]
        widgets = {
            'es_assessment_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'es_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
        labels = {
            'es_risk_category': 'E&S risk category',
            'es_eligibility_decision': 'E&S eligibility (loan officer)',
            'es_screened_by': 'Screened by (loan officer)',
            'es_checked_by': 'Checked by (loan officer)',
            'es_approved_by': 'E&S confirmed by (loan officer)',
            'es_assessment_date': 'Assessment date',
            'es_notes': 'E&S notes / action points',
        }
        help_texts = {
            'es_eligibility_decision': (
                'Loan officer E&S screening result. Credit committee signs the loan decision '
                'separately on the committee pack / voting — not on this sheet.'
            ),
            'es_screened_by': 'Officer who completed the E&S checklist screening.',
            'es_checked_by': 'Officer who verified checklist answers and mitigations.',
            'es_approved_by': (
                'Loan officer confirmation of E&S eligibility. Not a credit-committee signature.'
            ),
        }

    def __init__(self, *args, **kwargs):
        officer = kwargs.pop('officer', None)
        super().__init__(*args, **kwargs)
        from .models import CustomUser
        qs = CustomUser.objects.filter(
            is_active=True,
            role__in=('loan_officer', 'branch_manager'),
        ).order_by('username')
        for f in ('es_screened_by', 'es_checked_by', 'es_approved_by'):
            self.fields[f].queryset = qs
            self.fields[f].required = False
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')
        # Default empty sign-off fields to the assigned / current loan officer
        if officer and officer.is_authenticated:
            for f in ('es_screened_by', 'es_checked_by', 'es_approved_by'):
                if not self.initial.get(f) and not getattr(self.instance, f'{f}_id', None):
                    self.initial[f] = officer.pk
            if not self.initial.get('es_assessment_date') and not self.instance.es_assessment_date:
                from django.utils import timezone
                self.initial['es_assessment_date'] = timezone.localdate()



class AppraisalCollateralForm(forms.ModelForm):
    """Sheet (5) Collateral worksheet – breakdown and total, coverage ratio."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'collateral_immovable_value', 'collateral_moveable_value',
            'collateral_intangible_value', 'collateral_guarantors_value',
            'collateral_total_value', 'collateral_coverage_ratio',
        ]
        widgets = {
            'collateral_immovable_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_moveable_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_intangible_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_guarantors_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_total_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'collateral_coverage_ratio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        from decimal import Decimal
        data = super().clean()
        imm = data.get('collateral_immovable_value') or Decimal('0')
        mov = data.get('collateral_moveable_value') or Decimal('0')
        intan = data.get('collateral_intangible_value') or Decimal('0')
        guar = data.get('collateral_guarantors_value') or Decimal('0')
        total_comp = imm + mov + intan + guar
        if total_comp > 0 and not data.get('collateral_total_value'):
            data['collateral_total_value'] = total_comp
        return data


class AppraisalSummaryForm(forms.ModelForm):
    """Sheet (6) Summary & decision – recommendation, strengths/weaknesses, committee."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'recommendation', 'recommendation_comment',
            'strengths', 'weaknesses', 'committee_comments',
            'amount_approved', 'term_approved_months', 'rate_approved',
        ]
        widgets = {
            'recommendation': forms.Select(attrs={'class': 'form-control'}),
            'recommendation_comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'strengths': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'weaknesses': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'committee_comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'amount_approved': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'term_approved_months': forms.NumberInput(attrs={'class': 'form-control'}),
            'rate_approved': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['amount_approved'].label = 'Recommended amount (ETB)'
        self.fields['amount_approved'].help_text = (
            'Amount the loan officer recommends; sent to the approval committee after appraisal.'
        )
        self.fields['term_approved_months'].label = 'Recommended term (months)'
        self.fields['rate_approved'].label = 'Recommended rate (%)'
        self.fields['committee_comments'].label = 'Notes for committee (optional)'


class CommitteeVoteForm(forms.Form):
    vote = forms.ChoiceField(
        choices=[
            ('approve', 'Approve'),
            ('decline', 'Decline'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    amount_supported = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=20,
        label='Amount you approve (ETB)',
        help_text='Leave blank to use the loan officer’s recommended amount.',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    comments = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )


class ApprovalCommitteeLevelForm(forms.ModelForm):
    """Settings UI: edit an approval committee level (thresholds + routing)."""

    class Meta:
        model = ApprovalCommitteeLevel
        fields = [
            'name', 'voter_scope', 'sequence_order', 'is_active',
            'min_approvals_required', 'min_declines_required',
            'tiebreaker_role',
            'min_loan_amount', 'max_loan_amount',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'voter_scope': forms.Select(attrs={'class': 'form-control'}),
            'sequence_order': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'is_active': forms.CheckboxInput(),
            'min_approvals_required': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'min_declines_required': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'tiebreaker_role': forms.Select(attrs={'class': 'form-control'}),
            'min_loan_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'max_loan_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tiebreaker_role'].required = False
        self.fields['tiebreaker_role'].choices = [('', '— Default by level —')] + list(ACTIVE_USER_ROLE_CHOICES)
        self.fields['tiebreaker_role'].help_text = (
            'On equal approve/reject votes, this role decides. '
            'Defaults: Branch→BM, District→DM, HO→Credit Head, Management→Board then CEO.'
        )


class ApprovalCommitteeLevelCreateForm(forms.ModelForm):
    """Settings UI: add a new custom approval level."""

    class Meta:
        model = ApprovalCommitteeLevel
        fields = [
            'name', 'key', 'voter_scope', 'sequence_order', 'is_active',
            'min_approvals_required', 'min_declines_required',
            'tiebreaker_role',
            'min_loan_amount', 'max_loan_amount',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Regional risk committee'}),
            'key': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. regional_risk (leave blank to auto-generate)',
            }),
            'voter_scope': forms.Select(attrs={'class': 'form-control'}),
            'sequence_order': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'is_active': forms.CheckboxInput(),
            'min_approvals_required': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'min_declines_required': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'tiebreaker_role': forms.Select(attrs={'class': 'form-control'}),
            'min_loan_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'max_loan_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['key'].required = False
        self.fields['key'].help_text = 'Unique slug. Leave blank to generate from the name.'
        self.fields['min_loan_amount'].required = False
        self.fields['max_loan_amount'].required = False
        self.fields['tiebreaker_role'].required = False
        self.fields['tiebreaker_role'].choices = [('', '— Default by level —')] + list(ACTIVE_USER_ROLE_CHOICES)

    def clean_key(self):
        from django.utils.text import slugify

        key = (self.cleaned_data.get('key') or '').strip()
        name = (self.data.get('name') or '').strip()
        if not key:
            key = slugify(name).replace('-', '_')[:50]
        key = slugify(key).replace('-', '_')[:50]
        if not key:
            raise forms.ValidationError('Provide a name or key for this level.')
        qs = ApprovalCommitteeLevel.objects.filter(key=key)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'Key “{key}” is already used. Choose another.')
        return key


class ApprovalCommitteeMemberRuleForm(forms.ModelForm):
    """Who may vote at a committee level (by role or named user)."""

    class Meta:
        model = ApprovalCommitteeMemberRule
        fields = ['participant_type', 'role', 'user', 'label', 'is_active']
        widgets = {
            'participant_type': forms.Select(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
            'user': forms.Select(attrs={'class': 'form-control'}),
            'label': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = CustomUser.objects.filter(is_active=True).order_by('username')
        self.fields['user'].required = False
        self.fields['role'].required = False
        self.fields['role'].choices = [('', '---------')] + list(ACTIVE_USER_ROLE_CHOICES)
        self.fields['label'].required = False

    def clean(self):
        cleaned = super().clean()
        if self.cleaned_data.get('DELETE'):
            return cleaned
        ptype = cleaned.get('participant_type')
        role = cleaned.get('role')
        user = cleaned.get('user')
        if ptype == ApprovalCommitteeMemberRule.PARTICIPANT_ROLE:
            if not role:
                raise forms.ValidationError('Select a role when type is “Anyone with role”.')
            cleaned['user'] = None
        elif ptype == ApprovalCommitteeMemberRule.PARTICIPANT_USER:
            if not user:
                raise forms.ValidationError('Select a user when type is “Specific user”.')
            cleaned['role'] = ''
        return cleaned


def get_approval_committee_member_rule_formset(extra=1):
    return forms.inlineformset_factory(
        ApprovalCommitteeLevel,
        ApprovalCommitteeMemberRule,
        form=ApprovalCommitteeMemberRuleForm,
        extra=extra,
        can_delete=True,
    )


class LoanAppraisalForm(forms.ModelForm):
    """Full appraisal form (single-page fallback): Sheet 2 + cashflow + collateral + decision."""
    class Meta:
        model = LoanAppraisal
        fields = [
            'nbe_credit_report_obtained', 'nbe_report_date_received', 'total_number_repaid_loans',
            'credit_history_max_score', 'qualitative_total_score', 'qualitative_passed',
            'business_assessment', 'character_assessment',
            'monthly_business_income', 'monthly_business_expenses', 'other_monthly_income', 'other_monthly_expenses',
            'proposed_monthly_installment', 'net_monthly_cashflow', 'dscr',
            'collateral_total_value', 'recommendation', 'recommendation_comment',
        ]
        widgets = {
            'nbe_report_date_received': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'monthly_business_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monthly_business_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_monthly_expenses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'proposed_monthly_installment': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'net_monthly_cashflow': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'dscr': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'business_assessment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'character_assessment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'collateral_total_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'recommendation': forms.Select(attrs={'class': 'form-control'}),
            'recommendation_comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            if name != 'nbe_credit_report_obtained' and name != 'qualitative_passed':
                self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['nbe_credit_report_obtained'].widget.attrs['class'] = 'form-check-input'
        self.fields['qualitative_passed'].widget.attrs['class'] = 'form-check-input'

    def clean(self):
        from decimal import Decimal, InvalidOperation
        data = super().clean()
        inc1 = data.get('monthly_business_income') or Decimal('0')
        inc2 = data.get('other_monthly_income') or Decimal('0')
        exp1 = data.get('monthly_business_expenses') or Decimal('0')
        exp2 = data.get('other_monthly_expenses') or Decimal('0')
        net = inc1 + inc2 - exp1 - exp2
        data['net_monthly_cashflow'] = net
        installment = data.get('proposed_monthly_installment')
        if installment and installment > 0:
            try:
                data['dscr'] = (net / installment).quantize(Decimal('0.01'))
            except (InvalidOperation, ZeroDivisionError):
                data['dscr'] = None
        return data


class AssignLoanOfficerForm(forms.Form):
    """Assign a loan officer (branch, district, or credit) to a loan request."""
    assigned_loan_officer = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        required=False,
        empty_label='— Unassigned —',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, branch=None, district=None, credit_origin=False, **kwargs):
        super().__init__(*args, **kwargs)
        qs = CustomUser.objects.filter(is_active=True)
        if credit_origin:
            qs = qs.filter(role='credit_loan_officer')
        else:
            branch_officers = Q(role='loan_officer', branch=branch) if branch else Q(pk__in=[])
            district_id = getattr(district, 'id', None) or district
            district_officers = Q(
                role='loan_officer',
                district_id=district_id,
                branch__isnull=True,
            ) if district_id else Q(pk__in=[])
            qs = qs.filter(branch_officers | district_officers)
        self.fields['assigned_loan_officer'].queryset = qs.order_by('username')


class AssignEngineerForm(forms.Form):
    """Engineering head assigns an engineer to a loan sent for collateral estimation."""
    assigned_engineer = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        required=False,
        empty_label='— Unassigned —',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_engineer'].queryset = CustomUser.objects.filter(
            role='engineer', is_active=True
        ).order_by('username')