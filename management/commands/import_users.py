import pandas as pd
from django.core.management.base import BaseCommand
from loans.models import CustomUser, Zone, Branch  # Adjust the import based on your app name
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
            zone = row['zone']
            branch = row['branch']

            try:
                zone = Zone.objects.get(name=zone)
                branch = Branch.objects.get(name=branch, zone=zone)
                user, created = CustomUser.objects.get_or_create(
                    username=username,
                    defaults={
                        'email': email,
                        'phone_number': phone_number,
                        'role': role,
                        'zone': zone,
                        'branch': branch
                    }
                )
                if created:
                    user.set_password('Zemeo@zemeo10')  # You may want to set a default password or handle password securely
                    user.save()
                    self.stdout.write(self.style.SUCCESS(f'Successfully created user: {username}'))
                else:
                    self.stdout.write(self.style.WARNING(f'User already exists: {username}'))
            except Zone.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Zone does not exist: {zone}'))
            except Branch.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Branch does not exist: {branch}'))
