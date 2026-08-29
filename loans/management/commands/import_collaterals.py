from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'collateral_types'
    help = 'Alias for import_collateral_types (columns: name or collateral, kind).'
