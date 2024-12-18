import pandas as pd
from django.core.management.base import BaseCommand
from loans.models import LoanRequest, LoanCategory, Zone, Branch, CollateralType  # Adjust the import based on your app name
from loans.views import generate_incremental_loan_request_id

class Command(BaseCommand):
    help = 'Import loan requests from an Excel file'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the Excel file')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        data = pd.read_excel(file_path, engine='openpyxl')

        for index, row in data.iterrows():
            applicant_name = row['applicant_name']
            email = row['email']
            phone_number = row['phone_number']
            category = row['category']
            collateral = row['collateral']
            amount_requested = row['amount_requested']
            reason = row['reason']
            status = row['status']
            zone = row['zone']
            branch = row['branch']
            customer_history = row['customer_history']
            date_requested = row['date_requested']

            try:
                category = LoanCategory.objects.get(name=category)
                collateral = CollateralType.objects.get(name=collateral)
                zone = Zone.objects.get(name=zone)
                branch = Branch.objects.get(name=branch, zone=zone)
                loan_request, created = LoanRequest.objects.get_or_create(
                    loan_request_id=generate_incremental_loan_request_id(),
                    applicant_name=applicant_name,
                    email=email,
                    phone_number=phone_number,
                    category=category,
                    collateral=collateral,
                    amount_requested=amount_requested,
                    reason=reason,
                    status=status,
                    zone=zone,
                    branch=branch,
                    customer_history=customer_history,
                    date_requested=date_requested
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Successfully created loan request for: {applicant_name}'))
                else:
                    self.stdout.write(self.style.WARNING(f'Loan request already exists for: {applicant_name}'))
            except LoanCategory.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Loan category does not exist: {category}'))
            except CollateralType.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Collateral does not exist: {collateral}'))
            except Branch.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Branch does not exist: {branch}'))
