from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0015_loan_document_request_and_reviewed'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoanAppraisal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('monthly_business_income', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('monthly_business_expenses', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('other_monthly_income', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('other_monthly_expenses', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('proposed_monthly_installment', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('net_monthly_cashflow', models.DecimalField(blank=True, decimal_places=2, help_text='Calculated as (business + other income) – (business + other expenses).', max_digits=18, null=True)),
                ('dscr', models.DecimalField(blank=True, decimal_places=2, help_text='Debt service coverage ratio (net cashflow / proposed installment).', max_digits=10, null=True)),
                ('business_assessment', models.TextField(blank=True, help_text='Summary of business assessment.', null=True)),
                ('character_assessment', models.TextField(blank=True, help_text='Summary of character / E&S assessment.', null=True)),
                ('collateral_total_value', models.DecimalField(blank=True, decimal_places=2, help_text='Total collateral value considered in this appraisal (snapshot).', max_digits=20, null=True)),
                ('recommendation', models.CharField(blank=True, choices=[('approve', 'Approve'), ('decline', 'Decline'), ('escalate', 'Escalate / further review')], max_length=20, null=True)),
                ('recommendation_comment', models.TextField(blank=True, help_text='Reasoning behind the recommendation.', null=True)),
                ('created_by', models.ForeignKey(blank=True, help_text='Loan officer who created this appraisal.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='loan_appraisals_created', to=settings.AUTH_USER_MODEL)),
                ('loan_request', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='appraisal', to='loans.loanrequest')),
            ],
        ),
    ]

