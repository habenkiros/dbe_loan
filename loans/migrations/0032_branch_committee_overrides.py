# Per-branch committee overrides + branch member rules

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0031_auto_20260604_0228'),
    ]

    operations = [
        migrations.CreateModel(
            name='BranchCommitteeOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True)),
                ('min_approvals_required', models.PositiveIntegerField(blank=True, help_text='Leave blank to use the global level default.', null=True)),
                ('min_declines_required', models.PositiveIntegerField(blank=True, help_text='Leave blank to use the global level default.', null=True)),
                ('notes', models.CharField(blank=True, help_text='Optional note (e.g. “Main street branch — 3-person committee”).', max_length=255)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='committee_overrides', to='loans.branch')),
                (
                    'level',
                    models.ForeignKey(
                        limit_choices_to={'key': 'branch'},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='branch_overrides',
                        to='loans.approvalcommitteelevel',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Branch committee override',
                'verbose_name_plural': 'Branch committee overrides',
                'unique_together': {('branch', 'level')},
            },
        ),
        migrations.CreateModel(
            name='BranchCommitteeMemberRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('participant_type', models.CharField(choices=[('role', 'Anyone with role'), ('user', 'Specific user')], default='role', max_length=10)),
                ('role', models.CharField(blank=True, choices=[('superadmin', 'Super Administrator'), ('admin', 'System Administrator'), ('engineering_head', 'Engineering Head'), ('engineer', 'Engineer / Valuer'), ('loan_officer', 'Loan Officer'), ('branch_manager', 'Branch Manager'), ('accountant', 'Accountant'), ('district_manager', 'District Manager'), ('operation_manager', 'Operation Manager'), ('finance_manager', 'Finance Manager'), ('credit_committee', 'Credit Committee Member'), ('ceo', 'Chief Executive Officer'), ('vp', 'Vice President'), ('board_member', 'Board Member'), ('risk_compliance', 'Risk & Compliance Officer'), ('auditor', 'Auditor / Viewer')], max_length=30)),
                ('label', models.CharField(blank=True, max_length=120)),
                ('is_active', models.BooleanField(default=True)),
                ('override', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='member_rules', to='loans.branchcommitteeoverride')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='branch_committee_rules', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Branch committee member rule',
            },
        ),
    ]
