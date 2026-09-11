# Generated manually for committee P2: routing mode + info requests

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0097_committee_vote_event'),
    ]

    operations = [
        migrations.AddField(
            model_name='loananalysispolicyconfig',
            name='committee_routing_mode',
            field=models.CharField(
                choices=[
                    ('tier', 'Tier (exclusive amount bands)'),
                    ('cumulative', 'Cumulative chain (min floor only)'),
                ],
                default='tier',
                help_text=(
                    'Tier: each level’s min/max band (seed default — one band per amount). '
                    'Cumulative: include every active level whose min ≤ amount (ignore max), '
                    'so larger loans walk Branch → District → HO → Management in sequence.'
                ),
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='CommitteeInfoRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason', models.TextField()),
                ('due_date', models.DateField(blank=True, null=True)),
                ('status', models.CharField(
                    choices=[('open', 'Open'), ('cleared', 'Cleared')],
                    db_index=True,
                    default='open',
                    max_length=20,
                )),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('cleared_at', models.DateTimeField(blank=True, null=True)),
                ('clear_notes', models.TextField(blank=True)),
                ('approval_level', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='info_requests',
                    to='loans.approvalcommitteelevel',
                )),
                ('cleared_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='committee_info_requests_cleared',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='committee_info_requests',
                    to='loans.loanrequest',
                )),
                ('requested_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='committee_info_requests_made',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Committee info request',
                'verbose_name_plural': 'Committee info requests',
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='committeeinforequest',
            index=models.Index(fields=['loan_request', 'status'], name='loans_commi_loan_re_7c2e1a_idx'),
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
                    ('committee_info_requested', 'Committee requested information'),
                    ('committee_info_cleared', 'Committee info request cleared'),
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
                    ('compliance_case_opened', 'Compliance case opened'),
                ],
                max_length=40,
            ),
        ),
    ]
