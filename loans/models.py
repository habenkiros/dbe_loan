# loans/models.py

from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


# --- Geography: Region → Zone → City (woreda) ---
class Region(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Zone(models.Model):
    region = models.ForeignKey(Region, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

    class Meta:
        unique_together = [('region', 'name')]

    def __str__(self):
        return f"{self.name} ({self.region.name})"


class City(models.Model):
    """City / Woreda level — used for unit price per woreda."""
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

    class Meta:
        unique_together = [('zone', 'name')]
        verbose_name_plural = "Cities"

    def __str__(self):
        return f"{self.name} ({self.zone.name})"


# --- District & Branch (operational structure) ---
class District(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Branch(models.Model):
    district = models.ForeignKey(District, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return f"{self.name} ({self.district.name})"

class LoanCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

class CollateralType(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name


class LoanApplicationDocumentType(models.Model):
    """Configurable document type required or optional for loan application (e.g. National ID, Proof of income)."""
    name = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0, help_text='Display order (lower first).')
    is_required = models.BooleanField(
        default=True,
        help_text='If True, this document type is required for loan application.',
    )
    allowed_extensions = models.CharField(
        max_length=255,
        blank=True,
        help_text='Comma-separated (e.g. pdf,jpg,png). Leave blank to use bank-wide default.',
    )
    max_file_size_mb = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Max upload size for this document type. Leave blank to use bank-wide default.',
    )
    require_officer_verification = models.BooleanField(
        default=False,
        help_text='If checked, officer must manually verify — auto-pass is not enough for collateral.',
    )
    enable_ocr_match = models.BooleanField(
        default=False,
        help_text='Match applicant name, phone, TIN, business name from the loan against OCR text in the upload.',
    )
    identity_match_fields = models.CharField(
        max_length=255,
        blank=True,
        default='applicant_name,phone_number,tin_number',
        help_text='Comma-separated fields to verify in the document: applicant_name, phone_number, tin_number, business_name.',
    )
    identity_match_strict = models.BooleanField(
        default=False,
        help_text='If checked, reject upload when identity fields do not match (otherwise flag for officer review).',
    )
    enable_llm_check = models.BooleanField(
        default=False,
        help_text='Run LLM plausibility check on extracted text (e.g. bank statements).',
    )
    enable_external_id = models.BooleanField(
        default=False,
        help_text='Run external / core banking ID verification when TIN is on Sheet 1.',
    )
    auth_notes = models.CharField(
        max_length=255,
        blank=True,
        help_text='Optional hint shown to branch manager at upload (e.g. “Clear scan of both sides”).',
    )
    content_validation_sample = models.TextField(
        blank=True,
        help_text=(
            'Expected phrases or sample text for this document type — one phrase per line. '
            'Uploaded files are scanned (PDF/image/DOCX) and must contain enough matching phrases.'
        ),
    )
    content_validation_min_matches = models.PositiveSmallIntegerField(
        default=1,
        help_text='Minimum number of sample phrases that must appear in the upload.',
    )
    content_validation_strict = models.BooleanField(
        default=True,
        help_text='If checked, uploads that fail content validation are rejected before save.',
    )
    content_extraction_mappings = models.TextField(
        blank=True,
        help_text=(
            'Auto-fill appraisal fields from this document — one per line: '
            'field_name=Label in document, or field_name=regex:pattern. '
            'Example: tin_number=TIN  business_name=Business Name'
        ),
    )
    reference_sample = models.FileField(
        upload_to='document_type_samples/%Y/%m/',
        blank=True,
        null=True,
        help_text='Official blank/sample PDF or image — system learns validation phrases from this file.',
    )
    reference_sample_profile = models.JSONField(
        default=dict,
        blank=True,
        help_text='Auto-generated OCR profile from reference_sample (phrases, mappings, similarity).',
    )
    reference_sample_analyzed_at = models.DateTimeField(null=True, blank=True)
    use_reference_sample_validation = models.BooleanField(
        default=True,
        help_text='Compare uploads to the analyzed reference sample (in addition to manual phrases).',
    )
    reference_min_similarity = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=Decimal('0.080'),
        help_text='Minimum text similarity (0–1) vs reference sample. Lower = more lenient for scans.',
    )

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Loan application document type'
        verbose_name_plural = 'Loan application document types'

    def __str__(self):
        return self.name

    def _global_auth_defaults(self):
        policy = DocumentAuthenticationPolicy.objects.first()
        if policy:
            return policy
        return DocumentAuthenticationPolicy()

    def get_allowed_extensions_list(self):
        raw = (self.allowed_extensions or '').strip()
        if not raw:
            raw = self._global_auth_defaults().allowed_extensions
        return [x.strip().lstrip('.').lower() for x in raw.split(',') if x.strip()]

    def get_max_file_size_mb(self) -> int:
        if self.max_file_size_mb:
            return self.max_file_size_mb
        return self._global_auth_defaults().max_file_size_mb

    def get_accept_attribute(self) -> str:
        exts = self.get_allowed_extensions_list()
        return ','.join(f'.{e}' for e in exts)

    def get_identity_match_field_list(self) -> list:
        raw = (self.identity_match_fields or 'applicant_name,phone_number,tin_number').strip()
        return [x.strip() for x in raw.split(',') if x.strip()]

    def get_content_validation_phrases(self) -> list:
        phrases = []
        for line in (self.content_validation_sample or '').splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                phrases.append(line)
        return phrases

    def has_content_validation(self) -> bool:
        if self.use_reference_sample_validation and self.reference_sample:
            profile = self.reference_sample_profile or {}
            if profile.get('validation_phrases'):
                return True
        return bool(self.get_content_validation_phrases())

    def get_effective_validation_phrases(self) -> list:
        manual = self.get_content_validation_phrases()
        profile = self.reference_sample_profile or {}
        ref_phrases = profile.get('validation_phrases') or []
        if self.use_reference_sample_validation and ref_phrases:
            if manual:
                merged = list(manual)
                for p in ref_phrases:
                    if p not in merged:
                        merged.append(p)
                return merged
            return list(ref_phrases)
        return manual

    def has_reference_sample(self) -> bool:
        return bool(self.reference_sample)

    def get_extraction_mappings(self) -> list:
        from loans.services.appraisal_prefill import parse_extraction_mappings
        return parse_extraction_mappings(self.content_extraction_mappings)

    def auth_checks_summary(self) -> str:
        parts = [f'{self.get_max_file_size_mb()}MB', '/'.join(self.get_allowed_extensions_list())]
        if self.has_reference_sample():
            parts.append('ref sample')
        if self.has_content_validation():
            n = len(self.get_effective_validation_phrases())
            parts.append(f'content≥{self.content_validation_min_matches}/{n}')
        if (self.content_extraction_mappings or '').strip():
            parts.append(f'extract:{len(self.get_extraction_mappings())}')
        if self.require_officer_verification:
            parts.append('officer verify')
        if self.enable_ocr_match:
            fields = ','.join(self.get_identity_match_field_list())
            parts.append(f'OCR({fields})')
            if self.identity_match_strict:
                parts.append('identity strict')
        if self.enable_llm_check:
            parts.append('LLM')
        if self.enable_external_id:
            parts.append('ext. ID')
        return ' · '.join(parts)


class CollateralEstimationConfig(models.Model):
    """
    Bank-wide config: who does collateral estimation.
    One row only (managed in admin). When 'loan_officer', branch manager assigns loan officer.
    When 'engineering_team', branch manager sends to engineering head who then assigns an engineer.
    When 'both', either can be used: loan officers see their assigned loans, engineers see theirs.
    """
    MODE_LOAN_OFFICER = 'loan_officer'
    MODE_ENGINEERING_TEAM = 'engineering_team'
    MODE_BOTH = 'both'
    MODE_CHOICES = [
        (MODE_LOAN_OFFICER, 'Loan Officer (branch manager assigns loan officer)'),
        (MODE_ENGINEERING_TEAM, 'Engineering Team (branch manager sends to engineering head; engineering head assigns engineer)'),
        (MODE_BOTH, 'Both (loan officers and engineering team can both be used)'),
    ]
    mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default=MODE_LOAN_OFFICER,
        help_text='Who performs collateral estimation: loan officer, engineering team, or both.',
    )

    class Meta:
        verbose_name = 'Collateral estimation config'
        verbose_name_plural = 'Collateral estimation config'

    def __str__(self):
        return dict(self.MODE_CHOICES).get(self.mode, self.mode)

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('superadmin', 'Super Administrator'),
        ('admin', 'System Administrator'),
        ('engineering_head', 'Engineering Head'),
        ('engineer', 'Engineer / Valuer'),
        ('loan_officer', 'Loan Officer'),
        ('branch_manager', 'Branch Manager'),
        ('accountant', 'Accountant'),
        ('district_manager', 'District Manager'),
        ('operation_manager', 'Operation Manager'),
        ('finance_manager', 'Finance Manager'),
        ('credit_committee', 'Credit Committee Member'),
        ('ceo', 'Chief Executive Officer'),
        ('vp', 'Vice President'),
        ('board_member', 'Board Member'),
        ('risk_compliance', 'Risk & Compliance Officer'),
        ('auditor', 'Auditor / Viewer'),
    ]
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='loan_officer')
    phone_number = models.CharField(max_length=20)
    district = models.ForeignKey(District, on_delete=models.SET_NULL, null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)

