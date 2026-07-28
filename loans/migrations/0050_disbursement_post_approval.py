# Post-committee disbursement track

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_disbursement_status(apps, schema_editor):
    from django.db.models import Q

    LoanRequest = apps.get_model('loans', 'LoanRequest')
    AppraisalCondition = apps.get_model('loans', 'AppraisalCondition')
    LoanRequest.objects.filter(
        committee_status='committee_approved',
        disbursement_status='',
    ).update(disbursement_status='awaiting_conditions')
    AppraisalCondition.objects.filter(Q(condition_type='covenant')).update(
        required_before_disbursement=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0049_custom_approval_levels'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequest',
            name='disbursement_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Not started'),
                    ('awaiting_conditions', 'Awaiting conditions'),
                    ('schedule_confirmed', 'Schedule confirmed'),
                    ('ready_for_disbursement', 'Ready for disbursement'),
                    ('disbursed', 'Disbursed'),
                ],
                default='',
                help_text='Post-committee track: conditions → schedule → ready → disbursed.',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='schedule_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='schedule_confirmed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loan_schedules_confirmed',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='ready_for_disbursement_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='ready_for_disbursement_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loans_marked_ready_disbursement',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='disbursed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='disbursed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loans_disbursed',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='disbursement_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='appraisalcondition',
            name='required_before_disbursement',
            field=models.BooleanField(
                default=True,
                help_text='If true (typical for conditions precedent), must be fulfilled before schedule confirm / disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='appraisalcondition',
            name='fulfilled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='appraisalcondition',
            name='fulfilled_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='appraisal_conditions_fulfilled',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='appraisalcondition',
            name='evidence_note',
            field=models.TextField(
                blank=True,
                help_text='How this condition was satisfied (document ref, date, etc.).',
            ),
        ),
        migrations.AlterField(
            model_name='loannotification',
            name='kind',
            field=models.CharField(
                choices=[
                    ('vote_needed', 'Vote needed'),
                    ('level_advanced', 'Advanced to next level'),
                    ('committee_approved', 'Committee approved'),
                    ('committee_declined', 'Committee declined'),
                    ('returned_to_officer', 'Returned to loan officer'),
                    ('document_uploaded', 'Document uploaded'),
                    ('document_needs_review', 'Document needs review'),
                    ('document_verified', 'Document verified'),
                    ('document_rejected', 'Document rejected'),
                    ('document_requested', 'Document requested'),
                    ('collateral_assigned', 'Collateral assigned'),
                    ('collateral_submitted', 'Collateral submitted'),
                    ('collateral_engineering_return', 'Collateral returned by engineering'),
                    ('collateral_engineering_approved', 'Collateral approved by engineering'),
                    ('disbursement_ready', 'Ready for disbursement'),
                    ('disbursed', 'Disbursed'),
                ],
                max_length=40,
            ),
        ),
        migrations.RunPython(seed_disbursement_status, migrations.RunPython.noop),
    ]
