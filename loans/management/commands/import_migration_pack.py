from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from loans.excel_import import import_pack
from loans.management.commands._excel_cmd import ExcelImportCommand


class Command(BaseCommand):
    help = (
        'Import a multi-sheet DECSI migration workbook (all master data + optional loan requests). '
        'Sheet names should match the pack (01_Regions, 02_Zones, …).'
    )

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Path to DECSI_Migration_Pack.xlsx')
        parser.add_argument('--update', action='store_true')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--default-password', default='')

    def handle(self, *args, **options):
        def _run():
            return import_pack(
                options['file_path'],
                update=options['update'],
                default_password=options['default_password'],
            )

        if options['dry_run']:
            with transaction.atomic():
                result = _run()
                transaction.set_rollback(True)
        else:
            result = _run()
        ExcelImportCommand()._emit(result, dry_run=options['dry_run'])
        if result.errors:
            raise CommandError(f'{len(result.errors)} row error(s); see above.')
