from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'category_documents'
    help = 'Import per-loan-type document packs (columns: category, document_type, is_required, order).'
