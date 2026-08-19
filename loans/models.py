# loans/models.py

from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
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


class Department(models.Model):
    """Head-office / governance departments (Cooperative, Finance, Credit, Management, Board)."""
    KEY_COOPERATIVE = 'cooperative'
    KEY_FINANCE = 'finance'
    KEY_CREDIT = 'credit'
    KEY_MANAGEMENT = 'management'
    KEY_BOARD = 'board'
    KEY_CHOICES = [
        (KEY_COOPERATIVE, 'Branch Cooperative'),
        (KEY_FINANCE, 'Finance'),
        (KEY_CREDIT, 'Credit'),
        (KEY_MANAGEMENT, 'Management'),
        (KEY_BOARD, 'Board of Directors'),
    ]

    key = models.CharField(max_length=30, unique=True, choices=KEY_CHOICES)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

class LoanCategory(models.Model):
    MODE_MSME = 'msme'
    MODE_CORPORATE = 'corporate'
    APPRAISAL_MODE_CHOICES = [
        (MODE_MSME, 'MSME / cashflow'),
        (MODE_CORPORATE, 'Corporate'),
    ]

    name = models.CharField(max_length=255, unique=True)
    appraisal_mode = models.CharField(
        max_length=20,
        choices=APPRAISAL_MODE_CHOICES,
        default=MODE_MSME,
        help_text='Which appraisal wizard content to use for loans in this category.',
    )

    def __str__(self):
        return self.name


class LoanCategoryDocumentRequirement(models.Model):
    """Which application document types apply to a given loan category (loan type)."""

    category = models.ForeignKey(
        LoanCategory,
        on_delete=models.CASCADE,
        related_name='document_requirements',
    )
    document_type = models.ForeignKey(
        'LoanApplicationDocumentType',
        on_delete=models.CASCADE,
        related_name='category_requirements',
    )
    is_required = models.BooleanField(
        default=True,
        help_text='If True, this document is required before collateral for this loan type.',
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text='Display order within this loan type (lower first).',
    )

    class Meta:
        ordering = ['order', 'document_type__order', 'document_type__name']
        constraints = [
            models.UniqueConstraint(
                fields=['category', 'document_type'],
                name='loans_unique_category_document_type',
            ),
        ]
        verbose_name = 'Loan type document requirement'
        verbose_name_plural = 'Loan type document requirements'

    def __str__(self):
        req = 'required' if self.is_required else 'optional'
        return f'{self.category.name}: {self.document_type.name} ({req})'


class CollateralType(models.Model):
    KIND_BUILDING = 'building'
    KIND_LAND = 'land'
    KIND_MOVABLE = 'movable'
    KIND_MIXED = 'mixed'
    KIND_CHOICES = [
        (KIND_BUILDING, 'Building / house (BOQ)'),
        (KIND_LAND, 'Land (size × price)'),
        (KIND_MOVABLE, 'Vehicle / machinery / other movable'),
        (KIND_MIXED, 'Mixed (sum engines that apply)'),
    ]

    name = models.CharField(max_length=255, unique=True)
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        blank=True,
        default='',
        db_index=True,
        help_text='Which estimation engine(s) this type uses. Blank infers from the name. Mixed sums building + land + movable that have data.',
    )

    def __str__(self):
        return self.name

    def resolved_kind(self) -> str:
        from loans.collateral_kind import resolve_type_kind
        return resolve_type_kind(self)

    def uses_building(self) -> bool:
        from loans.collateral_kind import uses_building
        return uses_building(self)

    def uses_land(self) -> bool:
        from loans.collateral_kind import uses_land
        return uses_land(self)

    def uses_movable(self) -> bool:
        from loans.collateral_kind import uses_movable
        return uses_movable(self)


