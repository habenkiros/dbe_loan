# loans/admin.py

from django.contrib import admin
from .models import Zone, Branch, LoanCategory, CollateralType, LoanRequest, CustomUser


@admin.register(LoanRequest)
class LoanRequestAdmin(admin.ModelAdmin):
    list_display = (
        'loan_request_id', 'applicant_name', 'phone_number', 'category', 'collateral',
        'amount_requested', 'branch', 'status', 'queue_approved', 'date_requested',
    )
    list_filter = ('status', 'branch', 'category', 'collateral', 'queue_approved')
    search_fields = ('loan_request_id', 'applicant_name', 'phone_number')
    readonly_fields = ('loan_request_id',)
    list_per_page = 20

    def has_add_permission(self, request):
        """Loan requests are created from the main app, not from admin."""
        return False


admin.site.register(Zone)
admin.site.register(Branch)
admin.site.register(LoanCategory)
admin.site.register(CollateralType)
admin.site.register(CustomUser)
