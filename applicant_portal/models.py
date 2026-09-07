"""External applicant digital-apply accounts and online loan drafts."""

from decimal import Decimal
from uuid import uuid4

from django.db import models
from django.utils import timezone


class ApplicantPortalSettings(models.Model):
    """Singleton: digital-apply switch, fee, and security policy (admin-managed)."""

    enabled = models.BooleanField(
        default=True,
        help_text='If off, the public apply site shows a closed message.',
    )
    processing_fee_etb = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('50.00'),
        help_text='Application processing fee in ETB (demo pay amount).',
    )
    min_password_length = models.PositiveSmallIntegerField(
        default=10,
        help_text='Minimum password length for applicants.',
    )
    require_uppercase = models.BooleanField(default=True)
    require_lowercase = models.BooleanField(default=True)
    require_digit = models.BooleanField(default=True)
    require_special = models.BooleanField(
        default=True,
        help_text='Require a non-letter, non-digit character.',
    )
    max_failed_logins = models.PositiveSmallIntegerField(
        default=5,
        help_text='Failed login attempts before temporary lockout.',
    )
    lockout_minutes = models.PositiveSmallIntegerField(
        default=15,
        help_text='Account/IP lockout duration in minutes.',
    )
    register_rate_limit_per_hour = models.PositiveSmallIntegerField(
        default=8,
        help_text='Max registration attempts per IP address per hour.',
    )
    session_idle_minutes = models.PositiveSmallIntegerField(
        default=30,
        help_text='Sign applicants out after this many minutes of inactivity.',
    )
    require_terms_acceptance = models.BooleanField(
        default=True,
        help_text='Require applicants to accept terms of use on registration.',
    )
    require_customer_lookup = models.BooleanField(
        default=False,
        help_text='If on (or when BANK_CBS_BASE_URL / DECSI_BASE_URL is set live), registration requires a successful '
                  'customer-number match in core banking before an account can be created.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Applicant portal settings'
        verbose_name_plural = 'Applicant portal settings'

    def __str__(self):
        state = 'open' if self.enabled else 'closed'
        return f'Digital apply ({state}) · fee {self.processing_fee_etb} ETB'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Singleton — never delete the row from admin accidentally.
        return


class ApplicantAccount(models.Model):
    """Portal-only identity (not staff CustomUser).

    DECSI customers are actor_kind=person (CBS customer number).
    DBE institutions and promoters are different doors on the same table.
    """

    ACTOR_PERSON = 'person'
    ACTOR_INSTITUTION = 'institution'
    ACTOR_PROMOTER = 'promoter'
    ACTOR_CHOICES = [
        (ACTOR_PERSON, 'Customer (MSME / retail)'),
        (ACTOR_INSTITUTION, 'Institution (bank / MFI / PFI)'),
        (ACTOR_PROMOTER, 'Project / idea promoter'),
    ]

    public_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    actor_kind = models.CharField(
        max_length=16, choices=ACTOR_CHOICES, default=ACTOR_PERSON, db_index=True,
    )
    full_name = models.CharField(max_length=255)
    institution_name = models.CharField(max_length=255, blank=True)
    license_number = models.CharField(max_length=80, blank=True)
    phone_number = models.CharField(max_length=30, unique=True, db_index=True)
    customer_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text='CBS customer ID for persons. Generated portal ID for institutions / promoters.',
    )
    email = models.EmailField(blank=True)
    password_hash = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True, db_index=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    customer_profile_snapshot = models.JSONField(
        blank=True,
        default=dict,
        help_text='Last CBS/mock customer lookup payload (name, phone hints, etc.).',
    )
    preferred_branch = models.ForeignKey(
        'loans.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='applicant_accounts',
    )
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True, db_index=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Applicant portal account'
        verbose_name_plural = 'Applicant portal accounts'

    def __str__(self):
        return f'{self.full_name} ({self.phone_number})'

    def set_password(self, raw_password: str) -> None:
        from django.contrib.auth.hashers import make_password
        self.password_hash = make_password(raw_password) if raw_password else ''
        self.password_changed_at = timezone.now()

    def check_password(self, raw_password: str) -> bool:
        from django.contrib.auth.hashers import check_password
        if not self.password_hash or not raw_password:
            return False
        return check_password(raw_password, self.password_hash)

    def is_login_locked(self) -> bool:
        if self.locked_until and self.locked_until > timezone.now():
            return True
        if self.locked_until and self.locked_until <= timezone.now():
            # auto-clear expired lock in memory; persist on next save path
            self.failed_login_attempts = 0
            self.locked_until = None
        return False

    def can_use_portal(self) -> bool:
        return bool(
            self.is_active
            and self.phone_number
            and self.password_hash
            and not self.is_login_locked()
        )


