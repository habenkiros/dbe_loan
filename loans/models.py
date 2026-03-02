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