class LoanApplicationDocumentType(models.Model):
    """Configurable document type required or optional for loan application (e.g. National ID, Proof of income)."""
    name = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0, help_text='Display order (lower first).')
    is_required = models.BooleanField(
        default=True,
        help_text=(
            'Fallback required flag when a loan type has no document pack configured. '
            'When a pack exists for a loan category, that pack controls required/optional.'
        ),
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
    for_appraisal_mode = models.CharField(
        max_length=20,
        blank=True,
        default='',
        choices=[
            ('', 'All modes'),
            ('msme', 'MSME only'),
            ('corporate', 'Corporate only'),
        ],
        help_text='Limit this document type to MSME or Corporate loans (blank = both).',
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


class CustomUserManager(UserManager):
    """Ensure createsuperuser gets hub role=superadmin, not the loan_officer default."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', 'superadmin')
        return super().create_superuser(username, email, password, **extra_fields)


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
        ('cooperative_manager', 'Branch Cooperative Manager'),
        ('finance_manager', 'Finance Manager'),
        ('credit_head', 'Credit Department Head'),
        ('credit_loan_officer', 'Credit Loan Officer'),
        ('ceo', 'Chief Executive Officer'),
        ('vp', 'Vice President'),
        ('vp_operations', 'VP Operations'),
        ('vp_it', 'VP IT'),
        ('vp_customer_service', 'VP Customer Service'),
        ('board_member', 'Board Member'),
        ('risk_compliance', 'Risk & Compliance Officer'),
        ('auditor', 'Auditor / Viewer'),
        # Legacy aliases (data-migrated; kept so old rows/forms do not crash).
        ('operation_manager', 'Operation Manager (legacy)'),
        ('credit_committee', 'Credit Committee Member (legacy)'),
    ]
    MANAGEMENT_VP_ROLES = ('vp', 'vp_operations', 'vp_it', 'vp_customer_service')

    objects = CustomUserManager()

    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='loan_officer')
    phone_number = models.CharField(max_length=20)
    district = models.ForeignKey(District, on_delete=models.SET_NULL, null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)
    department = models.ForeignKey(
        'Department',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text='Head-office department (Cooperative, Finance, Credit, Management, Board).',
    )
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    lockout_until = models.DateTimeField(blank=True, null=True, db_index=True)
    mfa_enabled = models.BooleanField(
        default=False,
        help_text='When True, staff must enter a TOTP code after password login.',
    )
    mfa_secret_encrypted = models.TextField(
        blank=True,
        default='',
        help_text='Encrypted TOTP shared secret (not plaintext).',
    )

    def is_login_locked(self) -> bool:
        if self.lockout_until is None:
            return False
        from django.utils import timezone
        return self.lockout_until > timezone.now()

    def is_cooperative_manager(self) -> bool:
        return self.role in ('cooperative_manager', 'operation_manager')

    def is_credit_staff(self) -> bool:
        return self.role in ('credit_head', 'credit_loan_officer')

    def is_district_loan_officer(self) -> bool:
        return self.role == 'loan_officer' and bool(self.district_id) and not self.branch_id

    def is_management_vp(self) -> bool:
        return self.role in self.MANAGEMENT_VP_ROLES


class IpLoginThrottle(models.Model):
    """Per-IP login failure throttle used by staff auth hardening."""

    ip_address = models.GenericIPAddressField(unique=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    lockout_until = models.DateTimeField(blank=True, null=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_locked(self) -> bool:
        if self.lockout_until is None:
            return False
        from django.utils import timezone
        return self.lockout_until > timezone.now()

    def __str__(self):
        return f'{self.ip_address} ({self.failed_attempts})'


class SecurityAuditLog(models.Model):
    """Append-only security and auth events for staff portal hardening."""

    EVT_LOGIN_SUCCESS = 'login_success'
    EVT_LOGIN_FAILED = 'login_failed'
    EVT_LOGIN_LOCKED = 'login_locked'
    EVT_LOGOUT = 'logout'
    EVT_MFA_CHALLENGE = 'mfa_challenge'
    EVT_MFA_SUCCESS = 'mfa_success'
    EVT_MFA_FAILED = 'mfa_failed'
    EVT_MFA_ENROLLED = 'mfa_enrolled'
    EVT_MFA_DISABLED = 'mfa_disabled'
    EVT_USER_CREATED = 'user_created'
    EVT_USER_UPDATED = 'user_updated'
    EVT_USER_UNLOCKED = 'user_unlocked'
    EVT_PASSWORD_RESET_REQUESTED = 'password_reset_requested'
    EVT_PASSWORD_RESET_COMPLETED = 'password_reset_completed'
    EVT_PASSWORD_CHANGED = 'password_changed'
    EVT_AUDIT_EXPORTED = 'audit_exported'
    EVT_SESSION_TIMEOUT = 'session_timeout'
    EVT_CHOICES = [
        (EVT_LOGIN_SUCCESS, 'Login success'),
        (EVT_LOGIN_FAILED, 'Login failed'),
        (EVT_LOGIN_LOCKED, 'Account locked'),
        (EVT_LOGOUT, 'Logout'),
        (EVT_MFA_CHALLENGE, 'MFA challenge issued'),
        (EVT_MFA_SUCCESS, 'MFA success'),
        (EVT_MFA_FAILED, 'MFA failed'),
        (EVT_MFA_ENROLLED, 'MFA enrolled'),
        (EVT_MFA_DISABLED, 'MFA disabled'),
        (EVT_USER_CREATED, 'User created'),
        (EVT_USER_UPDATED, 'User updated'),
        (EVT_USER_UNLOCKED, 'User unlocked'),
        (EVT_PASSWORD_RESET_REQUESTED, 'Password reset requested'),
        (EVT_PASSWORD_RESET_COMPLETED, 'Password reset completed'),
        (EVT_PASSWORD_CHANGED, 'Password changed'),
        (EVT_AUDIT_EXPORTED, 'Security audit exported'),
        (EVT_SESSION_TIMEOUT, 'Session idle timeout'),
    ]

    event_type = models.CharField(max_length=32, choices=EVT_CHOICES, db_index=True)
    username = models.CharField(max_length=150, blank=True, default='', db_index=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=512, blank=True, default='')
    detail = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_events',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', '-created_at']),
        ]

    def __str__(self):
        return f'{self.event_type} · {self.username or "—"}'

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
    customer_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text='Core banking / Temenos-style customer id for party lookup.',
    )
    email = models.EmailField(null=True, blank=True)
    customer_profile_snapshot = models.JSONField(
        null=True,
        blank=True,
        help_text='Important core-banking / party API fields (subset) for staff display.',
    )
    category = models.ForeignKey(LoanCategory, on_delete=models.CASCADE)
    collateral = models.ForeignKey(CollateralType, on_delete=models.CASCADE)
    amount_requested = models.DecimalField(max_digits=20, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, null=True, blank=True)
    operation_manager_approval = models.BooleanField(
        default=False,
        help_text='Branch Cooperative intake-queue approval (field name kept for DB compatibility).',
    )
    finance_approval = models.BooleanField(
        default=False,
        help_text='Legacy intake flag; no longer required for queue. Prefer finance_disbursement_approval.',
    )
    finance_disbursement_approval = models.BooleanField(
        default=False,
        help_text='Finance department approval required before confirming disbursement.',
    )

    # Collateral legal papers (post-approval → before disbursement)
    require_collateral_restriction = models.BooleanField(
        default=True,
        help_text='Applicant must bring a government Collateral Restriction paper before disbursement.',
    )
    collateral_held_via_poa = models.BooleanField(
        default=False,
        help_text='Collateral is pledged under a Loan Collateral Power of Attorney (POA required).',
    )
    require_agreement_signatures = models.BooleanField(
        default=True,
        help_text='Loan agreement must be digitally signed before disbursement.',
    )
    require_title_search = models.BooleanField(
        default=False,
        help_text='Title / ownership search paper must be uploaded and verified before disbursement.',
    )
    require_mortgage_registration = models.BooleanField(
        default=False,
        help_text='Mortgage / restriction registration proof must be verified before disbursement.',
    )
    require_notary_stamp = models.BooleanField(
        default=False,
        help_text='Notary / stamp-duty receipt must be verified before disbursement.',
    )
    own_contribution_required = models.BooleanField(
        default=False,
        help_text='Borrower own-contribution / equity must be verified before first disbursement.',
    )
    own_contribution_amount = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
    )
    own_contribution_verified_at = models.DateTimeField(null=True, blank=True)
    own_contribution_verified_by = models.ForeignKey(
        'CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loans_own_contribution_verified',
    )
    own_contribution_note = models.TextField(blank=True)
    ORIGIN_BRANCH = 'branch'
    ORIGIN_HEAD_OFFICE = 'head_office'
    ORIGIN_CHOICES = [
        (ORIGIN_BRANCH, 'Branch'),
        (ORIGIN_HEAD_OFFICE, 'Head Office / Credit'),
    ]
    origin_level = models.CharField(
        max_length=20,
        choices=ORIGIN_CHOICES,
        default=ORIGIN_BRANCH,
        db_index=True,
        help_text='Where the loan was originated: branch (default) or head-office Credit.',
    )
    SOURCE_STAFF = 'staff'
    SOURCE_ONLINE = 'online'
    SOURCE_CHANNEL_CHOICES = [
        (SOURCE_STAFF, 'Staff / branch entry'),
        (SOURCE_ONLINE, 'Applicant digital apply'),
    ]
    source_channel = models.CharField(
        max_length=20,
        choices=SOURCE_CHANNEL_CHOICES,
        default=SOURCE_STAFF,
        db_index=True,
        help_text='How the application entered the system (staff desk vs applicant portal).',
    )
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
        limit_choices_to=models.Q(role__in=['loan_officer', 'credit_loan_officer']),
        help_text='Loan officer assigned for analysis and collateral estimation.',
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
        help_text='When the assigned loan officer finished appraisal (locks Sheets 1–7 until returned).',
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

    # Risk & Compliance desk review (gates committee when policy requires it)
    risk_reviewed_at = models.DateTimeField(null=True, blank=True)
    risk_reviewed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_requests_risk_reviewed',
        limit_choices_to={'role': 'risk_compliance'},
    )
    risk_review_note = models.TextField(
        blank=True,
        help_text='Risk & Compliance note on credit / E&S / coverage concerns.',
    )

    # Post-committee disbursement track (conditions → schedule → ready → disbursed)
    DISBURSE_NONE = ''
    DISBURSE_AWAITING_CONDITIONS = 'awaiting_conditions'
    DISBURSE_SCHEDULE_CONFIRMED = 'schedule_confirmed'
    DISBURSE_READY = 'ready_for_disbursement'
    DISBURSE_PARTIAL = 'partially_disbursed'
    DISBURSE_DISBURSED = 'disbursed'
    DISBURSE_STATUS_CHOICES = [
        (DISBURSE_NONE, 'Not started'),
        (DISBURSE_AWAITING_CONDITIONS, 'Awaiting conditions'),
        (DISBURSE_SCHEDULE_CONFIRMED, 'Schedule confirmed'),
        (DISBURSE_READY, 'Ready for disbursement'),
        (DISBURSE_PARTIAL, 'Partially disbursed'),
        (DISBURSE_DISBURSED, 'Disbursed'),
    ]
    disbursement_status = models.CharField(
        max_length=30,
        choices=DISBURSE_STATUS_CHOICES,
        default=DISBURSE_NONE,
        blank=True,
        help_text='Post-committee track: conditions → schedule → ready → disbursed.',
    )
    schedule_confirmed_at = models.DateTimeField(null=True, blank=True)
    schedule_confirmed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_schedules_confirmed',
    )
    ready_for_disbursement_at = models.DateTimeField(null=True, blank=True)
    ready_for_disbursement_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loans_marked_ready_disbursement',
    )
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loans_disbursed',
    )
    disbursement_notes = models.TextField(blank=True)

    # CBS / Temenos booking result (written when DECSI_CBS_BOOK_ON_DISBURSE)
    CBS_BOOK_NONE = ''
    CBS_BOOK_MOCK = 'mock'
    CBS_BOOK_BOOKED = 'booked'
    CBS_BOOK_FAILED = 'failed'
    CBS_BOOK_SKIPPED = 'skipped'
    CBS_BOOKING_STATUS_CHOICES = [
        (CBS_BOOK_NONE, 'Not booked'),
        (CBS_BOOK_MOCK, 'Mock booked'),
        (CBS_BOOK_BOOKED, 'Booked in CBS'),
        (CBS_BOOK_FAILED, 'CBS booking failed'),
        (CBS_BOOK_SKIPPED, 'Skipped'),
    ]
    cbs_booking_status = models.CharField(
        max_length=20,
        choices=CBS_BOOKING_STATUS_CHOICES,
        default=CBS_BOOK_NONE,
        blank=True,
    )
    cbs_booking_ref = models.CharField(max_length=120, blank=True)
    cbs_loan_account = models.CharField(max_length=120, blank=True)
    cbs_booked_at = models.DateTimeField(null=True, blank=True)
    cbs_outstanding_at_booking = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text='Customer outstanding snapshot from CBS at booking time (ETB).',
    )

    # Post-book monitoring / collections (hub case file; CBS still posts money)
    watchlist = models.BooleanField(default=False, db_index=True)
    watchlist_reason = models.CharField(max_length=400, blank=True)
    watchlist_at = models.DateTimeField(null=True, blank=True)
    watchlist_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loans_watchlisted',
    )
    ARREARS_CURRENT = 'current'
    ARREARS_30 = 'dpd_30'
    ARREARS_60 = 'dpd_60'
    ARREARS_90 = 'dpd_90'
    ARREARS_NPL = 'npl'
    ARREARS_CHOICES = [
        (ARREARS_CURRENT, 'Current'),
        (ARREARS_30, '1–30 days past due'),
        (ARREARS_60, '31–60 days past due'),
        (ARREARS_90, '61–90 days past due'),
        (ARREARS_NPL, 'NPL / 90+ days'),
    ]
    arrears_status = models.CharField(
        max_length=20,
        choices=ARREARS_CHOICES,
        default=ARREARS_CURRENT,
        blank=True,
        db_index=True,
    )
    WORKOUT_NONE = ''
    WORKOUT_REQUESTED = 'requested'
    WORKOUT_APPROVED = 'approved'
    WORKOUT_REJECTED = 'rejected'
    WORKOUT_CHOICES = [
        (WORKOUT_NONE, 'None'),
        (WORKOUT_REQUESTED, 'Reschedule requested'),
        (WORKOUT_APPROVED, 'Reschedule approved'),
        (WORKOUT_REJECTED, 'Reschedule rejected'),
    ]
    workout_status = models.CharField(
        max_length=20, choices=WORKOUT_CHOICES, default=WORKOUT_NONE, blank=True, db_index=True,
    )
    workout_proposed_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    workout_proposed_term_months = models.PositiveIntegerField(null=True, blank=True)
    workout_note = models.TextField(blank=True)
    workout_decided_at = models.DateTimeField(null=True, blank=True)
    workout_decided_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loans_workout_decided',
    )
    WRITEOFF_NONE = ''
    WRITEOFF_REQUESTED = 'requested'
    WRITEOFF_APPROVED = 'approved'
    WRITEOFF_WRITTEN_BACK = 'written_back'
    WRITEOFF_CHOICES = [
        (WRITEOFF_NONE, 'None'),
        (WRITEOFF_REQUESTED, 'Write-off requested'),
        (WRITEOFF_APPROVED, 'Written off'),
        (WRITEOFF_WRITTEN_BACK, 'Written back'),
    ]
    writeoff_status = models.CharField(
        max_length=20, choices=WRITEOFF_CHOICES, default=WRITEOFF_NONE, blank=True, db_index=True,
    )
    writeoff_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    writeoff_note = models.TextField(blank=True)
    writeoff_decided_at = models.DateTimeField(null=True, blank=True)
    writeoff_decided_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loans_writeoff_decided',
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
    
    @property
    def cooperative_approval(self) -> bool:
        """Alias for Branch Cooperative intake approval."""
        return bool(self.operation_manager_approval)

    @cooperative_approval.setter
    def cooperative_approval(self, value: bool) -> None:
        self.operation_manager_approval = bool(value)

    @property
    def amount_approved_display(self):
        """Credit-approved amount when committee has approved; else None."""
        if self.committee_status == self.COMMITTEE_APPROVED:
            if self.committee_final_amount is not None:
                return self.committee_final_amount
            appr = getattr(self, 'appraisal', None)
            if appr is not None and getattr(appr, 'amount_approved', None) is not None:
                return appr.amount_approved
            return self.amount_requested
        return None

    @property
    def cbs_highlights(self) -> dict:
        """Important party/API fields for list/detail (excludes email)."""
        from loans.services.customer import loan_cbs_highlights
        return loan_cbs_highlights(self)

    def managers_queue_approved(self) -> bool:
        """Initial queue gate: Branch Cooperative only (before loan officer / engineering)."""
        if self.origin_level == self.ORIGIN_HEAD_OFFICE:
            return True
        return bool(self.operation_manager_approval)

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
        if self.origin_level == self.ORIGIN_HEAD_OFFICE and not self.operation_manager_approval:
            self.operation_manager_approval = True
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
    peak_sales_percent = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text='Peak-season sales as % of average (Excel seasonality).',
    )
    lowest_sales_percent = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text='Low-season sales as % of average (Excel seasonality).',
    )
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

    # Corporate / entity KYC (shown when appraisal_mode=corporate)
    legal_registration_number = models.CharField(
        max_length=100, null=True, blank=True,
        help_text='Company registration / CR number.',
    )
    directors_summary = models.TextField(
        null=True, blank=True,
        help_text='Directors / board summary.',
    )
    ubo_summary = models.TextField(
        null=True, blank=True,
        help_text='Ultimate beneficial owners (UBO) summary.',
    )

    def __str__(self):
        return f'Basic info – {self.loan_request.loan_request_id}'


class AppraisalPurposeLine(models.Model):
    """Sheet 1 purpose / investment breakdown (qty × unit price → value)."""
    basic_info = models.ForeignKey(
        LoanRequestBasicInfo,
        on_delete=models.CASCADE,
        related_name='purpose_lines',
    )
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.description or f'Purpose line {self.pk}'

    def compute_value(self):
        if self.quantity is not None and self.unit_price is not None:
            return (self.quantity * self.unit_price).quantize(Decimal('0.01'))
        return self.value


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

    # Locked at appraisal create from LoanCategory.appraisal_mode
    appraisal_mode = models.CharField(
        max_length=20,
        choices=[
            ('msme', 'MSME / cashflow'),
            ('corporate', 'Corporate'),
        ],
        default='msme',
        db_index=True,
        help_text='MSME vs Corporate sheet content (copied from category at create).',
    )

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

    # Sheet (3) balance sheet / ratios (Excel depth)
    bs_current_assets = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    bs_current_liabilities = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    bs_inventory = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    bs_total_assets = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    bs_total_liabilities = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    bs_equity = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    ratio_current = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Current assets / current liabilities.',
    )
    ratio_acid_test = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='(Current assets − inventory) / current liabilities.',
    )
    ratio_debt_equity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Total liabilities / equity.',
    )
    # 12-month cashflow grid: [{month, sales, expenses, net}, ...]
    monthly_cashflow_grid = models.JSONField(default=list, blank=True)

    # Corporate statement highlights (also usable for MSME when filled)
    corp_annual_revenue = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    corp_operating_profit = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text='EBIT / operating profit.',
    )

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
        help_text='Loan officer who screened the E&S checklist.',
        verbose_name='Screened by (loan officer)',
    )
    es_checked_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='es_checked_appraisals',
        help_text='Loan officer who checked checklist answers and mitigations.',
        verbose_name='Checked by (loan officer)',
    )
    es_approved_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='es_approved_appraisals',
        help_text=(
            'Loan officer confirmation of E&S eligibility. '
            'Credit committee signs the loan decision separately via committee voting.'
        ),
        verbose_name='E&S confirmed by (loan officer)',
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
    # Banking conduct (live/mock account transactions) — CREDIT_SCORE_ALGORITHM_V2
    banking_behavior = models.JSONField(
        null=True, blank=True, default=dict,
        help_text='Account transaction metrics for banking pillar (turnover, NSF, stability, …).',
    )
    banking_refreshed_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When banking_behavior was last refreshed from core banking / mock.',
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
    required_before_disbursement = models.BooleanField(
        default=True,
        help_text='If true (typical for conditions precedent), must be fulfilled before schedule confirm / disbursement.',
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    fulfilled_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='appraisal_conditions_fulfilled',
    )
    evidence_note = models.TextField(
        blank=True,
        help_text='How this condition was satisfied (document ref, date, etc.).',
    )
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
    # Corporate governance factors
    'board_governance': ['Strong board / clear oversight', 'Adequate governance', 'Weak / informal board'],
    'management_depth': ['Deep bench / succession ready', 'Adequate management', 'Key-person risk'],
    'financial_discipline': ['Strong controls & reporting', 'Adequate discipline', 'Weak controls'],
    'transparency': ['High transparency', 'Adequate disclosure', 'Opaque / delayed reporting'],
    'related_party': ['Low / well managed', 'Moderate exposure', 'High / poorly controlled'],
    'industry_position': ['Market leader / strong niche', 'Average position', 'Weak / declining'],
    'shareholder_stability': ['Stable ownership', 'Some changes', 'Unstable / contested'],
    'audit_quality': ['Clean audited statements', 'Qualified / limited scope', 'Unaudited / unreliable'],
    'covenant_compliance': ['Full compliance history', 'Minor breaches resolved', 'Material breaches'],
    'reputation': ['Strong market/bank reputation', 'Neutral', 'Adverse reputation signals'],
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

# 10 factors from Sheet (2) Bus. and Character Assess. – MSME
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

# Corporate Sheet 2 – governance / character (10 factors, same 0–100 scoring scale)
CORPORATE_QUALITATIVE_FACTOR_KEYS = [
    ('board_governance', 'Board / governance quality'),
    ('management_depth', 'Management depth & succession'),
    ('financial_discipline', 'Financial discipline / controls'),
    ('transparency', 'Transparency & disclosure'),
    ('related_party', 'Related-party exposure'),
    ('industry_position', 'Industry / competitive position'),
    ('shareholder_stability', 'Shareholder / ownership stability'),
    ('audit_quality', 'Audit quality & reporting'),
    ('covenant_compliance', 'Covenant / regulatory compliance'),
    ('reputation', 'Market / bank reputation'),
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
    require_risk_review_before_committee = models.BooleanField(
        default=True,
        help_text='Loan officer cannot submit to committee until Risk & Compliance has signed off.',
    )

    class Meta:
        verbose_name = 'Loan analysis policy'
        verbose_name_plural = 'Loan analysis policy'

    def __str__(self):
        return 'Loan analysis policy'


class LoanProcessPolicyConfig(models.Model):
    """Singleton: who may use Monitoring / Collections and who may decide workout."""

    book_ops_roles = models.JSONField(
        default=list,
        blank=True,
        help_text='Staff roles that may open Monitoring and Collections.',
    )
    workout_decide_roles = models.JSONField(
        default=list,
        blank=True,
        help_text='Staff roles that may approve or reject workout and write-off.',
    )
    require_collateral_restriction = models.BooleanField(
        default=False,
        help_text='Bank-wide: government Collateral Restriction must be verified before disbursement.',
    )
    require_agreement_signatures = models.BooleanField(
        default=False,
        help_text='Bank-wide: digital loan agreement signatures required before disbursement.',
    )
    require_title_search = models.BooleanField(
        default=False,
        help_text='Bank-wide: title / ownership search required before disbursement.',
    )
    require_mortgage_registration = models.BooleanField(
        default=False,
        help_text='Bank-wide: mortgage / restriction registration proof required before disbursement.',
    )
    require_notary_stamp = models.BooleanField(
        default=False,
        help_text='Bank-wide: notary / stamp-duty receipt required before disbursement.',
    )
    require_own_contribution = models.BooleanField(
        default=False,
        help_text='Bank-wide: borrower own-contribution / equity required before first disbursement.',
    )
    enable_disbursement_tranches = models.BooleanField(
        default=True,
        help_text='Allow staged (tranche) disbursement on post-approval.',
    )

    class Meta:
        verbose_name = 'Loan process policy'
        verbose_name_plural = 'Loan process policy'

    def __str__(self):
        return 'Loan process policy'


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
    Configurable approval tier in the committee chain.
    Loans pass through active levels in sequence_order (amount filters apply).

    Well-known keys (branch, district, head_office, management) ship by default;
    admins may add extra levels with any unique key and a voter_scope.
    """
    LEVEL_BRANCH = 'branch'
    LEVEL_DISTRICT = 'district'
    LEVEL_HEAD_OFFICE = 'head_office'
    LEVEL_MANAGEMENT = 'management'

    SCOPE_BRANCH = 'branch'
    SCOPE_DISTRICT = 'district'
    SCOPE_ORGANIZATION = 'organization'
    VOTER_SCOPE_CHOICES = [
        (SCOPE_BRANCH, 'Loan’s branch (role users at that branch)'),
        (SCOPE_DISTRICT, 'Loan’s district (role users in that district)'),
        (SCOPE_ORGANIZATION, 'Organization-wide (roles or named users)'),
    ]

    key = models.SlugField(
        max_length=50,
        unique=True,
        help_text='Stable id (e.g. branch, regional_risk). Used in URLs/logs; unique.',
    )
    name = models.CharField(max_length=120, help_text='Display name in UI.')
    voter_scope = models.CharField(
        max_length=20,
        choices=VOTER_SCOPE_CHOICES,
        default=SCOPE_ORGANIZATION,
        help_text='How role-based voters are scoped for this level.',
    )
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
    tiebreaker_role = models.CharField(
        max_length=30,
        blank=True,
        choices=CustomUser.ROLE_CHOICES,
        help_text=(
            'When approve and decline votes are equal, this role’s vote decides. '
            'Defaults by level: branch→branch_manager, district→district_manager, '
            'head_office→credit_head, management→board_member then ceo.'
        ),
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

    def get_key_display(self):
        """Human label for key (backwards-compatible with old choices)."""
        labels = {
            self.LEVEL_BRANCH: 'Branch committee',
            self.LEVEL_DISTRICT: 'District committee',
            self.LEVEL_HEAD_OFFICE: 'Head office committee',
            self.LEVEL_MANAGEMENT: 'Management committee (CEO / VP / Board)',
        }
        return labels.get(self.key, self.key.replace('_', ' ').title())

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
    def allows_branch_override(self) -> bool:
        return self.voter_scope == self.SCOPE_BRANCH

    @property
    def member_scope_description(self) -> str:
        """How member rules resolve to voters for a given loan (shown in admin / settings)."""
        if self.voter_scope == self.SCOPE_BRANCH:
            return (
                'Configure roles (e.g. loan officer, branch manager, accountant). '
                'At vote time the system includes every active user with that role '
                'who is assigned to the same branch as the loan.'
            )
        if self.voter_scope == self.SCOPE_DISTRICT:
            return (
                'Configure roles (e.g. district manager, accountant). '
                'Voters are users with that role assigned to the loan’s district.'
            )
        return (
            'Configure roles organization-wide, or add specific users '
            '(executives, board members, standing committee).'
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
        limit_choices_to={'voter_scope': ApprovalCommitteeLevel.SCOPE_BRANCH},
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

        if self.level_id and self.level.voter_scope != ApprovalCommitteeLevel.SCOPE_BRANCH:
            raise ValidationError(
                {'level': 'Per-branch overrides are only supported for branch-scoped committee levels.'}
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
    cast_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='committee_votes_cast_for_others',
        help_text='If set, this vote was cast by a delegate acting for member.',
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
    KIND_DISBURSEMENT_READY = 'disbursement_ready'
    KIND_DISBURSED = 'disbursed'
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
        (KIND_DISBURSEMENT_READY, 'Ready for disbursement'),
        (KIND_DISBURSED, 'Disbursed'),
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


class AgentRun(models.Model):
    """Audit trail for in-app Agentic Assist pipeline runs."""
    STATUS_OK = 'ok'
    STATUS_ERROR = 'error'
    STATUS_PARTIAL = 'partial'
    STATUS_CHOICES = [
        (STATUS_OK, 'Completed'),
        (STATUS_ERROR, 'Failed'),
        (STATUS_PARTIAL, 'Partial'),
    ]

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='agent_runs',
    )
    loan_request = models.ForeignKey(
        LoanRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_runs',
    )
    conversation = models.ForeignKey(
        'AgentConversation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='runs',
    )
    intent_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OK)
    steps = models.JSONField(default=list, blank=True, help_text='Ordered tool results.')
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Agent assist run'
        verbose_name_plural = 'Agent assist runs'

    def __str__(self):
        code = self.loan_request.loan_request_id if self.loan_request_id else '—'
        return f'AgentRun #{self.pk} by {self.user_id} → {code} ({self.status})'


class AgentConversation(models.Model):
    """Multi-turn Agentic Assist chat (LLM + tool audit)."""
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='agent_conversations',
    )
    title = models.CharField(max_length=200, blank=True)
    # OpenAI-compatible message list for continuity (user/assistant/tool).
    messages = models.JSONField(default=list, blank=True)
    # UI timeline: {role, content, tools?} without raw tool payloads.
    ui_messages = models.JSONField(default=list, blank=True)
    llm_provider = models.CharField(max_length=40, blank=True)
    last_loan_request = models.ForeignKey(
        LoanRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_conversations',
    )
    # Editable draft the user can correct before commit (loan bootstrap story).
    story = models.JSONField(
        default=dict,
        blank=True,
        help_text='Held loan draft: applicant, amount, flags, revision history.',
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Agent conversation'
        verbose_name_plural = 'Agent conversations'

    def __str__(self):
        return f'AgentChat #{self.pk} ({self.user_id}) {self.title[:40]}'


class LoanCollateralLegalDocument(models.Model):
    """
    Post-approval legal papers for collateral:
    - Government Collateral Restriction (required before disbursement when flagged on the loan)
    - Loan Collateral Power of Attorney (when collateral is pledged via POA)
    """

    KIND_RESTRICTION = 'collateral_restriction'
    KIND_POA = 'power_of_attorney'
    KIND_TITLE_SEARCH = 'title_search'
    KIND_MORTGAGE_REG = 'mortgage_registration'
    KIND_NOTARY_STAMP = 'notary_stamp'
    KIND_CHOICES = [
        (KIND_RESTRICTION, 'Collateral Restriction (government)'),
        (KIND_POA, 'Loan Collateral Power of Attorney'),
        (KIND_TITLE_SEARCH, 'Title / ownership search'),
        (KIND_MORTGAGE_REG, 'Mortgage / restriction registration'),
        (KIND_NOTARY_STAMP, 'Notary / stamp-duty receipt'),
    ]

    STATUS_UPLOADED = 'uploaded'
    STATUS_VERIFIED = 'verified'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_UPLOADED, 'Uploaded — pending verification'),
        (STATUS_VERIFIED, 'Verified'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    loan_request = models.ForeignKey(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name='collateral_legal_documents',
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_UPLOADED,
        db_index=True,
    )
    reference_number = models.CharField(
        max_length=120,
        blank=True,
        help_text='Government restriction ref / POA deed number.',
    )
    issuing_office = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g. Land Administration / Municipality / Notary.',
    )
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    # POA parties
    grantor_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Person/entity granting the Power of Attorney (collateral owner).',
    )
    attorney_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Attorney-in-fact named in the POA (often the borrower).',
    )
    parcel_reference = models.CharField(
        max_length=160,
        blank=True,
        help_text='Plot / parcel / kebele / title deed number.',
    )
    property_location = models.CharField(
        max_length=255,
        blank=True,
        help_text='Woreda / kebele / site of the restricted or pledged property.',
    )
    verification_note = models.CharField(
        max_length=400,
        blank=True,
        help_text='Staff note recorded when verifying or rejecting.',
    )
    file = models.FileField(
        upload_to='collateral_legal/%Y/%m/',
        blank=True,
        null=True,
        help_text='Scan/photo of the restriction paper or POA deed.',
    )
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collateral_legal_uploads',
    )
    verified_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collateral_legal_verifications',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Collateral legal document'
        verbose_name_plural = 'Collateral legal documents'
        indexes = [
            models.Index(fields=['loan_request', 'kind', 'status']),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} — {self.loan_request_id} [{self.status}]'


