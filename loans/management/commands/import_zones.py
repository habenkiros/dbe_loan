from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'zones'
    help = (
        'Import geographic zones (columns: region, name). '
        'This is NOT operational districts — use import_districts for those.'
    )
