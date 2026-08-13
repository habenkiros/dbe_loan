# Backfill: prior live delegations become approved.

from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    StaffDelegation = apps.get_model('loans', 'StaffDelegation')
    now = timezone.now()
    StaffDelegation.objects.filter(is_active=True, revoked_at__isnull=True).exclude(
        status='approved',
    ).update(status='approved', reviewed_at=now)
    StaffDelegation.objects.filter(revoked_at__isnull=False).exclude(
        status='revoked',
    ).update(status='revoked', is_active=False)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0065_delegation_approval_status'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
