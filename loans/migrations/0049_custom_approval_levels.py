# Custom open-ended approval committee levels (voter_scope + free-form key)

import django.db.models.deletion
from django.db import migrations, models


def populate_voter_scope(apps, schema_editor):
    Level = apps.get_model('loans', 'ApprovalCommitteeLevel')
    for level in Level.objects.all():
        if level.key == 'branch':
            level.voter_scope = 'branch'
        elif level.key == 'district':
            level.voter_scope = 'district'
        else:
            level.voter_scope = 'organization'
        level.save(update_fields=['voter_scope'])


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0048_appraisal_banking_behavior'),
    ]

    operations = [
        migrations.AddField(
            model_name='approvalcommitteelevel',
            name='voter_scope',
            field=models.CharField(
                choices=[
                    ('branch', 'Loan’s branch (role users at that branch)'),
                    ('district', 'Loan’s district (role users in that district)'),
                    ('organization', 'Organization-wide (roles or named users)'),
                ],
                default='organization',
                help_text='How role-based voters are scoped for this level.',
                max_length=20,
            ),
        ),
        migrations.RunPython(populate_voter_scope, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='approvalcommitteelevel',
            name='key',
            field=models.SlugField(
                help_text='Stable id (e.g. branch, regional_risk). Used in URLs/logs; unique.',
                max_length=50,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name='branchcommitteeoverride',
            name='level',
            field=models.ForeignKey(
                limit_choices_to={'voter_scope': 'branch'},
                on_delete=django.db.models.deletion.CASCADE,
                related_name='branch_overrides',
                to='loans.approvalcommitteelevel',
            ),
        ),
    ]
