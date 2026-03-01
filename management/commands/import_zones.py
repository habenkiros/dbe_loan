import pandas as pd
from django.core.management.base import BaseCommand
from loans.models import District

class Command(BaseCommand):
    help = 'Import districts from an Excel file (column: name)'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the Excel file')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        data = pd.read_excel(file_path, engine='openpyxl')
        for index, row in data.iterrows():
            district, created = District.objects.get_or_create(name=row['name'])
            if created:
                self.stdout.write(self.style.SUCCESS(f'Successfully created district: {district.name}'))
            else:
                self.stdout.write(self.style.WARNING(f'District already exists: {district.name}'))