# loans/models.py
class LatestLoanRequestID(models.Model):
    latest_id = models.BigIntegerField(default=0)

    def __str__(self):
        return str(self.latest_id)
    
# loans/models.py

class LoanRequest(models.Model):
    loan_request_id = models.CharField(max_length=22, unique=True)
    applicant_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=15, default='0953333311')
    email = models.EmailField(null=True, blank=True)
    category = models.ForeignKey(LoanCategory, on_delete=models.CASCADE)
    collateral = models.ForeignKey(CollateralType, on_delete=models.CASCADE)
    amount_requested = models.DecimalField(max_digits=20, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, null=True, blank=True)
    operation_manager_approval = models.BooleanField(default=False)
    finance_approval = models.BooleanField(default=False)
    # date_requested = models.DateTimeField(auto_now_add=True)
    date_requested = models.DateTimeField(default=timezone.now)
    date_reviewed = models.DateTimeField(null=True, blank=True)
    district = models.ForeignKey(District, on_delete=models.CASCADE, null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    queue_approved = models.BooleanField(
        default=False,
        help_text="When True, loan is eligible for collateral valuation workflow.",
    )
    customer_history = models.CharField(null=True, blank=True, max_length=50, choices=[('new', 'New'), ('existing', 'Existing')])
    assigned_loan_officer = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_loan_requests',
        limit_choices_to={'role': 'loan_officer'},
        help_text='Loan officer assigned by branch manager for analysis and collateral estimation.',
    )
    collateral_submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the loan officer submitted the collateral estimation (summary). All building valuations, land, other collateral are saved when submitted.',
    )
    collateral_submitted_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collateral_submissions',
        help_text='User (e.g. loan officer) who submitted the collateral estimation.',
    )
    ENG_COLLATERAL_NA = ''
    ENG_COLLATERAL_PENDING = 'pending_review'
    ENG_COLLATERAL_APPROVED = 'approved'
    ENG_COLLATERAL_RETURNED = 'returned'
    COLLATERAL_ENGINEERING_STATUS_CHOICES = [
        (ENG_COLLATERAL_NA, 'Not applicable'),
        (ENG_COLLATERAL_PENDING, 'Pending engineering review'),
        (ENG_COLLATERAL_APPROVED, 'Engineering approved'),
        (ENG_COLLATERAL_RETURNED, 'Returned for correction'),
    ]
    collateral_engineering_status = models.CharField(
        max_length=30,
        choices=COLLATERAL_ENGINEERING_STATUS_CHOICES,
        default=ENG_COLLATERAL_NA,
        blank=True,
        help_text='Engineering QA after collateral submit (when engineering team mode is enabled).',
    )
    collateral_engineering_reviewed_at = models.DateTimeField(null=True, blank=True)
    collateral_engineering_reviewed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collateral_engineering_reviews',
    )
    collateral_engineering_return_note = models.TextField(blank=True)
    declared_address_text = models.TextField(
        blank=True,
        help_text='Cached address text used for geocoding (from Sheet 1).',
    )
    declared_address_lat = models.DecimalField(
        max_digits=12, decimal_places=8, null=True, blank=True,
    )
    declared_address_lon = models.DecimalField(
        max_digits=12, decimal_places=8, null=True, blank=True,
    )
    declared_address_geocoded_at = models.DateTimeField(null=True, blank=True)
    declared_address_source = models.CharField(
        max_length=20, blank=True,
        help_text='business or home — which Sheet 1 address was geocoded.',
    )
    sent_to_engineering_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When branch manager sent this loan to engineering head for collateral estimation.',
    )
    assigned_engineer = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_engineer_loan_requests',
        limit_choices_to={'role': 'engineer'},
        help_text='Engineer assigned by engineering head for collateral estimation (when mode is Engineering Team).',
    )
    documents_reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the assigned loan officer or engineer marked documents reviewed and proceeded to collateral.',
    )
    documents_reviewed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_requests_documents_reviewed',
        help_text='Loan officer or engineer who reviewed documents and proceeded to collateral estimation.',
    )

    COMMITTEE_NOT_SUBMITTED = ''
    COMMITTEE_PENDING = 'pending_committee'
    COMMITTEE_APPROVED = 'committee_approved'
    COMMITTEE_DECLINED = 'committee_declined'
    COMMITTEE_RETURNED = 'returned_to_officer'
    COMMITTEE_STATUS_CHOICES = [
        (COMMITTEE_NOT_SUBMITTED, 'Not submitted'),
        (COMMITTEE_PENDING, 'Pending committee'),
        (COMMITTEE_APPROVED, 'Committee approved'),
        (COMMITTEE_DECLINED, 'Committee declined'),
        (COMMITTEE_RETURNED, 'Returned to loan officer'),
    ]

    appraisal_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the assigned loan officer finished appraisal (Sheet 7).',
    )
    committee_status = models.CharField(
        max_length=30,
        choices=COMMITTEE_STATUS_CHOICES,
        default=COMMITTEE_NOT_SUBMITTED,
        blank=True,
        help_text='Credit committee workflow status (separate from queue op/finance approval).',
    )
    submitted_to_committee_at = models.DateTimeField(null=True, blank=True)
    submitted_to_committee_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_requests_submitted_to_committee',
        limit_choices_to={'role': 'loan_officer'},
    )
    committee_submission_notes = models.TextField(
        blank=True,
        help_text='Loan officer notes when submitting to the approval committee.',
    )
    committee_final_decision = models.CharField(
        max_length=20,
        blank=True,
        choices=[('approve', 'Approve'), ('decline', 'Decline')],
    )
    committee_final_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Final amount after committee majority decision.',
    )
    committee_decided_at = models.DateTimeField(null=True, blank=True)
    current_approval_level = models.ForeignKey(
        'ApprovalCommitteeLevel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_requests_at_level',
        help_text='Active approval level (branch → district → head office → management).',
    )
    committee_return_notes = models.TextField(
        blank=True,
        help_text='Committee feedback when returned to the loan officer for corrections.',
    )
    committee_returned_at = models.DateTimeField(null=True, blank=True)
    committee_returned_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_requests_returned_to_officer',
    )

    # def save(self, *args, **kwargs):
    #     # If this is a new record without a status, apply system rules
    #     if not self.status:
    #         if self.operation_manager_approval and self.finance_approval:
    #             self.status = 'Approved'
    #         else:
    #             self.status = 'pending'
    #     # Otherwise, preserve whatever status is already set (e.g., during migration)
    #     super(LoanRequest, self).save(*args, **kwargs)
    
    def managers_queue_approved(self) -> bool:
        """Initial queue gate: operation + finance managers (before loan officer / engineering)."""
        return self.operation_manager_approval and self.finance_approval

    def committee_allows_final_approval(self) -> bool:
        """Post-appraisal credit committee decision (separate from initial manager queue)."""
        return self.committee_status == self.COMMITTEE_APPROVED

    def committee_approval_block_reason(self) -> str:
        if self.committee_status == self.COMMITTEE_APPROVED:
            return ''
        if self.committee_status == self.COMMITTEE_PENDING:
            return 'Loan is still in the approval committee workflow.'
        if self.committee_status == self.COMMITTEE_RETURNED:
            return 'Loan was returned to the loan officer — resubmit to committee after corrections.'
        if self.committee_status == self.COMMITTEE_DECLINED:
            return 'Loan was declined by the approval committee.'
        if self.appraisal_completed_at:
            return 'Loan must be submitted and approved by the credit committee.'
        return 'Complete appraisal and submit to the credit committee.'

    def save(self, *args, **kwargs):
        if self.managers_queue_approved():
            self.status = 'Approved'
            self.queue_approved = True
            if not self.date_reviewed:
                self.date_reviewed = timezone.now()
        elif self.status != 'Rejected':
            self.status = 'Pending'
            self.queue_approved = False

        super(LoanRequest, self).save(*args, **kwargs)


