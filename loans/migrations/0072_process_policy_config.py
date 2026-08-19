# Superadmin-configurable Monitoring / Collections / workout roles

from django.db import migrations, models


DEFAULT_BOOK_OPS = [
    'branch_manager', 'loan_officer', 'credit_loan_officer', 'credit_head',
    'district_manager', 'accountant', 'cooperative_manager', 'operation_manager',
    'finance_manager', 'risk_compliance', 'ceo', 'admin', 'superadmin',
]
DEFAULT_DECIDE = ['credit_head', 'finance_manager', 'ceo', 'admin', 'superadmin']


def seed_process_policy(apps, schema_editor):
    Policy = apps.get_model('loans', 'LoanProcessPolicyConfig')
    if not Policy.objects.exists():
        Policy.objects.create(
            book_ops_roles=DEFAULT_BOOK_OPS,
            workout_decide_roles=DEFAULT_DECIDE,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0071_decsi_process_gaps'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoanProcessPolicyConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('book_ops_roles', models.JSONField(blank=True, default=list, help_text='Staff roles that may open Monitoring and Collections.')),
                ('workout_decide_roles', models.JSONField(blank=True, default=list, help_text='Staff roles that may approve or reject workout and write-off.')),
            ],
            options={
                'verbose_name': 'Loan process policy',
                'verbose_name_plural': 'Loan process policy',
            },
        ),
        migrations.RunPython(seed_process_policy, migrations.RunPython.noop),
    ]
