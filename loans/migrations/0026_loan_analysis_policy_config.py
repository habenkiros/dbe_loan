# Configurable loan analysis policy (warnings + hard block thresholds)

from decimal import Decimal

from django.db import migrations, models


def seed_policy(apps, schema_editor):
    Policy = apps.get_model('loans', 'LoanAnalysisPolicyConfig')
    if not Policy.objects.exists():
        Policy.objects.create()


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0025_full_loan_analysis'),
        ('loans', '0025_qualitative_factor_weight_earned_score'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoanAnalysisPolicyConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'warn_monthly_dscr_min',
                    models.DecimalField(
                        decimal_places=4,
                        default=Decimal('1.2000'),
                        help_text='Warn if monthly DSCR is below this (base policy hint).',
                        max_digits=6,
                    ),
                ),
                (
                    'warn_annual_dscr_min',
                    models.DecimalField(
                        decimal_places=4,
                        default=Decimal('1.2000'),
                        help_text='Warn if annual DSCR is below this.',
                        max_digits=6,
                    ),
                ),
                (
                    'warn_stressed_dscr_min',
                    models.DecimalField(
                        decimal_places=4,
                        default=Decimal('1.0000'),
                        help_text='Warn if stressed DSCR is below this.',
                        max_digits=6,
                    ),
                ),
                (
                    'warn_collateral_coverage_min',
                    models.DecimalField(
                        decimal_places=4,
                        default=Decimal('1.0000'),
                        help_text='Warn if collateral coverage ratio is below this.',
                        max_digits=6,
                    ),
                ),
                (
                    'warn_bureau_inquiries_count',
                    models.PositiveIntegerField(
                        default=3,
                        help_text='Warn if bureau inquiries in 6 months are at or above this number.',
                    ),
                ),
                (
                    'hard_block_qualitative_fail',
                    models.BooleanField(default=True, help_text='Block when qualitative assessment failed.'),
                ),
                (
                    'hard_block_es_reject',
                    models.BooleanField(default=True, help_text='Block when E&S eligibility is REJECT.'),
                ),
                (
                    'hard_block_es_high_risk',
                    models.BooleanField(
                        default=False,
                        help_text='Block when E&S risk category is High.',
                    ),
                ),
                (
                    'hard_block_annual_dscr',
                    models.BooleanField(
                        default=True,
                        help_text='Enable hard block when annual DSCR is below hard_annual_dscr_min.',
                    ),
                ),
                (
                    'hard_annual_dscr_min',
                    models.DecimalField(
                        decimal_places=4,
                        default=Decimal('1.0000'),
                        help_text='Hard block if annual DSCR is strictly below this (when enabled).',
                        max_digits=6,
                    ),
                ),
                (
                    'hard_block_stressed_dscr',
                    models.BooleanField(
                        default=True,
                        help_text='Enable hard block when stressed DSCR is below hard_stressed_dscr_min.',
                    ),
                ),
                (
                    'hard_stressed_dscr_min',
                    models.DecimalField(
                        decimal_places=4,
                        default=Decimal('1.0000'),
                        help_text='Hard block if stressed DSCR is strictly below this (when enabled).',
                        max_digits=6,
                    ),
                ),
                (
                    'hard_block_monthly_dscr',
                    models.BooleanField(
                        default=False,
                        help_text='Enable hard block when monthly DSCR is below hard_monthly_dscr_min.',
                    ),
                ),
                (
                    'hard_monthly_dscr_min',
                    models.DecimalField(
                        decimal_places=4,
                        default=Decimal('1.0000'),
                        help_text='Hard block if monthly DSCR is strictly below this (when enabled).',
                        max_digits=6,
                    ),
                ),
                (
                    'hard_block_bureau_defaults',
                    models.BooleanField(
                        default=True,
                        help_text='Block when bureau indicates historical defaults.',
                    ),
                ),
                (
                    'hard_block_bureau_restructured',
                    models.BooleanField(
                        default=False,
                        help_text='Block when bureau indicates past restructuring.',
                    ),
                ),
                (
                    'hard_block_bureau_inquiries',
                    models.BooleanField(
                        default=False,
                        help_text='Block when inquiries in 6 months are at or above hard_bureau_inquiries_count.',
                    ),
                ),
                (
                    'hard_bureau_inquiries_count',
                    models.PositiveIntegerField(
                        default=3,
                        help_text='Hard block when inquiries >= this (when inquiry hard block enabled).',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Loan analysis policy',
                'verbose_name_plural': 'Loan analysis policy',
            },
        ),
        migrations.RunPython(seed_policy, migrations.RunPython.noop),
    ]
