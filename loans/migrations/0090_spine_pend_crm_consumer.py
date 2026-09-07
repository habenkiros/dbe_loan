from django.db import migrations, models
import django.db.models.deletion


def update_consumer_appraisal_mode(apps, schema_editor):
    LoanCategory = apps.get_model('loans', 'LoanCategory')
    ProductFamilyPolicy = apps.get_model('loans', 'ProductFamilyPolicy')
    ProductFamilyPolicy.objects.filter(family='consumer').update(
        default_appraisal_mode='consumer',
    )
    LoanCategory.objects.filter(product_family='consumer', appraisal_mode='msme').update(
        appraisal_mode='consumer',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0089_family_policy_requires_collateral'),
    ]

    operations = [
        migrations.AlterField(
            model_name='loancategory',
            name='appraisal_mode',
            field=models.CharField(
                choices=[
                    ('msme', 'MSME / cashflow sheets'),
                    ('corporate', 'Corporate / financial statements'),
                    ('project', 'Project desk (viability, equity, plant)'),
                    ('wholesale', 'Wholesale / PFI institution desk'),
                    ('lease', 'Lease / hire-purchase asset desk'),
                    ('ifb_murabaha', 'Murabaha cost-plus desk'),
                    ('ifb_ijarah', 'Ijarah rental desk'),
                    ('idea_equity', 'Idea / quasi-equity desk'),
                    ('consumer', 'Consumer / HRM scorecard'),
                ],
                default='msme',
                help_text='Appraisal modality. MSME/corporate = 7-sheet wizard. Other values use the product desk.',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='productfamilypolicy',
            name='default_appraisal_mode',
            field=models.CharField(
                choices=[
                    ('msme', 'MSME / cashflow sheets'),
                    ('corporate', 'Corporate / financial statements'),
                    ('project', 'Project desk (viability, equity, plant)'),
                    ('wholesale', 'Wholesale / PFI institution desk'),
                    ('lease', 'Lease / hire-purchase asset desk'),
                    ('ifb_murabaha', 'Murabaha cost-plus desk'),
                    ('ifb_ijarah', 'Ijarah rental desk'),
                    ('idea_equity', 'Idea / quasi-equity desk'),
                    ('consumer', 'Consumer / HRM scorecard'),
                ],
                default='msme',
                help_text='Pre-selected when a loan type uses this family. Can still be changed per category.',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='loanrequest',
            name='committee_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Not submitted'),
                    ('pending_committee', 'Pending committee'),
                    ('committee_pended', 'Committee pended'),
                    ('committee_approved', 'Committee approved'),
                    ('committee_declined', 'Committee declined'),
                    ('returned_to_officer', 'Returned to loan officer'),
                ],
                default='',
                help_text='Credit committee workflow status (separate from queue op/finance approval).',
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name='loancommitteevote',
            name='vote',
            field=models.CharField(
                choices=[
                    ('approve', 'Approve'),
                    ('decline', 'Decline'),
                    ('pend', 'Pend'),
                ],
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='AppraisalCrmRound',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveSmallIntegerField(default=1)),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'Draft'),
                        ('with_crm', 'With CRM'),
                        ('returned', 'Returned to appraisal'),
                        ('cleared', 'Cleared for committee'),
                    ],
                    db_index=True, default='draft', max_length=16,
                )),
                ('appraisal_note', models.TextField(blank=True)),
                ('crm_note', models.TextField(blank=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('crm_at', models.DateTimeField(blank=True, null=True)),
                ('cleared_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('crm_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='appraisal_packs_reviewed', to='loans.customuser',
                )),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='appraisal_crm_rounds', to='loans.loanrequest',
                )),
                ('sent_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='appraisal_packs_sent', to='loans.customuser',
                )),
            ],
            options={
                'ordering': ['-version', '-id'],
                'verbose_name': 'Appraisal / CRM round',
                'unique_together': {('loan_request', 'version')},
            },
        ),
        migrations.CreateModel(
            name='ConsumerProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('purpose', models.CharField(
                    choices=[('housing', 'Housing'), ('vehicle', 'Vehicle')],
                    db_index=True, default='housing', max_length=12,
                )),
                ('employer_name', models.CharField(blank=True, max_length=255)),
                ('occupation', models.CharField(blank=True, max_length=120)),
                ('monthly_salary', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('monthly_obligations', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('asset_value', models.DecimalField(
                    blank=True, decimal_places=2,
                    help_text='House or vehicle value for LTV.',
                    max_digits=20, null=True,
                )),
                ('term_months', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='consumer_profile', to='loans.loanrequest',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='consumer_profiles_updated', to='loans.customuser',
                )),
            ],
        ),
        migrations.RunPython(update_consumer_appraisal_mode, migrations.RunPython.noop),
    ]
