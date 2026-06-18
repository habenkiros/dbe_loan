# Committee return tracking, in-app notifications, disbursement gate fields

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0032_branch_committee_overrides'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequest',
            name='committee_return_notes',
            field=models.TextField(blank=True, help_text='Committee feedback when returned to the loan officer for corrections.'),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='committee_returned_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='committee_returned_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loan_requests_returned_to_officer',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name='LoanNotification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('vote_needed', 'Vote needed'), ('level_advanced', 'Advanced to next level'), ('committee_approved', 'Committee approved'), ('committee_declined', 'Committee declined'), ('returned_to_officer', 'Returned to loan officer')], max_length=30)),
                ('title', models.CharField(max_length=200)),
                ('message', models.TextField()),
                ('url', models.CharField(blank=True, max_length=500)),
                ('is_read', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('loan_request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='loans.loanrequest')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='loan_notifications', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Loan notification',
                'ordering': ['-created_at'],
            },
        ),
    ]