class LoanRequestDocument(models.Model):
    """An uploaded document attached to a loan request (e.g. ID, proof of income)."""
    AUTH_PENDING = 'pending'
    AUTH_AUTO_PASSED = 'auto_passed'
    AUTH_NEEDS_REVIEW = 'needs_review'
    AUTH_VERIFIED = 'verified'
    AUTH_REJECTED = 'rejected'
    AUTH_STATUS_CHOICES = [
        (AUTH_PENDING, 'Pending checks'),
        (AUTH_AUTO_PASSED, 'Auto-passed (integrity OK)'),
        (AUTH_NEEDS_REVIEW, 'Needs manual review'),
        (AUTH_VERIFIED, 'Verified authentic'),
        (AUTH_REJECTED, 'Rejected / not authentic'),
    ]
    VERDICT_AUTHENTIC = 'authentic'
    VERDICT_SUSPICIOUS = 'suspicious'
    VERDICT_NOT_AUTHENTIC = 'not_authentic'
    VERDICT_INCONCLUSIVE = 'inconclusive'
    AUTH_VERDICT_CHOICES = [
        (VERDICT_AUTHENTIC, 'Authentic'),
        (VERDICT_SUSPICIOUS, 'Suspicious'),
        (VERDICT_NOT_AUTHENTIC, 'Not authentic'),
        (VERDICT_INCONCLUSIVE, 'Inconclusive'),
    ]

    loan_request = models.ForeignKey(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name='application_documents',
    )
    document_type = models.ForeignKey(
        LoanApplicationDocumentType,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    file = models.FileField(upload_to='loan_application_docs/%Y/%m/')
    original_filename = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    uploaded_at = models.DateTimeField(default=timezone.now)
    uploaded_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_documents_uploaded',
    )
    auth_status = models.CharField(max_length=20, choices=AUTH_STATUS_CHOICES, default=AUTH_PENDING)
    auth_verdict = models.CharField(max_length=20, choices=AUTH_VERDICT_CHOICES, null=True, blank=True)
    auth_notes = models.TextField(blank=True)
    automated_checks = models.JSONField(default=dict, blank=True)
    authenticated_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_documents_authenticated',
    )
    authenticated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['document_type__order', 'document_type__name', 'uploaded_at']
        verbose_name = 'Loan request document'
        verbose_name_plural = 'Loan request documents'

    def __str__(self):
        return f'{self.document_type.name} – {self.loan_request.loan_request_id}'

    def get_display_filename(self) -> str:
        if self.original_filename:
            return self.original_filename
        if self.file:
            return self.file.name.split('/')[-1]
        return ''

    def get_file_extension(self) -> str:
        name = self.get_display_filename()
        if '.' not in name:
            return ''
        return name.rsplit('.', 1)[-1].lower()

    def is_viewable_inline(self) -> bool:
        return self.get_file_extension() in ('pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp')

    def file_is_available(self) -> bool:
        if not self.file:
            return False
        try:
            return self.file.storage.exists(self.file.name)
        except Exception:
            return False


class LoanDocumentRequest(models.Model):
    """Request by assigned loan officer or engineer for a document type (branch manager can then upload)."""
    loan_request = models.ForeignKey(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name='document_requests',
    )
    document_type = models.ForeignKey(
        LoanApplicationDocumentType,
        on_delete=models.CASCADE,
        related_name='loan_requests_requested',
    )
    requested_by = models.ForeignKey(
        'CustomUser',
        on_delete=models.CASCADE,
        related_name='document_requests_made',
    )
    requested_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-requested_at']
        verbose_name = 'Loan document request'
        verbose_name_plural = 'Loan document requests'
        unique_together = [('loan_request', 'document_type')]  # one pending request per type per loan

    def __str__(self):
        return f'{self.document_type.name} for {self.loan_request.loan_request_id}'


