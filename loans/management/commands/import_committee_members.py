from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'committee_members'
    help = 'Import committee voters (level_key, participant_type=role|user, role, username).'
