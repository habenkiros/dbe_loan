from django.core.management.base import BaseCommand

from loans.licensing import clear_license_cache, get_license_status


class Command(BaseCommand):
    help = 'Show current on-prem license status.'

    def handle(self, *args, **options):
        clear_license_cache()
        s = get_license_status(force_refresh=True)
        rows = [
            ('enforced', s.enforced),
            ('present', s.present),
            ('valid', s.valid),
            ('expired', s.expired),
            ('grace', s.grace),
            ('ok_to_run', s.ok_to_run),
            ('org', s.org),
            ('org_code', s.org_code),
            ('issued_on', s.issued_on),
            ('expires_on', s.expires_on),
            ('days_remaining', s.days_remaining),
            ('features', ','.join(s.features)),
            ('note', s.note),
            ('message', s.message),
        ]
        for k, v in rows:
            self.stdout.write(f'{k}: {v}')
        if s.ok_to_run:
            self.stdout.write(self.style.SUCCESS('RESULT: OK'))
        else:
            self.stdout.write(self.style.ERROR('RESULT: BLOCKED'))
