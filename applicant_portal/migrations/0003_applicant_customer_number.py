# Generated for customer_number on applicant accounts

from django.db import migrations, models


def fill_empty_customer_numbers(apps, schema_editor):
    Account = apps.get_model('applicant_portal', 'ApplicantAccount')
    for acc in Account.objects.all():
        cn = (getattr(acc, 'customer_number', None) or '').strip()
        if not cn:
            acc.customer_number = f'TMP-{acc.pk}'
            acc.save(update_fields=['customer_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('applicant_portal', '0002_portal_security_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='applicantaccount',
            name='customer_number',
            field=models.CharField(
                blank=True,
                default='',
                max_length=50,
                help_text='Core banking / customer ID used at registration (future login option).',
            ),
        ),
        migrations.RunPython(fill_empty_customer_numbers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='applicantaccount',
            name='customer_number',
            field=models.CharField(
                db_index=True,
                help_text='Core banking / customer ID used at registration (future login option).',
                max_length=50,
                unique=True,
            ),
        ),
    ]
