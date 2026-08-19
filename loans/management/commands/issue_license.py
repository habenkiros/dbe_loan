from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from loans.licensing import issue_license


class Command(BaseCommand):
    help = 'Issue a signed on-prem LICENSE_KEY (requires Seqela private key).'

    def add_arguments(self, parser):
        parser.add_argument('--org', required=True, help='Customer legal name')
        parser.add_argument('--org-code', required=True, help='Short code, e.g. DECSI')
        parser.add_argument(
            '--expires',
            required=True,
            help='Expiry date YYYY-MM-DD (license stops working after this day + grace)',
        )
        parser.add_argument('--issued', default='', help='Issue date YYYY-MM-DD (default: today)')
        parser.add_argument('--note', default='', help='Optional note embedded in the key')
        parser.add_argument(
            '--features',
            default='hub,digital_apply,market,collateral',
            help='Comma-separated feature flags',
        )
        parser.add_argument(
            '--write',
            default='',
            help='Optional path to write license.key (e.g. deploy/license/license.key)',
        )

    def handle(self, *args, **options):
        try:
            expires = datetime.strptime(options['expires'], '%Y-%m-%d').date()
            issued = None
            if options['issued']:
                issued = datetime.strptime(options['issued'], '%Y-%m-%d').date()
        except ValueError as exc:
            raise CommandError(f'Bad date: {exc}') from exc

        features = [f.strip() for f in options['features'].split(',') if f.strip()]
        try:
            key = issue_license(
                org=options['org'],
                org_code=options['org_code'],
                expires_on=expires,
                issued_on=issued,
                features=features,
                note=options['note'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(key)
        write_path = (options['write'] or '').strip()
        if write_path:
            from pathlib import Path
            Path(write_path).parent.mkdir(parents=True, exist_ok=True)
            Path(write_path).write_text(key + '\n', encoding='utf-8')
            self.stderr.write(self.style.SUCCESS(f'Wrote {write_path}'))