class LoanRequestBasicInfo(models.Model):
    """
    Sheet (1) Basic Info and loan request – client, business, and loan request details.
    One-to-one with LoanRequest. Data we don't already have on LoanRequest.
    """
    loan_request = models.OneToOneField(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name='basic_info',
    )

    # ----- Client (personal) -----
    tin_number = models.CharField(max_length=50, null=True, blank=True)
    gender = models.CharField(max_length=20, null=True, blank=True, choices=[('Male', 'Male'), ('Female', 'Female')])
    age = models.PositiveIntegerField(null=True, blank=True)
    MARITAL_SINGLE = 'Single'
    MARITAL_MARRIED = 'Married'
    MARITAL_DIVORCED = 'Divorced'
    MARITAL_WIDOWED = 'Widowed'
    MARITAL_CHOICES = [(MARITAL_SINGLE, 'Single'), (MARITAL_MARRIED, 'Married'), (MARITAL_DIVORCED, 'Divorced'), (MARITAL_WIDOWED, 'Widowed')]
    marital_status = models.CharField(max_length=30, null=True, blank=True, choices=MARITAL_CHOICES)
    EDUCATION_NONE = 'None'
    EDUCATION_PRIMARY = 'Primary'
    EDUCATION_SECONDARY = 'Secondary'
    EDUCATION_COLLEGE = 'College'
    EDUCATION_BA = 'BA and above'
    EDUCATION_CHOICES = [(EDUCATION_NONE, 'None'), (EDUCATION_PRIMARY, 'Primary'), (EDUCATION_SECONDARY, 'Secondary'), (EDUCATION_COLLEGE, 'College'), (EDUCATION_BA, 'BA and above')]
    education_level = models.CharField(max_length=100, null=True, blank=True, choices=EDUCATION_CHOICES)
    home_address = models.TextField(null=True, blank=True)
    spouse_name = models.CharField(max_length=255, null=True, blank=True)
    spouse_occupation = models.CharField(max_length=255, null=True, blank=True)
    father_name = models.CharField(max_length=255, null=True, blank=True)
    grandfather_name = models.CharField(max_length=255, null=True, blank=True)

    # ----- Business -----
    business_name = models.CharField(max_length=255, null=True, blank=True)
    business_description = models.TextField(null=True, blank=True)
    business_address = models.TextField(null=True, blank=True)
    date_business_started = models.DateField(null=True, blank=True)
    OWNERSHIP_SOLE = 'Sole Proprietorship'
    OWNERSHIP_PLC = 'PLC'
    OWNERSHIP_PARTNERSHIP = 'Partnership'
    OWNERSHIP_ASSOCIATION = 'Association'
    OWNERSHIP_SHARE = 'Share Company'
    OWNERSHIP_CHOICES = [(OWNERSHIP_SOLE, 'Sole Proprietorship'), (OWNERSHIP_PLC, 'PLC'), (OWNERSHIP_PARTNERSHIP, 'Partnership'), (OWNERSHIP_ASSOCIATION, 'Association'), (OWNERSHIP_SHARE, 'Share Company')]
    form_of_ownership = models.CharField(max_length=100, null=True, blank=True, choices=OWNERSHIP_CHOICES)
    SECTOR_MANUFACTURING = 'Manufacturing'
    SECTOR_TRADE = 'Trade'
    SECTOR_SERVICE = 'Service'
    SECTOR_CONSTRUCTION = 'Construction'
    SECTOR_AGRICULTURE = 'Agriculture'
    SECTOR_CHOICES = [(SECTOR_MANUFACTURING, 'Manufacturing'), (SECTOR_TRADE, 'Trade'), (SECTOR_SERVICE, 'Service'), (SECTOR_CONSTRUCTION, 'Construction'), (SECTOR_AGRICULTURE, 'Agriculture')]
    economic_sector = models.CharField(max_length=100, null=True, blank=True, choices=SECTOR_CHOICES)
    subsector_activity = models.CharField(max_length=255, null=True, blank=True)
    employees_full_time = models.PositiveIntegerField(null=True, blank=True)
    employees_part_time = models.PositiveIntegerField(null=True, blank=True)
    employees_seasonal = models.PositiveIntegerField(null=True, blank=True)
    employees_ft_equivalent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    family_members_employed = models.PositiveIntegerField(null=True, blank=True)
    peak_sales_months = models.CharField(max_length=100, null=True, blank=True)
    lowest_sales_months = models.CharField(max_length=100, null=True, blank=True)
    number_business_owners = models.PositiveIntegerField(null=True, blank=True)

    # ----- Loan request (additional to LoanRequest.amount_requested, etc.) -----
    term_months = models.PositiveIntegerField(null=True, blank=True)
    FREQ_BIWEEKLY = 'Bi-Weekly'
    FREQ_MONTHLY = 'Monthly'
    FREQ_QUARTERLY = 'Quarterly'
    FREQ_SEMI = 'Semi-annual'
    FREQ_ANNUAL = 'Annual'
    REPAYMENT_FREQUENCY_CHOICES = [(FREQ_BIWEEKLY, 'Bi-Weekly'), (FREQ_MONTHLY, 'Monthly'), (FREQ_QUARTERLY, 'Quarterly'), (FREQ_SEMI, 'Semi-annual'), (FREQ_ANNUAL, 'Annual')]
    repayment_frequency = models.CharField(max_length=50, null=True, blank=True, choices=REPAYMENT_FREQUENCY_CHOICES)
    interest_rate = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    INTEREST_DECLINING = 'Declining'
    INTEREST_FLAT = 'Flat'
    INTEREST_BASIS_CHOICES = [(INTEREST_DECLINING, 'Declining'), (INTEREST_FLAT, 'Flat')]
    interest_basis = models.CharField(max_length=50, null=True, blank=True, choices=INTEREST_BASIS_CHOICES)
    grace_period_months = models.PositiveIntegerField(null=True, blank=True)
    interest_only_months = models.PositiveIntegerField(null=True, blank=True)
    instalments_per_year = models.PositiveIntegerField(null=True, blank=True)
    cash_contribution = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    # Per-field provenance for Sheet 1 (registration / document / banking / manual / default).
    # Shape: {field_name: {"source": "...", "label": "...", "document_id": optional}}
    field_sources = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f'Basic info – {self.loan_request.loan_request_id}'


