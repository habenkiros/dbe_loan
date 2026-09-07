from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'financing_funds'
    help = 'Import funding windows (columns: code, name, kind, source_name, is_active, notes).'