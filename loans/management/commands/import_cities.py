from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'cities'
    help = 'Import cities / woredas (columns: region, zone, name). Used for construction unit prices.'
