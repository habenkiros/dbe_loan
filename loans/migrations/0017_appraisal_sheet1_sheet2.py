# Sheet (1) Basic Info and Sheet (2) Business & character – models

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0016_loan_appraisal'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoanRequestBasicInfo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tin_number', models.CharField(blank=True, max_length=50, null=True)),
                ('gender', models.CharField(blank=True, choices=[('Male', 'Male'), ('Female', 'Female')], max_length=20, null=True)),
                ('age', models.PositiveIntegerField(blank=True, null=True)),
                ('marital_status', models.CharField(blank=True, max_length=30, null=True)),
                ('education_level', models.CharField(blank=True, max_length=100, null=True)),
                ('home_address', models.TextField(blank=True, null=True)),
                ('spouse_name', models.CharField(blank=True, max_length=255, null=True)),
                ('spouse_occupation', models.CharField(blank=True, max_length=255, null=True)),
                ('father_name', models.CharField(blank=True, max_length=255, null=True)),
                ('grandfather_name', models.CharField(blank=True, max_length=255, null=True)),
                ('business_name', models.CharField(blank=True, max_length=255, null=True)),
                ('business_description', models.TextField(blank=True, null=True)),
                ('business_address', models.TextField(blank=True, null=True)),
                ('date_business_started', models.DateField(blank=True, null=True)),
                ('form_of_ownership', models.CharField(blank=True, max_length=100, null=True)),
                ('economic_sector', models.CharField(blank=True, max_length=100, null=True)),
                ('subsector_activity', models.CharField(blank=True, max_length=255, null=True)),
                ('employees_full_time', models.PositiveIntegerField(blank=True, null=True)),
                ('employees_part_time', models.PositiveIntegerField(blank=True, null=True)),
                ('employees_seasonal', models.PositiveIntegerField(blank=True, null=True)),
                ('employees_ft_equivalent', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('family_members_employed', models.PositiveIntegerField(blank=True, null=True)),
                ('peak_sales_months', models.CharField(blank=True, max_length=100, null=True)),
                ('lowest_sales_months', models.CharField(blank=True, max_length=100, null=True)),
                ('number_business_owners', models.PositiveIntegerField(blank=True, null=True)),
                ('term_months', models.PositiveIntegerField(blank=True, null=True)),
                ('repayment_frequency', models.CharField(blank=True, max_length=50, null=True)),
                ('interest_rate', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('interest_basis', models.CharField(blank=True, max_length=50, null=True)),
                ('grace_period_months', models.PositiveIntegerField(blank=True, null=True)),
                ('interest_only_months', models.PositiveIntegerField(blank=True, null=True)),
                ('instalments_per_year', models.PositiveIntegerField(blank=True, null=True)),
                ('cash_contribution', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('loan_request', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='basic_info', to='loans.loanrequest')),
            ],
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='nbe_credit_report_obtained',
            field=models.BooleanField(blank=True, help_text='NBE Credit Report obtained (Y/N).', null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='nbe_report_date_received',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='total_number_repaid_loans',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='credit_history_max_score',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='qualitative_total_score',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Business and character total score (0–100). Applicant needs ≥75% to proceed.', max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='qualitative_passed',
            field=models.BooleanField(blank=True, help_text='True if qualitative assessment passed (≥75%). Proceed to Cashflow Analysis.', null=True),
        ),
        migrations.CreateModel(
            name='AppraisalCreditHistoryEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lender', models.CharField(blank=True, max_length=255, null=True)),
                ('loan_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('current_balance', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('maturity_date', models.DateField(blank=True, null=True)),
                ('purpose', models.CharField(blank=True, max_length=255, null=True)),
                ('status', models.CharField(blank=True, choices=[('regular', 'Regular'), ('settled_on_time', 'Settled on time'), ('settled_late', 'Settled late'), ('irregular', 'Irregular'), ('defaulted', 'Defaulted')], max_length=30, null=True)),
                ('repayment', models.CharField(blank=True, max_length=100, null=True)),
                ('letter_from_lender', models.CharField(blank=True, max_length=100, null=True)),
                ('score', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('appraisal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='credit_history_entries', to='loans.loanappraisal')),
            ],
            options={
                'ordering': ['display_order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='AppraisalQualitativeFactor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('factor_key', models.CharField(max_length=50)),
                ('factor_name', models.CharField(blank=True, max_length=255, null=True)),
                ('rating', models.CharField(blank=True, max_length=100, null=True)),
                ('notes', models.TextField(blank=True, help_text='Observation / justification.', null=True)),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('appraisal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='qualitative_factors', to='loans.loanappraisal')),
            ],
            options={
                'ordering': ['display_order', 'id'],
                'unique_together': {('appraisal', 'factor_key')},
            },
        ),
    ]
