from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'collateral_types'
    help = 'Import collateral types (columns: name, kind). kind is building, land, movable, or mixed.'