class LoanAppraisal(models.Model):
    """
    Cashflow-based loan appraisal linked to a loan request.
    One appraisal per loan request, created by the assigned loan officer.
    """
    RECOMMEND_APPROVE = 'approve'
    RECOMMEND_DECLINE = 'decline'
    RECOMMEND_ESCALATE = 'escalate'
    RECOMMEND_CHOICES = [
        (RECOMMEND_APPROVE, 'Approve'),
        (RECOMMEND_DECLINE, 'Decline'),
        (RECOMMEND_ESCALATE, 'Escalate / further review'),
    ]

    loan_request = models.OneToOneField(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name='appraisal',
    )
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_appraisals_created',
        help_text='Loan officer who created this appraisal.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Financial / cashflow analysis
    monthly_business_income = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    monthly_business_expenses = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    other_monthly_income = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    other_monthly_expenses = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    proposed_monthly_installment = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    net_monthly_cashflow = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Calculated as (business + other income) – (business + other expenses).',
    )
    dscr = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Debt service coverage ratio (net cashflow / proposed installment).',
    )

    # Sheet (3) Phase 1 – P&L breakdown (monthly)
    cf_monthly_sales = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cf_monthly_cogs = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cf_monthly_salaries = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cf_monthly_rent = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cf_monthly_utilities = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cf_monthly_transport = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cf_monthly_other_operating = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cf_monthly_taxes = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cf_annual_net_cashflow = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    cf_annual_debt_service = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    dscr_annual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Bureau / credit score summary
    BUREAU_BAND_EXCELLENT = 'excellent'
    BUREAU_BAND_GOOD = 'good'
    BUREAU_BAND_FAIR = 'fair'
    BUREAU_BAND_POOR = 'poor'
    BUREAU_BAND_THIN = 'thin'
    BUREAU_BAND_CHOICES = [
        (BUREAU_BAND_EXCELLENT, 'Excellent'),
        (BUREAU_BAND_GOOD, 'Good'),
        (BUREAU_BAND_FAIR, 'Fair'),
        (BUREAU_BAND_POOR, 'Poor'),
        (BUREAU_BAND_THIN, 'Thin file / No bureau'),
    ]
    bureau_score = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    bureau_score_band = models.CharField(max_length=20, choices=BUREAU_BAND_CHOICES, null=True, blank=True)
    bureau_report_date = models.DateField(null=True, blank=True)
    bureau_active_loans_count = models.PositiveIntegerField(null=True, blank=True)
    bureau_total_outstanding = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    bureau_total_monthly_debt_service = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    bureau_inquiries_6m = models.PositiveIntegerField(null=True, blank=True)
    bureau_defaults_ever = models.BooleanField(null=True, blank=True)
    bureau_restructured_ever = models.BooleanField(null=True, blank=True)
    bureau_thin_file = models.BooleanField(null=True, blank=True)

    # Stress test
    stress_sales_drop_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    stress_cost_increase_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    stressed_net_monthly_cashflow = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    stressed_dscr = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # ----- Sheet (2) Business & character assessment -----
    nbe_credit_report_obtained = models.BooleanField(null=True, blank=True, help_text='NBE Credit Report obtained (Y/N).')
    nbe_report_date_received = models.DateField(null=True, blank=True)
    total_number_repaid_loans = models.PositiveIntegerField(null=True, blank=True)
    credit_history_max_score = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    qualitative_total_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Business and character total score (0–100). Applicant needs ≥75% to proceed.',
    )
    qualitative_passed = models.BooleanField(
        null=True,
        blank=True,
        help_text='True if qualitative assessment passed (≥75%). Proceed to Cashflow Analysis.',
    )
    business_assessment = models.TextField(null=True, blank=True, help_text='Summary of business assessment.')
    character_assessment = models.TextField(null=True, blank=True, help_text='Summary of character / E&S assessment.')

    # ----- Sheet (4) E&S Assessment -----
    ES_RISK_LOW = 'low'
    ES_RISK_MEDIUM = 'medium'
    ES_RISK_HIGH = 'high'
    ES_RISK_CHOICES = [
        (ES_RISK_LOW, 'Low'),
        (ES_RISK_MEDIUM, 'Medium'),
        (ES_RISK_HIGH, 'High'),
    ]
    ES_ELIGIBILITY_PASS = 'pass'
    ES_ELIGIBILITY_PASS_ACTION = 'pass_action'
    ES_ELIGIBILITY_REJECT = 'reject'
    ES_ELIGIBILITY_CHOICES = [
        (ES_ELIGIBILITY_PASS, 'PASS'),
        (ES_ELIGIBILITY_PASS_ACTION, 'PASS WITH ACTION POINTS'),
        (ES_ELIGIBILITY_REJECT, 'REJECT'),
    ]
    es_risk_category = models.CharField(
        max_length=20, choices=ES_RISK_CHOICES, null=True, blank=True,
        help_text='E&S risk category.',
    )
    es_eligibility_decision = models.CharField(
        max_length=20, choices=ES_ELIGIBILITY_CHOICES, null=True, blank=True,
        help_text='Decision on eligibility: PASS / PASS WITH ACTION POINTS / REJECT.',
    )
    es_screened_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='es_screened_appraisals',
    )
    es_checked_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='es_checked_appraisals',
    )
    es_approved_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='es_approved_appraisals',
    )
    es_assessment_date = models.DateField(null=True, blank=True)
    es_notes = models.TextField(null=True, blank=True, help_text='E&S checklist summary / action points.')

    # ----- Sheet (5) Collateral Worksheet -----
    collateral_total_value = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Total collateral value considered in this appraisal (snapshot).',
    )
    collateral_immovable_value = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text='Immovable (land/buildings) value.',
    )
    collateral_moveable_value = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text='Moveable / fixed deposits value.',
    )
    collateral_intangible_value = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text='Intangible / securities / contracts value.',
    )
    collateral_guarantors_value = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text='Guarantors value.',
    )
    collateral_coverage_ratio = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Collateral coverage (total collateral / loan amount).',
    )

    # ----- Sheet (6) Summary & decision -----
    recommendation = models.CharField(
        max_length=20,
        choices=RECOMMEND_CHOICES,
        null=True,
        blank=True,
    )
    recommendation_comment = models.TextField(
        null=True,
        blank=True,
        help_text='Reasoning behind the recommendation.',
    )
    strengths = models.TextField(null=True, blank=True, help_text='Key strengths.')
    weaknesses = models.TextField(null=True, blank=True, help_text='Key weaknesses.')
    committee_comments = models.TextField(null=True, blank=True, help_text='Credit committee comments.')
    amount_approved = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text='Amount approved by committee (if different from requested).',
    )
    term_approved_months = models.PositiveIntegerField(null=True, blank=True, help_text='Term approved (months).')
    rate_approved = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Interest rate approved (%).',
    )

    # Credit scorecard (explainable, AI-ready) — computed on Sheet 6 / finish
    credit_score_total = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text='Composite 0–100 explainable credit score.',
    )
    credit_score_band = models.CharField(max_length=20, null=True, blank=True)
    scorecard_detail = models.JSONField(
        null=True, blank=True, default=dict,
        help_text='Pillars + contributions for explainability / training.',
    )
    feature_snapshot = models.JSONField(
        null=True, blank=True,
        help_text='Versioned appraisal_features_v1 JSON for future ML.',
    )
    suggested_monthly_installment = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
        help_text='Suggested installment from Sheet 1 terms (not from rate workbook).',
    )
    max_loan_capacity = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text='Max loan capacity from cashflow at target DSCR.',
    )

    def __str__(self):
        return f'Appraisal for {self.loan_request.loan_request_id}'


class AppraisalRiskMitigation(models.Model):
    """Sheet (6) – structured risks and mitigations."""
    SEVERITY_LOW = 'low'
    SEVERITY_MEDIUM = 'medium'
    SEVERITY_HIGH = 'high'
    SEVERITY_CHOICES = [
        (SEVERITY_LOW, 'Low'),
        (SEVERITY_MEDIUM, 'Medium'),
        (SEVERITY_HIGH, 'High'),
    ]

    appraisal = models.ForeignKey(
        LoanAppraisal,
        on_delete=models.CASCADE,
        related_name='risk_mitigations',
    )
    risk = models.CharField(max_length=255, help_text='Risk statement (what could go wrong).')
    severity = models.CharField(
        max_length=10,
        choices=SEVERITY_CHOICES,
        null=True,
        blank=True,
    )
    mitigation = models.TextField(
        null=True,
        blank=True,
        help_text='Mitigation / control / condition to reduce the risk.',
    )
    owner = models.CharField(
        max_length=120,
        null=True,
        blank=True,
        help_text='Who will implement the mitigation (e.g., client, branch, credit).',
    )
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        help_text='Open / In progress / Done (free text).',
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return f'{self.risk[:50]} – {self.appraisal.loan_request.loan_request_id}'


class AppraisalCondition(models.Model):
    """Sheet (6) – conditions precedent / covenants."""
    TYPE_CP = 'cp'
    TYPE_COVENANT = 'covenant'
    TYPE_OTHER = 'other'
    TYPE_CHOICES = [
        (TYPE_CP, 'Condition precedent'),
        (TYPE_COVENANT, 'Covenant / monitoring'),
        (TYPE_OTHER, 'Other'),
    ]

    appraisal = models.ForeignKey(
        LoanAppraisal,
        on_delete=models.CASCADE,
        related_name='conditions',
    )
    condition_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        null=True,
        blank=True,
    )
    description = models.TextField(help_text='Condition text (clear and measurable).')
    responsible_party = models.CharField(max_length=120, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    fulfilled = models.BooleanField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return f'{self.description[:50]} – {self.appraisal.loan_request.loan_request_id}'


class AppraisalCreditHistoryEntry(models.Model):
    """Sheet (2) – one row per existing loan/lease in credit history."""
    STATUS_REGULAR = 'regular'
    STATUS_SETTLED_ON_TIME = 'settled_on_time'
    STATUS_SETTLED_LATE = 'settled_late'
    STATUS_IRREGULAR = 'irregular'
    STATUS_DEFAULTED = 'defaulted'
    STATUS_NONE = 'none'
    STATUS_CHOICES = [
        (STATUS_REGULAR, 'Regular'),
        (STATUS_SETTLED_ON_TIME, 'Settled on time'),
        (STATUS_SETTLED_LATE, 'Settled late'),
        (STATUS_IRREGULAR, 'Irregular'),
        (STATUS_DEFAULTED, 'Defaulted'),
        (STATUS_NONE, 'None'),
    ]
    appraisal = models.ForeignKey(
        LoanAppraisal,
        on_delete=models.CASCADE,
        related_name='credit_history_entries',
    )
    lender = models.CharField(max_length=255, null=True, blank=True)
    loan_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    current_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    maturity_date = models.DateField(null=True, blank=True)
    PURPOSE_CHOICES = [('Working capital', 'Working capital'), ('Fixed Asset', 'Fixed Asset')]
    purpose = models.CharField(max_length=255, null=True, blank=True, choices=PURPOSE_CHOICES)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, null=True, blank=True)
    REPAYMENT_CHOICES = [('Regular', 'Regular'), ('Irregular', 'Irregular'), ('On time', 'On time'), ('Delayed', 'Delayed')]
    repayment = models.CharField(max_length=100, null=True, blank=True, choices=REPAYMENT_CHOICES)
    LETTER_CHOICES = [('Yes', 'Yes'), ('No', 'No')]
    letter_from_lender = models.CharField(max_length=100, null=True, blank=True, choices=LETTER_CHOICES)
    score = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return f'{self.lender} – {self.appraisal.loan_request.loan_request_id}'


