import pandas as pd
from django.core.management.base import BaseCommand
from loans.models import CollateralType  # Adjust the import based on your app name

class Command(BaseCommand):
    help = 'Import collaterals from an Excel file'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the Excel file')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        data = pd.read_excel(file_path, engine='openpyxl')

        for index, row in data.iterrows():
            collateral_name = row['collateral']
            
            collateral, created = CollateralType.objects.get_or_create(name=collateral_name)
            if created:
                self.stdout.write(self.style.SUCCESS(f'Successfully created collateral: {collateral}'))
            else:
                self.stdout.write(self.style.WARNING(f'Collateral already exists: {collateral}'))
