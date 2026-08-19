# Generated manually for DECSI process-gap extras

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def infer_kind(name):
    n = (name or '').lower()
    has_building = any(x in n for x in ('building', 'house', 'construction'))
    has_land = 'land' in n
    has_movable = any(x in n for x in ('vehicle', 'machinery', 'equipment', 'movable'))
    if 'other' in n and not has_building and not has_land:
        has_movable = True
    matched = sum(1 for flag in (has_building, has_land, has_movable) if flag)
    if matched > 1:
        return 'mixed'
    if has_building:
        return 'building'
    if has_land:
        return 'land'
    if has_movable:
        return 'movable'
    return 'mixed'


def backfill_collateral_kind(apps, schema_editor):
    CollateralType = apps.get_model('loans', 'CollateralType')
    for row in CollateralType.objects.all():
        if not row.kind:
            row.kind = infer_kind(row.name)
            row.save(update_fields=['kind'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0070_closing_pack_enhancements'),
    ]

    operations = [
        migrations.AddField(
            model_name='collateraltype',
            name='kind',
            field=models.CharField(
                blank=True,
                choices=[
                    ('building', 'Building / house (BOQ)'),
                    ('land', 'Land (size × price)'),
                    ('movable', 'Vehicle / machinery / other movable'),
                    ('mixed', 'Mixed (sum engines that apply)'),
                ],
                db_index=True,
                default='',
                help_text='Which estimation engine(s) this type uses. Blank infers from the name. Mixed sums building + land + movable that have data.',
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_collateral_kind, migrations.RunPython.noop),
        migrations.AddField(
            model_name='loananalysispolicyconfig',
            name='require_risk_review_before_committee',
            field=models.BooleanField(
                default=True,
                help_text='Loan officer cannot submit to committee until Risk & Compliance has signed off.',
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='require_title_search',
            field=models.BooleanField(
                default=False,
                help_text='Title / ownership search paper must be uploaded and verified before disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='require_mortgage_registration',
            field=models.BooleanField(
                default=False,
                help_text='Mortgage / restriction registration proof must be verified before disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='require_notary_stamp',
            field=models.BooleanField(
                default=False,
                help_text='Notary / stamp-duty receipt must be verified before disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='own_contribution_required',
            field=models.BooleanField(
                default=False,
                help_text='Borrower own-contribution / equity must be verified before first disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='own_contribution_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='own_contribution_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='own_contribution_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='own_contribution_verified_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loans_own_contribution_verified',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='watchlist',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='watchlist_reason',
            field=models.CharField(blank=True, max_length=400),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='watchlist_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='watchlist_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loans_watchlisted',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='arrears_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('current', 'Current'),
                    ('dpd_30', '1–30 days past due'),
                    ('dpd_60', '31–60 days past due'),
                    ('dpd_90', '61–90 days past due'),
                    ('npl', 'NPL / 90+ days'),
                ],
                db_index=True,
                default='current',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='workout_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'None'),
                    ('requested', 'Reschedule requested'),
                    ('approved', 'Reschedule approved'),
                    ('rejected', 'Reschedule rejected'),
                ],
                db_index=True,
                default='',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='workout_proposed_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='workout_proposed_term_months',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='workout_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='workout_decided_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='workout_decided_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loans_workout_decided',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='writeoff_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'None'),
                    ('requested', 'Write-off requested'),
                    ('approved', 'Written off'),
                    ('written_back', 'Written back'),
                ],
                db_index=True,
                default='',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='writeoff_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='writeoff_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='writeoff_decided_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='writeoff_decided_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loans_writeoff_decided',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='loanrequest',
            name='disbursement_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Not started'),
                    ('awaiting_conditions', 'Awaiting conditions'),
                    ('schedule_confirmed', 'Schedule confirmed'),
                    ('ready_for_disbursement', 'Ready for disbursement'),
                    ('partially_disbursed', 'Partially disbursed'),
                    ('disbursed', 'Disbursed'),
                ],
                default='',
                help_text='Post-committee track: conditions → schedule → ready → disbursed.',
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name='loancollaterallegaldocument',
            name='kind',
            field=models.CharField(
                choices=[
                    ('collateral_restriction', 'Collateral Restriction (government)'),
                    ('power_of_attorney', 'Loan Collateral Power of Attorney'),
                    ('title_search', 'Title / ownership search'),
                    ('mortgage_registration', 'Mortgage / restriction registration'),
                    ('notary_stamp', 'Notary / stamp-duty receipt'),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name='LoanDisbursementTranche',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sequence', models.PositiveSmallIntegerField(default=1)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('note', models.CharField(blank=True, max_length=400)),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('disbursed', 'Disbursed')],
                    db_index=True,
                    default='pending',
                    max_length=20,
                )),
                ('disbursed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('disbursed_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='tranches_disbursed', to=settings.AUTH_USER_MODEL,
                )),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='disbursement_tranches', to='loans.loanrequest',
                )),
            ],
            options={'ordering': ['loan_request', 'sequence', 'id']},
        ),
        migrations.AlterUniqueTogether(
            name='loandisbursementtranche',
            unique_together={('loan_request', 'sequence')},
        ),
        migrations.CreateModel(
            name='LoanMonitoringVisit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('visited_at', models.DateField()),
                ('notes', models.TextField()),
                ('gps_lat', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('gps_lon', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='monitoring_visits', to='loans.loanrequest',
                )),
                ('recorded_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='monitoring_visits_recorded', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-visited_at', '-id']},
        ),
        migrations.CreateModel(
            name='LoanCollectionAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(
                    choices=[
                        ('reminder', 'Reminder'),
                        ('demand', 'Demand notice'),
                        ('visit', 'Collection visit'),
                        ('legal_referral', 'Legal referral'),
                    ],
                    db_index=True,
                    max_length=20,
                )),
                ('notes', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='collection_actions', to='loans.loanrequest',
                )),
                ('recorded_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='collection_actions_recorded', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
