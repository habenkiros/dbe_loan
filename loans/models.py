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

    def __str__(self):
        return f'Appraisal for {self.loan_request.loan_request_id}'


class AppraisalCreditHistoryEntry(models.Model):
    """Sheet (2) – one row per existing loan/lease in credit history."""
    STATUS_REGULAR = 'regular'
    STATUS_SETTLED_ON_TIME = 'settled_on_time'
    STATUS_SETTLED_LATE = 'settled_late'
    STATUS_IRREGULAR = 'irregular'
    STATUS_DEFAULTED = 'defaulted'
    STATUS_CHOICES = [
        (STATUS_REGULAR, 'Regular'),
        (STATUS_SETTLED_ON_TIME, 'Settled on time'),
        (STATUS_SETTLED_LATE, 'Settled late'),
        (STATUS_IRREGULAR, 'Irregular'),
        (STATUS_DEFAULTED, 'Defaulted'),
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
    purpose = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, null=True, blank=True)
    repayment = models.CharField(max_length=100, null=True, blank=True)
    letter_from_lender = models.CharField(max_length=100, null=True, blank=True)
    score = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return f'{self.lender} – {self.appraisal.loan_request.loan_request_id}'


# Qualitative factor rating scale (from Excel Sheet 2)
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
    rating = models.CharField(max_length=100, null=True, blank=True)  # e.g. Very competent, Average
    notes = models.TextField(null=True, blank=True, help_text='Observation / justification.')
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']
        unique_together = [('appraisal', 'factor_key')]

    def __str__(self):
        return f'{self.factor_key} – {self.appraisal.loan_request.loan_request_id}'


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

