from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'loan_requests'
    help = (
        'Import loan requests for migration (applicant_name, category, collateral, amount_requested, '
        'branch, optional loan_request_id / customer_number / officer / status).'
    )
