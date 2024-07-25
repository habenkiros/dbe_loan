import pandas as pd
from django.core.management.base import BaseCommand
from loans.models import Zone  # Adjust the import based on your app name

class Command(BaseCommand):
    help = 'Import zones from an Excel file'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the Excel file')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        data = pd.read_excel(file_path, engine='openpyxl')

        for index, row in data.iterrows():
            zone, created = Zone.objects.get_or_create(name=row['name'])
            if created:
                self.stdout.write(self.style.SUCCESS(f'Successfully created zone: {zone.name}'))
            else:
                self.stdout.write(self.style.WARNING(f'Zone already exists: {zone.name}'))
