from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0080_project_overlay'),
    ]

    operations = [
        migrations.AddField(
            model_name='loandisbursementtranche',
            name='purpose_code',
            field=models.CharField(
                blank=True,
                help_text='Project draws: civil / machinery / working_capital / insurance / other.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loandisbursementtranche',
            name='utilization_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='loandisbursementtranche',
            name='utilization_recorded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loandisbursementtranche',
            name='lc_status',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='discount_rate_pct',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='npv',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='irr_pct',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='project_dscr',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='equity_plan',
            field=models.CharField(
                choices=[
                    ('lump', 'Lump — full promoter equity before first loan release'),
                    ('staggered', 'Staggered — 1/3, then 2/3, then 100%'),
                ],
                default='lump',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='equity_stage',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='0 = none; 1 = 1/3; 2 = 2/3; 3 = 100%. Used when equity is staggered.',
            ),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='current_account_opened',
            field=models.BooleanField(
                default=False,
                help_text='DBE current account opened before equity or loan release.',
            ),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='other_bank_name',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='other_bank_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='projectprofile',
            name='other_bank_note',
            field=models.CharField(blank=True, max_length=400),
        ),
        migrations.CreateModel(
            name='ProjectCashflowYear',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year_number', models.PositiveSmallIntegerField()),
                ('operating_cf', models.DecimalField(decimal_places=2, max_digits=20)),
                ('debt_service', models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ('profile', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='cashflows',
                    to='loans.projectprofile',
                )),
            ],
            options={
                'ordering': ['year_number', 'id'],
                'unique_together': {('profile', 'year_number')},
            },
        ),
        migrations.CreateModel(
            name='ProjectTechnicalReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('desk', models.CharField(
                    choices=[
                        ('civil', 'Civil'),
                        ('mechanical', 'Mechanical'),
                        ('electrical', 'Electrical'),
                    ],
                    max_length=16,
                )),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('cleared', 'Cleared'),
                        ('returned', 'Returned'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=12,
                )),
                ('note', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('profile', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='technical_reviews',
                    to='loans.projectprofile',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='project_technical_reviews',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['desk'],
                'unique_together': {('profile', 'desk')},
            },
        ),
    ]
