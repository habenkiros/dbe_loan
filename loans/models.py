# loans/models.py

from django.contrib.auth.models import AbstractUser
from django.db import models

class Zone(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name

class Branch(models.Model):
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return f"{self.name} ({self.zone.name})"

class LoanCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

class CollateralType(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

class CustomUser(AbstractUser):
    USER_ROLES = [
        ('loan_officer', 'Loan Officer'),
        ('finance', 'Finance'),
        ('operational_manager', 'Operational Manager'),
        ('manager', 'Manager')
    ]

    role = models.CharField(max_length=20, choices=USER_ROLES)
    phone_number = models.CharField(max_length=20)
    zone = models.ForeignKey(Zone, on_delete=models.SET_NULL, null=True, blank=True)
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
    email = models.EmailField()
    category = models.ForeignKey(LoanCategory, on_delete=models.CASCADE)
    collateral = models.ForeignKey(CollateralType, on_delete=models.CASCADE)
    amount_requested = models.DecimalField(max_digits=20, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, default='pending')
    operation_manager_approval = models.BooleanField(default=False)
    finance_approval = models.BooleanField(default=False)
    date_requested = models.DateTimeField(auto_now_add=True)
    date_reviewed = models.DateTimeField(null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    customer_history = models.CharField(null=True, blank=True, max_length=50, choices=[('new', 'New'), ('existing', 'Existing')])

    def save(self, *args, **kwargs):
        if self.operation_manager_approval and self.finance_approval:
            self.status = 'approved'
        else:
            self.status = 'pending'
        super(LoanRequest, self).save(*args, **kwargs)
