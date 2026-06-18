# Policy flags for Excel sheet completeness gates

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0026_loan_analysis_policy_config'),
    ]

    operations = [
        migrations.AddField(
            model_name='loananalysispolicyconfig',
            name='hard_block_incomplete_sheets',
            field=models.BooleanField(
                default=True,
                help_text='Block continuing to Sheet 7 when Sheets 1–6 (Excel requirements) are incomplete.',
            ),
        ),
        migrations.AddField(
            model_name='loananalysispolicyconfig',
            name='require_sheets_complete_before_finish',
            field=models.BooleanField(
                default=True,
                help_text='Block finishing appraisal on Sheet 7 until all sheets (including amortization) are complete.',
            ),
        ),
    ]
