from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(ExcelImportCommand):
    kind = 'construction_catalog'
    help = (
        'Import BOQ catalog and woreda unit prices '
        '(main_work, sub_work, sub_sub_work, city, unit_price, …).'
    )