# Per-factor rating options from Excel Sheet (2)
QUALITATIVE_RATING_CHOICES_BY_FACTOR = {
    'years_operation': [
        'Startup (< 6months)', '6-12 months', '12-24 months', '> 24 months',
    ],
    'management_competence': [
        'Competent/ well performing', 'Average/Adequate business skills', 'Below average',
    ],
    'supplier_quality': [
        'Very reliable supply chain', 'Satisfactory/ Adequate supply chain', 'Often face challenge',
    ],
    'sales_prospects': [
        'Very good/ High demand projection', 'Adequate demand projection', 'Unrelaible demand projection',
    ],
    'project_plan': ['Well planned', 'Some gaps', 'unclear'],
    'savings_record': [
        'Regular pattern/ verified saving habit', 'Some savings habit', 'No savings habit',
    ],
    'character': [
        'Cooperative/shared all relevant info/doc ',
        'Average-Provided some but not all',
        'Not willing to share any documents',
    ],
    'asset_management': [
        'Financial record all in order', 'Basic record keeping',
        'inconsistent record of daily sales/ expenses',
    ],
    'record_keeping': [
        'Financial record all in order', 'Basic record keeping',
        'inconsistent record of daily sales/ expenses',
    ],
    'third_party_opinion': ['Positive, Respected', 'Moderate', 'No feedback received'],
}


def qualitative_rating_field_choices(factor_key):
    opts = QUALITATIVE_RATING_CHOICES_BY_FACTOR.get(factor_key) or []
    return [('', '—')] + [(v, v) for v in opts]


QUALITATIVE_RATING_CHOICES = [
    ('', '—'),
    ('Poor', 'Poor'),
    ('basic', 'Basic'),
    ('Professional', 'Professional'),
]

# 10 factors from Sheet (2) Bus. and Character Assess. – fixed list
QUALITATIVE_FACTOR_KEYS = [
    ('years_operation', 'Years of business operation'),
    ('management_competence', 'Management competence'),
    ('supplier_quality', 'Supplier quality'),
    ('sales_prospects', 'Sales prospects / market suitability'),
    ('project_plan', 'Project plan (preparation)'),
    ('savings_record', 'Savings record'),
    ('character', 'Character'),
    ('asset_management', 'Record keeping and asset management'),
    ('record_keeping', 'Record keeping'),
    ('third_party_opinion', '3rd party opinion'),
]


class AppraisalQualitativeFactor(models.Model):
    """Sheet (2) – one row per qualitative factor (10 factors). Rating and notes per factor."""
    appraisal = models.ForeignKey(
        LoanAppraisal,
        on_delete=models.CASCADE,
        related_name='qualitative_factors',
    )
    factor_key = models.CharField(max_length=50)  # e.g. years_operation
    factor_name = models.CharField(max_length=255, null=True, blank=True)
    rating = models.CharField(max_length=255, null=True, blank=True)
    weight = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Excel weight / maximum score for this factor.',
    )
    earned_score = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Excel earned score based on selected rating.',
    )
    notes = models.TextField(null=True, blank=True, help_text='Observation / justification.')
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']
        unique_together = [('appraisal', 'factor_key')]

    def __str__(self):
        return f'{self.factor_key} – {self.appraisal.loan_request.loan_request_id}'


# Sheet (4) E&S – structured checklist (21 questions)
ES_CHECKLIST_STRUCTURE = [
    (
        'exposure',
        'Exposure & compliance',
        [
            (
                'excluded_activities',
                'Does or will the client carry out any activities listed on the List of Excluded Activities? '
                '(If yes, describe in the adjacent column.)',
            ),
            ('owner_of_premises', 'Are you the owner of the premises of the business?'),
            ('displacement', 'Would the proposed activity involve the displacement of people?'),
            (
                'green_area',
                'Is the proposed activity situated within a green area designated by the municipality?',
            ),
            ('child_labour', 'Would the proposed project employ children under the age of 18?'),
            (
                'assistance_checklist',
                'Were you provided assistance by the project staff in filling out this checklist?',
            ),
        ],
    ),
    (
        'enterprise',
        'Enterprise & sub-project',
        [
            (
                'representative_details',
                'Name of the representative of the enterprise, function and contact details (describe).',
            ),
            ('subproject_description', 'Provide a brief technical description of the sub-project.'),
            (
                'chemicals_pesticides',
                'Would the project utilize chemicals and/or pesticides? '
                '(If yes, describe type, quantity, storage and handling.)',
            ),
        ],
    ),
    (
        'environmental',
        'Environmental aspects',
        [
            (
                'surface_water',
                'Is there a surface water body in the surroundings that could be affected by the sub-project?',
            ),
            (
                'groundwater',
                'Are there groundwater resources in the area that could be affected by the sub-project?',
            ),
            ('pollutants', 'Would the sub-project emit pollutants to air, water or soil? (If yes, describe.)'),
            ('vegetation', 'Would the sub-project involve the removal or clearance of vegetation?'),
            ('waste_types', 'List the type(s) of waste the sub-project will generate.'),
            ('waste_disposal', 'How do you plan to dispose of this waste?'),
            ('waste_minimization', 'Do you intend to have a waste minimization, recycling or recovery plan?'),
        ],
    ),
    (
        'osh',
        'Occupational health & safety',
        [
            ('labour_intensive', 'Does the enterprise engage in manufacturing or other labour-intensive activities?'),
            ('ohs_issues', 'Are there existing and/or anticipated occupational health and safety issues? (Describe.)'),
            ('ohs_reduction', 'What do you intend to do to reduce occupational health and safety risks?'),
        ],
    ),
    (
        'health',
        'Health & sanitation',
        [
            (
                'employees_health',
                'State the number of employees and describe the nature of work and any health-related concerns.',
            ),
            ('sanitation', 'Are there sanitation and hygiene services adequate for workers and the community?'),
        ],
    ),
]


def es_checklist_item_count():
    return sum(len(rows) for _s, _t, rows in ES_CHECKLIST_STRUCTURE)


class AppraisalESChecklistItem(models.Model):
    """Sheet (4) – one row per E&S checklist question."""
    YES_NO_NA_CHOICES = [
        ('', '—'),
        ('yes', 'Yes'),
        ('no', 'No'),
        ('na', 'N/A'),
    ]
    appraisal = models.ForeignKey(
        LoanAppraisal,
        on_delete=models.CASCADE,
        related_name='es_checklist_items',
    )
    section_key = models.CharField(max_length=40)
    section_label = models.CharField(max_length=120)
    item_key = models.CharField(max_length=80)
    question_text = models.TextField(help_text='Checklist question (from workbook).')
    response_yes_no = models.CharField(
        max_length=10,
        choices=YES_NO_NA_CHOICES,
        null=True,
        blank=True,
    )
    description = models.TextField(null=True, blank=True)
    mitigation = models.TextField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']
        unique_together = [('appraisal', 'item_key')]
        verbose_name = 'E&S checklist item'
        verbose_name_plural = 'E&S checklist items'

    def __str__(self):
        return f'{self.item_key} – {self.appraisal.loan_request.loan_request_id}'


