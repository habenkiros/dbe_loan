# loans/models.py

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

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Loan application document type'
        verbose_name_plural = 'Loan application document types'

    def __str__(self):
        return self.name


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
        ('operation_manager', 'Operation Manager'),
        ('finance_manager', 'Finance Manager'),
        ('credit_committee', 'Credit Committee Member'),
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

    # def save(self, *args, **kwargs):
    #     # If this is a new record without a status, apply system rules
    #     if not self.status:
    #         if self.operation_manager_approval and self.finance_approval:
    #             self.status = 'Approved'
    #         else:
    #             self.status = 'pending'
    #     # Otherwise, preserve whatever status is already set (e.g., during migration)
    #     super(LoanRequest, self).save(*args, **kwargs)
    
    def save(self, *args, **kwargs):
        # Always recalculate status from approvals
        if self.operation_manager_approval and self.finance_approval:
            self.status = 'Approved'
            self.queue_approved = True  # Approved loans are eligible for collateral
        elif self.status != 'Rejected':  # don’t override rejection
            self.status = 'Pending'
        
        super(LoanRequest, self).save(*args, **kwargs)


class LoanRequestDocument(models.Model):
    """An uploaded document attached to a loan request (e.g. ID, proof of income)."""
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
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['document_type__order', 'document_type__name', 'uploaded_at']
        verbose_name = 'Loan request document'
        verbose_name_plural = 'Loan request documents'

    def __str__(self):
        return f'{self.document_type.name} – {self.loan_request.loan_request_id}'

