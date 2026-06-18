# Sheet 3 Phase 1 (P&L breakdown) + Phase 2 (annual repayment capacity fields)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0022_qualitative_rating_and_status_none'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_monthly_sales',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Monthly sales / revenue (feeds business income when set).', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_monthly_cogs',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Cost of goods sold (monthly).', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_monthly_salaries',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Salaries (monthly).', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_monthly_rent',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Rent (monthly).', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_monthly_utilities',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Utilities (monthly).', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_monthly_transport',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Transport (monthly).', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_monthly_other_operating',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Other operating expenses (monthly).', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_monthly_taxes',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Taxes (monthly).', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_annual_net_cashflow',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Annual net cashflow (monthly net × 12).', max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='cf_annual_debt_service',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Annual debt service (installment × payments per year from Sheet 1 frequency).', max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='dscr_annual',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Annual DSCR: annual net cashflow / annual debt service.', max_digits=10, null=True),
        ),
    ]
