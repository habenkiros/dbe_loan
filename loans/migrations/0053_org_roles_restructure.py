# Org roles restructure: cooperative_manager, credit roles, finance disbursement gate

import django.db.models.deletion
from django.db import migrations, models


ROLE_CHOICES = [
    ('superadmin', 'Super Administrator'),
    ('admin', 'System Administrator'),
    ('engineering_head', 'Engineering Head'),
    ('engineer', 'Engineer / Valuer'),
    ('loan_officer', 'Loan Officer'),
    ('branch_manager', 'Branch Manager'),
    ('accountant', 'Accountant'),
    ('district_manager', 'District Manager'),
    ('cooperative_manager', 'Branch Cooperative Manager'),
    ('finance_manager', 'Finance Manager'),
    ('credit_head', 'Credit Department Head'),
    ('credit_loan_officer', 'Credit Loan Officer'),
    ('credit_committee', 'Credit Committee Member'),
    ('ceo', 'Chief Executive Officer'),
    ('vp', 'Vice President'),
    ('board_member', 'Board Member'),
    ('risk_compliance', 'Risk & Compliance Officer'),
    ('auditor', 'Auditor / Viewer'),
    ('operation_manager', 'Operation Manager (legacy)'),
]


def migrate_operation_manager_role(apps, schema_editor):
    CustomUser = apps.get_model('loans', 'CustomUser')
    CustomUser.objects.filter(role='operation_manager').update(role='cooperative_manager')
    ApprovalCommitteeMemberRule = apps.get_model('loans', 'ApprovalCommitteeMemberRule')
    ApprovalCommitteeMemberRule.objects.filter(role='operation_manager').update(role='cooperative_manager')
    try:
        BranchRule = apps.get_model('loans', 'BranchCommitteeMemberRule')
    except LookupError:
        BranchRule = None
    if BranchRule is not None:
        BranchRule.objects.filter(role='operation_manager').update(role='cooperative_manager')


def noop_reverse(apps, schema_editor):
    CustomUser = apps.get_model('loans', 'CustomUser')
    CustomUser.objects.filter(role='cooperative_manager').update(role='operation_manager')
    ApprovalCommitteeMemberRule = apps.get_model('loans', 'ApprovalCommitteeMemberRule')
    ApprovalCommitteeMemberRule.objects.filter(role='cooperative_manager').update(role='operation_manager')
    try:
        BranchRule = apps.get_model('loans', 'BranchCommitteeMemberRule')
    except LookupError:
        BranchRule = None
    if BranchRule is not None:
        BranchRule.objects.filter(role='cooperative_manager').update(role='operation_manager')


def update_ho_committee_voters(apps, schema_editor):
    """Prefer credit_head / credit_loan_officer at HO; drop cooperative from HO voters."""
    ApprovalCommitteeLevel = apps.get_model('loans', 'ApprovalCommitteeLevel')
    ApprovalCommitteeMemberRule = apps.get_model('loans', 'ApprovalCommitteeMemberRule')
    ho = ApprovalCommitteeLevel.objects.filter(key='head_office').first()
    if not ho:
        return
    ApprovalCommitteeMemberRule.objects.filter(
        level=ho, role='cooperative_manager',
    ).delete()
    ApprovalCommitteeMemberRule.objects.filter(
        level=ho, role='operation_manager',
    ).delete()
    for role, label in (
        ('credit_head', 'Credit department head'),
        ('credit_loan_officer', 'Credit loan officer'),
        ('finance_manager', 'Finance manager'),
    ):
        ApprovalCommitteeMemberRule.objects.get_or_create(
            level=ho,
            participant_type='role',
            role=role,
            defaults={'label': label, 'is_active': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0052_cbs_disbursement_booking_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequest',
            name='finance_disbursement_approval',
            field=models.BooleanField(
                default=False,
                help_text='Finance department approval required before confirming disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='origin_level',
            field=models.CharField(
                choices=[('branch', 'Branch'), ('head_office', 'Head Office / Credit')],
                db_index=True,
                default='branch',
                help_text='Where the loan was originated: branch (default) or head-office Credit.',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(choices=ROLE_CHOICES, default='loan_officer', max_length=30),
        ),
        migrations.AlterField(
            model_name='loanrequest',
            name='operation_manager_approval',
            field=models.BooleanField(
                default=False,
                help_text='Branch Cooperative intake-queue approval (field name kept for DB compatibility).',
            ),
        ),
        migrations.AlterField(
            model_name='loanrequest',
            name='finance_approval',
            field=models.BooleanField(
                default=False,
                help_text='Legacy intake flag; no longer required for queue. Prefer finance_disbursement_approval.',
            ),
        ),
        migrations.AlterField(
            model_name='loanrequest',
            name='assigned_loan_officer',
            field=models.ForeignKey(
                blank=True,
                help_text='Loan officer assigned for analysis and collateral estimation.',
                limit_choices_to=models.Q(('role__in', ['loan_officer', 'credit_loan_officer'])),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_loan_requests',
                to='loans.customuser',
            ),
        ),
        migrations.RunPython(migrate_operation_manager_role, noop_reverse),
        migrations.RunPython(update_ho_committee_voters, migrations.RunPython.noop),
    ]
