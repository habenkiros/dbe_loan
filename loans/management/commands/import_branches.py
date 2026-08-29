from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'branches'
    help = 'Import branches (columns: district, name). Legacy “zone” column is treated as district.'
