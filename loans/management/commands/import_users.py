from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'users'
    help = (
        'Import staff users (username, email, phone_number, role, district, branch, department, …). '
        'Head-office roles may leave branch blank. Pass --default-password for new accounts.'
    )
