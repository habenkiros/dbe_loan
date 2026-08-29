from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'document_types'
    help = 'Import application document types (name, order, is_required, OCR flags, …).'
