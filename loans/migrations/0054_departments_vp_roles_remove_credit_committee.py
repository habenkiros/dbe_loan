# Department model, VP specialty roles, retire credit_committee voters

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
    ('ceo', 'Chief Executive Officer'),
    ('vp', 'Vice President'),
    ('vp_operations', 'VP Operations'),
    ('vp_it', 'VP IT'),
    ('vp_customer_service', 'VP Customer Service'),
    ('board_member', 'Board Member'),
    ('risk_compliance', 'Risk & Compliance Officer'),
    ('auditor', 'Auditor / Viewer'),
    ('operation_manager', 'Operation Manager (legacy)'),
    ('credit_committee', 'Credit Committee Member (legacy)'),
]


DEFAULT_DEPARTMENTS = [
    ('cooperative', 'Branch Cooperative', 1),
    ('finance', 'Finance', 2),
    ('credit', 'Credit', 3),
    ('management', 'Management', 4),
    ('board', 'Board of Directors', 5),
]


def seed_departments(apps, schema_editor):
    Department = apps.get_model('loans', 'Department')
    for key, name, order in DEFAULT_DEPARTMENTS:
        Department.objects.get_or_create(
            key=key,
            defaults={'name': name, 'sort_order': order, 'is_active': True},
        )


def migrate_credit_committee_away(apps, schema_editor):
    CustomUser = apps.get_model('loans', 'CustomUser')
    for user in CustomUser.objects.filter(role='credit_committee'):
        if user.branch_id or user.district_id:
            user.role = 'accountant'
        else:
            user.role = 'credit_loan_officer'
        user.save(update_fields=['role'])

    ApprovalCommitteeMemberRule = apps.get_model('loans', 'ApprovalCommitteeMemberRule')
    ApprovalCommitteeMemberRule.objects.filter(role='credit_committee').delete()
    try:
        BranchRule = apps.get_model('loans', 'BranchCommitteeMemberRule')
    except LookupError:
        BranchRule = None
    if BranchRule is not None:
        BranchRule.objects.filter(role='credit_committee').delete()


def migrate_vp_specialty_roles(apps, schema_editor):
    CustomUser = apps.get_model('loans', 'CustomUser')
    mapping = {
        'vp.operations': 'vp_operations',
        'vp.it': 'vp_it',
        'vp.customerservice': 'vp_customer_service',
    }
    for username, role in mapping.items():
        CustomUser.objects.filter(username=username).update(role=role)


def assign_users_to_departments(apps, schema_editor):
    CustomUser = apps.get_model('loans', 'CustomUser')
    Department = apps.get_model('loans', 'Department')
    depts = {d.key: d for d in Department.objects.all()}
    role_to_dept = {
        'cooperative_manager': 'cooperative',
        'operation_manager': 'cooperative',
        'finance_manager': 'finance',
        'credit_head': 'credit',
        'credit_loan_officer': 'credit',
        'ceo': 'management',
        'vp': 'management',
        'vp_operations': 'management',
        'vp_it': 'management',
        'vp_customer_service': 'management',
        'board_member': 'board',
    }
    for role, dept_key in role_to_dept.items():
        dept = depts.get(dept_key)
        if not dept:
            continue
        CustomUser.objects.filter(role=role, department__isnull=True).update(department=dept)


def ensure_management_committee_vp_rules(apps, schema_editor):
    """Management level can vote via specialized VP roles as well as generic vp."""
    ApprovalCommitteeLevel = apps.get_model('loans', 'ApprovalCommitteeLevel')
    ApprovalCommitteeMemberRule = apps.get_model('loans', 'ApprovalCommitteeMemberRule')
    mgmt = ApprovalCommitteeLevel.objects.filter(key='management').first()
    if not mgmt:
        return
    for role, label in (
        ('vp', 'Vice president'),
        ('vp_operations', 'VP Operations'),
        ('vp_it', 'VP IT'),
        ('vp_customer_service', 'VP Customer Service'),
        ('ceo', 'CEO'),
        ('board_member', 'Board member'),
    ):
        ApprovalCommitteeMemberRule.objects.get_or_create(
            level=mgmt,
            participant_type='role',
            role=role,
            defaults={'label': label, 'is_active': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0053_org_roles_restructure'),
    ]

    operations = [
        migrations.CreateModel(
            name='Department',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(
                    choices=[
                        ('cooperative', 'Branch Cooperative'),
                        ('finance', 'Finance'),
                        ('credit', 'Credit'),
                        ('management', 'Management'),
                        ('board', 'Board of Directors'),
                    ],
                    max_length=30,
                    unique=True,
                )),
                ('name', models.CharField(max_length=120)),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.AddField(
            model_name='customuser',
            name='department',
            field=models.ForeignKey(
                blank=True,
                help_text='Head-office department (Cooperative, Finance, Credit, Management, Board).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='users',
                to='loans.department',
            ),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(choices=ROLE_CHOICES, default='loan_officer', max_length=30),
        ),
        migrations.RunPython(seed_departments, migrations.RunPython.noop),
        migrations.RunPython(migrate_credit_committee_away, migrations.RunPython.noop),
        migrations.RunPython(migrate_vp_specialty_roles, migrations.RunPython.noop),
        migrations.RunPython(assign_users_to_departments, migrations.RunPython.noop),
        migrations.RunPython(ensure_management_committee_vp_rules, migrations.RunPython.noop),
    ]
