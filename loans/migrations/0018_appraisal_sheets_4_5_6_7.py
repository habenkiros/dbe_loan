# Sheets (4) E&S, (5) Collateral worksheet, (6) Summary & decision, (7) Amortization

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0017_appraisal_sheet1_sheet2'),
    ]

    operations = [
        # Sheet (4) E&S Assessment
        migrations.AddField(
            model_name='loanappraisal',
            name='es_risk_category',
            field=models.CharField(blank=True, choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='es_eligibility_decision',
            field=models.CharField(blank=True, choices=[('pass', 'PASS'), ('pass_action', 'PASS WITH ACTION POINTS'), ('reject', 'REJECT')], max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='es_screened_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='es_screened_appraisals', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='es_checked_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='es_checked_appraisals', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='es_approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='es_approved_appraisals', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='es_assessment_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='es_notes',
            field=models.TextField(blank=True, null=True),
        ),
        # Sheet (5) Collateral breakdown
        migrations.AddField(
            model_name='loanappraisal',
            name='collateral_immovable_value',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='collateral_moveable_value',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='collateral_intangible_value',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='collateral_guarantors_value',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='collateral_coverage_ratio',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        # Sheet (6) Summary & decision
        migrations.AddField(
            model_name='loanappraisal',
            name='strengths',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='weaknesses',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='committee_comments',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='amount_approved',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='term_approved_months',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='rate_approved',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
        # Sheet (7) Amortization
        migrations.CreateModel(
            name='AppraisalAmortizationEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_number', models.PositiveIntegerField()),
                ('payment_date', models.DateField(blank=True, null=True)),
                ('payment_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('principal', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('interest', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('balance_after', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('appraisal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='amortization_entries', to='loans.loanappraisal')),
            ],
            options={
                'ordering': ['period_number'],
                'verbose_name_plural': 'Appraisal amortization entries',
            },
        ),
    ]
