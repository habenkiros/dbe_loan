# Collateral estimation mode (loan officer vs engineering team) and sent_to_engineering / assigned_engineer

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0010_collateral_submitted'),
    ]

    operations = [
        migrations.CreateModel(
            name='CollateralEstimationConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mode', models.CharField(
                    choices=[('loan_officer', 'Loan Officer (branch manager assigns loan officer)'), ('engineering_team', 'Engineering Team (branch manager sends to engineering head; engineering head assigns engineer)')],
                    default='loan_officer',
                    help_text='Who performs collateral estimation: loan officer or engineering team.',
                    max_length=20,
                )),
            ],
            options={
                'verbose_name': 'Collateral estimation config',
                'verbose_name_plural': 'Collateral estimation config',
            },
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='sent_to_engineering_at',
            field=models.DateTimeField(blank=True, help_text='When branch manager sent this loan to engineering head for collateral estimation.', null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='assigned_engineer',
            field=models.ForeignKey(
                blank=True,
                help_text='Engineer assigned by engineering head for collateral estimation (when mode is Engineering Team).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_engineer_loan_requests',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(
            lambda apps, schema_editor: apps.get_model('loans', 'CollateralEstimationConfig').objects.get_or_create(
                defaults={'mode': 'loan_officer'}
            ),
            migrations.RunPython.noop,
        ),
    ]
