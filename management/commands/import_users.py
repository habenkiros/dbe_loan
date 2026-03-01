import pandas as pd
from django.core.management.base import BaseCommand
from loans.models import CustomUser, District, Branch
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Import users from an Excel file'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='The path to the Excel file')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        data = pd.read_excel(file_path, engine='openpyxl')

        for index, row in data.iterrows():
            username = row['username']
            email = row['email']
            phone_number = row['phone_number']
            role = row['role']
            district_name = row.get('district', row.get('zone'))
            branch_name = row['branch']
            try:
                district = District.objects.get(name=district_name)
                branch = Branch.objects.get(name=branch_name, district=district)
                user, created = CustomUser.objects.get_or_create(
                    username=username,
                    defaults={
                        'email': email,
                        'phone_number': phone_number,
                        'role': role,
                        'district': district,
                        'branch': branch
                    }
                )
                if created:
                    user.set_password('decsiloan10')
                    user.save()
                    self.stdout.write(self.style.SUCCESS(f'Successfully created user: {username}'))
                else:
                    self.stdout.write(self.style.WARNING(f'User already exists: {username}'))
            except District.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'District does not exist: {district_name}'))
            except Branch.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Branch does not exist: {branch_name}'))