class ApplicantIpThrottle(models.Model):
    """Per-IP throttle for login failures and registration rate limits."""

    ip_address = models.GenericIPAddressField(unique=True)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    lockout_until = models.DateTimeField(null=True, blank=True)
    register_count = models.PositiveSmallIntegerField(default=0)
    register_window_start = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Applicant IP throttle'
        verbose_name_plural = 'Applicant IP throttles'

    def __str__(self):
        return self.ip_address

    def is_locked(self) -> bool:
        return bool(self.lockout_until and self.lockout_until > timezone.now())


class ApplicantAuthEvent(models.Model):
    """Security audit trail for the applicant portal."""

    EVT_REGISTER = 'register'
    EVT_LOGIN_SUCCESS = 'login_success'
    EVT_LOGIN_FAILED = 'login_failed'
    EVT_LOGIN_LOCKED = 'login_locked'
    EVT_LOGOUT = 'logout'
    EVT_PASSWORD_CHANGED = 'password_changed'
    EVT_PASSWORD_RESET_REQUEST = 'password_reset_request'
    EVT_PASSWORD_RESET_OK = 'password_reset_ok'
    EVT_SESSION_TIMEOUT = 'session_timeout'
    EVT_CHOICES = [
        (EVT_REGISTER, 'Registered'),
        (EVT_LOGIN_SUCCESS, 'Login success'),
        (EVT_LOGIN_FAILED, 'Login failed'),
        (EVT_LOGIN_LOCKED, 'Login locked'),
        (EVT_LOGOUT, 'Logout'),
        (EVT_PASSWORD_CHANGED, 'Password changed'),
        (EVT_PASSWORD_RESET_REQUEST, 'Password reset requested'),
        (EVT_PASSWORD_RESET_OK, 'Password reset completed'),
        (EVT_SESSION_TIMEOUT, 'Session idle timeout'),
    ]

    event_type = models.CharField(max_length=32, choices=EVT_CHOICES, db_index=True)
    account = models.ForeignKey(
        ApplicantAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auth_events',
    )
    phone_number = models.CharField(max_length=30, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default='')
    detail = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Applicant auth event'
        verbose_name_plural = 'Applicant auth events'

    def __str__(self):
        return f'{self.event_type} · {self.phone_number or "—"}'


class OnlineApplication(models.Model):
    """Draft digital application until fee is paid and a LoanRequest is minted."""

    STATUS_DRAFT = 'draft'
    STATUS_DOCUMENTS = 'documents'
    STATUS_PAYMENT = 'payment'
    STATUS_SUBMITTED = 'submitted'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Application details'),
        (STATUS_DOCUMENTS, 'Documents'),
        (STATUS_PAYMENT, 'Processing fee'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    PAY_UNPAID = 'unpaid'
    PAY_PENDING = 'pending'
    PAY_PAID = 'paid'
    PAY_WAIVED = 'waived'
    PAY_FAILED = 'failed'
    PAY_CHOICES = [
        (PAY_UNPAID, 'Unpaid'),
        (PAY_PENDING, 'Payment pending'),
        (PAY_PAID, 'Paid'),
        (PAY_WAIVED, 'Waived'),
        (PAY_FAILED, 'Failed'),
    ]

    public_id = models.UUIDField(default=uuid4, unique=True, editable=False, db_index=True)
    applicant = models.ForeignKey(
        ApplicantAccount,
        on_delete=models.CASCADE,
        related_name='applications',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True,
    )

    applicant_name = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    customer_number = models.CharField(max_length=50, blank=True)
    customer_history = models.CharField(
        max_length=50,
        blank=True,
        choices=[('new', 'New customer'), ('existing', 'Existing customer')],
        default='new',
    )
    category = models.ForeignKey(
        'loans.LoanCategory',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='online_applications',
    )
    collateral = models.ForeignKey(
        'loans.CollateralType',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='online_applications',
    )
    branch = models.ForeignKey(
        'loans.Branch',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='online_applications',
    )
    amount_requested = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
    )
    reason = models.TextField(blank=True)

    processing_fee_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
    )
    payment_status = models.CharField(
        max_length=20, choices=PAY_CHOICES, default=PAY_UNPAID, db_index=True,
    )
    payment_reference = models.CharField(max_length=64, blank=True)
    payment_paid_at = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=40, blank=True)
    chapa_tx_ref = models.CharField(max_length=64, blank=True, db_index=True)
    chapa_checkout_url = models.URLField(blank=True, max_length=500)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdraw_reason = models.CharField(max_length=255, blank=True)

    loan_request = models.OneToOneField(
        'loans.LoanRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='online_application',
    )
    kyc_identity_case = models.OneToOneField(
        'loans.KycIdentityCase',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='online_application',
    )
    queue_id = models.CharField(
        max_length=22,
        blank=True,
        db_index=True,
        help_text='Loan request id issued on submit (e.g. HK-000000001).',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['applicant', 'status']),
        ]

    def __str__(self):
        return f'{self.applicant_name or self.applicant.full_name} · {self.get_status_display()}'

    @property
    def is_editable(self) -> bool:
        return self.status in {
            self.STATUS_DRAFT,
            self.STATUS_DOCUMENTS,
            self.STATUS_PAYMENT,
        } and self.status != self.STATUS_SUBMITTED

    def payment_satisfied(self) -> bool:
        if self.processing_fee_amount <= 0:
            return True
        return self.payment_status in (self.PAY_PAID, self.PAY_WAIVED)

    def step_index(self) -> int:
        order = [
            self.STATUS_DRAFT,
            self.STATUS_DOCUMENTS,
            self.STATUS_PAYMENT,
            self.STATUS_SUBMITTED,
        ]
        try:
            return order.index(self.status) + 1
        except ValueError:
            return 1


