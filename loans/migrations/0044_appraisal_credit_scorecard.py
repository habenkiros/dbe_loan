# Generated manually for credit scorecard / feature snapshot fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0043_alter_loanrequest_declared_address_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanappraisal',
            name='credit_score_band',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='credit_score_total',
            field=models.DecimalField(
                blank=True, decimal_places=2, help_text='Composite 0–100 explainable credit score.',
                max_digits=6, null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='feature_snapshot',
            field=models.JSONField(blank=True, help_text='Versioned appraisal_features_v1 JSON for future ML.', null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='max_loan_capacity',
            field=models.DecimalField(
                blank=True, decimal_places=2, help_text='Max loan capacity from cashflow at target DSCR.',
                max_digits=20, null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='scorecard_detail',
            field=models.JSONField(
                blank=True, default=dict, help_text='Pillars + contributions for explainability / training.', null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='suggested_monthly_installment',
            field=models.DecimalField(
                blank=True, decimal_places=2,
                help_text='Suggested installment from Sheet 1 terms (not from rate workbook).',
                max_digits=18, null=True,
            ),
        ),
    ]
