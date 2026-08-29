from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'departments'
    help = 'Import HO departments (columns: key, name, is_active, sort_order).'
