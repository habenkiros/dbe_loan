# loans/admin.py

from django.contrib import admin
from .models import Zone, Branch, LoanCategory, CollateralType, LoanRequest, CustomUser

admin.site.register(Zone)
admin.site.register(Branch)
admin.site.register(LoanCategory)
admin.site.register(CollateralType)
admin.site.register(LoanRequest)
admin.site.register(CustomUser)
