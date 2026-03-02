# Add assigned_loan_officer for branch manager assignment

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0007_update_role_choices'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequest',
            name='assigned_loan_officer',
            field=models.ForeignKey(
                blank=True,
                help_text='Loan officer assigned by branch manager for analysis and collateral estimation.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_loan_requests',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