class AppraisalAmortizationEntry(models.Model):
    """Sheet (7) / Loan Amortization Schedule – one row per payment."""
    appraisal = models.ForeignKey(
        LoanAppraisal,
        on_delete=models.CASCADE,
        related_name='amortization_entries',
    )
    period_number = models.PositiveIntegerField(help_text='Payment number.')
    payment_date = models.DateField(null=True, blank=True)
    payment_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    principal = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    interest = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    balance_after = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['period_number']
        verbose_name_plural = 'Appraisal amortization entries'

    def __str__(self):
        return f'#{self.period_number} – {self.appraisal.loan_request.loan_request_id}'


class LoanAnalysisPolicyConfig(models.Model):
    """Singleton: DSCR / bureau warning and hard-block thresholds for appraisal analysis."""
    warn_monthly_dscr_min = models.DecimalField(max_digits=6, decimal_places=4, default=1.2)
    warn_annual_dscr_min = models.DecimalField(max_digits=6, decimal_places=4, default=1.2)
    warn_stressed_dscr_min = models.DecimalField(max_digits=6, decimal_places=4, default=1.0)
    warn_collateral_coverage_min = models.DecimalField(max_digits=6, decimal_places=4, default=1.0)
    warn_bureau_inquiries_count = models.PositiveIntegerField(default=3)
    hard_block_qualitative_fail = models.BooleanField(default=True)
    hard_block_es_reject = models.BooleanField(default=True)
    hard_block_es_high_risk = models.BooleanField(default=False)
    hard_block_annual_dscr = models.BooleanField(default=True)
    hard_annual_dscr_min = models.DecimalField(max_digits=6, decimal_places=4, default=1.0)
    hard_block_stressed_dscr = models.BooleanField(default=True)
    hard_stressed_dscr_min = models.DecimalField(max_digits=6, decimal_places=4, default=1.0)
    hard_block_monthly_dscr = models.BooleanField(default=False)
    hard_monthly_dscr_min = models.DecimalField(max_digits=6, decimal_places=4, default=1.0)
    hard_block_bureau_defaults = models.BooleanField(default=True)
    hard_block_bureau_restructured = models.BooleanField(default=False)
    hard_block_bureau_inquiries = models.BooleanField(default=False)
    hard_bureau_inquiries_count = models.PositiveIntegerField(default=3)
    hard_block_incomplete_sheets = models.BooleanField(default=True)
    require_sheets_complete_before_finish = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Loan analysis policy'
        verbose_name_plural = 'Loan analysis policy'

    def __str__(self):
        return 'Loan analysis policy'


class DocumentAuthenticationPolicy(models.Model):
    """Singleton: upload validation rules."""
    allowed_extensions = models.CharField(max_length=255, default='pdf,jpg,jpeg,png,doc,docx')
    max_file_size_mb = models.PositiveIntegerField(default=15)
    require_verified_documents_for_collateral = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Document authentication policy'
        verbose_name_plural = 'Document authentication policy'

    def __str__(self):
        return 'Document authentication policy'


class CommitteeApprovalPolicy(models.Model):
    """Legacy singleton — per-level thresholds are on ApprovalCommitteeLevel."""
    min_approvals_required = models.PositiveIntegerField(default=2)
    min_declines_required = models.PositiveIntegerField(default=2)

    class Meta:
        verbose_name = 'Committee approval policy (legacy)'
        verbose_name_plural = 'Committee approval policy (legacy)'

    def __str__(self):
        return f'Legacy policy (approve≥{self.min_approvals_required})'


class ApprovalCommitteeLevel(models.Model):
    """
    Configurable approval tier: branch, district, head office, management.
    Loans pass through active levels in sequence_order.
    """
    LEVEL_BRANCH = 'branch'
    LEVEL_DISTRICT = 'district'
    LEVEL_HEAD_OFFICE = 'head_office'
    LEVEL_MANAGEMENT = 'management'
    LEVEL_KEY_CHOICES = [
        (LEVEL_BRANCH, 'Branch committee'),
        (LEVEL_DISTRICT, 'District committee'),
        (LEVEL_HEAD_OFFICE, 'Head office committee'),
        (LEVEL_MANAGEMENT, 'Management committee (CEO / VP / Board)'),
    ]

    key = models.CharField(max_length=30, choices=LEVEL_KEY_CHOICES, unique=True)
    name = models.CharField(max_length=120, help_text='Display name in UI.')
    sequence_order = models.PositiveIntegerField(
        default=1,
        help_text='Order in the chain (1 = first after loan officer submits).',
    )
    is_active = models.BooleanField(default=True)
    min_approvals_required = models.PositiveIntegerField(
        default=2,
        help_text='Approve votes needed at this level (e.g. 2 of 3 branch members).',
    )
    min_declines_required = models.PositiveIntegerField(
        default=2,
        help_text='Decline votes needed to reject at this level.',
    )
    min_loan_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Optional: level applies only if requested amount ≥ this.',
    )
    max_loan_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Optional: level applies only if requested amount ≤ this.',
    )

    class Meta:
        ordering = ['sequence_order', 'id']
        verbose_name = 'Approval committee level'
        verbose_name_plural = 'Approval committee levels'

    def __str__(self):
        return f'{self.name} (order {self.sequence_order})'

    def applies_to_amount(self, amount: 'Decimal') -> bool:
        from decimal import Decimal

        amt = amount if amount is not None else Decimal('0')
        if self.min_loan_amount is not None and amt < self.min_loan_amount:
            return False
        if self.max_loan_amount is not None and amt > self.max_loan_amount:
            return False
        return True

    def skip_reason_for_amount(self, amount) -> str:
        from decimal import Decimal

        amt = amount if amount is not None else Decimal('0')
        if self.min_loan_amount is not None and amt < self.min_loan_amount:
            return f'Recommended/requested amount ({amt:,.2f}) is below minimum {self.min_loan_amount:,.2f} for this level.'
        if self.max_loan_amount is not None and amt > self.max_loan_amount:
            return f'Recommended/requested amount ({amt:,.2f}) exceeds maximum {self.max_loan_amount:,.2f} for this level.'
        return 'Level is inactive.'

    @property
    def member_scope_description(self) -> str:
        """How member rules resolve to voters for a given loan (shown in admin)."""
        if self.key == self.LEVEL_BRANCH:
            return (
                'Configure roles (e.g. loan officer, branch manager, accountant). '
                'At vote time the system includes every active user with that role '
                'who is assigned to the same branch as the loan.'
            )
        if self.key == self.LEVEL_DISTRICT:
            return (
                'Configure roles (e.g. district manager, accountant). '
                'Voters are users with that role assigned to the loan’s district.'
            )
        if self.key == self.LEVEL_HEAD_OFFICE:
            return (
                'Configure roles (operation/finance managers, credit committee) or '
                'named users. Role rules apply organization-wide (no branch filter).'
            )
        return (
            'Configure board / executive roles or add specific users (CEO, VP, '
            'individual board members). Role rules are organization-wide.'
        )