class LoanAgreement(models.Model):
    """Loan / collateral agreement prepared after approval; signed digitally before disbursement."""

    KIND_LOAN = 'loan_agreement'
    KIND_COLLATERAL_PLEDGE = 'collateral_pledge'
    KIND_GUARANTEE = 'guarantee'
    KIND_CHOICES = [
        (KIND_LOAN, 'Loan agreement'),
        (KIND_COLLATERAL_PLEDGE, 'Collateral pledge agreement'),
        (KIND_GUARANTEE, 'Guarantee agreement'),
    ]

    STATUS_DRAFT = 'draft'
    STATUS_PENDING = 'pending_signatures'
    STATUS_PARTIAL = 'partially_signed'
    STATUS_SIGNED = 'fully_signed'
    STATUS_VOID = 'void'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PENDING, 'Pending signatures'),
        (STATUS_PARTIAL, 'Partially signed'),
        (STATUS_SIGNED, 'Fully signed'),
        (STATUS_VOID, 'Void'),
    ]

    loan_request = models.ForeignKey(
        LoanRequest,
        on_delete=models.CASCADE,
        related_name='agreements',
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_LOAN, db_index=True)
    title = models.CharField(max_length=255)
    body_text = models.TextField(help_text='Agreement text snapshot at generation time.')
    content_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text='SHA-256 of body_text; signatures bind to this hash.',
    )
    status = models.CharField(
        max_length=24,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )
    require_borrower = models.BooleanField(default=True)
    require_guarantor = models.BooleanField(default=False)
    require_officer = models.BooleanField(default=True)
    require_branch_manager = models.BooleanField(default=False)
    generated_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agreements_generated',
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-generated_at']
        verbose_name = 'Loan agreement'
        verbose_name_plural = 'Loan agreements'

    def __str__(self):
        return f'{self.title} ({self.loan_request_id}) [{self.status}]'

    def refresh_status(self):
        needed = []
        if self.require_borrower:
            needed.append(LoanAgreementSignature.ROLE_BORROWER)
        if self.require_guarantor:
            needed.append(LoanAgreementSignature.ROLE_GUARANTOR)
        if self.require_officer:
            needed.append(LoanAgreementSignature.ROLE_OFFICER)
        if self.require_branch_manager:
            needed.append(LoanAgreementSignature.ROLE_BRANCH_MANAGER)
        have = set(
            self.signatures.filter(is_valid=True).values_list('role', flat=True)
        )
        if self.status == self.STATUS_VOID:
            return
        if not needed:
            self.status = self.STATUS_SIGNED
        elif all(r in have for r in needed):
            self.status = self.STATUS_SIGNED
        elif any(r in have for r in needed):
            self.status = self.STATUS_PARTIAL
        else:
            self.status = self.STATUS_PENDING
        self.save(update_fields=['status'])


