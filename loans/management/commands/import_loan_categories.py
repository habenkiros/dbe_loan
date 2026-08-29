from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'loan_categories'
    help = 'Import loan categories / products (columns: name, appraisal_mode). appraisal_mode is msme or corporate.'
