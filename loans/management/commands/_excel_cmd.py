"""Shared argparse / dry-run wrapper for Excel import commands."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class ExcelImportCommand(BaseCommand):
    kind = ''
    help = 'Import an Excel/CSV file.'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Path to .xlsx or .csv')
        parser.add_argument('--sheet', default='', help='Sheet name (xlsx only)')
        parser.add_argument(
            '--update',
            action='store_true',
            help='Update existing rows instead of skipping them.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and print counts without keeping changes.',
        )
        parser.add_argument(
            '--default-password',
            default='',
            help='Temporary password for new users when the password column is empty.',
        )

    def handle(self, *args, **options):
        from loans.excel_import import run_import

        def _run():
            return run_import(
                self.kind,
                options['file_path'],
                sheet_name=options['sheet'] or None,
                update=options['update'],
                default_password=options['default_password'],
            )

        if options['dry_run']:
            with transaction.atomic():
                result = _run()
                transaction.set_rollback(True)
        else:
            result = _run()
        self._emit(result, dry_run=options['dry_run'])
        if result.errors:
            raise CommandError(f'{len(result.errors)} row error(s); see above.')

    def _emit(self, result, dry_run=False):
        prefix = 'DRY-RUN ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(prefix + result.summary()))
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(warning))
        for error in result.errors:
            self.stderr.write(self.style.ERROR(error))
