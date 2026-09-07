import django.db.models.deletion
from django.db import migrations, models


def seed_dbe_desks(apps, schema_editor):
    Department = apps.get_model('loans', 'Department')
    rows = (
        ('crm', 'Credit Relation Management (CRM)', 10),
        ('appraisal', 'Appraisal Directorate', 11),
        ('engineering', 'Engineering Directorate', 12),
        ('legal', 'Legal Affairs Directorate', 13),
        ('hrm', 'Human Resource Management', 14),
        ('ongoing_concern', 'Ongoing Concern & Acquired Assets', 15),
        ('scan_admin', 'Scanning / Admin Unit', 16),
        ('its', 'ITS Directorate', 17),
        ('mis', 'PM & MIS Directorate', 18),
        ('external_fund', 'External Fund & Wholesale Financing', 19),
    )
    for key, name, order in rows:
        Department.objects.get_or_create(
            key=key,
            defaults={'name': name, 'sort_order': order, 'is_active': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0086_product_relations_and_appraisal_modes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='department',
            name='key',
            field=models.CharField(
                choices=[
                    ('cooperative', 'Branch Cooperative'),
                    ('finance', 'Finance'),
                    ('credit', 'Credit'),
                    ('management', 'Management'),
                    ('board', 'Board of Directors'),
                    ('crm', 'Credit Relation Management (CRM)'),
                    ('appraisal', 'Appraisal Directorate'),
                    ('engineering', 'Engineering Directorate'),
                    ('legal', 'Legal Affairs Directorate'),
                    ('hrm', 'Human Resource Management'),
                    ('ongoing_concern', 'Ongoing Concern & Acquired Assets'),
                    ('scan_admin', 'Scanning / Admin Unit'),
                    ('its', 'ITS Directorate'),
                    ('mis', 'PM & MIS Directorate'),
                    ('external_fund', 'External Fund & Wholesale Financing'),
                ],
                max_length=30,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='department',
            field=models.ForeignKey(
                blank=True,
                help_text='Head-office work unit (DECSI departments or DBE CRM / Appraisal / …).',
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='users',
                to='loans.department',
            ),
        ),
        migrations.RunPython(seed_dbe_desks, migrations.RunPython.noop),
    ]
