import pandas as pd
from django.core.management.base import BaseCommand
from loans.models import Branch, Zone  # Adjust the import based on your app name

class Command(BaseCommand):
    help = 'Import branches from an Excel file'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the Excel file')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        data = pd.read_excel(file_path, engine='openpyxl')

        for index, row in data.iterrows():
            zone_name = row['zone']
            branch_name = row['name']
            
            try:
                zone = Zone.objects.get(name=zone_name)
                branch, created = Branch.objects.get_or_create(name=branch_name, zone=zone)
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Successfully created branch: {branch.name} in zone: {zone.name}'))
                else:
                    self.stdout.write(self.style.WARNING(f'Branch already exists: {branch.name} in zone: {zone.name}'))
            except Zone.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Zone does not exist: {zone_name}'))