class LoanAgreementSignature(models.Model):
    """One digital (drawn) signature on an agreement, with audit metadata."""

    ROLE_BORROWER = 'borrower'
    ROLE_GUARANTOR = 'guarantor'
    ROLE_OFFICER = 'officer'
    ROLE_BRANCH_MANAGER = 'branch_manager'
    ROLE_CHOICES = [
        (ROLE_BORROWER, 'Borrower / applicant'),
        (ROLE_GUARANTOR, 'Guarantor'),
        (ROLE_OFFICER, 'Loan officer'),
        (ROLE_BRANCH_MANAGER, 'Branch manager'),
    ]

    agreement = models.ForeignKey(
        LoanAgreement,
        on_delete=models.CASCADE,
        related_name='signatures',
    )
    role = models.CharField(max_length=24, choices=ROLE_CHOICES, db_index=True)
    signer_name = models.CharField(max_length=255)
    typed_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Name typed by the signer to confirm identity (must match signer_name).',
    )
    signer_id_number = models.CharField(
        max_length=80,
        blank=True,
        help_text='National ID / kebele ID / passport / staff ID shown at signing.',
    )
    declaration_accepted = models.BooleanField(
        default=False,
        help_text='Signer confirmed they have read the agreement and intend to be bound.',
    )
    signer_user = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agreement_signatures',
        help_text='Staff user when an officer/BM signs; blank for walk-in borrower.',
    )
    signature_image = models.ImageField(
        upload_to='agreement_signatures/%Y/%m/',
        help_text='PNG captured from signature pad.',
    )
    content_hash_at_sign = models.CharField(
        max_length=64,
        help_text='Must match agreement.content_hash at time of signing.',
    )
    signed_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    is_valid = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['signed_at']
        verbose_name = 'Agreement signature'
        verbose_name_plural = 'Agreement signatures'
        constraints = [
            models.UniqueConstraint(
                fields=['agreement', 'role'],
                condition=models.Q(is_valid=True),
                name='loans_unique_valid_signature_per_role',
            ),
        ]

    def __str__(self):
        return f'{self.get_role_display()} — {self.signer_name} @ {self.signed_at}'


