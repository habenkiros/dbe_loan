import pandas as pd
from django.core.management.base import BaseCommand
from loans.models import Branch, District

class Command(BaseCommand):
    help = 'Import branches from an Excel file (columns: district or zone, name)'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the Excel file')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            district_name = row.get('district', row.get('zone'))
            branch_name = row['name']
            try:
                district = District.objects.get(name=district_name)
                branch, created = Branch.objects.get_or_create(name=branch_name, district=district)
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Successfully created branch: {branch.name} in district: {district.name}'))
                else:
                    self.stdout.write(self.style.WARNING(f'Branch already exists: {branch.name} in district: {district.name}'))
            except District.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'District does not exist: {district_name}'))
