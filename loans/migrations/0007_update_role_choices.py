# Update CustomUser role choices and map old values to new

from django.db import migrations, models

ROLE_CHOICES = [
    ('superadmin', 'Super Administrator'),
    ('admin', 'System Administrator'),
    ('engineering_head', 'Engineering Head'),
    ('engineer', 'Engineer / Valuer'),
    ('loan_officer', 'Loan Officer'),
    ('branch_manager', 'Branch Manager'),
    ('operation_manager', 'Operation Manager'),
    ('finance_manager', 'Finance Manager'),
    ('credit_committee', 'Credit Committee Member'),
    ('risk_compliance', 'Risk & Compliance Officer'),
    ('auditor', 'Auditor / Viewer'),
]

OLD_TO_NEW_ROLE = {
    'operational_manager': 'operation_manager',
    'finance': 'finance_manager',
    'manager': 'credit_committee',
}


def migrate_roles(apps, schema_editor):
    CustomUser = apps.get_model('loans', 'CustomUser')
    for old, new in OLD_TO_NEW_ROLE.items():
        CustomUser.objects.filter(role=old).update(role=new)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0006_region_district_city_queue_approved'),
    ]

    operations = [
        migrations.RunPython(migrate_roles, noop_reverse),
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(
                choices=ROLE_CHOICES,
                default='loan_officer',
                max_length=30,
            ),
        ),
    ]