class StaffDelegation(models.Model):
    """Temporary authority: principal proposes a delegate; admin approves before it is live."""

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_REVOKED = 'revoked'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending approval'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_REVOKED, 'Revoked'),
    ]

    principal = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='delegations_given',
        help_text='User whose authority is granted.',
    )
    delegate = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='delegations_received',
        help_text='Proposed / signed user who may act with principal authority.',
    )
    scopes = models.JSONField(
        default=list,
        help_text='List of scope keys: committee_vote, cooperative_intake, appraisal, …',
    )
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    is_active = models.BooleanField(
        default=False,
        db_index=True,
        help_text='True only while approved and not revoked (authority gate also checks dates).',
    )
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='delegations_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='delegations_reviewed',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='delegations_revoked',
    )

    class Meta:
        ordering = ['-starts_at']
        verbose_name = 'Staff delegation'
        verbose_name_plural = 'Staff delegations'
        indexes = [
            models.Index(fields=['delegate', 'status', 'is_active', 'starts_at', 'ends_at']),
            models.Index(fields=['principal', 'status', 'is_active']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return (
            f'{self.principal_id} → {self.delegate_id} '
            f'[{self.status}] ({", ".join(self.scopes or [])})'
        )

    def is_currently_active(self) -> bool:
        now = timezone.now()
        return bool(
            self.status == self.STATUS_APPROVED
            and self.is_active
            and self.revoked_at is None
            and self.starts_at <= now <= self.ends_at
        )

    def scope_labels(self) -> list:
        from loans.delegation import SCOPE_CHOICES
        labels = dict(SCOPE_CHOICES)
        return [labels.get(s, s) for s in (self.scopes or [])]

    @property
    def status_label(self) -> str:
        return dict(self.STATUS_CHOICES).get(self.status, self.status)


class DelegationActionLog(models.Model):
    """Audit when a delegate uses principal authority."""

    delegation = models.ForeignKey(
        StaffDelegation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='action_logs',
    )
    actor = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='delegation_actions_as_actor',
    )
    principal = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='delegation_actions_as_principal',
    )
    action = models.CharField(max_length=64, db_index=True)
    loan_request = models.ForeignKey(
        'LoanRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='delegation_actions',
    )
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} by {self.actor_id} as {self.principal_id}'


