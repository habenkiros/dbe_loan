from django.core.management.base import BaseCommand

from partners.market_bands import recompute_all_bands
from partners.models import MarketPriceBand


class Command(BaseCommand):
    help = 'Recompute market price bands from active observations (rolling window).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--window-days',
            type=int,
            default=MarketPriceBand.WINDOW_DAYS_DEFAULT,
        )

    def handle(self, *args, **options):
        n = recompute_all_bands(window_days=options['window_days'])
        self.stdout.write(self.style.SUCCESS(f'Rebuilt {n} market price band(s).'))
