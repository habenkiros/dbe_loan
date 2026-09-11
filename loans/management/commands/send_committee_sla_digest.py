"""Email / in-app digest for committee files past vote SLA."""

from django.core.management.base import BaseCommand

from loans.ci_alerts import send_committee_sla_digest


class Command(BaseCommand):
    help = (
        'Notify eligible committee voters (and assigned officers) for loans '
        'past CI_COMMITTEE_SLA_DAYS. Dedupes per loan within 24h. '
        'Schedule via cron, e.g. daily morning.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List breaches without creating notifications or sending email.',
        )
        parser.add_argument(
            '--dedupe-hours',
            type=int,
            default=24,
            help='Skip loans that already received a committee_sla notice within this window.',
        )

    def handle(self, *args, **options):
        result = send_committee_sla_digest(
            dry_run=options['dry_run'],
            dedupe_hours=options['dedupe_hours'],
        )
        mode = 'DRY-RUN' if result['dry_run'] else 'SENT'
        self.stdout.write(
            self.style.SUCCESS(
                f'[{mode}] SLA={result["sla_days"]}d · '
                f'loans={result["notified_loans"]} · '
                f'notifications={result["notifications"]} · '
                f'skipped={result["skipped"]}'
            )
        )
        for row in result.get('details') or []:
            self.stdout.write(
                f'  {row.get("loan")}: {row.get("status")}'
                + (f' (age {row["age"]}d)' if 'age' in row else '')
                + (f' n={row["notifications"]}' if 'notifications' in row else '')
            )