class LoanDisbursementTranche(models.Model):
    """Optional additional drawdowns after committee approval. Schedule stays on full amount."""

    STATUS_PENDING = 'pending'
    STATUS_DISBURSED = 'disbursed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_DISBURSED, 'Disbursed'),
    ]

    loan_request = models.ForeignKey(
        LoanRequest, on_delete=models.CASCADE, related_name='disbursement_tranches',
    )
    sequence = models.PositiveSmallIntegerField(default=1)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    note = models.CharField(max_length=400, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tranches_disbursed',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['loan_request', 'sequence', 'id']
        unique_together = [('loan_request', 'sequence')]

    def __str__(self):
        return f'Tranche {self.sequence} {self.loan_request.loan_request_id} {self.amount}'


class LoanMonitoringVisit(models.Model):
    """Post-disbursement follow-up visit."""

    loan_request = models.ForeignKey(
        LoanRequest, on_delete=models.CASCADE, related_name='monitoring_visits',
    )
    visited_at = models.DateField()
    notes = models.TextField()
    gps_lat = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    gps_lon = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)
    recorded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='monitoring_visits_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-visited_at', '-id']

    def __str__(self):
        return f'Visit {self.loan_request.loan_request_id} {self.visited_at}'


class LoanCollectionAction(models.Model):
    """Collections case-file action (reminder, demand, visit, legal). Money posting stays in CBS."""

    KIND_REMINDER = 'reminder'
    KIND_DEMAND = 'demand'
    KIND_VISIT = 'visit'
    KIND_LEGAL = 'legal_referral'
    KIND_CHOICES = [
        (KIND_REMINDER, 'Reminder'),
        (KIND_DEMAND, 'Demand notice'),
        (KIND_VISIT, 'Collection visit'),
        (KIND_LEGAL, 'Legal referral'),
    ]

    loan_request = models.ForeignKey(
        LoanRequest, on_delete=models.CASCADE, related_name='collection_actions',
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, db_index=True)
    notes = models.TextField()
    recorded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='collection_actions_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.kind} {self.loan_request.loan_request_id}'