class ApprovalCommitteeMemberRule(models.Model):
    """
    Who may vote at a level: by role (scoped to branch/district) or named user (e.g. CEO).
    """
    PARTICIPANT_ROLE = 'role'
    PARTICIPANT_USER = 'user'
    PARTICIPANT_CHOICES = [
        (PARTICIPANT_ROLE, 'Anyone with role'),
        (PARTICIPANT_USER, 'Specific user'),
    ]

    level = models.ForeignKey(
        ApprovalCommitteeLevel,
        on_delete=models.CASCADE,
        related_name='member_rules',
    )
    participant_type = models.CharField(max_length=10, choices=PARTICIPANT_CHOICES, default=PARTICIPANT_ROLE)
    role = models.CharField(
        max_length=30,
        blank=True,
        choices=CustomUser.ROLE_CHOICES,
        help_text='For branch: user must belong to the loan branch. For district: loan district.',
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='approval_committee_rules',
        help_text='Named participant (e.g. CEO) when not using role.',
    )
    label = models.CharField(
        max_length=120,
        blank=True,
        help_text='Optional label shown in admin (e.g. Branch accountant).',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['level__sequence_order', 'id']
        verbose_name = 'Committee member rule'

    def __str__(self):
        if self.participant_type == self.PARTICIPANT_USER and self.user_id:
            return f'{self.level.name}: {self.user.username}'
        return f'{self.level.name}: role {self.role}'


class BranchCommitteeOverride(models.Model):
    """
    Optional per-branch committee setup for the branch approval level.
    When active member rules exist here, they replace the global branch-level rules for that branch.
    """
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name='committee_overrides',
    )
    level = models.ForeignKey(
        ApprovalCommitteeLevel,
        on_delete=models.CASCADE,
        related_name='branch_overrides',
        limit_choices_to={'key': ApprovalCommitteeLevel.LEVEL_BRANCH},
    )
    is_active = models.BooleanField(default=True)
    min_approvals_required = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Leave blank to use the global level default.',
    )
    min_declines_required = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Leave blank to use the global level default.',
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        help_text='Optional note (e.g. “Main street branch — 3-person committee”).',
    )

    class Meta:
        unique_together = [('branch', 'level')]
        verbose_name = 'Branch committee override'
        verbose_name_plural = 'Branch committee overrides'

    def __str__(self):
        return f'{self.branch.name} — {self.level.name}'

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.level_id and self.level.key != ApprovalCommitteeLevel.LEVEL_BRANCH:
            raise ValidationError(
                {'level': 'Per-branch overrides are only supported for the branch committee level.'}
            )


class BranchCommitteeMemberRule(models.Model):
    """Member rules for a branch-specific committee override."""
    PARTICIPANT_ROLE = 'role'
    PARTICIPANT_USER = 'user'
    PARTICIPANT_CHOICES = [
        (PARTICIPANT_ROLE, 'Anyone with role'),
        (PARTICIPANT_USER, 'Specific user'),
    ]

    override = models.ForeignKey(
        BranchCommitteeOverride,
        on_delete=models.CASCADE,
        related_name='member_rules',
    )
    participant_type = models.CharField(max_length=10, choices=PARTICIPANT_CHOICES, default=PARTICIPANT_ROLE)
    role = models.CharField(max_length=30, blank=True, choices=CustomUser.ROLE_CHOICES)
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='branch_committee_rules',
    )
    label = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Branch committee member rule'

    def __str__(self):
        if self.participant_type == self.PARTICIPANT_USER and self.user_id:
            return f'{self.override.branch.name}: {self.user.username}'
        return f'{self.override.branch.name}: role {self.role}'


class LoanApprovalLevelProgress(models.Model):
    """Tracks each loan at each approval level."""
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_DECLINED = 'declined'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_DECLINED, 'Declined'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    loan_request = models.ForeignKey(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name='approval_level_progress',
    )
    level = models.ForeignKey(
        ApprovalCommitteeLevel,
        on_delete=models.CASCADE,
        related_name='loan_progress',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('loan_request', 'level')]
        ordering = ['level__sequence_order']
        verbose_name = 'Loan approval level progress'

    def __str__(self):
        return f'{self.loan_request.loan_request_id} @ {self.level.name}: {self.status}'


class LoanCommitteeVote(models.Model):
    """One member vote per loan per approval level."""
    VOTE_APPROVE = 'approve'
    VOTE_DECLINE = 'decline'
    VOTE_CHOICES = [
        (VOTE_APPROVE, 'Approve'),
        (VOTE_DECLINE, 'Decline'),
    ]

    loan_request = models.ForeignKey(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name='committee_votes',
    )
    approval_level = models.ForeignKey(
        ApprovalCommitteeLevel,
        on_delete=models.CASCADE,
        related_name='votes',
    )
    member = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='committee_votes',
    )
    vote = models.CharField(max_length=20, choices=VOTE_CHOICES)
    amount_supported = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Amount this member approves (optional; defaults to officer recommendation).',
    )
    comments = models.TextField(blank=True)
    voted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-voted_at']
        unique_together = [('loan_request', 'member', 'approval_level')]
        verbose_name = 'Committee vote'

    def __str__(self):
        return f'{self.member.username} – {self.vote} @ {self.approval_level.key}'


class LoanNotification(models.Model):
    """In-app notification for committee workflow and related events."""
    KIND_VOTE_NEEDED = 'vote_needed'
    KIND_LEVEL_ADVANCED = 'level_advanced'
    KIND_COMMITTEE_APPROVED = 'committee_approved'
    KIND_COMMITTEE_DECLINED = 'committee_declined'
    KIND_RETURNED_TO_OFFICER = 'returned_to_officer'
    KIND_DOCUMENT_UPLOADED = 'document_uploaded'
    KIND_DOCUMENT_NEEDS_REVIEW = 'document_needs_review'
    KIND_DOCUMENT_VERIFIED = 'document_verified'
    KIND_DOCUMENT_REJECTED = 'document_rejected'
    KIND_DOCUMENT_REQUESTED = 'document_requested'
    KIND_COLLATERAL_ASSIGNED = 'collateral_assigned'
    KIND_COLLATERAL_SUBMITTED = 'collateral_submitted'
    KIND_COLLATERAL_ENGINEERING_RETURN = 'collateral_engineering_return'
    KIND_COLLATERAL_ENGINEERING_APPROVED = 'collateral_engineering_approved'
    KIND_CHOICES = [
        (KIND_VOTE_NEEDED, 'Vote needed'),
        (KIND_LEVEL_ADVANCED, 'Advanced to next level'),
        (KIND_COMMITTEE_APPROVED, 'Committee approved'),
        (KIND_COMMITTEE_DECLINED, 'Committee declined'),
        (KIND_RETURNED_TO_OFFICER, 'Returned to loan officer'),
        (KIND_DOCUMENT_UPLOADED, 'Document uploaded'),
        (KIND_DOCUMENT_NEEDS_REVIEW, 'Document needs review'),
        (KIND_DOCUMENT_VERIFIED, 'Document verified'),
        (KIND_DOCUMENT_REJECTED, 'Document rejected'),
        (KIND_DOCUMENT_REQUESTED, 'Document requested'),
        (KIND_COLLATERAL_ASSIGNED, 'Collateral assigned'),
        (KIND_COLLATERAL_SUBMITTED, 'Collateral submitted'),
        (KIND_COLLATERAL_ENGINEERING_RETURN, 'Collateral returned by engineering'),
        (KIND_COLLATERAL_ENGINEERING_APPROVED, 'Collateral approved by engineering'),
    ]

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='loan_notifications',
    )
    loan_request = models.ForeignKey(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name='notifications',
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=40, choices=KIND_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    url = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Loan notification'

    def __str__(self):
        return f'{self.title} → {self.user.username}'

