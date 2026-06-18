# Fix loans where both managers approved but status stayed Pending (committee gate removed).

from django.db import migrations
from django.utils import timezone


def approve_manager_queue(apps, schema_editor):
    LoanRequest = apps.get_model('loans', 'LoanRequest')
    now = timezone.now()
    qs = LoanRequest.objects.filter(
        operation_manager_approval=True,
        finance_approval=True,
    ).exclude(status__iexact='Rejected')
    for loan in qs.iterator():
        updates = {}
        if loan.status != 'Approved':
            updates['status'] = 'Approved'
        if not loan.queue_approved:
            updates['queue_approved'] = True
        if not loan.date_reviewed:
            updates['date_reviewed'] = now
        if updates:
            LoanRequest.objects.filter(pk=loan.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0035_document_type_auth_rules'),
    ]

    operations = [
        migrations.RunPython(approve_manager_queue, migrations.RunPython.noop),
    ]
