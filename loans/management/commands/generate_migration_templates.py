from pathlib import Path

from django.core.management.base import BaseCommand

from loans.migration_templates import write_individual_files, write_pack

DEFAULT_DIR = Path('docs/migration_templates')


class Command(BaseCommand):
    help = 'Write fillable DECSI Excel templates (migration pack + one file per sheet).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            default=str(DEFAULT_DIR),
            help='Directory to write .xlsx files (default: docs/migration_templates).',
        )
        parser.add_argument(
            '--no-examples',
            action='store_true',
            help='Omit yellow example rows (headers only).',
        )

    def handle(self, *args, **options):
        output = Path(options['output_dir'])
        include = not options['no_examples']
        pack = write_pack(output, include_examples=include)
        files = write_individual_files(output, include_examples=include)
        self.stdout.write(self.style.SUCCESS(f'Wrote pack: {pack}'))
        for path in files:
            self.stdout.write(f'  {path}')
