# loans/models.py

from django.contrib.auth.models import AbstractUser
from django.db import models

class Zone(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name

class Branch(models.Model):
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name

class LoanCategory(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name

class CollateralType(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name

class CustomUser(AbstractUser):
    USER_ROLES = [
        ('admin', 'Admin'),
        ('loan_officer', 'Loan Officer'),
        ('operational_manager', 'Operational Manager'),
        ('manager', 'Manager')
    ]

    role = models.CharField(max_length=20, choices=USER_ROLES)
    phone_number = models.CharField(max_length=20)
    zone = models.ForeignKey(Zone, on_delete=models.SET_NULL, null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)

class LoanRequest(models.Model):
    number = models.CharField(max_length=13, unique=True, blank=True)
    applicant_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    category = models.ForeignKey(LoanCategory, on_delete=models.SET_NULL, null=True)
    collateral = models.ForeignKey(CollateralType, on_delete=models.SET_NULL, null=True)
    amount_requested = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending')
    date_requested = models.DateTimeField(auto_now_add=True)
    date_reviewed = models.DateTimeField(null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        if not self.number:
            last_loan = LoanRequest.objects.all().order_by('id').last()
            if last_loan:
                last_number = int(last_loan.number.split('-')[1])
                self.number = f'Decsi-{last_number + 1:010d}'
            else:
                self.number = 'Decsi-0000000001'
        super().save(*args, **kwargs)
