# Full loan analysis: bureau score summary, stress test DSCR, risks/mitigations, conditions

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0024_appraisal_es_checklist'),
    ]

    operations = [
        # LoanAppraisal: credit score / bureau summary
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_score',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='External bureau / internal credit score (numeric).', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_score_band',
            field=models.CharField(blank=True, choices=[('excellent', 'Excellent'), ('good', 'Good'), ('fair', 'Fair'), ('poor', 'Poor'), ('thin', 'Thin file / No bureau')], help_text='Score band used for decisioning (Excellent/Good/Fair/Poor/Thin file).', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_report_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_active_loans_count',
            field=models.PositiveIntegerField(blank=True, help_text='Number of active loans per bureau.', null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_total_outstanding',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Total outstanding debt per bureau.', max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_total_monthly_debt_service',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Total monthly debt service from bureau (all loans).', max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_inquiries_6m',
            field=models.PositiveIntegerField(blank=True, help_text='Credit inquiries in last 6 months.', null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_defaults_ever',
            field=models.BooleanField(blank=True, help_text='Any default history (ever) per bureau.', null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_restructured_ever',
            field=models.BooleanField(blank=True, help_text='Any restructuring/rescheduling history per bureau.', null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='bureau_thin_file',
            field=models.BooleanField(blank=True, help_text='True if no bureau record / insufficient history.', null=True),
        ),

        # LoanAppraisal: stress test
        migrations.AddField(
            model_name='loanappraisal',
            name='stress_sales_drop_pct',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Stress: sales/income drop percentage (e.g., 10 for -10%).', max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='stress_cost_increase_pct',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Stress: expense increase percentage (e.g., 5 for +5%).', max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='stressed_net_monthly_cashflow',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Computed stressed net monthly cashflow.', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='stressed_dscr',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Computed stressed DSCR: stressed net / proposed installment.', max_digits=10, null=True),
        ),

        # Structured risks/mitigations
        migrations.CreateModel(
            name='AppraisalRiskMitigation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('risk', models.CharField(help_text='Risk statement (what could go wrong).', max_length=255)),
                ('severity', models.CharField(blank=True, choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], max_length=10, null=True)),
                ('mitigation', models.TextField(blank=True, help_text='Mitigation / control / condition to reduce the risk.', null=True)),
                ('owner', models.CharField(blank=True, help_text='Who will implement the mitigation (e.g., client, branch, credit).', max_length=120, null=True)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('status', models.CharField(blank=True, help_text='Open / In progress / Done (free text).', max_length=40, null=True)),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('appraisal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='risk_mitigations', to='loans.loanappraisal')),
            ],
            options={
                'ordering': ['display_order', 'id'],
            },
        ),

        # Conditions precedent / covenants
        migrations.CreateModel(
            name='AppraisalCondition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('condition_type', models.CharField(blank=True, choices=[('cp', 'Condition precedent'), ('covenant', 'Covenant / monitoring'), ('other', 'Other')], max_length=20, null=True)),
                ('description', models.TextField(help_text='Condition text (clear and measurable).')),
                ('responsible_party', models.CharField(blank=True, max_length=120, null=True)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('fulfilled', models.BooleanField(blank=True, null=True)),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('appraisal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conditions', to='loans.loanappraisal')),
            ],
            options={
                'ordering': ['display_order', 'id'],
            },
        ),
    ]

