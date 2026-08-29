from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'committee_levels'
    help = 'Import approval committee levels (key, name, voter_scope, sequence_order, amount bounds, …).'
