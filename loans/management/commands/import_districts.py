from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'districts'
    help = (
        'Import operational districts (column: name). '
        'Legacy name-only “zones” Excel files belong here.'
    )
