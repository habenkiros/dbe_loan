# Credit committee workflow: submit from loan officer + multi-member votes

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def seed_committee_policy(apps, schema_editor):
    Policy = apps.get_model('loans', 'CommitteeApprovalPolicy')
    if not Policy.objects.exists():
        Policy.objects.create(min_approvals_required=2, min_declines_required=2)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0028_document_authentication'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommitteeApprovalPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'min_approvals_required',
                    models.PositiveIntegerField(
                        default=2,
                        help_text='Number of approve votes required to approve the loan (e.g. 2 of 3 members).',
                    ),
                ),
                (
                    'min_declines_required',
                    models.PositiveIntegerField(
                        default=2,
                        help_text='Number of decline votes required to decline the loan.',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Committee approval policy',
                'verbose_name_plural': 'Committee approval policy',
            },
        ),
        migrations.RunPython(seed_committee_policy, migrations.RunPython.noop),
        migrations.AddField(
            model_name='loanrequest',
            name='appraisal_completed_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When the assigned loan officer finished appraisal (Sheet 7).',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='committee_decided_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='committee_final_amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Final amount after committee majority decision.',
                max_digits=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='committee_final_decision',
            field=models.CharField(
                blank=True,
                choices=[('approve', 'Approve'), ('decline', 'Decline')],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='committee_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Not submitted'),
                    ('pending_committee', 'Pending committee'),
                    ('committee_approved', 'Committee approved'),
                    ('committee_declined', 'Committee declined'),
                    ('returned_to_officer', 'Returned to loan officer'),
                ],
                default='',
                help_text='Credit committee workflow status (separate from queue op/finance approval).',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='committee_submission_notes',
            field=models.TextField(
                blank=True,
                help_text='Loan officer notes when submitting to the approval committee.',
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='submitted_to_committee_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='submitted_to_committee_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loan_requests_submitted_to_committee',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name='LoanCommitteeVote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vote', models.CharField(choices=[('approve', 'Approve'), ('decline', 'Decline')], max_length=20)),
                (
                    'amount_supported',
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text='Amount this member approves (optional; defaults to officer recommendation).',
                        max_digits=20,
                        null=True,
                    ),
                ),
                ('comments', models.TextField(blank=True)),
                ('voted_at', models.DateTimeField(default=django.utils.timezone.now)),
                (
                    'loan_request',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='committee_votes',
                        to='loans.loanrequest',
                    ),
                ),
                (
                    'member',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='committee_votes',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Committee vote',
                'ordering': ['-voted_at'],
                'unique_together': {('loan_request', 'member')},
            },
        ),
    ]
