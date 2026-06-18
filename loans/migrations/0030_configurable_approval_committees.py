# Configurable multi-level approval committees (branch → district → HO → management)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_approval_levels(apps, schema_editor):
    Level = apps.get_model('loans', 'ApprovalCommitteeLevel')
    Rule = apps.get_model('loans', 'ApprovalCommitteeMemberRule')
    CustomUser = apps.get_model('loans', 'CustomUser')

    role_choices = [c[0] for c in CustomUser._meta.get_field('role').choices]

    def add_level(key, name, order, min_app=2, min_dec=2):
        level, _ = Level.objects.update_or_create(
            key=key,
            defaults={
                'name': name,
                'sequence_order': order,
                'is_active': True,
                'min_approvals_required': min_app,
                'min_declines_required': min_dec,
            },
        )
        return level

    def add_role(level, role, label=''):
        if role not in role_choices:
            return
        Rule.objects.get_or_create(
            level=level,
            participant_type='role',
            role=role,
            user=None,
            defaults={'label': label, 'is_active': True},
        )

    branch = add_level('branch', 'Branch approval committee', 1, 2, 2)
    for r, lbl in [
        ('loan_officer', 'Loan officer'),
        ('branch_manager', 'Branch manager'),
        ('accountant', 'Branch accountant'),
    ]:
        add_role(branch, r, lbl)

    district = add_level('district', 'District approval committee', 2, 2, 2)
    for r, lbl in [
        ('district_manager', 'District manager'),
        ('accountant', 'District accountant'),
        ('branch_manager', 'Branch manager (district)'),
    ]:
        add_role(district, r, lbl)

    ho = add_level('head_office', 'Head office approval committee', 3, 2, 2)
    for r, lbl in [
        ('operation_manager', 'Operation manager'),
        ('finance_manager', 'Finance manager'),
        ('credit_committee', 'Credit committee'),
    ]:
        add_role(ho, r, lbl)

    mgmt = add_level('management', 'Management approval committee', 4, 2, 2)
    for r, lbl in [
        ('ceo', 'CEO'),
        ('vp', 'Vice president'),
        ('board_member', 'Board member'),
    ]:
        add_role(mgmt, r, lbl)


def attach_legacy_votes_to_branch(apps, schema_editor):
    Vote = apps.get_model('loans', 'LoanCommitteeVote')
    Level = apps.get_model('loans', 'ApprovalCommitteeLevel')
    branch = Level.objects.filter(key='branch').first()
    if not branch:
        return
    Vote.objects.filter(approval_level__isnull=True).update(approval_level=branch)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0029_committee_approval_workflow'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(
                choices=[
                    ('superadmin', 'Super Administrator'),
                    ('admin', 'System Administrator'),
                    ('engineering_head', 'Engineering Head'),
                    ('engineer', 'Engineer / Valuer'),
                    ('loan_officer', 'Loan Officer'),
                    ('branch_manager', 'Branch Manager'),
                    ('accountant', 'Accountant'),
                    ('district_manager', 'District Manager'),
                    ('operation_manager', 'Operation Manager'),
                    ('finance_manager', 'Finance Manager'),
                    ('credit_committee', 'Credit Committee Member'),
                    ('ceo', 'Chief Executive Officer'),
                    ('vp', 'Vice President'),
                    ('board_member', 'Board Member'),
                    ('risk_compliance', 'Risk & Compliance Officer'),
                    ('auditor', 'Auditor / Viewer'),
                ],
                default='loan_officer',
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name='ApprovalCommitteeLevel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(choices=[('branch', 'Branch committee'), ('district', 'District committee'), ('head_office', 'Head office committee'), ('management', 'Management committee (CEO / VP / Board)')], max_length=30, unique=True)),
                ('name', models.CharField(help_text='Display name in UI.', max_length=120)),
                ('sequence_order', models.PositiveIntegerField(default=1, help_text='Order in the chain (1 = first after loan officer submits).')),
                ('is_active', models.BooleanField(default=True)),
                ('min_approvals_required', models.PositiveIntegerField(default=2, help_text='Approve votes needed at this level (e.g. 2 of 3 branch members).')),
                ('min_declines_required', models.PositiveIntegerField(default=2, help_text='Decline votes needed to reject at this level.')),
                ('min_loan_amount', models.DecimalField(blank=True, decimal_places=2, help_text='Optional: level applies only if requested amount ≥ this.', max_digits=20, null=True)),
                ('max_loan_amount', models.DecimalField(blank=True, decimal_places=2, help_text='Optional: level applies only if requested amount ≤ this.', max_digits=20, null=True)),
            ],
            options={
                'verbose_name': 'Approval committee level',
                'verbose_name_plural': 'Approval committee levels',
                'ordering': ['sequence_order', 'id'],
            },
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='current_approval_level',
            field=models.ForeignKey(
                blank=True,
                help_text='Active approval level (branch → district → head office → management).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loan_requests_at_level',
                to='loans.approvalcommitteelevel',
            ),
        ),
        migrations.CreateModel(
            name='ApprovalCommitteeMemberRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('participant_type', models.CharField(choices=[('role', 'Anyone with role'), ('user', 'Specific user')], default='role', max_length=10)),
                ('role', models.CharField(blank=True, choices=[('superadmin', 'Super Administrator'), ('admin', 'System Administrator'), ('engineering_head', 'Engineering Head'), ('engineer', 'Engineer / Valuer'), ('loan_officer', 'Loan Officer'), ('branch_manager', 'Branch Manager'), ('accountant', 'Accountant'), ('district_manager', 'District Manager'), ('operation_manager', 'Operation Manager'), ('finance_manager', 'Finance Manager'), ('credit_committee', 'Credit Committee Member'), ('ceo', 'Chief Executive Officer'), ('vp', 'Vice President'), ('board_member', 'Board Member'), ('risk_compliance', 'Risk & Compliance Officer'), ('auditor', 'Auditor / Viewer')], help_text='For branch: user must belong to the loan branch. For district: loan district.', max_length=30)),
                ('label', models.CharField(blank=True, help_text='Optional label shown in admin (e.g. Branch accountant).', max_length=120)),
                ('is_active', models.BooleanField(default=True)),
                ('level', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='member_rules', to='loans.approvalcommitteelevel')),
                ('user', models.ForeignKey(blank=True, help_text='Named participant (e.g. CEO) when not using role.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='approval_committee_rules', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Committee member rule',
                'ordering': ['level__sequence_order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='LoanApprovalLevelProgress',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('declined', 'Declined'), ('skipped', 'Skipped')], default='pending', max_length=20)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('level', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='loan_progress', to='loans.approvalcommitteelevel')),
                ('loan_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='approval_level_progress', to='loans.loanrequest')),
            ],
            options={
                'verbose_name': 'Loan approval level progress',
                'ordering': ['level__sequence_order'],
                'unique_together': {('loan_request', 'level')},
            },
        ),
        migrations.AddField(
            model_name='loancommitteevote',
            name='approval_level',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='votes',
                to='loans.approvalcommitteelevel',
            ),
        ),
        migrations.RunPython(seed_approval_levels, migrations.RunPython.noop),
        migrations.RunPython(attach_legacy_votes_to_branch, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name='loancommitteevote',
            unique_together={('loan_request', 'member', 'approval_level')},
        ),
        migrations.AlterField(
            model_name='loancommitteevote',
            name='approval_level',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='votes',
                to='loans.approvalcommitteelevel',
            ),
        ),
    ]
