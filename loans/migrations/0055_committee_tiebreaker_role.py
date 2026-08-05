# Tiebreaker role on approval committee levels (chair weight on equal votes)

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


DEFAULTS = {
    'branch': 'branch_manager',
    'district': 'district_manager',
    'head_office': 'credit_head',
    # management: leave blank so runtime default uses board_member then ceo
}


def seed_tiebreaker_roles(apps, schema_editor):
    Level = apps.get_model('loans', 'ApprovalCommitteeLevel')
    for key, role in DEFAULTS.items():
        Level.objects.filter(key=key).exclude(tiebreaker_role__gt='').update(tiebreaker_role=role)
    Level.objects.filter(key='management').update(tiebreaker_role='')


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0054_departments_vp_roles_remove_credit_committee'),
    ]

    operations = [
        migrations.AddField(
            model_name='approvalcommitteelevel',
            name='tiebreaker_role',
            field=models.CharField(
                blank=True,
                choices=ROLE_CHOICES,
                help_text=(
                    'When approve and decline votes are equal, this role’s vote decides. '
                    'Defaults by level: branch→branch_manager, district→district_manager, '
                    'head_office→credit_head, management→board_member then ceo.'
                ),
                max_length=30,
            ),
        ),
        migrations.RunPython(seed_tiebreaker_roles, migrations.RunPython.noop),
    ]
