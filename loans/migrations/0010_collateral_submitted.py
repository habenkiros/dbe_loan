# Collateral submission tracking for loan officers

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0009_alter_loanrequest_assigned_loan_officer'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequest',
            name='collateral_submitted_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When the loan officer submitted the collateral estimation (summary). All building valuations, land, other collateral are saved when submitted.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='collateral_submitted_by',
            field=models.ForeignKey(
                blank=True,
                help_text='User (e.g. loan officer) who submitted the collateral estimation.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='collateral_submissions',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
