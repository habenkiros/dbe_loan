from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0079_product_family_and_financing_fund'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanmonitoringvisit',
            name='visit_kind',
            field=models.CharField(
                choices=[('followup', 'Follow-up'), ('implementation', 'Implementation')],
                db_index=True,
                default='followup',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loanmonitoringvisit',
            name='percent_complete',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Physical progress 0–100. Used on project implementation visits.',
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanmonitoringvisit',
            name='purpose_code',
            field=models.CharField(
                blank=True,
                help_text='civil / machinery / working_capital / insurance / other.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loanmonitoringvisit',
            name='unlocks_next_tranche',
            field=models.BooleanField(
                default=False,
                help_text='When set on a project file, this visit may release the next draw.',
            ),
        ),
        migrations.AddField(
            model_name='loanmonitoringvisit',
            name='unlocked_tranche',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='unlocking_visits',
                to='loans.loandisbursementtranche',
            ),
        ),
        migrations.CreateModel(
            name='ProjectProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('project_title', models.CharField(blank=True, max_length=255)),
                ('sector', models.CharField(
                    choices=[
                        ('agriculture', 'Commercial agriculture / agro-processing'),
                        ('industry', 'Manufacturing / industry'),
                        ('infrastructure', 'Infrastructure'),
                        ('other', 'Other'),
                    ],
                    default='other',
                    max_length=20,
                )),
                ('location', models.CharField(blank=True, max_length=255)),
                ('implementation_months', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('grace_months', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('debt_equity_policy', models.CharField(
                    choices=[
                        ('75_25', '75 : 25 (domestic new project)'),
                        ('50_50', '50 : 50 (FDI / industrial park)'),
                        ('70_30', '70 : 30 (export linkage)'),
                        ('custom', 'Custom / other'),
                    ],
                    default='75_25',
                    max_length=12,
                )),
                ('total_project_cost', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('promoter_equity', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('requested_debt', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('purpose_summary', models.TextField(blank=True)),
                ('notes', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='project_profile',
                    to='loans.loanrequest',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='project_profiles_updated',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='ProjectSourceUseLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('side', models.CharField(choices=[('source', 'Source'), ('use', 'Use')], db_index=True, max_length=8)),
                ('purpose', models.CharField(
                    choices=[
                        ('promoter_cash', 'Promoter cash / in-kind'),
                        ('dbe_loan', 'DBE loan'),
                        ('other_bank', 'Other bank / tripartite WC'),
                        ('grant', 'Grant / donor'),
                        ('civil', 'Civil works'),
                        ('machinery', 'Machinery / equipment'),
                        ('working_capital', 'Working capital'),
                        ('insurance', 'Insurance / ancillary'),
                        ('other', 'Other'),
                    ],
                    default='other',
                    max_length=20,
                )),
                ('label', models.CharField(blank=True, max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('sequence', models.PositiveSmallIntegerField(default=1)),
                ('profile', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lines',
                    to='loans.projectprofile',
                )),
            ],
            options={
                'ordering': ['side', 'sequence', 'id'],
            },
        ),
    ]