class OnlineApplicationDocument(models.Model):
    """Pre-submit document upload for an online application."""

    AUTH_PENDING = 'pending'
    AUTH_AUTO_PASSED = 'auto_passed'
    AUTH_NEEDS_REVIEW = 'needs_review'
    AUTH_VERIFIED = 'verified'
    AUTH_REJECTED = 'rejected'
    AUTH_STATUS_CHOICES = [
        (AUTH_PENDING, 'Pending checks'),
        (AUTH_AUTO_PASSED, 'Auto-passed (integrity OK)'),
        (AUTH_NEEDS_REVIEW, 'Needs manual review'),
        (AUTH_REJECTED, 'Rejected / not authentic'),
    ]

    application = models.ForeignKey(
        OnlineApplication,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    document_type = models.ForeignKey(
        'loans.LoanApplicationDocumentType',
        on_delete=models.CASCADE,
        related_name='online_documents',
    )
    file = models.FileField(upload_to='online_apply_docs/%Y/%m/')
    original_filename = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    auth_status = models.CharField(
        max_length=20, choices=AUTH_STATUS_CHOICES, default=AUTH_PENDING,
    )
    automated_checks = models.JSONField(default=dict, blank=True)
    quality_score = models.PositiveSmallIntegerField(null=True, blank=True)
    authenticity_score = models.PositiveSmallIntegerField(null=True, blank=True)
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['document_type__order', 'document_type__name', '-uploaded_at']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'document_type'],
                name='applicant_portal_unique_app_doc_type',
            ),
        ]

    def __str__(self):
        return f'{self.document_type.name} · {self.application.public_id}'


class ApplicantPasswordReset(models.Model):
    """Phone OTP password reset (hashed code; raw code delivered via SMS/outbox)."""

    account = models.ForeignKey(
        ApplicantAccount, on_delete=models.CASCADE, related_name='password_resets',
    )
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def is_valid(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()


class ApplicantNotification(models.Model):
    """In-portal notices for applicants (submit, payment, status)."""

    KIND_INFO = 'info'
    KIND_SUCCESS = 'success'
    KIND_WARN = 'warn'
    KIND_CHOICES = [
        (KIND_INFO, 'Info'),
        (KIND_SUCCESS, 'Success'),
        (KIND_WARN, 'Warning'),
    ]

    account = models.ForeignKey(
        ApplicantAccount, on_delete=models.CASCADE, related_name='notifications',
    )
    application = models.ForeignKey(
        OnlineApplication,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_INFO)
    title = models.CharField(max_length=160)
    message = models.TextField()
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} · {self.account_id}'


class ApplicantMessageOutbox(models.Model):
    """Outbound delivery log (SMS/email) — SMS gateway optional."""

    CHANNEL_SMS = 'sms'
    CHANNEL_EMAIL = 'email'
    CHANNEL_LOG = 'log'
    CHANNEL_CHOICES = [
        (CHANNEL_SMS, 'SMS'),
        (CHANNEL_EMAIL, 'Email'),
        (CHANNEL_LOG, 'Log only'),
    ]

    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES, default=CHANNEL_LOG)
    recipient = models.CharField(max_length=255)
    subject = models.CharField(max_length=160, blank=True)
    body = models.TextField()
    sent = models.BooleanField(default=False)
    detail = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Applicant message outbox'

    def __str__(self):
        return f'{self.channel} · {self.recipient}'
