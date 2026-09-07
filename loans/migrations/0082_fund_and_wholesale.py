from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0081_project_engine_phase_b'),
    ]

    operations = [
        migrations.AddField(
            model_name='financingfund',
            name='envelope_amount',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Total line from the donor / MoF agreement.', max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='max_tenor_months',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='dbe_to_pfi_rate_pct',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='218.26: 4.5% DBE → PFI.', max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='max_end_user_rate_pct',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='218.26: PFI → MSME ≤ 11%.', max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='eligible_regions',
            field=models.CharField(blank=True, help_text='Comma-separated, e.g. Tigray, Amhara, Afar.', max_length=400),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='eligible_sectors',
            field=models.CharField(blank=True, max_length=400),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='women_min_pct',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='On-lending cut, e.g. 30 for 218.26.', max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='youth_min_pct',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='On-lending cut, e.g. 20 for 218.26.', max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='require_climate_cut',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='require_fx_window',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='par90_max_pct',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='218.26: PFI PAR>90 ≤ 10%.', max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='financingfund',
            name='agreement_ref',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.CreateModel(
            name='FundFileTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('women_owned', models.BooleanField(default=False)),
                ('youth_owned', models.BooleanField(default=False)),
                ('climate_tagged', models.BooleanField(default=False)),
                ('fx_window', models.BooleanField(default=False)),
                ('region', models.CharField(blank=True, max_length=120)),
                ('sector', models.CharField(blank=True, max_length=120)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fund_tag',
                    to='loans.loanrequest',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='fund_file_tags_updated',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='PfiInstitutionProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('institution_name', models.CharField(blank=True, max_length=255)),
                ('kind', models.CharField(
                    choices=[
                        ('bank', 'Commercial bank'),
                        ('mfi', 'Microfinance institution'),
                        ('lease', 'Leasing company'),
                        ('rusacco', 'RUSACCO / union'),
                    ],
                    default='mfi',
                    max_length=16,
                )),
                ('license_number', models.CharField(blank=True, max_length=80)),
                ('ownership', models.CharField(blank=True, max_length=120)),
                ('footprint_regions', models.CharField(
                    blank=True, help_text='Regions where the PFI has branches.', max_length=400,
                )),
                ('branch_count', models.PositiveIntegerField(blank=True, null=True)),
                ('has_adequate_mis', models.BooleanField(
                    default=False, help_text='218.26 asks for adequate MIS before a facility.',
                )),
                ('capital', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('liquidity_ratio_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('npl_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('par30_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('par90_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('has_governance', models.BooleanField(default=False)),
                ('has_esms', models.BooleanField(default=False)),
                ('existing_dbe_exposure', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('other_lender_exposure', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('facility_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('tenor_months', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('facility_purpose', models.CharField(
                    choices=[
                        ('wc_onlending', 'Working-capital on-lending'),
                        ('lease_onlending', 'Lease on-lending'),
                    ],
                    default='wc_onlending',
                    max_length=20,
                )),
                ('pfi_match_pct', models.DecimalField(
                    blank=True, decimal_places=2,
                    help_text='Share the PFI matches from its own book.',
                    max_digits=5, null=True,
                )),
                ('end_user_rate_ceiling_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('dbe_to_pfi_rate_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('target_sectors', models.CharField(blank=True, max_length=400)),
                ('target_regions', models.CharField(blank=True, max_length=400)),
                ('target_women_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('target_youth_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('notes', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='pfi_profile',
                    to='loans.loanrequest',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='pfi_profiles_updated',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='PfiUtilizationReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('as_of', models.DateField()),
                ('amount_onlent', models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ('pfi_repaid_to_dbe', models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ('sub_par30_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('sub_par90_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('women_onlent_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('youth_onlent_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('note', models.CharField(blank=True, max_length=400)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('profile', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='utilization_reports',
                    to='loans.pfiinstitutionprofile',
                )),
                ('recorded_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='pfi_utilization_reports',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-as_of', '-id']},
        ),
    ]
